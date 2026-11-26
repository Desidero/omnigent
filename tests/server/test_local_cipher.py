"""The local key file cipher: an explicit opt-in that never stands in for KMS or Vault."""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

import pytest

from omnigent.stores.credential_store.local_cipher import (
    CREDENTIAL_LOCAL_KEY_FILE_ENV_VAR,
    LocalKeySecretCipher,
    build_local_secret_cipher,
    load_local_key,
)
from omnigent.stores.credential_store.secret_cipher import (
    CREDENTIAL_CIPHER_ENV_VAR,
    CREDENTIAL_KMS_KEY_ENV_VAR,
    KmsSecretCipher,
    SecretCipher,
    build_secret_cipher,
)
from omnigent.stores.credential_store.sqlalchemy_store import CredentialStore
from omnigent.stores.credential_store.vault_cipher import (
    CREDENTIAL_VAULT_KEY_ENV_VAR,
    VaultSecretCipher,
)

CTX_ALICE = {"workspace_id": "0", "user_id": "alice", "provider": "github", "account_id": ""}
CTX_BOB = {"workspace_id": "0", "user_id": "bob", "provider": "github", "account_id": ""}

KEY = bytes(range(32))
OTHER_KEY = bytes(range(1, 33))


def write_key_file(path: Path, content: bytes, mode: int = 0o600) -> str:
    path.write_bytes(content)
    path.chmod(mode)
    return str(path)


@pytest.fixture
def key_file(tmp_path: Path) -> str:
    return write_key_file(tmp_path / "credential.key", base64.b64encode(KEY) + b"\n")


