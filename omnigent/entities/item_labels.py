"""The chat's item-label rules, as the web reads them, for the server.

An agent tags an item it raises with a label such as ``[Q3]`` and closes it
by striking the label through, ``~~[Q3]~~``. These functions read a message
exactly as ``web/src/lib/itemLabels.ts`` and ``linksInMarkdown`` in
``web/src/lib/sessionLinks.ts`` do; both are tested against the same cases
(``web/src/lib/__fixtures__/itemLabelCases.json``), so change the two together.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# One to three capitals then one to three digits; a label followed by "(" is
# the text of a markdown link.
_ITEM_LABEL = re.compile(r"\[([A-Z]{1,3}[0-9]{1,3})\](?!\()")
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_INLINE_CODE = re.compile(r"(`+)[^`]*?\1")
_STRIKETHROUGH = re.compile(r"~~(?=\S)(.*?\S)~~")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=\S)")
_LEADING_MARKER = re.compile(r"^\s*(?:[-*+]\s+|[0-9]{1,9}[.)]\s+|#{1,6}\s+|>\s*)*")
_LEADING_EMPHASIS = re.compile(r"^(?:\*\*|__|\*|_|~~)+")
_LEADING_BOLD = re.compile(r"^(\*\*|__)(?!\s*\1)(.+?)\1")
_MARKUP = re.compile(r"\*\*|__|~~|`")
_TITLE_LEAD = re.compile(r"^[\s:.\-–—]+")
_TITLE_EDGES = re.compile(r"^[\s:.\-–—]+|:$")
_LIST_ITEM = re.compile(r"^(\s*)(?:[-*+]|[0-9]{1,9}[.)])\s+")
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
# A markdown link, an autolink, or a bare URL.
_LINK = re.compile(
    r"\[([^\]\n]*)\]\(\s*<?(https?://[^\s<>)]+)>?[^)\n]*\)|<(https?://[^\s<>]+)>|(https?://[^\s<>`\"]+)"
)
_BARE_URL_TAIL = re.compile(r"[.,;:!?'*_~\]]+$")


@dataclass(frozen=True)
class ScannedLine:
    """One line of a message; ``in_fence`` for lines of a fenced code block."""

    text: str
    in_fence: bool


@dataclass(frozen=True)
class WrittenLink:
    """A link a message writes; ``text`` is ``None`` for a bare URL or one used as its own text."""

    url: str
    text: str | None


def scan_lines(markdown: str) -> list[ScannedLine]:
    """Split markdown into lines, marking those inside fenced code blocks."""
    lines: list[ScannedLine] = []
    fence: str | None = None
    for text in markdown.split("\n"):
        if fence is None:
            opened = _FENCE_OPEN.match(text)
            if opened:
                fence = opened.group(1)
            lines.append(ScannedLine(text, opened is not None))
            continue
        close = text.strip()
        if len(close) >= len(fence) and close == fence[0] * len(close):
            fence = None
        lines.append(ScannedLine(text, True))
    return lines


def _without_inline_code(line: str) -> str:
    return _INLINE_CODE.sub(lambda span: " " * len(span.group(0)), line)


def labels_in_line(line: str) -> list[str]:
    """The labels one line mentions, in order, ignoring inline code."""
    return [match.group(1) for match in _ITEM_LABEL.finditer(_without_inline_code(line))]


def _struck_labels_in_line(line: str) -> list[str]:
    return [
        label
        for span in _STRIKETHROUGH.finditer(_without_inline_code(line))
        for label in labels_in_line(span.group(1))
    ]


def starts_with_label(line: str, label: str) -> bool:
    """Whether ``line`` starts with ``label``, after list, heading and emphasis markers."""
    rest = _LEADING_EMPHASIS.sub("", _LEADING_MARKER.sub("", line, count=1), count=1)
    return label in labels_in_line(rest) and rest.startswith(f"[{label}]")


def _definition_line_index(lines: list[ScannedLine], label: str) -> int:
    """The first line ``label`` starts, else the first that mentions it; -1 when absent."""
    for at, line in enumerate(lines):
        if not line.in_fence and starts_with_label(line.text, label):
            return at
    for at, line in enumerate(lines):
        if not line.in_fence and label in labels_in_line(line.text):
            return at
    return -1


def item_labels_in(markdown: str) -> list[str]:
    """The distinct labels in ``markdown``, in order of definition, skipping code."""
    lines = scan_lines(markdown)
    seen: dict[str, None] = {}
    for line in lines:
        if not line.in_fence:
            for label in labels_in_line(line.text):
                seen.setdefault(label)
    if len(seen) < 2:
        return list(seen)
    # Stable sort: labels defined on the same line keep their written order.
    return sorted(seen, key=lambda label: _definition_line_index(lines, label))


def struck_item_labels_in(markdown: str) -> list[str]:
    """The distinct labels ``markdown`` mentions inside strikethrough, skipping code."""
    seen: dict[str, None] = {}
    for line in scan_lines(markdown):
        if not line.in_fence:
            for label in _struck_labels_in_line(line.text):
                seen.setdefault(label)
    return list(seen)


def defines_label(markdown: str, label: str) -> bool:
    """Whether a line of ``markdown`` outside code starts with ``label``, as an item does."""
    return any(
        not line.in_fence and starts_with_label(line.text, label) for line in scan_lines(markdown)
    )


def extract_label_sentence(markdown: str, label: str) -> str | None:
    """The sentence that mentions ``label``, preferring a struck mention."""
    lines = [line for line in scan_lines(markdown) if not line.in_fence]
    line = next((c for c in lines if label in _struck_labels_in_line(c.text)), None) or next(
        (c for c in lines if label in labels_in_line(c.text)), None
    )
    if line is None:
        return None
    text = _LEADING_MARKER.sub("", line.text, count=1).strip()
    for sentence in _SENTENCE_BREAK.split(text):
        if label in labels_in_line(sentence):
            return sentence
    return text


def _plain_text(text: str) -> str:
    return _MARKUP.sub("", text).strip()


def item_label_title_parts(markdown: str, label: str) -> tuple[str, str]:
    """An item's short title and the text after it on its block's first line, without markup."""
    block = extract_item_block(markdown, label) or ""
    first = next((line for line in block.split("\n") if line.strip()), "")
    line = _LEADING_MARKER.sub("", first, count=1)
    line = _ITEM_LABEL.sub(lambda m: "" if m.group(1) == label else m.group(0), line)
    line = _TITLE_LEAD.sub("", line, count=1)
    bold = _LEADING_BOLD.match(line)
    if bold:
        title = _TITLE_EDGES.sub("", _plain_text(bold.group(2)))
        if title:
            return title, _plain_text(line[bold.end() :])
    title, *rest = _SENTENCE_BREAK.split(_plain_text(line))
    return title, " ".join(rest)


def _is_blank(lines: list[ScannedLine], at: int) -> bool:
    return 0 <= at < len(lines) and lines[at].text.strip() == ""


def _indent_of(text: str) -> int:
    return len(text) - len(text.lstrip())


def _heading_level(line: ScannedLine) -> int | None:
    if line.in_fence:
        return None
    match = _HEADING.match(line.text)
    return len(match.group(1)) if match else None


def _list_item_indent(line: ScannedLine) -> int | None:
    if line.in_fence:
        return None
    match = _LIST_ITEM.match(line.text)
    return len(match.group(1)) if match else None


def _end_of_list(lines: list[ScannedLine], start: int, indent: int) -> int:
    end = start + 1
    while end < len(lines):
        if _is_blank(lines, end):
            following = end + 1
            while _is_blank(lines, following):
                following += 1
            if following >= len(lines):
                break
            line = lines[following]
            nested = line.in_fence or _indent_of(line.text) > indent
            if not nested and _list_item_indent(line) != indent:
                break
            end = following
            continue
        if _heading_level(lines[end]) is not None:
            break
        end += 1
    return end


def _end_of_list_item(lines: list[ScannedLine], start: int, indent: int) -> int:
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if _is_blank(lines, end):
            following = end + 1
            while _is_blank(lines, following):
                following += 1
            if following >= len(lines) or (
                not lines[following].in_fence and _indent_of(lines[following].text) <= indent
            ):
                break
            end = following
            continue
        if line.in_fence:
            end += 1
            continue
        item_indent = _list_item_indent(line)
        if item_indent is not None and item_indent <= indent:
            break
        if _heading_level(line) is not None:
            break
        end += 1
    return end


def _dedent(texts: list[str], amount: int) -> list[str]:
    return [text[amount:] if _indent_of(text) >= amount else text.lstrip() for text in texts]


def extract_item_block(markdown: str, label: str) -> str | None:
    """The markdown block where ``label`` is first defined; ``None`` when it is absent.

    Its list item (with nested content), heading section, table row (with the
    header), or paragraph (with a list it introduces).
    """
    lines = scan_lines(markdown)
    at = _definition_line_index(lines, label)
    if at < 0:
        return None

    def texts(start: int, end: int) -> list[str]:
        return [line.text for line in lines[start:end]]

    def finish(parts: list[str]) -> str:
        return "\n".join(parts).strip()

    level = _heading_level(lines[at])
    if level is not None:
        end = at + 1
        while end < len(lines):
            next_level = _heading_level(lines[end])
            if next_level is not None and next_level <= level:
                break
            end += 1
        return finish(texts(at, end))

    # The innermost list item holding the label: walk up its paragraph lines.
    item_start = at
    while (
        item_start >= 0
        and not _is_blank(lines, item_start)
        and _heading_level(lines[item_start]) is None
        and _list_item_indent(lines[item_start]) is None
    ):
        item_start -= 1
    if item_start >= 0 and not lines[item_start].in_fence:
        marker = _LIST_ITEM.match(lines[item_start].text)
        if marker:
            end = _end_of_list_item(lines, item_start, len(marker.group(1)))
            first, *rest = texts(item_start, end)
            return finish([first[marker.end() :], *_dedent(rest, marker.end())])

    start = at
    while start > 0 and not _is_blank(lines, start - 1) and not lines[start - 1].in_fence:
        start -= 1
    end = at + 1
    while end < len(lines) and not _is_blank(lines, end) and not lines[end].in_fence:
        end += 1

    separator = lines[start + 1].text if start + 1 < len(lines) else ""
    if "|" in lines[at].text and _TABLE_SEPARATOR.match(separator):
        if at <= start + 1:
            return finish(texts(start, end))
        return finish([*texts(start, start + 2), lines[at].text])

    # A paragraph ending in ":" introduces the list that follows it.
    if lines[end - 1].text.rstrip().endswith(":"):
        following = end
        while _is_blank(lines, following):
            following += 1
        indent = _list_item_indent(lines[following]) if following < len(lines) else None
        if indent is not None:
            return finish(
                [*texts(start, end), "", *texts(following, _end_of_list(lines, following, indent))]
            )
    return finish(texts(start, end))


def _trim_bare_url(raw: str) -> str:
    """Drop the sentence punctuation and closing markup a bare URL runs into."""
    url = raw
    while True:
        trimmed = _BARE_URL_TAIL.sub("", url)
        if trimmed.endswith(")") and trimmed.count(")") > trimmed.count("("):
            trimmed = trimmed[:-1]
        if trimmed == url:
            return url
        url = trimmed


def without_links(text: str) -> str:
    """``text`` with markdown links as their text and bare URLs dropped, as a link title."""
    return re.sub(r"[\s:.\-–—]+$", "", _LINK.sub(lambda m: m.group(1) or "", text))


def links_in_markdown(markdown: str) -> list[WrittenLink]:
    """The http(s) links ``markdown`` writes outside fenced code, in order."""
    links: list[WrittenLink] = []
    for line in scan_lines(markdown):
        if line.in_fence:
            continue
        for match in _LINK.finditer(line.text):
            url = match.group(2) or match.group(3) or _trim_bare_url(match.group(4))
            text = _plain_text(match.group(1) or "")
            own_text = bool(text) and not re.match(r"https?://", text, re.IGNORECASE)
            links.append(WrittenLink(url=url, text=text if own_text else None))
    return links
