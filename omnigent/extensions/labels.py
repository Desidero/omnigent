"""Server-side checks for session labels that extensions declare.

An installed extension owns every label key under ``ext.<extension id>.``. A
write to one of those keys must name a key the extension declares and one of
its declared values; an empty value clears the label. Keys under ``ext.`` that
no installed extension's prefix covers stay ordinary labels.

The server installs its policy with :func:`set_active_label_policy`; every
label write path (session create and PATCH, policy label writes, forks)
checks it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.extensions.api import ExtensionManifest
from omnigent.extensions.registry import extension_label_prefix


class ExtensionLabelError(ValueError):
    """A label write falls outside an installed extension's declaration."""


class ExtensionLabelPolicy:
    """The declared label keys and values of the extensions a server serves."""

    def __init__(self, manifests: Iterable[ExtensionManifest] = ()) -> None:
        manifests = tuple(manifests)
        self._prefixes = {
            extension_label_prefix(manifest.id): manifest.id for manifest in manifests
        }
        self._values = {
            label.key: frozenset(value.value for value in label.values)
            for manifest in manifests
            for label in manifest.labels
        }

    def declares(self, key: str) -> bool:
        """Whether *key* is a declared extension label."""
        return key in self._values

    def _error(self, key: str, value: str) -> str | None:
        owners = sorted(
            owner for prefix, owner in self._prefixes.items() if key.startswith(prefix)
        )
        if not owners:
            return None
        allowed = self._values.get(key)
        if allowed is None:
            return f"label {key!r} is not declared by extension {' or '.join(map(repr, owners))}"
        if value != "" and value not in allowed:
            return (
                f"label {key!r} does not accept {value!r}; "
                f"declared values: {', '.join(sorted(allowed))}"
            )
        return None

    def check(self, labels: Mapping[str, str] | None) -> None:
        """Reject writes to an installed extension's keys outside its declaration.

        :param labels: The label map a client asked to write.
        :raises ExtensionLabelError: A key under an installed extension's
            namespace is undeclared, or its value isn't declared or empty.
        """
        for key, value in (labels or {}).items():
            error = self._error(key, value)
            if error is not None:
                raise ExtensionLabelError(error)

    def rejected_keys(self, labels: Mapping[str, str]) -> set[str]:
        """Return the keys :meth:`check` would reject, for paths that drop them instead."""
        return {key for key, value in labels.items() if self._error(key, value) is not None}

    def drop_cleared(self, labels: dict[str, str]) -> None:
        """Remove declared labels with an empty value, which mean "unset", in place."""
        for key in [key for key, value in labels.items() if value == "" and self.declares(key)]:
            del labels[key]


_active_policy = ExtensionLabelPolicy()


def active_label_policy() -> ExtensionLabelPolicy:
    """Return the label policy of the extensions this server serves."""
    return _active_policy


def set_active_label_policy(policy: ExtensionLabelPolicy) -> None:
    """Install the server's label policy; the server sets it when it builds the app."""
    global _active_policy
    _active_policy = policy


def reject_undeclared_extension_labels(
    labels: dict[str, str] | None, *, creating: bool = False
) -> None:
    """Reject a client's label write outside a declaration with a 400.

    :param labels: The labels to write, e.g. a PATCH body's ``labels``.
    :param creating: For a new session, also drop declared labels with an
        empty value in place, since a PATCH would delete them.
    :raises OmnigentError: ``INVALID_INPUT`` for an undeclared key or value.
    """
    try:
        _active_policy.check(labels)
    except ExtensionLabelError as exc:
        raise OmnigentError(str(exc), code=ErrorCode.INVALID_INPUT) from exc
    if creating and labels:
        _active_policy.drop_cleared(labels)
