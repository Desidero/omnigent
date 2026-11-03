"""Run operator-enabled extensions' server code: ``activate(ctx)`` (experimental).

An extension whose manifest declares ``entrypoints.server`` (an
``async def activate(ctx)`` in its own package) is activated once per server
process, at startup, when the operator enabled it in the server config. It
gets an :class:`ExtensionContext` bound to its id and deactivates at shutdown.

- **Only persistent enablement decides.** Runtime health never disables an
  extension. An activation that fails (import error, wrong package, raises or
  times out) quarantines it: logged, reported by ``GET
  /v1/extensions/diagnostics``, and its server code doesn't run until the next
  start. Its pages, state, commands and published fields are unaffected.
- **Every replica activates it.** Server code that acts on a session should do
  so only where :meth:`ExtensionContext.serves_session` is true.
- **Time limits bound waiting.** Extension code runs as its own tasks; code
  that ignores cancellation, blocks or runs at import can't be stopped.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import importlib
import importlib.metadata
import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from omnigent.db.db_models import current_workspace_id, workspace_scope
from omnigent.extensions.api import ExtensionManifest, ExtensionPluginState
from omnigent.server import session_pull_requests
from omnigent.server.extension_state import CommandEvent, ExtensionStateService
from omnigent.server.extension_status_observers import ExtensionStatusObservers, StatusCallback
from omnigent.server.session_wake import (
    DEFAULT_MAX_WAKES,
    SessionWakeService,
    WakeOutcome,
    WakeRequest,
    WakeStatus,
    WakeStop,
    served_here,
)
from omnigent.stores.conversation_store import ConversationStore, ExtensionStateEntry
from omnigent.stores.session_pull_request_store import SessionPullRequests

_logger = logging.getLogger(__name__)

ACTIVATE_TIMEOUT_S = 10.0
DEACTIVATE_TIMEOUT_S = 5.0
COMMAND_CALLBACK_TIMEOUT_S = 5.0
PULL_REQUEST_INFO_TIMEOUT_S = 30.0
_MAX_ERROR_CHARS = 512
_SESSIONS_PAGE = 100

CommandCallback = Callable[[CommandEvent], Coroutine[Any, Any, None]]
# read(session_id, pr_url) -> the Pull Requests panel's info, or None
PullRequestInfoReader = Callable[[str, str], Awaitable[dict[str, Any] | None]]
WakeStopCallback = Callable[[str, WakeStop], Coroutine[Any, Any, None]]


class ActivationState(enum.StrEnum):
    """Where an extension's server code stands in this process."""

    ACTIVE = "active"
    QUARANTINED = "quarantined"
    STOPPED = "stopped"


@dataclass(frozen=True)
class ActivationRecord:
    """One extension's activation, for diagnostics."""

    extension_id: str
    state: ActivationState
    error: str | None = None


@dataclass(frozen=True)
class SessionRef:
    """A session in a workspace; enter :meth:`ExtensionContext.workspace` to act on it."""

    workspace_id: int
    session_id: str


class ActivationError(Exception):
    """The server entrypoint can't be activated, or extension code misbehaved."""


def module_in_distribution(module: ModuleType, distribution: str) -> bool:
    """Whether a module's file is one the installed distribution recorded.

    Editable installs record no package files, so their modules never are.
    """
    location = getattr(module, "__file__", None)
    if not location:
        return False
    try:
        dist = importlib.metadata.distribution(distribution)
    except importlib.metadata.PackageNotFoundError:
        return False
    target = Path(location).resolve()
    return any(Path(str(dist.locate_file(file))).resolve() == target for file in dist.files or ())


def resolve_server_entrypoint(
    manifest: ExtensionManifest, package: str | None
) -> Callable[[ExtensionContext], Awaitable[Any]]:
    """Import an extension's ``activate`` function without running it.

    :param manifest: The extension; ``entrypoints.server`` must be set.
    :param package: The top-level package the extension's distribution owns.
    :raises ActivationError: It is outside that package or the distribution's
        files, isn't an ``async def``, or importing it exits or cancels.
    """
    entrypoint = manifest.entrypoints.server
    if entrypoint is None:
        raise ActivationError("no server entrypoint declared")
    module_name, _, attribute = entrypoint.partition(":")
    if package is None or module_name.split(".", 1)[0] != package:
        raise ActivationError(
            f"server entrypoint {entrypoint!r} is outside the extension's package {package!r}"
        )
    try:
        module = importlib.import_module(module_name)
        activate = getattr(module, attribute, None)
    except (SystemExit, asyncio.CancelledError) as error:
        # The import is synchronous, so a cancellation here is the module's own.
        raise ActivationError(f"importing {module_name} raised {type(error).__name__}") from None
    if not module_in_distribution(module, manifest.distribution):
        raise ActivationError(
            f"{module_name} is not a file of the installed distribution {manifest.distribution!r}"
            " (editable installs are not activated)"
        )
    if not inspect.iscoroutinefunction(activate):
        raise ActivationError(f"server entrypoint {entrypoint!r} must be an async def")
    return activate


