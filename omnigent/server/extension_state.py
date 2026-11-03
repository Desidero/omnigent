"""Server side of extension session state: access rules, commands and writes.

The conversation store keeps the rows; this module decides, per extension
manifest, who can read which key, what a command writes, and whether a write
mirrors a published field. HTTP callers act with their own share level on the
session: an extension's browser page runs for whoever opens it, so it is never
treated as the extension itself. Server code acting for an extension writes
through :meth:`ExtensionStateService.write_state`, never the store directly.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from omnigent.extensions.api import (
    ClearState,
    CommandAccess,
    CommandContribution,
    ExtensionManifest,
    ExtensionPluginState,
    SetState,
    StateVisibility,
)
from omnigent.extensions.state_fields import field_for, pinned_field
from omnigent.extensions.state_keys import (
    COMMAND_STATE_KEYS,
    DEFAULT_COMMAND_KEYS_PER_PREFIX,
    MAX_STATE_KEYS,
    validate_state_key,
)
from omnigent.server.auth import LEVEL_EDIT, LEVEL_OWNER, LEVEL_READ
from omnigent.stores.conversation_store import ConversationStore, ExtensionStateEntry

_logger = logging.getLogger(__name__)

_READ_LEVELS = {
    StateVisibility.READERS: LEVEL_READ,
    StateVisibility.PUBLISHED: LEVEL_READ,
    StateVisibility.EDITORS: LEVEL_EDIT,
}
_COMMAND_LEVELS = {CommandAccess.READ: LEVEL_READ, CommandAccess.EDIT: LEVEL_EDIT}
# Every key an extension holds on a session fits in one store page.
_ALL_KEYS_PAGE = 100


class ExtensionStateUnavailableError(Exception):
    """The extension is unknown, not enabled, or declares no such command."""


class ExtensionStateAccessError(Exception):
    """The caller's share level is below what the command requires."""


class ExtensionCommandArgumentError(ValueError):
    """A command argument is missing, unknown, or fails its declaration."""


@dataclass(frozen=True)
class CommandEvent:
    """A declared command that ran, as told to its extension's server code.

    :param extension_id: The extension declaring the command.
    :param session_id: The session it ran on.
    :param workspace_id: That session's workspace.
    :param command_id: The command.
    :param key: The state key it wrote or cleared.
    :param deleted: Whether it was a clear command.
    :param user_id: The caller, or ``None`` in single-user mode.
    :param generation: The caller's account generation, for automation that
        acts later on their behalf; ``None`` without account authentication.
    """

    extension_id: str
    session_id: str
    workspace_id: int
    command_id: str
    key: str
    deleted: bool
    user_id: str | None
    generation: str | None


CommandListener = Callable[[CommandEvent], Awaitable[None]]


@dataclass(frozen=True)
class CommandResult:
    """What a command did: the entry it wrote, or ``None`` after a clear."""

    key: str
    entry: ExtensionStateEntry | None
    deleted: bool = False


def visibility_of(manifest: ExtensionManifest, key: str) -> StateVisibility:
    """The visibility of one key; undeclared keys are service-only."""
    declared = field_for(manifest.state, key)
    return declared.visibility if declared is not None else StateVisibility.SERVICE


def effective_level(level: int | None) -> int:
    """A share level, where ``None`` (permissions off) means the local owner."""
    return LEVEL_OWNER if level is None else level


def _bind_arguments(
    command: CommandContribution, arguments: Mapping[str, object]
) -> dict[str, str]:
    declared = {argument.name: argument for argument in command.arguments}
    unknown = sorted(set(arguments) - set(declared))
    if unknown:
        raise ExtensionCommandArgumentError(f"unknown arguments: {', '.join(unknown)}")
    bound: dict[str, str] = {}
    for name, argument in declared.items():
        value = arguments.get(name)
        if not isinstance(value, str):
            raise ExtensionCommandArgumentError(f"argument {name!r} must be a string")
        if len(value) > argument.max_length:
            raise ExtensionCommandArgumentError(
                f"argument {name!r} is longer than {argument.max_length} characters"
            )
        if argument.choices and value not in argument.choices:
            raise ExtensionCommandArgumentError(
                f"argument {name!r} must be one of: {', '.join(argument.choices)}"
            )
        if argument.pattern is not None and not re.fullmatch(argument.pattern, value):
            raise ExtensionCommandArgumentError(f"argument {name!r} does not match its pattern")
        bound[name] = value
    return bound


