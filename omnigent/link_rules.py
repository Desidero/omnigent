"""Chat link rules: short references in chat messages that render as links.

Each viewer's browser runs the rules on every message, and agents can write
them, so a rule is validated here when it is saved and again by the web client
(``web/src/lib/linkRules.ts``) when it is compiled. Both sides accept the same
subset of regular expressions: one that Python and every supported browser
parse the same way, with no backreferences, lookbehind or named groups (older
Safari cannot parse the last two), no nested or alternating repeats, and
repeats capped at :data:`MAX_REPEAT`.

A ``url`` rule's pattern is a short form such as ``BST-{num}`` or a raw
``/regex/``; its URL template fills ``{num}``-style placeholders (or ``{1}``,
``{2}`` for regex groups, ``{0}`` for the whole match) with percent-encoded
captures. The ``github`` and ``session`` kinds are built in and take no
pattern or URL.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit


class LinkRuleKind(StrEnum):
    """What a rule links to."""

    URL = "url"
    GITHUB = "github"
    SESSION = "session"


BUILTIN_KINDS = frozenset({LinkRuleKind.GITHUB, LinkRuleKind.SESSION})
MAX_RULES = 32
MAX_NAME_LENGTH = 64
MAX_PATTERN_LENGTH = 200
MAX_URL_LENGTH = 500
MAX_REPEAT = 64
MAX_REPEATS = 3
MAX_GROUPS = 9

# Short-form placeholders and the text each one matches.
SHORT_FORM_PLACEHOLDERS: dict[str, str] = {
    "num": r"\d{1,10}",
    "key": r"[A-Z][A-Z0-9]{1,9}",
    "id": r"[A-Za-z0-9_-]{1,64}",
}
# Sample values for describing a short form to agents.
_PLACEHOLDER_EXAMPLES = {"num": "123", "key": "ABC", "id": "a1b2"}
_SHORT_FORM_TOKEN = re.compile(r"\{([a-z]+)\}")
_URL_PLACEHOLDER = re.compile(r"\{([a-z]+|\d)\}")
# Everything up to the first placeholder must be a complete scheme and host,
# so a capture can never choose where the link goes.
_URL_FIXED_PREFIX = re.compile(r"^https?://[^/?#{}\s@\\]+[/?#]", re.IGNORECASE)
# Matches start after a non-word character or at the start of the text and must
# not run into a word character. Compiled rules consume that one leading
# character as group 1 instead of using lookbehind, which older Safari lacks.
_WORD_CHAR_CLASS = "[A-Za-z0-9_]"
_LEADING_BOUNDARY = "(^|[^A-Za-z0-9_])"
_TRAILING_BOUNDARY = f"(?!{_WORD_CHAR_CLASS})"
_CLASS_ESCAPES = frozenset("dDwWsS")


class LinkRuleError(ValueError):
    """A rule that can't be saved; the message says which field and why."""


@dataclass(frozen=True)
class LinkRule:
    """One saved rule.

    :param name: Unique display name, e.g. ``"Jira"``.
    :param kind: What the rule links to.
    :param pattern: ``url`` kind only: a short form such as ``"BST-{num}"`` or a
        raw ``"/regex/"``; ``""`` for the built-in kinds.
    :param url: ``url`` kind only: the link template, e.g.
        ``"https://jira.example.com/browse/BST-{num}"``.
    :param enabled: Whether chat messages use the rule.
    """

    name: str
    kind: LinkRuleKind
    pattern: str = ""
    url: str | None = None
    enabled: bool = True

    def to_wire(self) -> dict[str, Any]:
        """The rule as stored and served, omitting ``url`` when unset."""
        wire: dict[str, Any] = {
            "name": self.name,
            "kind": str(self.kind),
            "pattern": self.pattern,
            "enabled": self.enabled,
        }
        if self.url is not None:
            wire["url"] = self.url
        return wire


