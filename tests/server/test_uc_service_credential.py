"""The KMS cipher signing with a Unity Catalog service credential's AWS credentials.

A fake workspace client stands in for Databricks and the HTTP send is replaced
on the boto3 client, so no call leaves the process. What is real is botocore:
its credential resolution, refresh timing and request signing, which is the part
that decides whether a server without an AWS identity can reach KMS and keep
reaching it after the first credentials expire.
"""

from __future__ import annotations

import base64
import datetime
import io
import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from botocore.awsrequest import AWSResponse

from omnigent.stores.credential_store import secret_cipher, uc_service_credential
from omnigent.stores.credential_store.secret_cipher import (
    CREDENTIAL_KMS_KEY_ENV_VAR,
    KmsSecretCipher,
    build_kms_secret_cipher,
)
from omnigent.stores.credential_store.uc_service_credential import (
    CREDENTIAL_KMS_UC_SERVICE_CREDENTIAL_ENV_VAR,
    build_aws_session,
    build_kms_client,
    fetch_aws_credentials,
)

_CONTEXT = {"workspace_id": "0", "user_id": "alice", "provider": "databricks", "account_id": ""}
_KEY_ARN = "arn:aws:kms:us-east-1:111122223333:key/00000000-0000-0000-0000-000000000000"


def _now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.UTC)


def _temporary(index: int, expires: datetime.datetime | None) -> SimpleNamespace:
    """The shape ``generate_temporary_service_credential`` returns, numbered per fetch."""
    return SimpleNamespace(
        aws_temp_credentials=SimpleNamespace(
            access_key_id=f"AKIAFETCH{index}",
            secret_access_key=f"secret-{index}",
            session_token=f"token-{index}",
        ),
        expiration_time=int(expires.timestamp() * 1000) if expires else None,
    )


class _FakeWorkspaceClient:
    """Hands out one numbered credential per call, with the given lifetimes."""

    def __init__(self, *lifetimes: datetime.timedelta | None) -> None:
        self._lifetimes = list(lifetimes)
        self.requested: list[str] = []
        self.credentials = SimpleNamespace(
            generate_temporary_service_credential=self._generate,
        )

    def _generate(self, *, credential_name: str) -> SimpleNamespace:
        self.requested.append(credential_name)
        lifetime = self._lifetimes[min(len(self.requested), len(self._lifetimes)) - 1]
        return _temporary(len(self.requested), _now() + lifetime if lifetime else None)


class _RawBody(io.BytesIO):
    def stream(self, **_kwargs: Any) -> Iterator[bytes]:
        yield self.read()


def _answer_locally(client: Any) -> list[Any]:
    """Answer the client's KMS requests in-process and return the signed requests."""
    sent: list[Any] = []

    def respond(request: Any, **_kwargs: Any) -> AWSResponse:
        sent.append(request)
        body = json.dumps(
            {"CiphertextBlob": base64.b64encode(b"blob").decode(), "KeyId": _KEY_ARN}
        )
        headers = {"content-type": "application/x-amz-json-1.1"}
        return AWSResponse(request.url, 200, headers, _RawBody(body.encode()))

    client.meta.events.register("before-send.kms", respond)
    return sent


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    # Credentials the default chain would pick up, which must never be used.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFROMENVIRONMENT")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "environment-secret")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)


def test_fetch_maps_the_temporary_credential_for_botocore() -> None:
    expires = datetime.datetime(2030, 1, 2, 3, 4, 5, tzinfo=datetime.UTC)
    workspace = SimpleNamespace(
        credentials=SimpleNamespace(
            generate_temporary_service_credential=lambda credential_name: _temporary(1, expires)
        )
    )

    assert fetch_aws_credentials("omnigent-kms", workspace) == {
        "access_key": "AKIAFETCH1",
        "secret_key": "secret-1",
        "token": "token-1",
        "expiry_time": "2030-01-02T03:04:05+00:00",
    }


def test_fetch_assumes_a_short_lifetime_when_no_expiry_is_reported() -> None:
    workspace = _FakeWorkspaceClient(None)

    metadata = fetch_aws_credentials("omnigent-kms", workspace)

    remaining = datetime.datetime.fromisoformat(metadata["expiry_time"]) - _now()
    # Past botocore's 15-minute refresh window, but far short of an unknown real expiry.
    assert datetime.timedelta(minutes=15) < remaining <= datetime.timedelta(minutes=20)


def test_fetch_rejects_a_service_credential_without_aws_credentials() -> None:
    workspace = SimpleNamespace(
        credentials=SimpleNamespace(
            generate_temporary_service_credential=lambda credential_name: SimpleNamespace(
                aws_temp_credentials=None, expiration_time=None
            )
        )
    )

    with pytest.raises(RuntimeError, match="'azure-credential' returned no AWS credentials"):
        fetch_aws_credentials("azure-credential", workspace)


