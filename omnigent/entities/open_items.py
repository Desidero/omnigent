"""Open items: the questions, risks, findings, follow-ups and links a session raises.

An item belongs to the session that raised it and is named by a label, the
kind's letter and a number, e.g. ``Q7``. The store allocates numbers, so a
label never changes and is never reused within its session. An item is
``open`` until it is closed with a resolution, or ``answered`` once the user
has replied and the agent has not closed it yet.

The normalizers here check every field a write carries and return what to
store; the store and the routes run them, so every write path applies them. Links and
topics are canonicalized as the Inbox's are (:mod:`omnigent.server.inbox_dedupe`).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# Kind name -> (stored code, label letter). Code 0 names a session's own head row.
KINDS: dict[str, tuple[int, str]] = {
    "question": (1, "Q"),
    "risk": (2, "R"),
    "finding": (3, "F"),
    "follow_up": (4, "T"),
    "link": (5, "L"),
}
KIND_BY_CODE: dict[int, str] = {code: name for name, (code, _) in KINDS.items()}
KIND_BY_LETTER: dict[str, str] = {letter: name for name, (_, letter) in KINDS.items()}
SESSION_HEAD_KIND = 0

STATUSES: dict[str, int] = {"open": 1, "answered": 2, "closed": 3}
STATUS_BY_CODE: dict[int, str] = {code: name for name, code in STATUSES.items()}
# What a list shows unless asked otherwise.
DEFAULT_LIST_STATUSES: tuple[str, ...] = ("open", "answered")

TITLE_MAX_CHARS = 160
DETAIL_MAX_CHARS = 6000
TOPIC_MAX_CHARS = 48
RESOLUTION_MAX_CHARS = 2000
ANSWER_MAX_CHARS = 2000
RAISED_BY_MAX_CHARS = 64
LINK_LABEL_MAX_CHARS = 120
URL_MAX_CHARS = 2048
LINKS_PER_ITEM = 8
ANSWERS_KEPT = 5
# The chat parses labels of one to three digits.
NUMBER_MAX = 999
ITEMS_PER_SESSION = 500
RAISE_BATCH_MAX = 10
UPDATE_BATCH_MAX = 20
LIST_PAGE_MAX = 200
# Names the write that raised an item, e.g. "tool:<call id>:<index>".
IDEMPOTENCY_KEY_MAX_CHARS = 128
BATCH_KEY_MAX_CHARS = 120

_LABEL = re.compile(r"([QRFTL])([1-9][0-9]{0,2})")
_TOPIC = re.compile(r"[a-z0-9][a-z0-9-]*")


class OpenItemError(ValueError):
    """A write or read the store refuses; ``code`` says why.

    :param code: ``invalid_input``, ``too_large``, ``session_full``,
        ``label_taken`` or ``not_found``.
    :param message: What is wrong, for the agent or person who sent it.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _invalid(message: str) -> OpenItemError:
    return OpenItemError("invalid_input", message)


@dataclass(frozen=True)
class OpenItem:
    """One stored item.

    :ivar content: ``title``, ``detail``, and optionally ``topic``, ``links``
        (``[{"url", "label"?}]``), ``url`` (a link item's target) and
        ``raised_by``.
    :ivar outcome: ``resolution``, ``closed_by``, ``closed_ref`` and
        ``answers`` (``[{"text", "at", "by"}]``, the latest five); empty until
        the item is answered or closed.
    """

    conversation_id: str
    kind: str
    number: int
    status: str
    created_at: int
    updated_at: int
    closed_at: int | None
    content: dict[str, Any]
    outcome: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """The item's label, e.g. ``"Q7"``."""
        return f"{KINDS[self.kind][1]}{self.number}"

    @property
    def sort_key(self) -> tuple[int, int]:
        """Label order: by kind, then number."""
        return KINDS[self.kind][0], self.number


@dataclass(frozen=True)
class NewOpenItem:
    """A checked item to raise; see :func:`normalize_new_item`."""

    kind: str
    content: dict[str, Any]
    number: int | None = None
    dedupe_key: str | None = None