@dataclass(frozen=True)
class CompiledPattern:
    """A pattern as a matching regex plus its placeholder names.

    :param source: The pattern's own regex, without the word boundaries.
    :param group_names: For a short form, each capture group's placeholder name
        in order; empty for a raw regex.
    :param group_count: Number of capture groups in ``source``.
    """

    source: str
    group_names: tuple[str, ...]
    group_count: int

    def bounded(self) -> str:
        """The full regex: leading boundary as group 1, then the pattern."""
        return f"{_LEADING_BOUNDARY}(?:{self.source}){_TRAILING_BOUNDARY}"


DEFAULT_LINK_RULES: tuple[LinkRule, ...] = (
    LinkRule(name="GitHub", kind=LinkRuleKind.GITHUB),
    LinkRule(name="Sessions", kind=LinkRuleKind.SESSION),
    LinkRule(
        name="Jira",
        kind=LinkRuleKind.URL,
        pattern="ABC-{num}",
        url="https://jira.example.com/browse/ABC-{num}",
        enabled=False,
    ),
    LinkRule(
        name="Linear",
        kind=LinkRuleKind.URL,
        pattern="/(ENG-\\d+)/",
        url="https://linear.app/example/issue/{1}",
        enabled=False,
    ),
)


def compile_pattern(pattern: str) -> CompiledPattern:
    """Compile a ``url`` rule's pattern after checking it is safe to run.

    :param pattern: A short form (``"BST-{num}"``) or a raw ``"/regex/"``.
    :returns: The compiled pattern.
    :raises LinkRuleError: If the pattern is empty, too long, uses an unknown
        placeholder or an unsupported regex construct, or can match empty text.
    """
    if not pattern:
        raise LinkRuleError("pattern: required for a url rule")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise LinkRuleError(f"pattern: longer than {MAX_PATTERN_LENGTH} characters")
    if len(pattern) >= 2 and pattern.startswith("/") and pattern.endswith("/"):
        source, group_count = _check_regex(pattern[1:-1])
        compiled = CompiledPattern(source=source, group_names=(), group_count=group_count)
    else:
        compiled = _compile_short_form(pattern)
    try:
        regex = re.compile(compiled.source, re.ASCII)
    except re.error as exc:
        raise LinkRuleError(f"pattern: {exc}") from exc
    if regex.fullmatch(""):
        raise LinkRuleError("pattern: must not match empty text")
    return compiled


def _compile_short_form(pattern: str) -> CompiledPattern:
    if any(char.isspace() for char in pattern):
        raise LinkRuleError("pattern: a short form can't contain spaces")
    parts: list[str] = []
    names: list[str] = []
    last = 0
    for match in _SHORT_FORM_TOKEN.finditer(pattern):
        literal = pattern[last : match.start()]
        if "{" in literal or "}" in literal:
            raise LinkRuleError("pattern: unmatched { or } in the short form")
        parts.append(re.escape(literal))
        name = match.group(1)
        if name not in SHORT_FORM_PLACEHOLDERS:
            known = ", ".join(f"{{{key}}}" for key in SHORT_FORM_PLACEHOLDERS)
            raise LinkRuleError(f"pattern: unknown placeholder {{{name}}}; use {known}")
        parts.append(f"({SHORT_FORM_PLACEHOLDERS[name]})")
        names.append(name)
        last = match.end()
    tail = pattern[last:]
    if "{" in tail or "}" in tail:
        raise LinkRuleError("pattern: unmatched { or } in the short form")
    parts.append(re.escape(tail))
    if not names:
        raise LinkRuleError("pattern: a short form needs a placeholder such as {num}")
    if len(names) > MAX_REPEATS + 1:
        raise LinkRuleError(f"pattern: at most {MAX_REPEATS + 1} placeholders")
    return CompiledPattern(source="".join(parts), group_names=tuple(names), group_count=len(names))


@dataclass
class _Group:
    has_repeat: bool = False
    has_alternation: bool = False


