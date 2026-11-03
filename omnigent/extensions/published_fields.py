"""Which ``ext.*`` session labels are live published fields.

Core mirrors an extension's published state fields as read-only session labels
``ext.<extension id>.<key>``. For every installed extension that declares
published fields, core *governs* its ``ext.<extension id>.`` label prefix. A
label there counts only when the operator has enabled the extension, it is a
declared published field, and a state row backs it with the same value
(``Conversation.verified_extension_labels``); every other label under the
prefix, including all of a disabled extension's, is hidden from session
responses and unreadable to policies (its row is kept).

Every other ``ext.*`` label, including those of uninstalled extensions, stays
visible as an ordinary label. Only core can write any ``ext.*`` label.

The server configures the view at startup. A process that never configures it
(a runner, a test) governs nothing and publishes nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from omnigent.extensions.api import ExtensionManifest, StateVisibility
from omnigent.extensions.state_keys import EXTENSION_LABEL_PREFIX, published_label_key


@dataclass(frozen=True)
class PublishedFieldView:
    """The published fields of enabled extensions.

    :param fields: ``{label key: (extension id, state key)}`` for every
        published field of an enabled extension.
    :param prefixes: The governed ``ext.<extension id>.`` label prefixes of
        installed extensions that declare published fields, enabled or not.
    """

    fields: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    prefixes: frozenset[str] = frozenset()

    def governs(self, label_key: str) -> bool:
        """Whether a label lies under an enabled extension's prefix."""
        return any(label_key.startswith(prefix) for prefix in self.prefixes)

    def is_available(self, label_key: str) -> bool:
        """Whether a label key names a published field of an enabled extension."""
        return label_key in self.fields

    def _verified(self, label_key: str, verified: frozenset[str]) -> bool:
        return label_key in self.fields and label_key in verified

    def visible_labels(
        self, labels: Mapping[str, str], verified: frozenset[str]
    ) -> dict[str, str]:
        """Drop governed labels that are not verified published fields."""
        return {
            key: value
            for key, value in labels.items()
            if not self.governs(key) or self._verified(key, verified)
        }

    def published_fields(
        self, labels: Mapping[str, str], verified: frozenset[str]
    ) -> dict[str, dict[str, str]]:
        """The session's verified published fields, grouped by extension."""
        grouped: dict[str, dict[str, str]] = {}
        for label_key, (extension_id, key) in self.fields.items():
            if label_key in labels and label_key in verified:
                grouped.setdefault(extension_id, {})[key] = labels[label_key]
        return grouped

    def policy_fields(
        self, labels: Mapping[str, str], verified: frozenset[str]
    ) -> dict[str, dict[str, str | None]]:
        """Every published field of enabled extensions, ``None`` where unset or unverified."""
        grouped: dict[str, dict[str, str | None]] = {}
        for label_key, (extension_id, key) in self.fields.items():
            grouped.setdefault(extension_id, {})[key] = (
                labels[label_key]
                if self._verified(label_key, verified) and label_key in labels
                else None
            )
        return grouped


def build_published_field_view(
    manifests: Iterable[ExtensionManifest],
    *,
    is_enabled: Callable[[str], bool],
) -> PublishedFieldView:
    """Build the view from installed manifests and the operator's enablement.

    :param manifests: The accepted extension manifests.
    :param is_enabled: The operator's persistent enablement of an extension
        id, never its runtime health.
    """
    fields: dict[str, tuple[str, str]] = {}
    prefixes: set[str] = set()
    for manifest in manifests:
        if manifest.state is None:
            continue
        published = [
            field_decl
            for field_decl in manifest.state.fields
            if field_decl.visibility is StateVisibility.PUBLISHED
        ]
        if not published:
            continue
        prefixes.add(f"{EXTENSION_LABEL_PREFIX}{manifest.id}.")
        if not is_enabled(manifest.id):
            continue
        for field_decl in published:
            fields[published_label_key(manifest.id, field_decl.key)] = (
                manifest.id,
                field_decl.key,
            )
    return PublishedFieldView(fields=fields, prefixes=frozenset(prefixes))


_view = PublishedFieldView()


def configure_published_fields(view: PublishedFieldView) -> None:
    """Install the process-wide view; the server calls this at startup."""
    global _view
    _view = view


def published_field_view() -> PublishedFieldView:
    """Return the process-wide view (empty until the server configures it)."""
    return _view
