"""Per-user preference routes (``/v1/preferences``), the chat-feature catalog,
and the chat link rules (``/v1/link-rules``).

Shared preferences take explicit reads and versioned edits. The only value the
server adopts is the chat-features default, read when a session is created.
Link rules are a shared preference too; their route serves the defaults when
none are saved and gives agent tools a single versioned write.
"""

import asyncio
import logging
import uuid
from collections.abc import Iterable
from functools import partial
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import TypeAdapter, ValidationError

from omnigent.configuration_profile import ConfigurationSave, ConfigurationSnapshot
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.link_rules import (
    DEFAULT_LINK_RULES,
    LinkRule,
    LinkRuleError,
    encode_link_rules,
    link_rules_from_value,
    validate_link_rules,
)
from omnigent.preference_sync import (
    MAX_VALUE_BYTES,
    PREFERENCE_PAGE_SIZE,
    Name,
    PreferenceMutation,
    PreferencePage,
    PreferenceResult,
    SharedPreferenceKey,
)
from omnigent.runtime.chat_features import (
    CHAT_FEATURE_DEFINITIONS,
    DEFAULT_CHAT_FEATURES,
    ChatFeature,
    chat_features_from_wire,
    decode_chat_features,
    parse_chat_features,
)
from omnigent.server.auth import AuthProvider
from omnigent.server.preference_requests import (
    DEFAULT_PREFERENCE_POLICY,
    MAX_PREFERENCE_REQUEST_BYTES,
    PreferencePolicy,
    read_preference_payload,
)
from omnigent.server.routes._auth_helpers import require_user
from omnigent.server.schemas import (
    ChatFeatureCatalogResponse,
    ChatFeatureOption,
    LinkRuleModel,
    LinkRulesResponse,
    LinkRulesUpdateRequest,
)
from omnigent.stores.preference_store import PreferenceStore, read_preference_entry

_logger = logging.getLogger(__name__)

_USER_ID = TypeAdapter(Name)


def create_preferences_router(
    store: PreferenceStore,
    auth_provider: AuthProvider | None = None,
    *,
    policy: PreferencePolicy = DEFAULT_PREFERENCE_POLICY,
) -> APIRouter:
    router = APIRouter()

    def user_id(request: Request) -> str | None:
        policy.require_enabled()
        authenticated = require_user(request, auth_provider)
        if authenticated is None:
            return None
        try:
            return _USER_ID.validate_python(authenticated)
        except ValidationError as exc:
            raise OmnigentError(
                "Invalid preference user ID", code=ErrorCode.INVALID_INPUT
            ) from exc

    @router.get("/preferences/shared", response_model=PreferencePage)
    async def read_preferences(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=PREFERENCE_PAGE_SIZE)] = PREFERENCE_PAGE_SIZE,
        cursor: Annotated[str | None, Query(max_length=4096)] = None,
    ) -> PreferencePage:
        authenticated = user_id(request)
        return await policy.run(
            authenticated, partial(store.read, user_id=authenticated, limit=limit, cursor=cursor)
        )

    @router.post("/preferences/shared/operations", response_model=PreferenceResult)
    async def apply_preference(request: Request) -> PreferenceResult:
        authenticated = user_id(request)
        payload = await read_preference_payload(request, MAX_PREFERENCE_REQUEST_BYTES)
        try:
            body = PreferenceMutation.model_validate_json(payload)
        except ValidationError as exc:
            raise HTTPException(422, "Invalid preference edit") from exc
        return await policy.run(authenticated, partial(store.apply, body, user_id=authenticated))

    @router.get("/preferences/configuration", response_model=ConfigurationSnapshot)
    async def read_configuration(request: Request) -> ConfigurationSnapshot:
        authenticated = user_id(request)
        return await policy.run(
            authenticated, partial(store.read_configuration, user_id=authenticated)
        )

    @router.put("/preferences/configuration", response_model=ConfigurationSnapshot)
    async def save_configuration(request: Request) -> ConfigurationSnapshot:
        authenticated = user_id(request)
        payload = await read_preference_payload(request, 16000)
        try:
            body = ConfigurationSave.model_validate_json(payload)
        except ValidationError as exc:
            raise HTTPException(422, "Invalid configuration snapshot") from exc
        return await policy.run(
            authenticated, partial(store.save_configuration, body, user_id=authenticated)
        )

    return router


