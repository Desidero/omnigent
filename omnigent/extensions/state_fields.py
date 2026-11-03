"""Which declared state field covers a key or a command's key template."""

from __future__ import annotations

import string

from omnigent.extensions.api import StateContribution, StateField


def field_for(state: StateContribution | None, key: str) -> StateField | None:
    """The declaration covering a key: an exact field first, then the longest prefix."""
    fields = state.fields if state is not None else ()
    exact = next((item for item in fields if item.key == key), None)
    if exact is not None:
        return exact
    prefixed = [
        item for item in fields if item.key.endswith("*") and key.startswith(item.key[:-1])
    ]
    return max(prefixed, key=lambda item: len(item.key), default=None)


def pinned_field(state: StateContribution | None, template: str) -> StateField | None:
    """The one declaration a command's key template writes to.

    A template without placeholders pins like a key. Otherwise only a
    ``prefix*`` field whose prefix lies in the literal text before the first
    placeholder qualifies, so no argument value can move the key to another
    declaration (callers check the bound key against this at run time).
    """
    parsed = list(string.Formatter().parse(template))
    if all(name is None for _, name, _, _ in parsed):
        return field_for(state, template)
    head = parsed[0][0]
    fields = state.fields if state is not None else ()
    prefixed = [
        item for item in fields if item.key.endswith("*") and head.startswith(item.key[:-1])
    ]
    return max(prefixed, key=lambda item: len(item.key), default=None)
