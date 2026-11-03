"""Shared limits and key rules for extension session state.

Kept free of other Omnigent imports so the conversation store and the manifest
registry can both use it.
"""

from __future__ import annotations

import re
import unicodedata

# Session labels under this prefix are written only by core, as read-only
# mirrors of extensions' published state fields.
EXTENSION_LABEL_PREFIX = "ext."
# Matches the String(128) label key and state key columns.
STATE_KEY_MAX_LENGTH = 128
# Keys per (session, extension); a write that would add one more is rejected.
MAX_STATE_KEYS = 64
# Commands may create at most this many keys in total, so readers running a
# command can never use up the room the extension's server code needs.
COMMAND_STATE_KEYS = 48
# Default cap on keys commands create under one declared ``prefix*`` field.
DEFAULT_COMMAND_KEYS_PER_PREFIX = 16
MAX_PUBLISHED_FIELDS = 3
# The conversation_labels value column holds at most 256 characters.
PUBLISHED_VALUE_MAX_LENGTH = 256

# No whitespace anywhere: utf8mb4_bin ignores trailing spaces on MySQL.
STATE_KEY_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._:=+/@-]{0,127}")
STATE_KEY_PREFIX_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._:=+/@-]{0,126}")
PUBLISHED_FIELD_KEY_RE = re.compile(r"[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?")
_ID_SEGMENT = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
EXTENSION_ID_RE = re.compile(rf"{_ID_SEGMENT}(?:\.{_ID_SEGMENT})+")


# Character categories collations commonly ignore: combining marks, format
# characters (zero-width joiners, soft hyphens) and controls.
_IGNORED_CATEGORIES = frozenset({"Mn", "Me", "Cf", "Cc"})


def fold_label_key(key: str) -> str:
    """Approximate how an accent- and case-insensitive collation compares a key.

    MySQL's default collation treats ``EXT.x``, ``éxt.x`` and ``ext.x`` as the
    same label key, so the reservation checks the folded form.
    """
    decomposed = unicodedata.normalize("NFKD", key)
    return "".join(
        char for char in decomposed if unicodedata.category(char) not in _IGNORED_CATEGORIES
    ).casefold()


def is_extension_label(key: str) -> bool:
    """Whether a label key is, or collates like, one in the core-owned ``ext.`` namespace."""
    return fold_label_key(key).startswith(EXTENSION_LABEL_PREFIX)


def published_label_key(extension_id: str, key: str) -> str:
    """The session label that mirrors one published state field."""
    return f"{EXTENSION_LABEL_PREFIX}{extension_id}.{key}"


def validate_state_address(extension_id: str, key: str) -> None:
    """Reject an extension id or state key the state table must not store.

    :raises ValueError: The id is not a lowercase, publisher-qualified id of
        at most 128 characters, or the key is empty, longer than 128
        characters, or contains whitespace or other unsupported characters.
    """
    if (
        not isinstance(extension_id, str)
        or len(extension_id) > STATE_KEY_MAX_LENGTH
        or not EXTENSION_ID_RE.fullmatch(extension_id)
    ):
        raise ValueError(f"invalid extension id {extension_id!r}")
    if not isinstance(key, str) or not STATE_KEY_RE.fullmatch(key):
        raise ValueError(
            f"invalid state key {key!r}: use 1-{STATE_KEY_MAX_LENGTH} letters, digits "
            "or ._:=+/@- characters"
        )