def parse_requested_chat_features(values: Iterable[str]) -> frozenset[ChatFeature]:
    """Parse chat-feature keys from an API request.

    :param values: Requested keys, e.g. ``["run_commands"]``.
    :returns: The parsed set.
    :raises OmnigentError: ``INVALID_INPUT`` naming any unknown key.
    """
    try:
        return parse_chat_features(values)
    except ValueError as exc:
        raise OmnigentError(str(exc), code=ErrorCode.INVALID_INPUT) from exc


CHAT_FEATURES_PREFERENCE_KEY = SharedPreferenceKey(kind="chat_features", name="default")


def saved_chat_features(
    preference_store: PreferenceStore | None, *, user_id: str | None
) -> frozenset[ChatFeature] | None:
    """Read the user's default chat features from shared preferences.

    :param preference_store: The shared store; ``None`` when the server has none.
    :param user_id: The user, as the shared routes identify them.
    :returns: The known features in the saved value, or ``None`` when there is
        no usable saved value (never saved, removed, or unreadable).
    """
    if preference_store is None:
        return None
    try:
        entry = read_preference_entry(
            preference_store,
            CHAT_FEATURES_PREFERENCE_KEY,
            user_id=None if user_id is None else _USER_ID.validate_python(user_id),
        )
    except (OmnigentError, ValidationError):
        # A broken preference read must not block creating the session.
        _logger.warning("Could not read the saved chat-features default", exc_info=True)
        return None
    if entry is None or entry.value is None:
        return None
    return chat_features_from_wire(entry.value)


def resolve_session_chat_features(
    requested: frozenset[ChatFeature] | None,
    *,
    user_id: str | None,
    preference_store: PreferenceStore | None,
) -> frozenset[ChatFeature]:
    """Resolve a new session's chat features: request, then saved default, then every feature.

    :param requested: Parsed features from the create request, or ``None`` if omitted.
    :param user_id: The creating user.
    :param preference_store: The shared store; ``None`` uses every feature.
    :returns: The set to store on the session.
    """
    if requested is not None:
        return requested
    saved = saved_chat_features(preference_store, user_id=user_id)
    return DEFAULT_CHAT_FEATURES if saved is None else saved


async def resolve_new_session_chat_features(
    requested: frozenset[ChatFeature] | None,
    *,
    user_id: str | None,
    app_state: Any,
    parent_chat_features_override: str | None = None,
    has_parent: bool = False,
) -> frozenset[ChatFeature]:
    """Resolve the chat features a new session stores.

    A sub-agent inherits its parent's set; otherwise an omitted request uses
    the creator's saved default, then every feature.

    :param requested: Parsed request value, or ``None`` when omitted.
    :param user_id: The creating user.
    :param app_state: ``app.state``, carrying the optional shared ``preference_store``.
    :param parent_chat_features_override: The parent's stored value.
    :param has_parent: Whether the session is a sub-agent child.
    :returns: The resolved set.
    """
    if requested is None and has_parent:
        return decode_chat_features(parent_chat_features_override)
    return await asyncio.to_thread(
        resolve_session_chat_features,
        requested,
        user_id=user_id,
        preference_store=getattr(app_state, "preference_store", None),
    )


def create_chat_features_router(auth_provider: AuthProvider | None = None) -> APIRouter:
    """Build the read-only chat-feature catalog router (``GET /chat-features``).

    :param auth_provider: Identifies the caller; ``None`` in single-user mode.
    :returns: A configured :class:`APIRouter`.
    """
    router = APIRouter()

    @router.get("/chat-features")
    async def list_chat_features(request: Request) -> ChatFeatureCatalogResponse:
        """Every chat feature a session can enable, in display order."""
        require_user(request, auth_provider)
        return ChatFeatureCatalogResponse(
            available=[
                ChatFeatureOption(
                    key=str(definition.feature),
                    title=definition.title,
                    description=definition.description,
                )
                for definition in CHAT_FEATURE_DEFINITIONS
            ]
        )

    return router


LINK_RULES_PREFERENCE_KEY = SharedPreferenceKey(kind="link_rules", name="default")
# Edits through /v1/link-rules (agent tools, scripts) share one source ID.
_LINK_RULES_INSTALLATION_ID = "link-rules-api"
_STALE_LINK_RULES = "The link rules changed since they were read; read them and retry"