async def _contained(awaitable: Awaitable[Any]) -> Any:
    """Await extension code; an exit it attempts becomes an ordinary error."""
    try:
        return await awaitable
    except SystemExit as error:
        raise ActivationError(f"extension code raised SystemExit({error.code!r})") from None


def _retrieve_late(task: asyncio.Task[Any]) -> None:
    if not task.cancelled() and (error := task.exception()) is not None:
        _logger.debug("extension code failed after its time limit", exc_info=error)


async def _bounded(awaitable: Awaitable[Any], timeout_s: float, name: str) -> Any:
    """Run extension code as its own task and stop waiting after ``timeout_s``.

    Code that ignores cancellation keeps running, unawaited; this only bounds
    how long the caller waits.

    :raises ActivationError: It timed out, cancelled itself or tried to exit.
    """
    task = asyncio.get_running_loop().create_task(_contained(awaitable), name=name)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout_s)
    except asyncio.CancelledError:
        task.cancel()
        raise
    if not done:
        task.cancel()
        task.add_done_callback(_retrieve_late)
        raise ActivationError(f"{name} timed out after {timeout_s:g} s")
    if task.cancelled():
        raise ActivationError(f"{name} cancelled itself")
    return task.result()


class ExtensionStateHandle:
    """The extension's own session state, read and written as its server code.

    Calls act in the current workspace (see :meth:`ExtensionContext.workspace`).
    Published keys are mirrored as labels, as for commands.
    """

    def __init__(self, context: ExtensionContext, service: ExtensionStateService) -> None:
        self._context = context
        self._service = service

    async def _run(self, method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        self._context.require_active()
        return await asyncio.to_thread(method, *args, **kwargs)

    async def read(self, session_id: str, key: str) -> ExtensionStateEntry | None:
        """One key, service keys included; ``None`` when unset."""
        return await self._run(
            self._service.read_state, session_id, self._context.extension_id, key
        )

    async def entries(self, session_id: str) -> list[ExtensionStateEntry]:
        """Every key the extension holds on the session."""
        return await self._run(self._service.list_state, session_id, self._context.extension_id)

    async def write(
        self,
        session_id: str,
        key: str,
        value: bytes | str,
        *,
        expected_version: int | None = None,
        updated_by: str | None = None,
    ) -> ExtensionStateEntry:
        """Write a key (compare-and-set with ``expected_version``; ``0`` means unset)."""
        return await self._run(
            self._service.write_state,
            session_id,
            self._context.extension_id,
            key,
            value.encode() if isinstance(value, str) else value,
            expected_version=expected_version,
            updated_by=updated_by,
        )

    async def clear(
        self, session_id: str, key: str, *, expected_version: int | None = None
    ) -> bool:
        """Delete a key; returns whether it existed."""
        return await self._run(
            self._service.clear_state,
            session_id,
            self._context.extension_id,
            key,
            expected_version=expected_version,
        )

    async def sessions(self, *, key_prefix: str | None = None) -> AsyncIterator[SessionRef]:
        """Every session, in every workspace, where the extension holds state.

        Read a page of 100 at a time, as the iteration reaches it.
        """
        after: tuple[int, str] | None = None
        while True:
            page = await self._run(
                self._service.sessions_with_state,
                self._context.extension_id,
                key_prefix=key_prefix,
                after=after,
                limit=_SESSIONS_PAGE,
            )
            for workspace_id, session_id in page:
                yield SessionRef(workspace_id, session_id)
            if len(page) < _SESSIONS_PAGE:
                return
            after = page[-1]


class ExtensionWakeHandle:
    """The session wake service, with ``source`` bound to ``ext:<extension id>``."""

    def __init__(self, context: ExtensionContext, service: SessionWakeService) -> None:
        self._context = context
        self._service = service
        self.source = f"ext:{context.extension_id}"
        # Wakes requested while activating, dropped if the activation fails.
        self._requested: set[tuple[int, str]] = set()

    def _drop_requested(self) -> None:
        for workspace_id, session_id in self._requested:
            with workspace_scope(workspace_id):
                self._service.cancel(session_id, self.source)
        self._requested.clear()

    async def request(
        self,
        session_id: str,
        text: str,
        *,
        on_behalf_of: str | None,
        generation: str | None,
        dedupe_key: str | None = None,
        evidence_key: str | None = None,
        max_wakes: int = DEFAULT_MAX_WAKES,
        merge: bool = False,
        label: str | None = None,
    ) -> WakeOutcome:
        """Queue a wake (see ``docs/extending/session_wake.md``).

        :param on_behalf_of: The user who turned the automation on.
        :param generation: Their account generation when they did
            (:attr:`CommandEvent.generation`); background code has none bound.
        """
        self._context.require_active()
        if not self._context.is_activated:
            self._requested.add((current_workspace_id(), session_id))
        return await self._service.request(
            WakeRequest(
                session_id=session_id,
                source=self.source,
                on_behalf_of=on_behalf_of,
                text=text,
                dedupe_key=dedupe_key,
                evidence_key=evidence_key,
                max_wakes=max_wakes,
                merge=merge,
                label=label,
                generation=generation,
            )
        )

    def cancel(self, session_id: str) -> bool:
        """Drop the pending wake for a session; returns whether one was pending."""
        return self._service.cancel(session_id, self.source)

    def status(self, session_id: str) -> WakeStatus | None:
        """This replica's wake state for a session, or ``None``."""
        return self._service.status(session_id, self.source)

    def on_stop(self, callback: WakeStopCallback) -> None:
        """Call ``async callback(session_id, reason)`` when a pending wake is dropped."""
        self._context.add_callback(self._context.stop_callbacks, callback)


class ExtensionContext:
    """What an extension's ``activate(ctx)`` can use; bound to its id."""

    def __init__(
        self,
        manifest: ExtensionManifest,
        *,
        state_service: ExtensionStateService,
        status_observers: ExtensionStatusObservers,
        session_wake: SessionWakeService,
        conversation_store: ConversationStore,
        host_registry: Any | None,
        pull_request_info: Callable[[], PullRequestInfoReader | None] = lambda: None,
    ) -> None:
        self.extension_id = manifest.id
        self.version = manifest.version
        self.logger = logging.getLogger(f"omnigent.extensions.{manifest.id}")
        self.state = ExtensionStateHandle(self, state_service)
        self.wake = ExtensionWakeHandle(self, session_wake)
        self.command_callbacks: list[CommandCallback] = []
        self.stop_callbacks: list[WakeStopCallback] = []
        self._status_observers = status_observers
        self._status_callback: StatusCallback | None = None
        self._conversation_store = conversation_store
        self._host_registry = host_registry
        self._pull_request_info = pull_request_info
        self._tasks: set[asyncio.Task[Any]] = set()
        self._active = False
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def is_activated(self) -> bool:
        return self._active

    def require_active(self) -> None:
        """Raise once the extension is quarantined or deactivated."""
        if self._closed:
            raise RuntimeError(f"extension {self.extension_id} is not active")

    def add_callback(self, callbacks: list[Any], callback: Callable[..., Any]) -> None:
        self.require_active()
        if not inspect.iscoroutinefunction(callback):
            raise TypeError(f"extension {self.extension_id}: callbacks must be async functions")
        callbacks.append(callback)

    def subscribe_status(self, callback: StatusCallback) -> None:
        """Receive session status observations (``docs/extending/status_observers.md``).

        Best-effort hints: also reconcile on a timer. Once per extension.
        """
        self.require_active()
        if self._status_callback is not None:
            raise RuntimeError(f"extension {self.extension_id} already subscribed")
        if not inspect.iscoroutinefunction(callback):
            raise TypeError(f"extension {self.extension_id}: callbacks must be async functions")
        self._status_callback = callback
        if self._active:
            self._subscribe_status()

    def on_command(self, callback: CommandCallback) -> None:
        """Call ``async callback(event)`` after one of the extension's commands runs.

        It runs before the command's HTTP response, on the replica that served
        it, concurrently with the extension's other command callbacks, all
        within 5 seconds. Record what you need (e.g. the caller's generation)
        in state; the command succeeds even if this fails.
        """
        self.add_callback(self.command_callbacks, callback)

    async def pull_requests(self, session_id: str) -> SessionPullRequests | None:
        """The session's linked pull requests (read-only), or ``None``."""
        self.require_active()
        store = session_pull_requests.open_store(self._conversation_store)
        if store is None:
            return None
        return await asyncio.to_thread(store.read, session_id)

    async def pull_request_info(self, session_id: str, pr_url: str) -> dict[str, Any] | None:
        """One linked PR as the Pull Requests panel reads it, read-only.

        The ``session.github.info`` payload (head commit, checks, reviews,
        comments, mergeability), read through the session's runner or host.
        ``None`` unless the session's host is connected to this replica.

        :raises TimeoutError: The read took longer than 30 seconds.
        """
        self.require_active()
        reader = self._pull_request_info()
        if reader is None:
            return None
        return await asyncio.wait_for(reader(session_id, pr_url), PULL_REQUEST_INFO_TIMEOUT_S)

    async def serves_session(self, session_id: str, *, require_host: bool = False) -> bool:
        """Whether this replica owns the session: it exists and its host is connected here.

        :param require_host: Also require that the session has a host. Without
            one, every replica counts as serving it (the wake service's rule),
            so single-owner work should pass ``True``.
        """
        conv = await asyncio.to_thread(self._conversation_store.get_conversation, session_id)
        if conv is None or (require_host and not conv.host_id):
            return False
        return served_here(conv.host_id, self._host_registry)

    @contextlib.contextmanager
    def workspace(self, workspace_id: int) -> Iterator[None]:
        """Act in a session's workspace, e.g. for a :class:`SessionRef`."""
        with workspace_scope(workspace_id):
            yield

    def create_task(
        self, coroutine: Coroutine[Any, Any, Any], *, name: str | None = None
    ) -> asyncio.Task[Any]:
        """Run background work; cancelled at deactivation. Failures are logged only."""
        if self._closed:
            coroutine.close()
            self.require_active()
        task = asyncio.get_running_loop().create_task(
            _contained(coroutine), name=name or f"extension-{self.extension_id}"
        )
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            self.logger.error("extension task %s failed", task.get_name(), exc_info=error)

    def _subscribe_status(self) -> None:
        callback = self._status_callback
        assert callback is not None

        async def deliver(observation: Any) -> None:
            if not self._closed:
                await _contained(callback(observation))

        self._status_observers.subscribe(self.extension_id, deliver)

    def _mark_activated(self) -> None:
        self._active = True
        if self._status_callback is not None:
            self._subscribe_status()

    async def _close(self, *, wait_s: float) -> None:
        """Stop callbacks and cancel tasks, waiting at most ``wait_s`` for them."""
        self._closed = True
        tasks = set(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=wait_s)


class ExtensionActivations:
    """Activates enabled extensions at startup and deactivates them at shutdown."""

    def __init__(
        self,
        plugin_state: ExtensionPluginState,
        *,
        is_enabled: Callable[[str], bool],
        state_service: ExtensionStateService,
        status_observers: ExtensionStatusObservers,
        session_wake: SessionWakeService,
        conversation_store: ConversationStore,
        host_registry: Any | None,
        pull_request_info: Callable[[], PullRequestInfoReader | None] = lambda: None,
        activate_timeout_s: float | None = None,
        deactivate_timeout_s: float | None = None,
    ) -> None:
        self._plugin_state = plugin_state
        self._is_enabled = is_enabled
        self._state_service = state_service
        self._status_observers = status_observers
        self._session_wake = session_wake
        self._conversation_store = conversation_store
        self._host_registry = host_registry
        self._pull_request_info = pull_request_info
        self._activate_timeout_s = (
            ACTIVATE_TIMEOUT_S if activate_timeout_s is None else activate_timeout_s
        )
        self._deactivate_timeout_s = (
            DEACTIVATE_TIMEOUT_S if deactivate_timeout_s is None else deactivate_timeout_s
        )
        self._active: dict[str, tuple[ExtensionContext, Callable[[], Awaitable[None]] | None]] = {}
        self._records: dict[str, ActivationRecord] = {}
        session_wake.add_stop_listener(self._on_wake_stop)
        state_service.set_command_listener(self._on_command)

    def records(self) -> dict[str, ActivationRecord]:
        """Each extension with a server entrypoint that this process tried to activate."""
        return dict(self._records)

    def context(self, extension_id: str) -> ExtensionContext | None:
        """An active extension's context."""
        active = self._active.get(extension_id)
        return active[0] if active is not None else None

    async def start(self) -> None:
        """Activate each enabled extension that declares a server entrypoint.

        Every entrypoint is imported first, one at a time and unbounded, so a
        slow import can't use up another extension's time. Then they activate
        concurrently, each within its own time limit.
        """
        resolved: list[tuple[ExtensionManifest, ExtensionContext, Callable[..., Any]]] = []
        for manifest in sorted(self._plugin_state.manifests, key=lambda item: item.id):
            if manifest.entrypoints.server is None or not self._is_enabled(manifest.id):
                continue
            context = ExtensionContext(
                manifest,
                state_service=self._state_service,
                status_observers=self._status_observers,
                session_wake=self._session_wake,
                conversation_store=self._conversation_store,
                host_registry=self._host_registry,
                pull_request_info=self._pull_request_info,
            )
            try:
                activate = resolve_server_entrypoint(
                    manifest, self._plugin_state.asset_package(manifest.id)
                )
            except Exception as error:  # noqa: BLE001 — extension code; logged by _quarantine
                await self._quarantine(manifest, context, error)
                continue
            resolved.append((manifest, context, activate))
        await asyncio.gather(
            *(
                self._activate(manifest, context, activate)
                for manifest, context, activate in resolved
            )
        )

    async def _activate(
        self,
        manifest: ExtensionManifest,
        context: ExtensionContext,
        activate: Callable[[ExtensionContext], Awaitable[Any]],
    ) -> None:
        try:
            deactivate = await _bounded(
                activate(context), self._activate_timeout_s, f"{manifest.id} activate"
            )
            if deactivate is not None and not inspect.iscoroutinefunction(deactivate):
                raise ActivationError("activate must return None or an async deactivate function")
            context._mark_activated()
        except Exception as error:  # noqa: BLE001 — extension code; logged by _quarantine
            await self._quarantine(manifest, context, error)
            return
        self._active[manifest.id] = (context, deactivate)
        self._records[manifest.id] = ActivationRecord(manifest.id, ActivationState.ACTIVE)
        _logger.info("extension %s activated", manifest.id)

    async def _quarantine(
        self, manifest: ExtensionManifest, context: ExtensionContext, error: Exception
    ) -> None:
        _logger.error("extension %s failed to activate; quarantined", manifest.id, exc_info=error)
        await context._close(wait_s=self._deactivate_timeout_s)
        context.wake._drop_requested()
        message = " ".join(f"{type(error).__name__}: {error}".split())
        self._records[manifest.id] = ActivationRecord(
            manifest.id, ActivationState.QUARANTINED, message[:_MAX_ERROR_CHARS]
        )

    async def aclose(self) -> None:
        """Deactivate every extension concurrently; waits at most twice the time limit."""
        await asyncio.gather(
            *(
                self._deactivate(extension_id, context, deactivate)
                for extension_id, (context, deactivate) in self._active.items()
            )
        )
        self._active.clear()

    async def _deactivate(
        self,
        extension_id: str,
        context: ExtensionContext,
        deactivate: Callable[[], Awaitable[None]] | None,
    ) -> None:
        if deactivate is not None:
            try:
                await _bounded(
                    deactivate(), self._deactivate_timeout_s, f"{extension_id} deactivate"
                )
            except Exception:
                _logger.exception("extension %s failed to deactivate", extension_id)
        await context._close(wait_s=self._deactivate_timeout_s)
        self._records[extension_id] = ActivationRecord(extension_id, ActivationState.STOPPED)

    def _on_wake_stop(self, session_id: str, source: str, reason: WakeStop) -> None:
        kind, _, extension_id = source.partition(":")
        context = self.context(extension_id) if kind == "ext" else None
        if context is None or context.closed:
            return
        for callback in context.stop_callbacks:
            context.create_task(callback(session_id, reason), name=f"wake-stop-{extension_id}")

    async def _on_command(self, event: CommandEvent) -> None:
        """Run the extension's command callbacks concurrently, together bounded.

        The command already committed, so failures are logged, not raised.
        """
        context = self.context(event.extension_id)
        if context is None or context.closed or not context.command_callbacks:
            return
        tasks = [
            context.create_task(callback(event), name=f"command-{event.command_id}")
            for callback in context.command_callbacks
        ]
        try:
            _, pending = await asyncio.wait(tasks, timeout=COMMAND_CALLBACK_TIMEOUT_S)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            raise
        for task in pending:
            task.cancel()
        unfinished = len(pending) + sum(task.cancelled() for task in tasks if task not in pending)
        if unfinished:
            context.logger.error(
                "%d command callback(s) for %s on session %s did not finish within %g s",
                unfinished,
                event.command_id,
                event.session_id,
                COMMAND_CALLBACK_TIMEOUT_S,
            )
