"""Chat link rules: the pattern compiler, URL template check and stored form."""

import json
import re
from uuid import uuid4

import pytest

from omnigent.git_providers import provider_display
from omnigent.link_rules import (
    DEFAULT_LINK_RULES,
    GIT_PROVIDERS,
    MAX_REPEAT,
    LinkRule,
    LinkRuleError,
    LinkRuleKind,
    check_git_host,
    check_url_template,
    compile_pattern,
    describe_link_syntax,
    encode_link_rules,
    github_git_rule,
    link_rules_from_value,
    parse_link_rules_json,
    session_git_rule,
    validate_link_rules,
)
from omnigent.preference_sync import PreferenceMutation

GITLAB_SELF_MANAGED = {
    "name": "Our GitLab",
    "kind": "git",
    "provider": "gitlab",
    "host": "gitlab.example.com",
}


@pytest.mark.parametrize(
    ("pattern", "text", "captures"),
    [
        ("BST-{num}", "see BST-42.", ("42",)),
        ("{key}-{num}", "(ENG-7)", ("ENG", "7")),
        ("PR.{id}", "PR.a_b-1 done", ("a_b-1",)),
        ("/(ENG-\\d+)/", "fixes ENG-12", ("ENG-12",)),
        ("/T(\\d{2,4})/", "T123", ("123",)),
    ],
)
def test_compiled_pattern_matches_whole_words(pattern, text, captures):
    compiled = compile_pattern(pattern)
    match = re.search(compiled.bounded(), text, re.ASCII)
    assert match is not None
    assert match.groups()[1:] == captures


@pytest.mark.parametrize("text", ["XBST-42", "BST-42x", "BST-", "bst-42"])
def test_short_form_needs_word_boundaries(text):
    assert re.search(compile_pattern("BST-{num}").bounded(), text, re.ASCII) is None


def test_short_form_escapes_literal_regex_characters():
    compiled = compile_pattern("a.b+{num}")
    assert re.search(compiled.bounded(), "a.b+1", re.ASCII)
    assert re.search(compiled.bounded(), "axbb1", re.ASCII) is None


def test_unbounded_repeats_are_capped():
    compiled = compile_pattern("/x.*y/")
    assert compiled.source == f"x.{{0,{MAX_REPEAT}}}y"
    assert compile_pattern("/a{2,}/").source == f"a{{2,{MAX_REPEAT}}}"


@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        ("", "required"),
        ("x" * 201, "longer than"),
        ("BST", "needs a placeholder"),
        ("BST-{nope}", "unknown placeholder"),
        ("BST {num}", "spaces"),
        ("BST-{num", "unmatched"),
        ("/(a+)+/", "repeated group"),
        ("/(a|b)*/", "repeated group"),
        ("/(?:a?)+/", "repeated group"),
        ("/(a)\\1/", "backreferences"),
        ("/(?<name>a)/", "named groups"),
        ("/(?P<name>a)/", "named groups"),
        ("/(?<=a)b/", "lookaround"),
        ("/(?=a)b/", "lookaround"),
        ("/(?i)a/", "inline flags"),
        ("/\\p{L}/", "isn't supported"),
        ("/a{1000}/", "capped"),
        ("/a{3,2}/", "min <= max"),
        ("/a{/", "escape a literal"),
        ("/[]a]/", "start of a [ ] class"),
        ("/[a[b]/", "inside a [ ] class"),
        ("/(a/", "unbalanced ("),
        ("/a)/", "unbalanced )"),
        ("/a*/", "empty text"),
        ("/*a/", "nothing to repeat"),
        ("/a**/", "nothing to repeat"),
        ("/\\b+/", "nothing to repeat"),
        ("/a+b+c+d+/", "at most 3 repeats"),
        ("/(a)(b)(c)(d)(e)(f)(g)(h)(i)(j)/", "capture groups"),
    ],
)
def test_unsafe_patterns_are_rejected(pattern, message):
    with pytest.raises(LinkRuleError, match=re.escape(message)):
        compile_pattern(pattern)


@pytest.mark.parametrize(
    "template",
    [
        "https://jira.example.com/browse/{key}-{num}",
        "http://tracker.example.com/?id={num}",
        "https://example.com#{0}",
        "https://example.com",
    ],
)
def test_url_templates_that_stay_on_their_host(template):
    check_url_template(template, compile_pattern("{key}-{num}"))


