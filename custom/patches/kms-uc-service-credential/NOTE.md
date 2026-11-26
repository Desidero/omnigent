# kms-uc-service-credential

Needs: none
Covers: 24cef1ab5a8b5cd9

The credential store's AWS KMS backend can sign with the short-lived AWS
credentials of a Unity Catalog service credential, so a server with no AWS
identity of its own (a Databricks App) can use KMS without static keys, an AWS
config file or a helper script. The credentials are renewed before they expire.

- **Turn on:** set `OMNIGENT_CREDENTIAL_KMS_UC_SERVICE_CREDENTIAL` to the
  service credential's name, next to `OMNIGENT_CREDENTIAL_KMS_KEY_ID` and
  `AWS_DEFAULT_REGION`; install the `kms` and `databricks` extras. Unset, KMS
  uses boto3's default credential chain as before.
- **Docs:** [Credential store](../../designs/CREDENTIAL_STORE.md)
  (Databricks identity → KMS) and the deploy guide's Databricks account
  connection.
- **Upstream:** not upstream yet and not proposed.

## Must hold

- With `OMNIGENT_CREDENTIAL_KMS_UC_SERVICE_CREDENTIAL` set, the KMS client signs only with that service credential's AWS credentials; boto3's default chain (`AWS_ACCESS_KEY_ID`, profiles, instance roles) is not consulted.
- Unset, the cipher builds its KMS client from boto3's default credential chain exactly as before.
- Nothing is fetched until the first encrypt or decrypt; new credentials are fetched before the current ones expire, and a 20-minute lifetime is assumed when the workspace reports no expiry.
- A service credential that returns no AWS credentials fails with an error that names it.
- No dependency changes: boto3 (the `kms` extra) and the Databricks SDK (the `databricks` extra, not part of `kms`) are imported lazily, and a missing one fails naming the extra to install.

## Key code

- `omnigent/stores/credential_store/uc_service_credential.py`: `build_kms_client`, `build_aws_session`, `fetch_aws_credentials`, `CREDENTIAL_KMS_UC_SERVICE_CREDENTIAL_ENV_VAR`
- `omnigent/stores/credential_store/secret_cipher.py`: `KmsSecretCipher`, `uc_service_credential`

## Tests

- `tests/server/test_uc_service_credential.py::test_kms_requests_are_signed_with_the_service_credential_across_a_refresh`
- `tests/server/test_uc_service_credential.py::test_the_session_uses_only_the_service_credential`
- `tests/server/test_uc_service_credential.py::test_credentials_are_fetched_again_once_they_near_expiry`
- `tests/server/test_uc_service_credential.py::test_the_cipher_builds_its_client_from_the_named_service_credential`
- `tests/server/test_uc_service_credential.py::test_without_the_option_the_cipher_keeps_the_default_chain`