def _check_regex(body: str) -> tuple[str, int]:
    """Check a raw regex against the shared safe subset and cap its repeats.

    :param body: The regex between the slashes.
    :returns: The regex with unbounded repeats rewritten to ``{n,MAX_REPEAT}``,
        and its capture-group count.
    :raises LinkRuleError: On any construct outside the subset.
    """
    out: list[str] = []
    stack = [_Group()]
    # What a quantifier would apply to: None (nothing), "atom", or a closed group.
    last: _Group | str | None = None
    groups = 0
    repeats = 0
    index = 0
    length = len(body)
    while index < length:
        char = body[index]
        if char == "\\":
            if index + 1 >= length:
                raise LinkRuleError("pattern: ends with a lone backslash")
            escaped = body[index + 1]
            if escaped in "bB":
                last = None
            elif escaped in _CLASS_ESCAPES or not escaped.isalnum():
                last = "atom"
            else:
                raise LinkRuleError(
                    f"pattern: \\{escaped} isn't supported (no backreferences or "
                    "letter escapes other than \\d \\w \\s \\b and their capitals)"
                )
            out.append(body[index : index + 2])
            index += 2
        elif char == "[":
            end = _class_end(body, index)
            out.append(body[index : end + 1])
            last = "atom"
            index = end + 1
        elif char == "(":
            if body.startswith("(?", index):
                if not body.startswith("(?:", index):
                    raise LinkRuleError(
                        "pattern: only (?: ) groups are supported; no lookaround, "
                        "named groups or inline flags"
                    )
                out.append("(?:")
                index += 3
            else:
                groups += 1
                out.append("(")
                index += 1
            stack.append(_Group())
            last = None
        elif char == ")":
            if len(stack) == 1:
                raise LinkRuleError("pattern: unbalanced )")
            closed = stack.pop()
            parent = stack[-1]
            parent.has_repeat |= closed.has_repeat
            parent.has_alternation |= closed.has_alternation
            out.append(")")
            last = closed
            index += 1
        elif char == "|":
            stack[-1].has_alternation = True
            out.append("|")
            last = None
            index += 1
        elif char in "*+?" or char == "{":
            quantifier = _read_quantifier(body, index)
            if quantifier is None:
                raise LinkRuleError("pattern: escape a literal { or } as \\{ or \\}")
            text, low, high, end = quantifier
            if last is None:
                raise LinkRuleError(f"pattern: nothing to repeat before {text}")
            repeats_more = high is None or high > 1
            if repeats_more:
                if isinstance(last, _Group) and (last.has_repeat or last.has_alternation):
                    raise LinkRuleError(
                        "pattern: a repeated group can't contain another repeat or |"
                    )
                repeats += 1
                if repeats > MAX_REPEATS:
                    raise LinkRuleError(f"pattern: at most {MAX_REPEATS} repeats")
            if high is not None and high > MAX_REPEAT:
                raise LinkRuleError(f"pattern: repeat counts are capped at {MAX_REPEAT}")
            if low > MAX_REPEAT:
                raise LinkRuleError(f"pattern: repeat counts are capped at {MAX_REPEAT}")
            stack[-1].has_repeat = True
            out.append(text if high is not None else f"{{{low},{MAX_REPEAT}}}")
            index = end
            if index < length and body[index] == "?":
                out.append("?")
                index += 1
            last = None
        elif char == "}":
            raise LinkRuleError("pattern: escape a literal { or } as \\{ or \\}")
        elif char in "^$":
            out.append(char)
            last = None
            index += 1
        else:
            out.append(char)
            last = "atom"
            index += 1
    if len(stack) != 1:
        raise LinkRuleError("pattern: unbalanced (")
    if groups > MAX_GROUPS:
        raise LinkRuleError(f"pattern: at most {MAX_GROUPS} capture groups")
    return "".join(out), groups


def _class_end(body: str, start: int) -> int:
    """Index of the ``]`` closing the character class opened at ``start``."""
    index = start + 1
    if index < len(body) and body[index] == "^":
        index += 1
    if index < len(body) and body[index] == "]":
        # Python reads []] as a class holding ], a browser as an empty class.
        raise LinkRuleError("pattern: escape ] at the start of a [ ] class as \\]")
    while index < len(body):
        char = body[index]
        if char == "\\":
            escaped = body[index + 1] if index + 1 < len(body) else ""
            if not escaped or (escaped.isalnum() and escaped not in _CLASS_ESCAPES):
                raise LinkRuleError(f"pattern: \\{escaped} isn't supported inside [ ]")
            index += 2
            continue
        if char == "[":
            raise LinkRuleError("pattern: escape [ inside a [ ] class as \\[")
        if char == "]":
            return index
        index += 1
    raise LinkRuleError("pattern: unclosed [")


