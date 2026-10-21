"""Unity Gateway usage-attribution headers."""

from __future__ import annotations

import pytest

from omnigent.databricks_ai_gateway import (
    gateway_attribution_headers,
    with_gateway_attribution,
    with_gateway_attribution_lines,
)

_GW = "https://dbc-1.cloud.databricks.com/ai-gateway/anthropic"


@pytest.mark.parametrize(("via_ug", "surfaces"), [(False, "omnigent"), (True, "omnigent, ug")])
def test_gateway_attribution_headers_name_omnigent_outermost(via_ug: bool, surfaces: str) -> None:
    assert gateway_attribution_headers("codex", via_ug=via_ug) == {
        "Databricks-Custom-Coding-Agent": "codex",
        "Databricks-Custom-Client-Surfaces": surfaces,
    }


def test_with_gateway_attribution_marks_ug_providers_by_user_agent() -> None:
    assert with_gateway_attribution({"User-Agent": "ucode/0.1.0 pi/0.80.0"}, "pi", _GW) == {
        "User-Agent": "ucode/0.1.0 pi/0.80.0",
        "Databricks-Custom-Coding-Agent": "pi",
        "Databricks-Custom-Client-Surfaces": "omnigent, ug",
    }
    assert (
        with_gateway_attribution(None, "pi", _GW)["Databricks-Custom-Client-Surfaces"]
        == "omnigent"
    )


def test_with_gateway_attribution_lines_appends_to_the_claude_block() -> None:
    block = with_gateway_attribution_lines(
        "x-databricks-use-coding-agent-mode: true", "claude-code", via_ug=True
    )

    assert block.splitlines() == [
        "x-databricks-use-coding-agent-mode: true",
        "Databricks-Custom-Coding-Agent: claude-code",
        "Databricks-Custom-Client-Surfaces: omnigent, ug",
    ]


