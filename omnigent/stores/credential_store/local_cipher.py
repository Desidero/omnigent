"""Local key file :class:`SecretCipher`, for servers with neither AWS KMS nor Vault.

Secrets are sealed with AES-256-GCM under a 32-byte key the operator creates and
keeps in a file. This gives up what the KMS and Vault backends are for: the key
is in the server process, so anyone who can read the key file and the database
can read every stored token, no decrypt is logged or revocable, and changing the
key makes every stored secret unreadable. It suits a trial or single-machine
server and nothing larger.

It is therefore an explicit choice and never a fallback: used only when
``OMNIGENT_CREDENTIAL_CIPHER=local`` names it and
``OMNIGENT_CREDENTIAL_LOCAL_KEY_FILE`` points at the key file (see
:func:`~omnigent.stores.credential_store.secret_cipher.build_secret_cipher`).
The key is never generated, defaulted or logged here. See
``designs/CREDENTIAL_STORE.md``.

The row identity is the AEAD's associated data, serialized as the Vault backend
serializes it, so a ciphertext only opens under the same identity. Each
ciphertext is ``oslocal:v1:<key id>:<base64(nonce + sealed)>``. The key id is a
one-way fingerprint of the key: a changed key file is detected store-wide and
raises, instead of reading as a per-user disconnect whose reconnect would
overwrite ciphertext the old key can still open.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
import stat

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from omnigent.stores.credential_store.secret_cipher import SecretContext

_logger = logging.getLogger(__name__)

#: Path of the operator-created key file. Read only when
#: ``OMNIGENT_CREDENTIAL_CIPHER=local`` selects this backend.
CREDENTIAL_LOCAL_KEY_FILE_ENV_VAR = "OMNIGENT_CREDENTIAL_LOCAL_KEY_FILE"

#: Envelope marker, distinct from Vault's ``osvault`` and KMS's bare base64.
_ENVELOPE_PREFIX = "oslocal"
_ENVELOPE_VERSION = "v1"
_KEY_BYTES = 32
_NONCE_BYTES = 12
_KEY_FILE_MAX_BYTES = 128
_KEY_ID_LABEL = b"omnigent credential store local key id\x00"


def build_local_secret_cipher() -> LocalKeySecretCipher | None:
    """Build the cipher from ``OMNIGENT_CREDENTIAL_LOCAL_KEY_FILE``, or ``None`` when unset.

    Unlike the KMS and Vault builders this reads the key now, so an unusable key
    file stops startup rather than failing the first connection.

    :raises ValueError: When the key file is missing, open to group or others,
        or does not hold a 32-byte base64 key.
    """
    path = os.environ.get(CREDENTIAL_LOCAL_KEY_FILE_ENV_VAR, "").strip()
    if not path:
        return None
    cipher = LocalKeySecretCipher(load_local_key(path))
    _logger.warning(
        "credential store: encrypting with the local key file %s. Anyone who can read "
        "that file and the database can read stored tokens; use KMS or Vault beyond a "
        "trial or single-machine server.",
        path,
    )
    return cipher


def load_local_key(path: str) -> bytes:
    """Read the 32-byte key from the operator's key file at *path*.

    :param path: Key file path, e.g. ``"/etc/omnigent/credential.key"``.
    :raises ValueError: Naming what is wrong with the file, never its content.
    """
    problem = f"{CREDENTIAL_LOCAL_KEY_FILE_ENV_VAR}: key file {path!r}"
    if os.name != "posix":
        raise ValueError(f"{problem} cannot be used: owner-only file modes need a POSIX system")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as exc:
        raise ValueError(f"{problem} cannot be opened ({exc.strerror})") from None
    try:
        # Checked on the open descriptor, so the file read is the file checked.
        mode = os.fstat(descriptor).st_mode
        if not stat.S_ISREG(mode):
            raise ValueError(f"{problem} is not a regular file")
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ValueError(
                f"{problem} is accessible by group or others "
                f"(mode {stat.S_IMODE(mode):03o}); run chmod 600 on it"
            )
        encoded = os.read(descriptor, _KEY_FILE_MAX_BYTES + 1)
    finally:
        os.close(descriptor)
    try:
        key = base64.b64decode(encoded.strip(), validate=True)
    except binascii.Error:
        key = b""
    if len(encoded) > _KEY_FILE_MAX_BYTES:
        key = b""
    if len(key) != _KEY_BYTES:
        raise ValueError(
            f"{problem} must hold one {_KEY_BYTES}-byte key in base64 "
            "(create it with: openssl rand -base64 32)"
        )
    return key


def _associated_data(key_id: str, context: SecretContext) -> bytes:
    """Bind the envelope header and the row identity to a ciphertext.

    Empty values are dropped and keys sorted, as the KMS and Vault backends do,
    so ``account_id=""`` and an absent account bind identically.
    """
    items = {k: v for k, v in context.items() if v != ""}
    canonical = json.dumps(items, sort_keys=True, separators=(",", ":"))
    return f"{_ENVELOPE_PREFIX}:{_ENVELOPE_VERSION}:{key_id}:{canonical}".encode()


class LocalKeySecretCipher:
    """:class:`SecretCipher` sealing secrets with AES-256-GCM under a local key.

    :param key: The 32-byte key, e.g. the result of :func:`load_local_key`.
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_BYTES:
            raise ValueError(f"the local credential key must be {_KEY_BYTES} bytes")
        self._aead = AESGCM(key)
        self._key_id = hashlib.sha256(_KEY_ID_LABEL + key).hexdigest()[:16]

    def encrypt(self, plaintext: str, *, context: SecretContext) -> str:
        # A random 96-bit nonce per secret; the store writes far too few to repeat one.
        nonce = os.urandom(_NONCE_BYTES)
        sealed = self._aead.encrypt(
            nonce, plaintext.encode("utf-8"), _associated_data(self._key_id, context)
        )
        payload = base64.b64encode(nonce + sealed).decode("ascii")
        return f"{_ENVELOPE_PREFIX}:{_ENVELOPE_VERSION}:{self._key_id}:{payload}"

    def decrypt(self, ciphertext: str, *, context: SecretContext) -> str | None:
        """Return the plaintext, or ``None`` when this row cannot be opened.

        ``None`` (reconnect) is for per-row failures only: a value that is not
        this backend's envelope, a different row identity, or a corrupt or
        altered ciphertext. A ciphertext written under another key, or in a
        newer envelope version, is store-wide and raises.
        """
        parts = ciphertext.split(":")
        if len(parts) != 4 or parts[0] != _ENVELOPE_PREFIX:
            _logger.warning(
                "local key cipher: stored value is not a local-key ciphertext "
                "(corrupt, or written by another backend); the affected integration "
                "will read as disconnected until reconnected"
            )
            return None
        _, version, key_id, payload = parts
        if version != _ENVELOPE_VERSION:
            raise ValueError(
                f"local key cipher: ciphertext has envelope version {version!r}, which "
                "this server does not read (written by a newer build?)"
            )
        if key_id != self._key_id:
            raise ValueError(
                "local key cipher: ciphertext was written under a different key than "
                f"the one in {CREDENTIAL_LOCAL_KEY_FILE_ENV_VAR}; refusing to read. "
                "Restore the previous key file, or delete the stored connections so "
                "users reconnect."
            )
        try:
            blob = base64.b64decode(payload, validate=True)
            opened = self._aead.decrypt(
                blob[:_NONCE_BYTES], blob[_NONCE_BYTES:], _associated_data(key_id, context)
            )
        except (InvalidTag, ValueError):
            _logger.warning(
                "local key cipher: could not open a ciphertext (wrong row identity, or "
                "corrupt); the affected integration will read as disconnected until "
                "reconnected"
            )
            return None
        return opened.decode("utf-8")