def _read_quantifier(body: str, start: int) -> tuple[str, int, int | None, int] | None:
    """Parse the quantifier at ``start``.

    :returns: ``(text, low, high, end)`` where ``high`` is ``None`` when
        unbounded, or ``None`` when ``{`` doesn't start a valid quantifier.
    """
    char = body[start]
    if char == "*":
        return "*", 0, None, start + 1
    if char == "+":
        return "+", 1, None, start + 1
    if char == "?":
        return "?", 0, 1, start + 1
    match = re.compile(r"\{(\d{1,4})(,(\d{0,4}))?\}").match(body, start)
    if match is None:
        return None
    low = int(match.group(1))
    if match.group(2) is None:
        high: int | None = low
    elif match.group(3):
        high = int(match.group(3))
    else:
        high = None
    if high is not None and high < low:
        raise LinkRuleError("pattern: a {min,max} repeat needs min <= max")
    return match.group(0), low, high, match.end()


def check_url_template(template: str, compiled: CompiledPattern) -> None:
    """Check that a URL template always yields an http(s) link.

    :param template: E.g. ``"https://jira.example.com/browse/{key}-{num}"``.
    :param compiled: The rule's compiled pattern, whose groups the
        placeholders must name.
    :raises LinkRuleError: If the template is too long, isn't http(s), lets a
        capture reach the scheme or host, or names an unknown placeholder.
    """
    if not template:
        raise LinkRuleError("url: required for a url rule")
    if len(template) > MAX_URL_LENGTH:
        raise LinkRuleError(f"url: longer than {MAX_URL_LENGTH} characters")
    if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in template):
        raise LinkRuleError("url: can't contain spaces or control characters")
    first = template.find("{")
    # A template with no placeholder may end at the host.
    prefix = template[:first] if first >= 0 else template + "/"
    if not _URL_FIXED_PREFIX.match(prefix):
        raise LinkRuleError(
            "url: must start with https:// or http:// and a host, followed by / ? or # "
            "before any placeholder"
        )
    scheme = urlsplit(template).scheme.lower()
    if scheme not in ("http", "https"):
        raise LinkRuleError("url: must be an https: or http: link")
    names = set(compiled.group_names)
    for match in _URL_PLACEHOLDER.finditer(template):
        token = match.group(1)
        if token.isdigit():
            if int(token) > compiled.group_count:
                raise LinkRuleError(
                    f"url: {{{token}}} has no matching group in the pattern "
                    f"({compiled.group_count} group(s))"
                )
        elif token not in names:
            available = ", ".join(f"{{{name}}}" for name in compiled.group_names) or "{0}, {1}…"
            raise LinkRuleError(f"url: unknown placeholder {{{token}}}; use {available}")
    leftover = _URL_PLACEHOLDER.sub("", template)
    if "{" in leftover or "}" in leftover:
        raise LinkRuleError("url: unmatched { or }")


def validate_link_rule(raw: object) -> LinkRule:
    """Validate one rule from the wire.

    :param raw: A mapping with ``name``, ``kind``, ``pattern``, ``url`` and
        ``enabled``; built-in kinds may omit ``pattern``.
    :returns: The rule, with its name trimmed.
    :raises LinkRuleError: Naming the field at fault.
    """
    if not isinstance(raw, dict):
        raise LinkRuleError("a rule must be an object")
    unknown = sorted(set(raw) - {"name", "kind", "pattern", "url", "enabled"})
    if unknown:
        raise LinkRuleError(f"unknown field(s): {', '.join(unknown)}")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise LinkRuleError("name: required")
    name = name.strip()
    if len(name) > MAX_NAME_LENGTH:
        raise LinkRuleError(f"name: longer than {MAX_NAME_LENGTH} characters")
    try:
        kind = LinkRuleKind(raw.get("kind"))
    except ValueError:
        raise LinkRuleError("kind: must be url, github or session") from None
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise LinkRuleError("enabled: must be true or false")
    pattern = raw.get("pattern", "")
    url = raw.get("url")
    if not isinstance(pattern, str):
        raise LinkRuleError("pattern: must be a string")
    if url is not None and not isinstance(url, str):
        raise LinkRuleError("url: must be a string")
    try:
        if kind in BUILTIN_KINDS:
            if pattern or url:
                raise LinkRuleError(f"the built-in {kind} kind takes no pattern or url")
        else:
            check_url_template(url or "", compile_pattern(pattern))
    except LinkRuleError as exc:
        raise LinkRuleError(f"{name}: {exc}") from None
    return LinkRule(name=name, kind=kind, pattern=pattern, url=url or None, enabled=enabled)


