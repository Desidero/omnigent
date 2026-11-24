"""AWS credentials for the KMS cipher from a Unity Catalog service credential.

The KMS cipher normally finds AWS credentials through boto3's default chain,
which suits a pod with an IAM role. A server that runs as a Databricks identity
with no AWS identity of its own (a Databricks App, for one) has nothing in that
chain. It can still reach KMS through a Unity Catalog *service credential*: the
workspace exchanges the server's Databricks identity for short-lived credentials
of the IAM role the service credential wraps.

``OMNIGENT_CREDENTIAL_KMS_UC_SERVICE_CREDENTIAL`` names that service credential.
When it is set, the KMS client signs with those credentials only (the default
chain is not consulted) and fetches new ones before the old ones expire. boto3
and the Databricks SDK are imported lazily, so this module costs nothing until
the option is used. See ``designs/CREDENTIAL_STORE.md``.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

#: Names the Unity Catalog service credential the KMS cipher gets its AWS
#: credentials from. Unset ⇒ boto3's default credential chain.
CREDENTIAL_KMS_UC_SERVICE_CREDENTIAL_ENV_VAR = "OMNIGENT_CREDENTIAL_KMS_UC_SERVICE_CREDENTIAL"

_CREDENTIAL_METHOD = "databricks-uc-service-credential"

#: Lifetime assumed when the workspace reports no expiry. botocore refreshes 15
#: minutes ahead, so this refetches about every five minutes rather than
#: trusting credentials of unknown age.
_ASSUMED_LIFETIME = datetime.timedelta(minutes=20)


def fetch_aws_credentials(credential_name: str, workspace_client: Any) -> dict[str, str]:
    """Exchange the workspace identity for the service credential's AWS credentials.

    :param credential_name: Unity Catalog service credential, e.g.
        ``"omnigent-kms"``.
    :param workspace_client: A ``databricks.sdk.WorkspaceClient``.
    :returns: botocore refresh metadata: ``access_key``, ``secret_key``,
        ``token`` and an ISO 8601 ``expiry_time``.
    :raises RuntimeError: If the service credential is not an AWS one.
    """
    temporary = workspace_client.credentials.generate_temporary_service_credential(
        credential_name=credential_name
    )
    aws = temporary.aws_temp_credentials
    if aws is None:
        raise RuntimeError(
            f"Unity Catalog service credential {credential_name!r} returned no AWS "
            "credentials; the KMS credential backend needs one that wraps an IAM role."
        )
    if temporary.expiration_time:
        expiry = datetime.datetime.fromtimestamp(temporary.expiration_time / 1000, tz=datetime.UTC)
    else:
        expiry = datetime.datetime.now(tz=datetime.UTC) + _ASSUMED_LIFETIME
    return {
        "access_key": aws.access_key_id,
        "secret_key": aws.secret_access_key,
        "token": aws.session_token,
        "expiry_time": expiry.isoformat(),
    }


def _credential_fetcher(credential_name: str, workspace_client: Any | None) -> Callable[[], dict]:
    """A zero-argument fetch for botocore; the workspace client is built on first use."""
    clients = [workspace_client] if workspace_client is not None else []

    def fetch() -> dict[str, str]:
        if not clients:
            try:
                from databricks.sdk import WorkspaceClient
            except ImportError as exc:  # pragma: no cover - import guard
                raise ImportError(
                    f"{CREDENTIAL_KMS_UC_SERVICE_CREDENTIAL_ENV_VAR} needs the Databricks "
                    "SDK. Install it with `pip install 'omnigent[databricks]'`."
                ) from exc
            clients.append(WorkspaceClient())
        return fetch_aws_credentials(credential_name, clients[0])

    return fetch


def build_aws_session(credential_name: str, *, workspace_client: Any | None = None) -> Any:
    """A botocore session whose only credential source is the service credential.

    The credentials are fetched on first use and again shortly before they
    expire; ``AWS_ACCESS_KEY_ID``, profiles and instance roles are not consulted.

    :param credential_name: Unity Catalog service credential, e.g.
        ``"omnigent-kms"``.
    :param workspace_client: Optional ``WorkspaceClient`` (tests inject a fake);
        default: one built from the ambient Databricks credentials.
    """
    import botocore.session
    from botocore.credentials import (
        CredentialProvider,
        CredentialResolver,
        DeferredRefreshableCredentials,
    )

    fetch = _credential_fetcher(credential_name, workspace_client)

    class _ServiceCredentialProvider(CredentialProvider):
        METHOD = _CREDENTIAL_METHOD
        CANONICAL_NAME = _CREDENTIAL_METHOD

        def load(self) -> Any:
            return DeferredRefreshableCredentials(refresh_using=fetch, method=self.METHOD)

    session = botocore.session.Session()
    session.register_component(
        "credential_provider", CredentialResolver([_ServiceCredentialProvider()])
    )
    return session


def build_kms_client(credential_name: str, *, workspace_client: Any | None = None) -> Any:
    """A boto3 KMS client that signs with the service credential's AWS credentials.

    The region comes from the usual AWS settings (``AWS_DEFAULT_REGION``).
    """
    import boto3

    session = build_aws_session(credential_name, workspace_client=workspace_client)
    return boto3.Session(botocore_session=session).client("kms")