@pytest.mark.parametrize(
    ("template", "message"),
    [
        ("javascript:alert(1)//{num}", "https://"),
        ("data:text/html,{num}", "https://"),
        ("JAVASCRIPT://example.com/{num}", "https://"),
        ("https://{key}.example.com/{num}", "https://"),
        ("https://user@evil.example/{num}", "https://"),
        ("//example.com/{num}", "https://"),
        ("ftp://example.com/{num}", "https://"),
        ("https://example.com/ {num}", "spaces"),
        ("https://example.com/{zzz}", "unknown placeholder"),
        ("https://example.com/{3}", "no matching group"),
        ("https://example.com/{num", "unmatched"),
        ("", "required"),
    ],
)
def test_url_templates_that_could_leave_http_are_rejected(template, message):
    with pytest.raises(LinkRuleError, match=re.escape(message)):
        check_url_template(template, compile_pattern("{key}-{num}"))


def test_builtin_kinds_take_no_pattern_or_url():
    with pytest.raises(LinkRuleError, match="takes no pattern"):
        validate_link_rules([{"name": "S", "kind": "session", "pattern": "s:{id}"}])
    with pytest.raises(LinkRuleError, match="takes no pattern"):
        validate_link_rules([{**GITLAB_SELF_MANAGED, "url": "https://x.example/{0}"}])
    rules = validate_link_rules([{"name": " S ", "kind": "session"}])
    assert rules[0].name == "S" and rules[0].kind == LinkRuleKind.SESSION


def test_git_rules_name_a_provider_and_a_bare_host():
    [rule] = validate_link_rules([{**GITLAB_SELF_MANAGED, "host": "GitLab.Example.COM:8443"}])
    assert rule.kind == LinkRuleKind.GIT
    assert (rule.provider, rule.host) == ("gitlab", "gitlab.example.com:8443")
    assert rule.to_wire() == {
        "name": "Our GitLab",
        "kind": "git",
        "provider": "gitlab",
        "host": "gitlab.example.com:8443",
        "pattern": "",
        "enabled": True,
    }


@pytest.mark.parametrize(
    "host",
    [
        "https://gitlab.example.com",
        "gitlab.example.com/group",
        "user@gitlab.example.com",
        "user:pw@gitlab.example.com",
        "gitlab example.com",
        "gitlab.example.com:0",
        "gitlab.example.com:99999",
        "-gitlab.example.com",
        "gitlab..example.com",
        "",
        None,
        "a" * 254,
    ],
)
def test_git_hosts_with_a_scheme_path_or_credentials_are_rejected(host):
    with pytest.raises(LinkRuleError, match="host:"):
        check_git_host(host)


@pytest.mark.parametrize(
    ("rules", "message"),
    [
        ({"name": "x"}, "must be a list"),
        ([{"name": "", "kind": "session"}], "name: required"),
        ([{"name": "a", "kind": "ftp"}], "kind: must be url, git or session"),
        ([{"name": "a", "kind": "session", "enabled": "yes"}], "enabled:"),
        ([{"name": "a", "kind": "session", "color": "red"}], "unknown field"),
        ([{"name": "a", "kind": "session"}, {**GITLAB_SELF_MANAGED, "name": "A"}], "two rules"),
        ([{"name": "a", "kind": "session"}, {"name": "b", "kind": "session"}], "only one"),
        ([{"name": f"r{i}", "kind": "session"} for i in range(33)], "at most 32"),
        ([{"name": "Jira", "kind": "url", "pattern": "B-{num}"}], "Jira: url: required"),
        ([{**GITLAB_SELF_MANAGED, "provider": "bitbucket"}], "provider: must be"),
        ([{**GITLAB_SELF_MANAGED, "provider": None}], "provider: must be"),
        ([{"name": "S", "kind": "session", "host": "x.example"}], "belong to a git rule"),
        (
            [
                GITLAB_SELF_MANAGED,
                {**GITLAB_SELF_MANAGED, "name": "Again", "host": "GITLAB.example.com"},
            ],
            "two git rules are for gitlab.example.com",
        ),
        ([{"name": "GH", "kind": "github", "host": "ghe.example.com"}], "old github kind"),
    ],
)
def test_rule_lists_are_validated(rules, message):
    with pytest.raises(LinkRuleError, match=re.escape(message)):
        validate_link_rules(rules)


def test_git_provider_notation_matches_the_provider_registry():
    """The web client links with the same prefixes the git providers declare."""
    for provider_id, notation in GIT_PROVIDERS.items():
        display = provider_display(provider_id)
        assert display is not None
        assert display["number_prefix"] == notation.request_prefix
        assert display["display_name"] == notation.display_name


# ─── The old github kind (accepted on input until 0.22.0) ────


def test_an_old_github_rule_is_read_as_the_github_git_rule():
    stored = '[{"name":"GitHub","kind":"github","pattern":"","enabled":false}]'
    assert link_rules_from_value(stored) == (
        LinkRule(
            name="GitHub",
            kind=LinkRuleKind.GIT,
            provider="github",
            host="github.com",
            enabled=False,
        ),
    )


