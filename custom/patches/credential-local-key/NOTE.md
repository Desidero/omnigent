# credential-local-key

Needs: none
Covers: ce9935ac6ec58082

A trial or single-machine server with neither AWS KMS nor Vault can turn on
the credential store, and so the per-user connections built on it, with a key
the operator keeps in a file (AES-256-GCM). It is an explicit choice and never
a fallback. The trade-off: anyone who can read the key file and the database
can read every stored token, no decrypt is logged or revocable, and changing
the key means every user reconnects.

- **Turn on:** create the key (`(umask 077 && openssl rand -base64 32 > <file>)`),
  then set `OMNIGENT_CREDENTIAL_CIPHER=local` and
  `OMNIGENT_CREDENTIAL_LOCAL_KEY_FILE=<file>`, with no KMS or Vault key set.
- **Docs:** "Local key file (explicit opt-in)" in the
  [credential store design](../../designs/CREDENTIAL_STORE.md#local-key-file-explicit-opt-in);
  a pointer in the [MCP registry README](../../examples/mcp-registry/README.md#administrator-configuration).
- **Upstream:** not proposed, no contribution branch. Upstream's design says
  "There is no non-KMS fallback", so this needs a maintainer's agreement before
  a proposal; no open issue or pull request asks for a local key (searched
  2026-11-26). Open neighbours on the same builder:
  [#9887](https://github.com/omnigent-ai/omnigent/pull/9887) (Azure Key Vault),
  [#14901](https://github.com/omnigent-ai/omnigent/pull/14901) (KMS envelope
  encryption), [#13868](https://github.com/omnigent-ai/omnigent/pull/13868) (KMS region).

## Must hold

- No key fallback: the local key is used only when `OMNIGENT_CREDENTIAL_CIPHER=local` names it. The key file variable without the selector, and `local` beside a configured KMS or Vault key, each stop startup; with `kms` or `vault` selected the key file is ignored and a failing KMS or Vault call fails.
- With nothing configured the store stays off, as before the series.
- A key file that is missing, not a regular file, accessible by group or others, or not exactly one 32-byte base64 key raises when the cipher is built, before anything is encrypted.
- The server never generates, writes or logs a key; errors and logs name the file's path only.
- A ciphertext opens only under the same key and the same row identity; an altered ciphertext, another identity, or another backend's value reads as disconnected (`None`), never as a wrong plaintext.
- A ciphertext written under a different local key raises instead of reading as disconnected, so a wrong key file is seen as a store-wide error; reconnecting overwrites the row under the current key.
- Stored values start with `oslocal:v1:`, apart from KMS (bare base64) and Vault (`osvault:`), and hold no key material.

## Key code

- `omnigent/stores/credential_store/local_cipher.py`: `LocalKeySecretCipher`, `load_local_key`, `build_local_secret_cipher`, `CREDENTIAL_LOCAL_KEY_FILE_ENV_VAR`
- `omnigent/stores/credential_store/secret_cipher.py`: `build_secret_cipher`, `explicit_only`

## Tests

- `tests/server/test_local_cipher.py::test_roundtrip_is_bound_to_the_row_identity`
- `tests/server/test_local_cipher.py::test_a_different_key_raises_instead_of_reading_as_disconnected`
- `tests/server/test_local_cipher.py::test_tampered_ciphertext_reads_as_disconnected`
- `tests/server/test_local_cipher.py::test_store_roundtrip_and_key_change`
- `tests/server/test_local_cipher.py::test_missing_key_file_is_refused`
- `tests/server/test_local_cipher.py::test_key_file_open_to_group_or_others_is_refused`
- `tests/server/test_local_cipher.py::test_key_of_the_wrong_length_or_encoding_is_refused`
- `tests/server/test_local_cipher.py::test_building_logs_the_path_and_never_the_key`
- `tests/server/test_local_cipher.py::test_a_key_file_alone_is_never_auto_detected`
- `tests/server/test_local_cipher.py::test_a_key_file_never_stands_in_beside_kms_or_vault`
- `tests/server/test_local_cipher.py::test_a_named_kms_or_vault_backend_ignores_the_key_file`
- `tests/server/test_local_cipher.py::test_a_failing_kms_call_raises_with_no_local_fallback`