@dataclass(frozen=True)
class OpenItemChange:
    """A checked change to one item; see :func:`normalize_change`.

    :ivar status: ``"open"`` or ``"closed"``; ``None`` leaves it.
    :ivar fields: Content fields to set; a ``None`` topic clears it.
    """

    kind: str
    number: int
    status: str | None = None
    resolution: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    add_links: tuple[dict[str, str], ...] = ()
    remove_links: tuple[str, ...] = ()


def parse_label(label: object) -> tuple[str, int]:
    """Return the kind and number a label names, e.g. ``("question", 7)`` for ``"Q7"``.

    :raises OpenItemError: If it is not a label this store allocates.
    """
    match = _LABEL.fullmatch(label.strip().upper()) if isinstance(label, str) else None
    if match is None:
        raise _invalid(f"{label!r} is not an item label such as Q7, R2, F1, T3 or L4")
    return KIND_BY_LETTER[match.group(1)], int(match.group(2))


def format_label(kind: str, number: int) -> str:
    """Return the label of *kind* and *number*, e.g. ``"Q7"``."""
    return f"{KINDS[kind][1]}{number}"


def _text(value: object, name: str, limit: int, *, required: bool) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise _invalid(f"{name} must be text")
    text = value.strip()
    if required and not text:
        raise _invalid(f"{name} is required")
    if len(text) > limit:
        raise OpenItemError("too_large", f"{name} is {len(text)} characters, over {limit}")
    return text