def test_the_session_uses_only_the_service_credential() -> None:
    workspace = _FakeWorkspaceClient(datetime.timedelta(hours=1))

    session = build_aws_session("omnigent-kms", workspace_client=workspace)

    # Nothing is fetched until a request needs signing.
    assert workspace.requested == []
    frozen = session.get_credentials().get_frozen_credentials()
    assert (frozen.access_key, frozen.secret_key, frozen.token) == (
        "AKIAFETCH1",
        "secret-1",
        "token-1",
    )
    assert workspace.requested == ["omnigent-kms"]


def test_credentials_are_fetched_again_once_they_near_expiry() -> None:
    # The first credential is already inside botocore's mandatory refresh window.
    workspace = _FakeWorkspaceClient(datetime.timedelta(minutes=1), datetime.timedelta(hours=1))
    credentials = build_aws_session("omnigent-kms", workspace_client=workspace).get_credentials()

    assert credentials.get_frozen_credentials().access_key == "AKIAFETCH1"
    assert credentials.get_frozen_credentials().access_key == "AKIAFETCH2"
    # The second one is long-lived, so it is reused.
    assert credentials.get_frozen_credentials().access_key == "AKIAFETCH2"
    assert len(workspace.requested) == 2


def test_kms_requests_are_signed_with_the_service_credential_across_a_refresh() -> None:
    workspace = _FakeWorkspaceClient(datetime.timedelta(minutes=1), datetime.timedelta(hours=1))
    client = build_kms_client("omnigent-kms", workspace_client=workspace)
    sent = _answer_locally(client)
    cipher = KmsSecretCipher(_KEY_ARN, client=client)

    first = cipher.encrypt("refresh-token", context=_CONTEXT)
    cipher.encrypt("refresh-token", context=_CONTEXT)

    assert first == base64.b64encode(b"blob").decode()
    signatures = [request.headers["Authorization"].decode() for request in sent]
    tokens = [request.headers["X-Amz-Security-Token"].decode() for request in sent]
    assert "Credential=AKIAFETCH1/" in signatures[0]
    assert "Credential=AKIAFETCH2/" in signatures[1]
    assert tokens == ["token-1", "token-2"]
    assert not any("AKIAFROMENVIRONMENT" in signature for signature in signatures)


def test_the_cipher_builds_its_client_from_the_named_service_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[str] = []
    fake_client = SimpleNamespace(
        encrypt=lambda **_kwargs: {"CiphertextBlob": b"blob", "KeyId": _KEY_ARN}
    )

    def fake_build(credential_name: str) -> Any:
        built.append(credential_name)
        return fake_client

    monkeypatch.setattr(uc_service_credential, "build_kms_client", fake_build)
    monkeypatch.setenv(CREDENTIAL_KMS_KEY_ENV_VAR, _KEY_ARN)
    monkeypatch.setenv(CREDENTIAL_KMS_UC_SERVICE_CREDENTIAL_ENV_VAR, " omnigent-kms ")

    cipher = build_kms_secret_cipher()

    assert cipher is not None
    # Building the cipher only reads config; the client is made on first use.
    assert built == []
    cipher.encrypt("refresh-token", context=_CONTEXT)
    cipher.encrypt("refresh-token", context=_CONTEXT)
    assert built == ["omnigent-kms"]


def test_without_the_option_the_cipher_keeps_the_default_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import boto3

    default_clients: list[str] = []
    fake_client = SimpleNamespace(
        encrypt=lambda **_kwargs: {"CiphertextBlob": b"blob", "KeyId": _KEY_ARN}
    )

    def fake_boto3_client(service: str) -> Any:
        default_clients.append(service)
        return fake_client

    def unexpected_build(credential_name: str) -> Any:
        raise AssertionError(f"service credential {credential_name!r} must not be used")

    monkeypatch.setattr(boto3, "client", fake_boto3_client)
    monkeypatch.setattr(uc_service_credential, "build_kms_client", unexpected_build)
    monkeypatch.setenv(CREDENTIAL_KMS_KEY_ENV_VAR, _KEY_ARN)
    monkeypatch.delenv(CREDENTIAL_KMS_UC_SERVICE_CREDENTIAL_ENV_VAR, raising=False)

    cipher = secret_cipher.build_secret_cipher()

    assert isinstance(cipher, KmsSecretCipher)
    cipher.encrypt("refresh-token", context=_CONTEXT)
    assert default_clients == ["kms"]