def validate_link_rules(raw: object) -> tuple[LinkRule, ...]:
    """Validate a whole rule list.

    :param raw: A list of rule mappings.
    :returns: The rules in order.
    :raises LinkRuleError: On a bad rule, too many rules, a repeated name, or a
        built-in kind listed twice.
    """
    if not isinstance(raw, list):
        raise LinkRuleError("link rules must be a list")
    if len(raw) > MAX_RULES:
        raise LinkRuleError(f"at most {MAX_RULES} link rules")
    rules = tuple(validate_link_rule(entry) for entry in raw)
    seen: set[str] = set()
    builtins: set[LinkRuleKind] = set()
    for rule in rules:
        folded = rule.name.casefold()
        if folded in seen:
            raise LinkRuleError(f"two rules are named {rule.name!r}")
        seen.add(folded)
        if rule.kind in BUILTIN_KINDS:
            if rule.kind in builtins:
                raise LinkRuleError(f"only one {rule.kind} rule")
            builtins.add(rule.kind)
    return rules


def parse_link_rules_json(value: str) -> tuple[LinkRule, ...]:
    """Parse and validate the stored JSON form.

    :param value: A JSON array of rules, as :func:`encode_link_rules` writes it.
    :returns: The rules.
    :raises LinkRuleError: If the JSON is malformed or a rule is invalid.
    """
    try:
        raw = json.loads(value)
    except ValueError as exc:
        raise LinkRuleError(f"link rules must be a JSON array: {exc}") from None
    return validate_link_rules(raw)


def encode_link_rules(rules: Iterable[LinkRule]) -> str:
    """Canonical stored form: compact JSON, keys in a fixed order."""
    return json.dumps(
        [rule.to_wire() for rule in rules], ensure_ascii=False, separators=(",", ":")
    )


def link_rules_from_value(value: object) -> tuple[LinkRule, ...]:
    """Rules from a stored preference value, leniently.

    :param value: The stored JSON string; anything else (``None`` after a
        reset, never saved) means the defaults.
    :returns: The saved rules, or :data:`DEFAULT_LINK_RULES` when there is no
        usable value.
    """
    if not isinstance(value, str):
        return DEFAULT_LINK_RULES
    try:
        return parse_link_rules_json(value)
    except LinkRuleError:
        return DEFAULT_LINK_RULES


def describe_link_syntax(rule: LinkRule) -> str:
    """How an agent writes a reference that ``rule`` links, for its prompt.

    :param rule: An enabled rule.
    :returns: E.g. ``"`ABC-123` (Jira)"``.
    """
    if rule.kind == LinkRuleKind.GITHUB:
        return "`#123` or `owner/repo#123` (issues and pull requests on this session's repository)"
    if rule.kind == LinkRuleKind.SESSION:
        return (
            "`session:<session id>` or `session:<session id>/<message id>` "
            "(an Omnigent session, or a message in it)"
        )
    if rule.pattern.startswith("/") and rule.pattern.endswith("/") and len(rule.pattern) >= 2:
        return f"text matching `{rule.pattern}` ({rule.name})"
    example = _SHORT_FORM_TOKEN.sub(
        lambda m: _PLACEHOLDER_EXAMPLES.get(m.group(1), m.group(0)), rule.pattern
    )
    return f"`{example}` ({rule.name})"


def enabled_link_rules(rules: Sequence[LinkRule]) -> tuple[LinkRule, ...]:
    """The rules chat messages use."""
    return tuple(rule for rule in rules if rule.enabled)