@pytest.fixture
def backend_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for var in (
        CREDENTIAL_CIPHER_ENV_VAR,
        CREDENTIAL_KMS_KEY_ENV_VAR,
        CREDENTIAL_VAULT_KEY_ENV_VAR,
        CREDENTIAL_LOCAL_KEY_FILE_ENV_VAR,
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


# ── the SecretCipher contract ───────────────────────────────────────────────


def test_roundtrip_is_bound_to_the_row_identity() -> None:
    cipher = LocalKeySecretCipher(KEY)
    assert isinstance(cipher, SecretCipher)
    sealed = cipher.encrypt("ghu_secret_token", context=CTX_ALICE)
    assert "ghu_secret_token" not in sealed
    assert cipher.decrypt(sealed, context=CTX_ALICE) == "ghu_secret_token"
    assert cipher.decrypt(sealed, context=CTX_BOB) is None
    # account_id="" binds like an absent account; a named account is distinct.
    named = {**CTX_ALICE, "account_id": "org1"}
    assert cipher.decrypt(sealed, context=named) is None
    assert cipher.decrypt(cipher.encrypt("y", context=named), context=named) == "y"
    # Two encryptions of one secret differ (fresh nonce) and both open.
    again = cipher.encrypt("ghu_secret_token", context=CTX_ALICE)
    assert again != sealed
    assert cipher.decrypt(again, context=CTX_ALICE) == "ghu_secret_token"


def test_large_secrets_are_not_capped_like_kms() -> None:
    cipher = LocalKeySecretCipher(KEY)
    secret = "t" * 20_000
    assert cipher.decrypt(cipher.encrypt(secret, context=CTX_ALICE), context=CTX_ALICE) == secret


def test_envelope_names_the_backend_and_never_the_key() -> None:
    sealed = LocalKeySecretCipher(KEY).encrypt("x", context=CTX_ALICE)
    prefix, version, key_id, payload = sealed.split(":")
    assert (prefix, version) == ("oslocal", "v1")
    blob = base64.b64decode(payload, validate=True)
    for form in (KEY, KEY.hex().encode(), base64.b64encode(KEY)):
        assert form not in blob
        assert form not in sealed.encode()
    assert key_id not in KEY.hex()
    # The same key gives the same id, so a restart reads what it wrote.
    assert LocalKeySecretCipher(KEY).encrypt("x", context=CTX_ALICE).split(":")[2] == key_id


def test_a_different_key_raises_instead_of_reading_as_disconnected() -> None:
    sealed = LocalKeySecretCipher(KEY).encrypt("x", context=CTX_ALICE)
    with pytest.raises(ValueError, match="different key") as failure:
        LocalKeySecretCipher(OTHER_KEY).decrypt(sealed, context=CTX_ALICE)
    assert base64.b64encode(OTHER_KEY).decode() not in str(failure.value)


def test_an_altered_key_id_raises_like_a_different_key() -> None:
    cipher = LocalKeySecretCipher(KEY)
    prefix, version, _key_id, payload = cipher.encrypt("x", context=CTX_ALICE).split(":")
    for altered in ("0" * 16, "", "clé"):
        with pytest.raises(ValueError, match="different key"):
            cipher.decrypt(f"{prefix}:{version}:{altered}:{payload}", context=CTX_ALICE)


def test_a_newer_envelope_version_raises() -> None:
    cipher = LocalKeySecretCipher(KEY)
    sealed = cipher.encrypt("x", context=CTX_ALICE).replace(":v1:", ":v2:")
    with pytest.raises(ValueError, match="envelope version"):
        cipher.decrypt(sealed, context=CTX_ALICE)


def tampered_forms(sealed: str) -> dict[str, str]:
    prefix, version, key_id, payload = sealed.split(":")
    blob = bytearray(base64.b64decode(payload))

    def with_blob(changed: bytes) -> str:
        return f"{prefix}:{version}:{key_id}:{base64.b64encode(changed).decode()}"

    flipped_nonce, flipped_body, flipped_tag = bytearray(blob), bytearray(blob), bytearray(blob)
    flipped_nonce[0] ^= 1
    flipped_body[12] ^= 1
    flipped_tag[-1] ^= 1
    return {
        "nonce": with_blob(bytes(flipped_nonce)),
        "body": with_blob(bytes(flipped_body)),
        "tag": with_blob(bytes(flipped_tag)),
        "truncated": with_blob(bytes(blob[:-1])),
        "shorter than a nonce": with_blob(bytes(blob[:5])),
        "empty payload": f"{prefix}:{version}:{key_id}:",
        "not base64": f"{prefix}:{version}:{key_id}:%%%",
    }


@pytest.mark.parametrize(
    "form",
    ["nonce", "body", "tag", "truncated", "shorter than a nonce", "empty payload", "not base64"],
)
def test_tampered_ciphertext_reads_as_disconnected(form: str) -> None:
    cipher = LocalKeySecretCipher(KEY)
    sealed = cipher.encrypt("ghu_secret_token", context=CTX_ALICE)
    assert cipher.decrypt(tampered_forms(sealed)[form], context=CTX_ALICE) is None


@pytest.mark.parametrize(
    "stored",
    [
        "not-a-real-ciphertext!!",
        "AQIDBAUGBwg=",
        "osvault:a2V5:vault:v1:abc",
        "oslocal:v1:onlythree",
    ],
)
def test_another_backends_or_corrupt_value_reads_as_disconnected(stored: str) -> None:
    assert LocalKeySecretCipher(KEY).decrypt(stored, context=CTX_ALICE) is None


def test_store_roundtrip_and_key_change(db_uri: str) -> None:
    store = CredentialStore(db_uri, LocalKeySecretCipher(KEY))
    store.upsert("alice", "github", secret={"access_token": "ghu_alice"}, metadata={})
    assert store.get("alice", "github", with_secret=True).secret == {"access_token": "ghu_alice"}

    rotated = CredentialStore(db_uri, LocalKeySecretCipher(OTHER_KEY))
    # Without the secret the row still lists; reading it under the new key is refused.
    assert rotated.get("alice", "github") is not None
    with pytest.raises(ValueError, match="different key"):
        rotated.get("alice", "github", with_secret=True)
    # Reconnecting overwrites the row under the new key.
    rotated.upsert("alice", "github", secret={"access_token": "ghu_new"}, metadata={})
    assert rotated.get("alice", "github", with_secret=True).secret == {"access_token": "ghu_new"}


# ── the key file ────────────────────────────────────────────────────────────


def test_key_file_is_read_with_surrounding_whitespace(key_file: str) -> None:
    assert load_local_key(key_file) == KEY


def test_missing_key_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot be opened"):
        load_local_key(str(tmp_path / "absent.key"))


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o620, 0o602, 0o610, 0o601, 0o644, 0o666])
def test_key_file_open_to_group_or_others_is_refused(tmp_path: Path, mode: int) -> None:
    path = write_key_file(tmp_path / "credential.key", base64.b64encode(KEY), mode)
    with pytest.raises(ValueError, match="group or others"):
        load_local_key(path)


