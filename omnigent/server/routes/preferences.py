"""Per-user preference routes (``/v1/preferences``) and the chat link rules
(``/v1/link-rules``).

Shared preferences take explicit reads and versioned edits; no implicit adoption.
Link rules are a shared preference too; their route serves the defaults when
none are saved and gives agent tools a single versioned write.
"""

import uuid
from functools import partial
from typing import Annotated

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
from omnigent.server.auth import AuthProvider
from omnigent.server.preference_requests import (
    DEFAULT_PREFERENCE_POLICY,
    MAX_PREFERENCE_REQUEST_BYTES,
    PreferencePolicy,
    read_preference_payload,
)
from omnigent.server.routes._auth_helpers import require_user
from omnigent.server.schemas import (
    LinkRuleModel,
    LinkRulesResponse,
    LinkRulesUpdateRequest,
)
from omnigent.stores.preference_store import PreferenceStore, read_preference_entry

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