def normalize_topic_slug(value: object) -> str | None:
    """Return a topic as a slug, e.g. ``"cache-rollout"``; ``None`` or empty clears it."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid("topic must be text")
    from omnigent.server.inbox_dedupe import normalize_topic

    topic = normalize_topic(value)
    if not topic:
        return None
    if len(topic) > TOPIC_MAX_CHARS or _TOPIC.fullmatch(topic) is None:
        raise _invalid(
            f"topic must be a short slug of letters, digits and hyphens, at most "
            f"{TOPIC_MAX_CHARS} characters, e.g. 'cache-rollout'"
        )
    return topic


def _canonical_url(value: object) -> str:
    from omnigent.server.inbox_dedupe import InvalidLinkError, canonical_link

    url = _text(value, "url", URL_MAX_CHARS, required=True)
    try:
        canonical = canonical_link({"type": "url", "ref": url})
    except InvalidLinkError as exc:
        raise _invalid(str(exc)) from exc
    assert canonical is not None
    return canonical


def normalize_link(value: object) -> dict[str, str]:
    """Check one attached link, ``{"url", "label"?}`` or a bare URL."""
    if isinstance(value, str):
        value = {"url": value}
    if not isinstance(value, Mapping) or set(value) - {"url", "label"}:
        raise _invalid("a link is a URL, or an object with url and an optional label")
    url = _text(value.get("url"), "url", URL_MAX_CHARS, required=True)
    _canonical_url(url)
    link = {"url": url}
    label = _text(value.get("label"), "link label", LINK_LABEL_MAX_CHARS, required=False)
    if label:
        link["label"] = label
    return link


def _links(value: object, name: str) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise _invalid(f"{name} must be a list")
    if len(value) > LINKS_PER_ITEM:
        raise _invalid(f"an item holds at most {LINKS_PER_ITEM} links")
    return [normalize_link(link) for link in value]


def short_link_name(url: str) -> str:
    """A short readable name for a link nothing names, e.g. ``"example.com/reports/q3"``.

    The host and the start of the path, never the whole address; the web's
    ``shortLinkName`` (``web/src/lib/sessionLinks.ts``) gives the same.
    """
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    host = (parts.hostname or "").removeprefix("www.")
    segments = [segment for segment in parts.path.split("/") if segment]
    shown = [segment if len(segment) <= 16 else f"{segment[:12]}…" for segment in segments[:2]]
    if len(segments) > 2:
        shown.append("…")
    return "/".join([host, *shown])[:TITLE_MAX_CHARS]


def link_dedupe_key(url: str) -> str:
    """The key that makes pinning one URL twice return one item."""
    return hashlib.sha256(_canonical_url(url).encode("utf-8")).hexdigest()


def normalize_new_item(value: object) -> NewOpenItem:
    """Check an item to raise, as the ``sys_open_items_raise`` tool sends it.

    :raises OpenItemError: If a field is missing, unknown or too large.
    """
    if not isinstance(value, Mapping):
        raise _invalid("each item must be an object")
    allowed = {"kind", "title", "detail", "topic", "links", "url", "raised_by", "label"}
    if unknown := sorted(set(value) - allowed):
        raise _invalid(f"unknown item fields: {', '.join(unknown)}")
    kind = value.get("kind")
    if kind not in KINDS:
        raise _invalid(f"kind must be one of {', '.join(KINDS)}")
    content: dict[str, Any] = {}
    dedupe_key = None
    if kind == "link":
        url = _text(value.get("url"), "url", URL_MAX_CHARS, required=True)
        dedupe_key = link_dedupe_key(url)
        content["url"] = url
        title = _text(value.get("title"), "title", TITLE_MAX_CHARS, required=False)
        content["title"] = title or short_link_name(url)
    else:
        if value.get("url") is not None:
            raise _invalid("only a link item has a url; attach links with links")
        content["title"] = _text(value.get("title"), "title", TITLE_MAX_CHARS, required=True)
    content["detail"] = _text(value.get("detail"), "detail", DETAIL_MAX_CHARS, required=False)
    if (topic := normalize_topic_slug(value.get("topic"))) is not None:
        content["topic"] = topic
    if links := _links(value.get("links"), "links"):
        content["links"] = links
    raised_by = _text(value.get("raised_by"), "raised_by", RAISED_BY_MAX_CHARS, required=False)
    if raised_by:
        content["raised_by"] = raised_by
    number = None
    if value.get("label") is not None:
        label_kind, number = parse_label(value.get("label"))
        if label_kind != kind:
            raise _invalid(f"label {value.get('label')!r} is not a {kind} label")
    return NewOpenItem(kind=kind, content=content, number=number, dedupe_key=dedupe_key)


def normalize_change(value: object) -> OpenItemChange:
    """Check one change, as ``sys_open_items_update`` or a person sends it.

    :raises OpenItemError: If the label or a field is invalid.
    """
    if not isinstance(value, Mapping):
        raise _invalid("each update must be an object")
    allowed = {"label", "status", "resolution", "title", "detail", "topic"}
    allowed |= {"add_links", "remove_links"}
    if unknown := sorted(set(value) - allowed):
        raise _invalid(f"unknown update fields: {', '.join(unknown)}")
    kind, number = parse_label(value.get("label"))
    status = value.get("status")
    if status is not None and status not in ("open", "closed"):
        raise _invalid("status must be open or closed")
    resolution = None
    if "resolution" in value:
        resolution = _text(value["resolution"], "resolution", RESOLUTION_MAX_CHARS, required=True)
    if status == "closed" and resolution is None:
        raise _invalid("closing an item needs a one-line resolution")
    fields: dict[str, Any] = {}
    if "title" in value:
        fields["title"] = _text(value["title"], "title", TITLE_MAX_CHARS, required=True)
    if "detail" in value:
        fields["detail"] = _text(value["detail"], "detail", DETAIL_MAX_CHARS, required=False)
    if "topic" in value:
        fields["topic"] = normalize_topic_slug(value["topic"])
    removed = value.get("remove_links") or []
    if not isinstance(removed, list) or not all(isinstance(url, str) for url in removed):
        raise _invalid("remove_links must be a list of URLs")
    change = OpenItemChange(
        kind=kind,
        number=number,
        status=status,
        resolution=resolution,
        fields=fields,
        add_links=tuple(_links(value.get("add_links"), "add_links")),
        remove_links=tuple(_canonical_url(url) for url in removed),
    )
    if change == OpenItemChange(kind=kind, number=number):
        raise _invalid(f"update for {format_label(kind, number)} changes nothing")
    return change


def apply_link_changes(
    links: Sequence[Mapping[str, str]], change: OpenItemChange
) -> list[dict[str, str]]:
    """Return an item's links after *change*, at most :data:`LINKS_PER_ITEM`."""
    kept = [dict(link) for link in links if _canonical_url(link["url"]) not in change.remove_links]
    seen = {_canonical_url(link["url"]) for link in kept}
    for link in change.add_links:
        if (canonical := _canonical_url(link["url"])) not in seen:
            kept.append(dict(link))
            seen.add(canonical)
    if len(kept) > LINKS_PER_ITEM:
        raise _invalid(f"an item holds at most {LINKS_PER_ITEM} links")
    return kept