@pytest.mark.parametrize("mode", [0o600, 0o400])
def test_owner_only_key_file_is_accepted(tmp_path: Path, mode: int) -> None:
    path = write_key_file(tmp_path / "credential.key", base64.b64encode(KEY), mode)
    assert load_local_key(path) == KEY


def test_permissions_are_those_of_the_file_a_link_points_at(tmp_path: Path) -> None:
    target = write_key_file(tmp_path / "target.key", base64.b64encode(KEY), 0o644)
    link = tmp_path / "credential.key"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="group or others"):
        load_local_key(str(link))


def test_a_directory_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / "keys"
    directory.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="not a regular file"):
        load_local_key(str(directory))


@pytest.mark.parametrize(
    "content",
    [
        b"",
        base64.b64encode(KEY[:16]),
        base64.b64encode(KEY + b"\x00"),
        base64.b64encode(KEY) * 2,
        KEY,  # raw bytes, not base64
        KEY.hex().encode(),
        b"A" * 1000,
        base64.b64encode(KEY) + b"\n" * 200 + base64.b64encode(OTHER_KEY),
    ],
)
def test_key_of_the_wrong_length_or_encoding_is_refused(tmp_path: Path, content: bytes) -> None:
    path = write_key_file(tmp_path / "credential.key", content)
    with pytest.raises(ValueError, match="32-byte key in base64") as failure:
        load_local_key(path)
    if content:
        assert content.decode("latin-1") not in str(failure.value)


def test_the_cipher_refuses_a_key_of_the_wrong_length() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        LocalKeySecretCipher(KEY[:16])


def test_building_logs_the_path_and_never_the_key(
    backend_env: pytest.MonkeyPatch, key_file: str, caplog: pytest.LogCaptureFixture
) -> None:
    assert build_local_secret_cipher() is None
    backend_env.setenv(CREDENTIAL_LOCAL_KEY_FILE_ENV_VAR, key_file)
    with caplog.at_level(logging.DEBUG):
        cipher = build_local_secret_cipher()
        sealed = cipher.encrypt("x", context=CTX_ALICE)
        cipher.decrypt(sealed, context=CTX_BOB)
    assert key_file in caplog.text
    for form in (base64.b64encode(KEY).decode(), KEY.hex()):
        assert form not in caplog.text
    # Nothing is created next to the operator's file.
    assert os.listdir(os.path.dirname(key_file)) == ["credential.key"]


# ── selection: explicit only, never a fallback ──────────────────────────────


def test_selected_by_name_with_its_key_file(
    backend_env: pytest.MonkeyPatch, key_file: str
) -> None:
    backend_env.setenv(CREDENTIAL_CIPHER_ENV_VAR, "local")
    backend_env.setenv(CREDENTIAL_LOCAL_KEY_FILE_ENV_VAR, key_file)
    cipher = build_secret_cipher()
    assert isinstance(cipher, LocalKeySecretCipher)
    assert cipher.decrypt(cipher.encrypt("x", context=CTX_ALICE), context=CTX_ALICE) == "x"