def test_an_old_github_rule_is_saved_in_the_new_form():
    stored = _mutation('[{"name":"GitHub","kind":"github","pattern":"","enabled":true}]').value
    assert stored == (
        '[{"name":"GitHub","kind":"git","provider":"github","host":"github.com",'
        '"pattern":"","enabled":true}]'
    )


# ─── Which git rules a session uses ────


def _git(name: str, provider: str, host: str, *, enabled: bool = True) -> LinkRule:
    return LinkRule(
        name=name, kind=LinkRuleKind.GIT, provider=provider, host=host, enabled=enabled
    )


GITHUB = _git("GitHub", "github", "github.com")
GITLAB = _git("GitLab", "gitlab", "gitlab.com")
OUR_GITLAB = _git("Our GitLab", "gitlab", "gitlab.example.com")


@pytest.mark.parametrize(
    ("provider", "host", "expected"),
    [
        ("github", "github.com", GITHUB),
        ("gitlab", "GitLab.com", GITLAB),
        # A listed self-managed host wins over the provider's public one.
        ("gitlab", "gitlab.example.com", OUR_GITLAB),
        # The listed host decides even when the server names no provider.
        (None, "gitlab.example.com", OUR_GITLAB),
        # A GitHub Enterprise host nobody listed falls back to the provider.
        ("github", "ghe.example.com", GITHUB),
        (None, "ghe.example.com", None),
        ("bitbucket", "bitbucket.org", None),
        ("github", None, None),
    ],
)
def test_the_session_repository_picks_one_git_rule(provider, host, expected):
    rules = (GITHUB, GITLAB, OUR_GITLAB)
    assert session_git_rule(rules, provider=provider, host=host) == expected


def test_a_disabled_git_rule_turns_its_host_off():
    rules = (GITHUB, _git("Our GitLab", "gitlab", "gitlab.example.com", enabled=False), GITLAB)
    assert session_git_rule(rules, provider="gitlab", host="gitlab.example.com") is None
    assert session_git_rule(rules, provider="gitlab", host="gitlab.com") == GITLAB


def test_github_links_qualified_references_unless_turned_off():
    assert github_git_rule(DEFAULT_LINK_RULES) == DEFAULT_LINK_RULES[0]
    disabled = _git("GitHub", "github", "github.com", enabled=False)
    assert github_git_rule((disabled, GITLAB)) is None


def test_defaults_round_trip_through_the_stored_form():
    encoded = encode_link_rules(DEFAULT_LINK_RULES)
    assert parse_link_rules_json(encoded) == DEFAULT_LINK_RULES
    assert [rule.enabled for rule in DEFAULT_LINK_RULES] == [True, True, True, True, False, False]
    assert [(rule.provider, rule.host) for rule in DEFAULT_LINK_RULES[:3]] == [
        ("github", "github.com"),
        ("gitlab", "gitlab.com"),
        ("azure_devops", "dev.azure.com"),
    ]


def test_unusable_stored_values_fall_back_to_the_defaults():
    assert link_rules_from_value(None) == DEFAULT_LINK_RULES
    assert link_rules_from_value("not json") == DEFAULT_LINK_RULES
    assert link_rules_from_value("[]") == ()


def test_describe_link_syntax_shows_an_example():
    jira, linear = DEFAULT_LINK_RULES[4], DEFAULT_LINK_RULES[5]
    assert describe_link_syntax(jira) == "`ABC-123` (Jira)"
    assert describe_link_syntax(linear) == "text matching `/(ENG-\\d+)/` (Linear)"
    assert describe_link_syntax(OUR_GITLAB).endswith("(GitLab on gitlab.example.com)")


def _mutation(value: object) -> PreferenceMutation:
    return PreferenceMutation.model_validate(
        {
            "protocol_version": 1,
            "identity": {"authority_id": "a", "user_id": "u", "workspace_id": "w"},
            "operation_id": str(uuid4()),
            "installation_id": "web-1",
            "key": {"kind": "link_rules", "name": "default"},
            "expected_version": 0,
            "value": value,
        }
    )


def test_shared_preference_edits_store_the_canonical_form():
    value = json.dumps([{"enabled": True, "kind": "session", "name": "  Sessions "}], indent=2)
    stored = _mutation(value).value
    assert stored == '[{"name":"Sessions","kind":"session","pattern":"","enabled":true}]'


@pytest.mark.parametrize(
    "value",
    [
        '[{"name":"x","kind":"url","pattern":"/(a+)+/","url":"https://e.com/{0}"}]',
        '[{"name":"x","kind":"url","pattern":"X-{num}","url":"javascript:x//{num}"}]',
        "not json",
        ["github"],
    ],
)
def test_shared_preference_edits_reject_invalid_rules(value):
    with pytest.raises(ValueError):
        _mutation(value)