# ── Reading ───────────────────────────────────────────


@dataclass(frozen=True)
class OpenItemFilter:
    """Which items a list returns; every field narrows it.

    :ivar statuses: Status names; empty means every status.
    :ivar kinds: Kind names; empty means every kind.
    :ivar query: Case-insensitive text matched against the item's words.
    :ivar after: A label; the page starts after it in label order.
    """

    statuses: tuple[str, ...] = DEFAULT_LIST_STATUSES
    kinds: tuple[str, ...] = ()
    topic: str | None = None
    raised_by: str | None = None
    has_links: bool | None = None
    query: str | None = None
    after: str | None = None
    limit: int = 100


@dataclass(frozen=True)
class OpenItemPage:
    """One page of a session's items, with counts over all of them."""

    items: list[OpenItem]
    has_more: bool
    status_counts: dict[str, int]
    kind_counts: dict[str, int]
    topics: list[str]


def _searchable(item: OpenItem) -> str:
    content, outcome = item.content, item.outcome
    parts = [item.label, content.get("title"), content.get("detail"), content.get("topic")]
    parts += [content.get("url"), content.get("raised_by"), outcome.get("resolution")]
    parts += [link.get("url") for link in content.get("links") or []]
    parts += [link.get("label") for link in content.get("links") or []]
    parts += [answer.get("text") for answer in outcome.get("answers") or []]
    return "\n".join(str(part) for part in parts if part).casefold()


def _matches(item: OpenItem, wanted: OpenItemFilter) -> bool:
    content = item.content
    return (
        (not wanted.statuses or item.status in wanted.statuses)
        and (not wanted.kinds or item.kind in wanted.kinds)
        and (wanted.topic is None or content.get("topic") == wanted.topic)
        and (wanted.raised_by is None or content.get("raised_by") == wanted.raised_by)
        and (wanted.has_links is None or bool(content.get("links")) == wanted.has_links)
        and (not wanted.query or wanted.query.casefold() in _searchable(item))
    )


def page_items(items: Sequence[OpenItem], wanted: OpenItemFilter) -> OpenItemPage:
    """Filter and page a session's items in label order, counting all of them.

    The store reads a session's items whole (the session cap bounds them):
    their content may be encrypted, so the database cannot search it.

    :raises OpenItemError: If ``after`` is not a label.
    """
    ordered = sorted(items, key=lambda item: item.sort_key)
    if wanted.after is not None:
        kind, number = parse_label(wanted.after)
        start = (KINDS[kind][0], number)
        ordered = [item for item in ordered if item.sort_key > start]
    matching = [item for item in ordered if _matches(item, wanted)]
    status_counts = dict.fromkeys(STATUSES, 0)
    kind_counts = dict.fromkeys(KINDS, 0)
    for item in items:
        status_counts[item.status] += 1
        kind_counts[item.kind] += 1
    topics = sorted({topic for item in items if (topic := item.content.get("topic"))})
    return OpenItemPage(
        items=matching[: wanted.limit],
        has_more=len(matching) > wanted.limit,
        status_counts=status_counts,
        kind_counts=kind_counts,
        topics=topics,
    )


def item_to_json(item: OpenItem) -> dict[str, Any]:
    """The full item as the routes return it."""
    content, outcome = item.content, item.outcome
    return {
        "label": item.label,
        "kind": item.kind,
        "number": item.number,
        "status": item.status,
        "title": content.get("title", ""),
        "detail": content.get("detail", ""),
        "topic": content.get("topic"),
        "links": content.get("links") or [],
        "url": content.get("url"),
        "raised_by": content.get("raised_by"),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "closed_at": item.closed_at,
        "resolution": outcome.get("resolution"),
        "closed_by": outcome.get("closed_by"),
        "answers": outcome.get("answers") or [],
    }
