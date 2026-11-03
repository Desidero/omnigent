"""Reading extensions' published fields from a policy, failing closed.

A published field disappears when the operator disables its extension. A
policy whose restriction depends on a field should read it with
:func:`require_published_field`: when the field is unavailable it raises, and
the policy engine turns a raising policy into a DENY that names the field.
Reading ``event["context"]["labels"]`` under an enabled extension's
``ext.<id>.`` prefix raises the same way for anything but a published field
that extension state backs.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


class PublishedFieldUnavailableError(LookupError):
    """The extension is not enabled, or does not publish the field."""


def require_published_field(event: Mapping[str, Any], extension_id: str, key: str) -> str | None:
    """Return a published field's value, or ``None`` when the session has none.

    :param event: The policy event.
    :param extension_id: The publishing extension, e.g. ``"acme.review"``.
    :param key: The published field, e.g. ``"status"``.
    :returns: The value, or ``None`` when the field is available but unset.
    :raises PublishedFieldUnavailableError: The field is unavailable.
    """
    fields = (event.get("context") or {}).get("published_fields") or {}
    extension_fields = fields.get(extension_id)
    if not isinstance(extension_fields, Mapping) or key not in extension_fields:
        raise PublishedFieldUnavailableError(
            f"published field ext.{extension_id}.{key} is unavailable "
            "(extension not enabled or field not published)"
        )
    return extension_fields[key]


class PolicyLabels(dict[str, str]):
    """Session labels for policies that refuse to read unreadable ones.

    :param labels: The labels policies may see.
    :param unreadable: Whether a key lies under an enabled extension's
        ``ext.<id>.`` prefix without being a published field state backs.
        Looking such a key up raises :class:`PublishedFieldUnavailableError`
        instead of quietly reporting it absent.
    """

    def __init__(self, labels: Mapping[str, str], *, unreadable: Callable[[str], bool]) -> None:
        super().__init__(labels)
        self._unreadable = unreadable

    def _check(self, key: object) -> None:
        if isinstance(key, str) and self._unreadable(key):
            raise PublishedFieldUnavailableError(
                f"label {key} is unavailable to policies "
                "(not a published field, or not backed by extension state)"
            )

    def __getitem__(self, key: str) -> str:
        self._check(key)
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        self._check(key)
        return super().__contains__(key)

    def get(self, key: str, default: Any = None, /) -> Any:  # pyrefly: ignore[bad-override]
        self._check(key)
        return super().get(key, default)

    def copy(self) -> PolicyLabels:
        return PolicyLabels(self, unreadable=self._unreadable)
