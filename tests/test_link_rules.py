"""Chat link rules: the pattern compiler, URL template check and stored form."""

import json
import re
from uuid import uuid4

import pytest

from omnigent.link_rules import (
    DEFAULT_LINK_RULES,
    MAX_REPEAT,
    LinkRuleError,
    LinkRuleKind,
    check_url_template,
    compile_pattern,
    describe_link_syntax,
    encode_link_rules,
    link_rules_from_value,
    parse_link_rules_json,
    validate_link_rules,
)
from omnigent.preference_sync import PreferenceMutation


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
        validate_link_rules([{"name": "GH", "kind": "github", "pattern": "#{num}"}])
    rules = validate_link_rules([{"name": " GH ", "kind": "github"}])
    assert rules[0].name == "GH" and rules[0].kind == LinkRuleKind.GITHUB


@pytest.mark.parametrize(
    ("rules", "message"),
    [
        ({"name": "x"}, "must be a list"),
        ([{"name": "", "kind": "github"}], "name: required"),
        ([{"name": "a", "kind": "ftp"}], "kind:"),
        ([{"name": "a", "kind": "github", "enabled": "yes"}], "enabled:"),
        ([{"name": "a", "kind": "github", "color": "red"}], "unknown field"),
        ([{"name": "a", "kind": "github"}, {"name": "A", "kind": "session"}], "two rules"),
        ([{"name": "a", "kind": "session"}, {"name": "b", "kind": "session"}], "only one"),
        ([{"name": f"r{i}", "kind": "github"} for i in range(33)], "at most 32"),
        ([{"name": "Jira", "kind": "url", "pattern": "B-{num}"}], "Jira: url: required"),
    ],
)
def test_rule_lists_are_validated(rules, message):
    with pytest.raises(LinkRuleError, match=re.escape(message)):
        validate_link_rules(rules)


def test_defaults_round_trip_through_the_stored_form():
    encoded = encode_link_rules(DEFAULT_LINK_RULES)
    assert parse_link_rules_json(encoded) == DEFAULT_LINK_RULES
    assert [rule.enabled for rule in DEFAULT_LINK_RULES] == [True, True, False, False]


def test_unusable_stored_values_fall_back_to_the_defaults():
    assert link_rules_from_value(None) == DEFAULT_LINK_RULES
    assert link_rules_from_value("not json") == DEFAULT_LINK_RULES
    assert link_rules_from_value("[]") == ()


def test_describe_link_syntax_shows_an_example():
    jira, linear = DEFAULT_LINK_RULES[2], DEFAULT_LINK_RULES[3]
    assert describe_link_syntax(jira) == "`ABC-123` (Jira)"
    assert describe_link_syntax(linear) == "text matching `/(ENG-\\d+)/` (Linear)"
    assert "owner/repo#123" in describe_link_syntax(DEFAULT_LINK_RULES[0])


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
    value = json.dumps([{"enabled": True, "kind": "github", "name": "  GitHub "}], indent=2)
    stored = _mutation(value).value
    assert stored == '[{"name":"GitHub","kind":"github","pattern":"","enabled":true}]'


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