class ExtensionStateService:
    """Applies manifest access rules and commands to the store's state rows.

    :param plugin_state: The accepted extensions.
    :param is_enabled: The operator's persistent enablement of an extension
        id (configuration, never runtime health).
    :param store: The conversation store holding the rows.
    """

    def __init__(
        self,
        plugin_state: ExtensionPluginState,
        *,
        is_enabled: Callable[[str], bool],
        store: ConversationStore,
    ) -> None:
        self._plugin_state = plugin_state
        self._is_enabled = is_enabled
        self._store = store
        self._command_listener: CommandListener | None = None

    def set_command_listener(self, listener: CommandListener | None) -> None:
        """Tell ``listener`` about every command that ran (see :meth:`notify_command`)."""
        self._command_listener = listener

    async def notify_command(self, event: CommandEvent) -> None:
        """Tell the listener a command ran; its failures are logged, never raised."""
        if self._command_listener is None:
            return
        try:
            await self._command_listener(event)
        except Exception:
            _logger.exception("extension command listener failed for %s", event.command_id)

    def manifest(self, extension_id: str) -> ExtensionManifest:
        """Return an enabled extension's manifest.

        :raises ExtensionStateUnavailableError: Unknown or not enabled.
        """
        manifest = self._plugin_state.get(extension_id)
        if manifest is None or not self._is_enabled(extension_id):
            raise ExtensionStateUnavailableError(extension_id)
        return manifest

    def can_read(self, manifest: ExtensionManifest, key: str, level: int | None) -> bool:
        """Whether a caller with this share level may read the key over HTTP."""
        required = _READ_LEVELS.get(visibility_of(manifest, key))
        return required is not None and effective_level(level) >= required

    def read(
        self, conversation_id: str, extension_id: str, key: str, level: int | None
    ) -> ExtensionStateEntry | None:
        """Read one key the caller may see; ``None`` when unset or not readable."""
        manifest = self.manifest(extension_id)
        validate_state_key(key)
        if not self.can_read(manifest, key, level):
            return None
        return self._store.get_extension_state(conversation_id, extension_id, key)

    def list_readable(
        self,
        conversation_id: str,
        extension_id: str,
        level: int | None,
        *,
        after: str | None,
        limit: int,
    ) -> tuple[list[ExtensionStateEntry], str | None]:
        """One page of the keys the caller may read, in key order.

        The extension's keys on a session are capped, so all of them are
        loaded and filtered before paging: page sizes and cursors depend
        only on readable keys, and ``after`` may name any key.
        """
        manifest = self.manifest(extension_id)
        if after is not None:
            validate_state_key(after)
        entries, more = self._store.list_extension_state(
            conversation_id, extension_id, limit=_ALL_KEYS_PAGE
        )
        if more is not None:
            # The store caps keys at 64 per extension, so this means a bug.
            _logger.error(
                "extension %s holds more than %d keys on session %s; listing the first",
                extension_id,
                _ALL_KEYS_PAGE,
                conversation_id,
            )
        readable = sorted(
            (entry for entry in entries if self.can_read(manifest, entry.key, level)),
            key=lambda entry: entry.key,
        )
        if after is not None:
            readable = [entry for entry in readable if entry.key > after]
        page = readable[:limit]
        return page, page[-1].key if len(readable) > limit else None

    def read_state(
        self, conversation_id: str, extension_id: str, key: str
    ) -> ExtensionStateEntry | None:
        """Read any key as the extension's server code, service keys included."""
        self.manifest(extension_id)
        return self._store.get_extension_state(conversation_id, extension_id, key)

    def list_state(self, conversation_id: str, extension_id: str) -> list[ExtensionStateEntry]:
        """Every key the extension holds on a session, as its server code sees them."""
        self.manifest(extension_id)
        entries, _ = self._store.list_extension_state(
            conversation_id, extension_id, limit=_ALL_KEYS_PAGE
        )
        return entries

    def sessions_with_state(
        self,
        extension_id: str,
        *,
        key_prefix: str | None = None,
        after: tuple[int, str] | None = None,
        limit: int = _ALL_KEYS_PAGE,
    ) -> list[tuple[int, str]]:
        """One page of ``(workspace_id, session_id)`` where the extension holds state."""
        self.manifest(extension_id)
        return self._store.list_extension_state_sessions(
            extension_id, key_prefix=key_prefix, after=after, limit=limit
        )

    def write_state(
        self,
        conversation_id: str,
        extension_id: str,
        key: str,
        value: bytes,
        *,
        expected_version: int | None = None,
        updated_by: str | None = None,
    ) -> ExtensionStateEntry:
        """Write a key as the extension's server code; published keys are mirrored.

        A published key must hold UTF-8 text within its declared
        ``max_length``, as for commands.

        :raises ExtensionStateUnavailableError: The extension is not enabled.
        :raises ValueError: The value does not fit the key's declaration.
        """
        manifest = self.manifest(extension_id)
        declared = field_for(manifest.state, key)
        if declared is not None and declared.visibility is StateVisibility.PUBLISHED:
            try:
                text = value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"published field {key!r} must hold UTF-8 text") from exc
            if len(text) > (declared.max_length or 0):
                raise ValueError(
                    f"value for published field {key!r} is longer than {declared.max_length}"
                )
        return self._store._put_extension_state(
            conversation_id,
            extension_id,
            key,
            value,
            expected_version=expected_version,
            updated_by=updated_by,
            publish=visibility_of(manifest, key) is StateVisibility.PUBLISHED,
            max_keys=MAX_STATE_KEYS,
        )

    def clear_state(
        self,
        conversation_id: str,
        extension_id: str,
        key: str,
        *,
        expected_version: int | None = None,
    ) -> bool:
        """Delete a key as the extension's server code, with its mirror label."""
        manifest = self.manifest(extension_id)
        return self._store._delete_extension_state(
            conversation_id,
            extension_id,
            key,
            expected_version=expected_version,
            publish=visibility_of(manifest, key) is StateVisibility.PUBLISHED,
        )

    def run_command(
        self,
        conversation_id: str,
        extension_id: str,
        command_id: str,
        arguments: Mapping[str, object],
        *,
        level: int | None,
        user_id: str | None,
        expected_version: int | None = None,
    ) -> CommandResult:
        """Bind and run one declared state command as the extension.

        :raises ExtensionStateUnavailableError: No such enabled extension or
            runnable command.
        :raises ExtensionStateAccessError: The caller's level is too low.
        :raises ExtensionCommandArgumentError: Bad arguments, or a bound key
            or value the state does not accept.
        """
        manifest = self.manifest(extension_id)
        command = next((item for item in manifest.commands if item.id == command_id), None)
        if command is None or command.action is None:
            raise ExtensionStateUnavailableError(command_id)
        if effective_level(level) < _COMMAND_LEVELS[command.required_access]:
            raise ExtensionStateAccessError(command_id)
        bound = _bind_arguments(command, arguments)
        action = command.action
        key = action.key.format(**bound)
        try:
            validate_state_key(key)
        except ValueError as exc:
            raise ExtensionCommandArgumentError(str(exc)) from exc
        target = pinned_field(manifest.state, action.key)
        # Manifest validation pins every template; an argument value must not
        # move the key under another declaration.
        if target is None or field_for(manifest.state, key) is not target:
            raise ExtensionCommandArgumentError(
                f"key {key!r} is outside the field this command writes"
            )
        published = target.visibility is StateVisibility.PUBLISHED
        family_prefix = target.key[:-1] if target.key.endswith("*") else None
        if isinstance(action, ClearState):
            deleted = self._store._delete_extension_state(
                conversation_id,
                extension_id,
                key,
                expected_version=expected_version,
                publish=published,
            )
            _logger.info(
                "extension command %s cleared %s on session %s for user %s",
                command_id,
                key,
                conversation_id,
                user_id,
            )
            return CommandResult(key=key, entry=None, deleted=deleted)
        assert isinstance(action, SetState)
        value = action.value.format(**bound)
        if published and len(value) > (target.max_length or 0):
            raise ExtensionCommandArgumentError(
                f"value for published field {key!r} is longer than {target.max_length}"
            )
        try:
            entry = self._store._put_extension_state(
                conversation_id,
                extension_id,
                key,
                value.encode(),
                expected_version=expected_version,
                updated_by=user_id,
                publish=published,
                # Commands share a total below the store's, and each prefix
                # field has its own cap.
                max_keys=COMMAND_STATE_KEYS,
                family_prefix=family_prefix,
                max_family_keys=(
                    target.max_keys or DEFAULT_COMMAND_KEYS_PER_PREFIX
                    if family_prefix is not None
                    else None
                ),
            )
        except ValueError as exc:
            raise ExtensionCommandArgumentError(str(exc)) from exc
        _logger.info(
            "extension command %s set %s on session %s for user %s",
            command_id,
            key,
            conversation_id,
            user_id,
        )
        return CommandResult(key=key, entry=entry)