def _link_rule_models(rules: tuple[LinkRule, ...]) -> list[LinkRuleModel]:
    return [LinkRuleModel.model_validate(rule.to_wire()) for rule in rules]


def _link_rules_response(*, supported: bool, value: object, version: int) -> LinkRulesResponse:
    saved = isinstance(value, str)
    return LinkRulesResponse(
        supported=supported,
        saved=saved,
        version=version,
        rules=_link_rule_models(link_rules_from_value(value)),
        defaults=_link_rule_models(DEFAULT_LINK_RULES),
    )


def create_link_rules_router(
    store: PreferenceStore | None,
    auth_provider: AuthProvider | None = None,
    *,
    policy: PreferencePolicy = DEFAULT_PREFERENCE_POLICY,
) -> APIRouter:
    """Build the chat link-rule routes (``GET``/``PUT /link-rules``).

    The rules are the caller's ``link_rules`` shared preference. Without a
    preference store the read serves the defaults with ``supported: false``
    and a save is refused.

    :param store: The shared-preference store, or ``None`` when disabled.
    :param auth_provider: Identifies the caller; ``None`` in single-user mode.
    :param policy: Rollout hooks shared with the preference routes.
    :returns: A configured :class:`APIRouter`.
    """
    router = APIRouter()

    def caller(request: Request) -> str | None:
        authenticated = require_user(request, auth_provider)
        return None if authenticated is None else _USER_ID.validate_python(authenticated)

    def enabled_store() -> PreferenceStore | None:
        return store if store is not None and policy.is_enabled() else None

    def read(active: PreferenceStore, user_id: str | None) -> LinkRulesResponse:
        entry = read_preference_entry(active, LINK_RULES_PREFERENCE_KEY, user_id=user_id)
        if entry is None:
            return _link_rules_response(supported=True, value=None, version=0)
        return _link_rules_response(supported=True, value=entry.value, version=entry.version)

    @router.get("/link-rules")
    async def get_link_rules(request: Request) -> LinkRulesResponse:
        """The caller's chat link rules, or the defaults when none are saved."""
        user_id = caller(request)
        active = enabled_store()
        if active is None:
            return _link_rules_response(supported=False, value=None, version=0)
        return await policy.run(user_id, partial(read, active, user_id))

    @router.put("/link-rules")
    async def put_link_rules(request: Request, body: LinkRulesUpdateRequest) -> LinkRulesResponse:
        """Replace the caller's link rules; ``rules: null`` restores the defaults.

        Returns 422 naming the rule and field when a rule is invalid, and 409
        when ``expected_version`` is stale or shared preferences are off.
        """
        user_id = caller(request)
        active = enabled_store()
        if active is None:
            raise HTTPException(409, "Saving link rules needs shared preferences on the server")
        value: str | None = None
        if body.rules is not None:
            try:
                value = encode_link_rules(validate_link_rules(body.rules))
            except LinkRuleError as exc:
                raise HTTPException(422, f"Invalid link rule: {exc}") from exc
            if len(value.encode()) > MAX_VALUE_BYTES - 64:
                raise HTTPException(422, "Link rules are too large to save; remove some rules")

        def write() -> LinkRulesResponse:
            # Refuse a stale edit up front: applying it would store a conflict
            # for the user to resolve in Settings.
            current = read_preference_entry(active, LINK_RULES_PREFERENCE_KEY, user_id=user_id)
            if body.expected_version != (0 if current is None else current.version):
                raise HTTPException(409, _STALE_LINK_RULES)
            mutation = PreferenceMutation(
                protocol_version=1,
                identity=active.identity(user_id),
                operation_id=uuid.uuid4(),
                installation_id=_LINK_RULES_INSTALLATION_ID,
                key=LINK_RULES_PREFERENCE_KEY,
                expected_version=body.expected_version,
                value=value,
            )
            result = active.apply(mutation, user_id=user_id)
            if result.status == "conflict":
                raise HTTPException(409, _STALE_LINK_RULES)
            return _link_rules_response(
                supported=True, value=result.entry.value, version=result.entry.version
            )

        return await policy.run(user_id, write)

    return router