def test_ug_configured_workspace_marks_a_provider_without_a_ug_user_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ug's state names the workspace even when only managed config carries ug's User-Agent."""
    from omnigent.databricks_ai_gateway import is_ug_route

    configured = {"https://dbc-1.cloud.databricks.com"}
    monkeypatch.setattr(
        "omnigent.onboarding.ucode_state.read_ucode_state",
        lambda url: object() if url in configured else None,
    )

    assert is_ug_route("https://dbc-1.cloud.databricks.com/ai-gateway/codex/v1")
    assert not is_ug_route("https://dbc-2.cloud.databricks.com/ai-gateway/codex/v1")
    assert with_gateway_attribution(
        {"X-Tag": "1"}, "codex", "https://dbc-1.cloud.databricks.com/ai-gateway/codex/v1"
    ) == {
        "X-Tag": "1",
        "Databricks-Custom-Coding-Agent": "codex",
        "Databricks-Custom-Client-Surfaces": "omnigent, ug",
    }


def test_gateway_request_tags_send_the_session_id_and_namespaced_user_labels() -> None:
    """User labels are sent as ``omnigent_label_<key>``, so a session editor
    cannot write a tag a gateway policy matches on, such as ``team``."""
    from omnigent.databricks_ai_gateway import gateway_request_tags_value

    labels = {
        "team": "ml",
        "project": "chat bot",
        "omnigent.wrapper": "claude-code-native-ui",
        "omni_project": "sidebar",
        "cost_control.plan": "{}",
        # A label cannot replace the session id.
        "omnigent_session_id": "spoofed",
    }

    assert gateway_request_tags_value("conv_abc123", labels) == (
        '{"omnigent_session_id":"conv_abc123",'
        '"omnigent_label_omnigent_session_id":"spoofed",'
        '"omnigent_label_project":"chat bot","omnigent_label_team":"ml"}'
    )


def test_gateway_request_tags_stop_at_the_first_label_past_the_cap() -> None:
    from omnigent.databricks_ai_gateway import gateway_request_tags, gateway_request_tags_value

    labels = {"a": "x" * 2000, "b": "y" * 3000, "c": "small", "d\n": "é"}

    tags = gateway_request_tags("conv_1", labels)

    # ``b`` overflows, and later shorter labels are not back-filled.
    assert list(tags) == ["omnigent_session_id", "omnigent_label_a"]
    encoded = gateway_request_tags_value("conv_1", labels)
    assert encoded is not None and encoded.isascii() and "\n" not in encoded
    assert len(encoded) <= 4 * 1024
    assert gateway_request_tags("conv_1", {"a": "x" * 4100}) == {"omnigent_session_id": "conv_1"}
    small = gateway_request_tags("conv_1", {"c": "small", "d\n": "é"})
    assert list(small) == ["omnigent_session_id", "omnigent_label_c", "omnigent_label_d\n"]


@pytest.mark.parametrize(
    ("switch", "enabled"), [(None, True), ("1", True), ("0", False), ("off", False)]
)
def test_gateway_request_tags_switch(
    monkeypatch: pytest.MonkeyPatch, switch: str | None, enabled: bool
) -> None:
    from omnigent.databricks_ai_gateway import (
        REQUEST_TAGS_SWITCH_ENV,
        REQUEST_TAGS_VALUE_ENV,
        gateway_request_tags_env,
        gateway_request_tags_headers,
    )

    if switch is None:
        monkeypatch.delenv(REQUEST_TAGS_SWITCH_ENV, raising=False)
    else:
        monkeypatch.setenv(REQUEST_TAGS_SWITCH_ENV, switch)

    env = gateway_request_tags_env("conv_1", {"team": "ml"})
    harness_env = {REQUEST_TAGS_VALUE_ENV: '{"omnigent_session_id":"conv_1"}'}
    if switch is not None:
        harness_env[REQUEST_TAGS_SWITCH_ENV] = switch

    assert bool(env) is enabled
    assert gateway_request_tags_headers(harness_env) == (
        {"Databricks-Ai-Gateway-Request-Tags": '{"omnigent_session_id":"conv_1"}'}
        if enabled
        else {}
    )
    assert gateway_request_tags_headers({}) == {}


def test_with_gateway_request_tags_line_replaces_an_existing_line() -> None:
    """Re-materialising a config or launching inside a tagged process keeps one line."""
    from omnigent.databricks_ai_gateway import with_gateway_request_tags_line

    assert with_gateway_request_tags_line(None, '{"omnigent_session_id":"c"}') == (
        'Databricks-Ai-Gateway-Request-Tags: {"omnigent_session_id":"c"}'
    )
    once = with_gateway_request_tags_line("X-A: 1", "{}")
    assert once.splitlines() == ["X-A: 1", "Databricks-Ai-Gateway-Request-Tags: {}"]
    stale = 'databricks-ai-gateway-request-tags: {"old":"1"}\nX-B: 2'
    assert with_gateway_request_tags_line(stale, "{}").splitlines() == [
        "X-B: 2",
        "Databricks-Ai-Gateway-Request-Tags: {}",
    ]


def test_with_gateway_request_tags_replaces_an_existing_header() -> None:
    from omnigent.databricks_ai_gateway import with_gateway_request_tags

    headers = {"User-Agent": "ucode/0.1.0", "databricks-ai-gateway-request-tags": "{}"}

    stamped = with_gateway_request_tags(headers, '{"omnigent_session_id":"c"}')

    assert stamped == {
        "User-Agent": "ucode/0.1.0",
        "Databricks-Ai-Gateway-Request-Tags": '{"omnigent_session_id":"c"}',
    }
    assert with_gateway_request_tags(stamped, "{}") == {
        "User-Agent": "ucode/0.1.0",
        "Databricks-Ai-Gateway-Request-Tags": "{}",
    }
    assert with_gateway_request_tags(None, "{}") == {"Databricks-Ai-Gateway-Request-Tags": "{}"}
    # The configured headers are shared across renders, so they stay unstamped.
    assert "Databricks-Ai-Gateway-Request-Tags" not in headers