def test_selected_without_a_key_file_refuses_and_generates_none(
    backend_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backend_env.setenv(CREDENTIAL_CIPHER_ENV_VAR, "local")
    with pytest.raises(ValueError, match="its key is unset"):
        build_secret_cipher()
    absent = tmp_path / "absent.key"
    backend_env.setenv(CREDENTIAL_LOCAL_KEY_FILE_ENV_VAR, str(absent))
    with pytest.raises(ValueError, match="cannot be opened"):
        build_secret_cipher()
    assert not absent.exists()


def test_selected_with_an_unusable_key_file_refuses(
    backend_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backend_env.setenv(CREDENTIAL_CIPHER_ENV_VAR, "local")
    readable = write_key_file(tmp_path / "open.key", base64.b64encode(KEY), 0o644)
    backend_env.setenv(CREDENTIAL_LOCAL_KEY_FILE_ENV_VAR, readable)
    with pytest.raises(ValueError, match="group or others"):
        build_secret_cipher()
    short = write_key_file(tmp_path / "short.key", base64.b64encode(KEY[:8]))
    backend_env.setenv(CREDENTIAL_LOCAL_KEY_FILE_ENV_VAR, short)
    with pytest.raises(ValueError, match="32-byte key in base64"):
        build_secret_cipher()


def test_a_key_file_alone_is_never_auto_detected(
    backend_env: pytest.MonkeyPatch, key_file: str
) -> None:
    backend_env.setenv(CREDENTIAL_LOCAL_KEY_FILE_ENV_VAR, key_file)
    with pytest.raises(ValueError, match="never auto-detected"):
        build_secret_cipher()


@pytest.mark.parametrize(
    ("other_var", "other_value"),
    [(CREDENTIAL_KMS_KEY_ENV_VAR, "alias/x"), (CREDENTIAL_VAULT_KEY_ENV_VAR, "omnigent-cred")],
)
def test_a_key_file_never_stands_in_beside_kms_or_vault(
    backend_env: pytest.MonkeyPatch, key_file: str, other_var: str, other_value: str
) -> None:
    backend_env.setenv(CREDENTIAL_LOCAL_KEY_FILE_ENV_VAR, key_file)
    backend_env.setenv(other_var, other_value)
    # No selector: a startup error, not a silent pick of either.
    with pytest.raises(ValueError, match="never auto-detected"):
        build_secret_cipher()
    # Selecting local while the other backend's key is still set is refused too.
    backend_env.setenv(CREDENTIAL_CIPHER_ENV_VAR, "local")
    with pytest.raises(ValueError, match="cannot be combined"):
        build_secret_cipher()


def test_a_named_kms_or_vault_backend_ignores_the_key_file(
    backend_env: pytest.MonkeyPatch, key_file: str
) -> None:
    backend_env.setenv(CREDENTIAL_LOCAL_KEY_FILE_ENV_VAR, key_file)
    backend_env.setenv(CREDENTIAL_CIPHER_ENV_VAR, "kms")
    # KMS named but unconfigured: an error, not the local key.
    with pytest.raises(ValueError, match="its key is unset"):
        build_secret_cipher()
    backend_env.setenv(CREDENTIAL_KMS_KEY_ENV_VAR, "alias/x")
    assert isinstance(build_secret_cipher(), KmsSecretCipher)
    backend_env.setenv(CREDENTIAL_CIPHER_ENV_VAR, "vault")
    backend_env.setenv(CREDENTIAL_VAULT_KEY_ENV_VAR, "omnigent-cred")
    assert isinstance(build_secret_cipher(), VaultSecretCipher)


def test_a_failing_kms_call_raises_with_no_local_fallback(
    backend_env: pytest.MonkeyPatch, key_file: str
) -> None:
    class FailingKms:
        def encrypt(self, **_: object) -> object:
            raise RuntimeError("kms unavailable")

    backend_env.setenv(CREDENTIAL_LOCAL_KEY_FILE_ENV_VAR, key_file)
    backend_env.setenv(CREDENTIAL_CIPHER_ENV_VAR, "kms")
    backend_env.setenv(CREDENTIAL_KMS_KEY_ENV_VAR, "alias/x")
    cipher = build_secret_cipher()
    assert isinstance(cipher, KmsSecretCipher)
    cipher._client = FailingKms()
    with pytest.raises(RuntimeError, match="kms unavailable"):
        cipher.encrypt("x", context=CTX_ALICE)


def test_unknown_selector_lists_local(backend_env: pytest.MonkeyPatch) -> None:
    backend_env.setenv(CREDENTIAL_CIPHER_ENV_VAR, "bogus")
    with pytest.raises(ValueError, match=r"\['kms', 'local', 'vault'\]"):
        build_secret_cipher()
