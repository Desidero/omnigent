# Per-user integration credential store

## Motivation

The GitHub App integration needs to persist a per-user OAuth token set and vend
it to managed sandboxes on demand (see the credential broker below). That secret
material must be encrypted at rest, per user, with the key never sitting in the
app process.

Two forces shape the design:

1. **More providers.** Connecting MCP integrations (Datadog, Slack, a hosted
   GitHub MCP, …) needs the same shape: a per-user secret + some non-secret
   metadata, connected once and re-vended to sandboxes. We do not want one
   bespoke table per provider.
2. **Managed key material.** The secret material is encrypted with **AWS KMS** —
   the key lives in KMS, the server only holds an IAM permission to call
   `Encrypt`/`Decrypt`, and each ciphertext is bound to its row's identity as the
   KMS *encryption context*. This gives per-user encryption, rotation, audit, and
   "the app process never holds the raw key" without us managing key material.

Getting the schema generic now is cheap; reshaping a provider-specific table
after users have connected means migrating encrypted rows. Hence this store
lands at the base of the integration stack, with GitHub as its first (and,
today, only) provider.

## Two independent axes

The design deliberately separates two concerns that are easy to conflate:

| Axis | What varies | This design |
| --- | --- | --- |
| **Data model** | "a credential for *any* provider, per user" | one generic table + typed façades per provider |
| **Secret backend** | *where* the key lives and *who* encrypts | a `SecretCipher` port; AWS KMS is the implementation |

Keeping them orthogonal means a new provider is a façade (no schema change) and
a different key backend (GCP/Azure KMS, Vault Transit) is a cipher adapter (no
schema change).

## Data model

One table, `connections`:

| column | type | notes |
| --- | --- | --- |
| `workspace_id` | bigint | tenant partition, part of PK (`0` = default) |
| `user_id` | str(128) | omnigent user, part of PK |
| `provider` | str(64) | e.g. `"github"`, part of PK |
| `account_id` | str(128) | provider account discriminator, part of PK; `""` = the user's single account for that provider |
| `secret_enc` | text | KMS ciphertext (base64) of a JSON blob holding *all* secret material (access token, refresh token, …) |
| `metadata_json` | text | non-secret provider metadata (login, ids, scopes, expiries, …) as JSON |
| `created_at` / `updated_at` | integer | unix epoch seconds (repo convention; `workspace_id` is the lone `bigint`) |

Primary key: `(workspace_id, user_id, provider, account_id)`.

Why a JSON secret blob rather than typed token columns: any provider's secret
shape (single API key, OAuth access+refresh, client-cert, …) fits one encrypted
column, and the ciphertext is opaque to SQL. Non-secret fields that a provider
needs at refresh time (token expiries, granted scopes, the connected login/id)
live in `metadata_json` — queryable enough for our access patterns (we always
load the whole connection) without widening the schema per provider.

The `account_id` column is `""` today (one account per provider per user) but is
in the PK so a future "connect two GitHub orgs" needs no migration.

## `SecretCipher` port

```python
class SecretCipher(Protocol):
    def encrypt(self, plaintext: str, *, context: Mapping[str, str]) -> str: ...
    def decrypt(self, ciphertext: str, *, context: Mapping[str, str]) -> str | None: ...  # None on mismatch
```

`context` is the row's identity (`workspace`/`user`/`provider`/`account`) and is
**required** — every secret is bound to a user; there is no unbound/global-key
path. The store depends on this port, not on a concrete backend, so the KMS
implementation can be swapped for GCP/Azure KMS or Vault Transit without a
schema change.

`KmsSecretCipher` is the implementation: `encrypt` is one `kms:Encrypt` call
under the configured key with `context` as the KMS encryption context; the
returned ciphertext blob is stored base64. Blobs are small (a token JSON
object), well under the 4 KB `Encrypt` limit, so no envelope/data-key layer is
needed. `decrypt` is `kms:Decrypt` with the same context.

`build_secret_cipher()` is the single seam where a deployment selects the
backend; it reads the **store-level** key `OMNIGENT_CREDENTIAL_KMS_KEY_ID` (id,
ARN, or `alias/…`) and returns the cipher, or `None` when unset — the store, and
every integration on it, is then disabled. **There is no non-KMS fallback:** no
key configured means the feature is off, not that it silently encrypts with a
local key. The [local key file](#local-key-file-explicit-opt-in) backend below
keeps that rule: it is used only when the operator selects it by name, never
because nothing else is configured or something else failed.

The key belongs to the **credential store**, not to any one provider: every
provider façade shares the one cipher, so connecting an MCP server or Datadog
account needs no provider-specific key and does not depend on GitHub being
configured. Provider config gates that provider's routes, not the store's
ability to encrypt.

### What the encryption context buys (and what it doesn't)

The *tenancy boundary* is the primary key and the `workspace_id`-scoped queries
— that is what stops user A reading user B's row, and it holds regardless of the
cipher. The KMS encryption context is not an access-control boundary; it is
cryptographic binding. What it buys:

- **The master key never enters the process.** KMS does the crypto inside its
  HSM; the server holds only an IAM permission (via IRSA). A stolen DB dump *and*
  a compromised server yield no exportable key — an attacker can only call
  `Decrypt` while the pod's credentials are valid, which is logged in CloudTrail
  and revocable.
- **Per-row binding.** A ciphertext can only be decrypted by presenting the same
  `{workspace, user, provider, account}` context, so a blob can't be replayed
  under a different identity, and a leak is scoped to one row.
- **Rotation / revocation / audit** are KMS key-policy operations, not app
  changes: rotate the key (versions, no re-encrypt), disable it to stop all
  decrypts, read every call in CloudTrail. An encryption-context *condition* in
  the key policy can further constrain what the server may decrypt.

Empty-valued context fields (`account_id=""`, the default single account) are
dropped before the KMS call — KMS rejects empty encryption-context values — done
consistently on encrypt and decrypt, so the binding is unchanged and a named
account still yields a distinct context.

`decrypt` returning `None` (not raising) on a ciphertext/context mismatch
(`InvalidCiphertextException` / `IncorrectKeyException`) is load-bearing: a
rotated-away key degrades to "reconnect this integration," never a 500 on the
vend path. Operational failures — access denied, disabled key, throttling —
propagate instead, since telling the user to reconnect wouldn't help and would
hide a misconfiguration.

### Pod → KMS auth (IRSA)

On the demo/prod EKS cluster the server runs as the `omnigent-server`
ServiceAccount, annotated with an IAM role (`eks.amazonaws.com/role-arn`) whose
policy allows `kms:Encrypt`/`kms:Decrypt`/`kms:DescribeKey` on the one
credential key. No AWS credentials sit in the pod; the KMS key ARN is passed as
plain config (`OMNIGENT_CREDENTIAL_KMS_KEY_ID`), not a secret. The key + role +
policy are provisioned in the infra repo (Pulumi, `cloud-infra/core`).

## Layers

The stack has four layers, each with one job:

```
route layer            provider-specific writes, uniform credential reads
   │
   ▼
ConnectionStore(ABC)   per-provider façade: maps the provider surface ⇄ a row
   │                   (GithubConnectionStore, DatabricksConnectionStore, …)
   ▼
CredentialStore        the one concrete DB backend (SQLAlchemy) — uniform writes
   │
   ▼
SecretCipher(Protocol) encrypt/decrypt the secret blob (KmsSecretCipher impl)
```

- **`CredentialStore`** is the generic, provider-agnostic persistence: rows keyed
  by `(workspace_id, user_id, provider, account_id)`, secret blob + metadata,
  returning plain `ProviderConnection` entities.
- **`ConnectionStore(ABC)`** is the per-provider façade base. It owns a
  `CredentialStore`, carries the provider key (`_PROVIDER`), and factors the
  uniform reads (`get`, `delete`, `list_all`) so a concrete façade only sets
  `_PROVIDER`, implements `_to_entity`, and adds its provider-specific writes.
  Callers (routes, broker, launch path) talk to the façade, never the generic
  store, so nothing changes when a second provider is added.

**This base PR ships `CredentialStore` + `ConnectionStore` + `SecretCipher`; the
first concrete façade lands in the connect PR (#4235):**

- `GithubConnectionStore(ConnectionStore[GithubConnection])` — `provider="github"`;
  secret = `{access_token, refresh_token}`; metadata = `{github_login,
  github_user_id, token_expires_at, refresh_token_expires_at, scopes}`; adds
  `upsert` / `update_tokens` and implements `_to_entity`.

A future MCP-credential façade is the same pattern with `provider="mcp:<name>"`.

## Migration

This PR adds a single new migration (`add_connections`) that
`CREATE`s `connections` with the generic schema. There is no
provider-specific table in the tree to reshape — the generic store lands at the
base of the stack, before any such table existed, which is the whole point of
sequencing it first. The migration chains off the current `upstream/main` head
(the branch is kept rebased on main) so the branch and the PR merge both resolve
to a single Alembic head; a test guards that
(`tests/db/test_migration_connections.py`).

## Broker endpoint (provider-generic)

The credential broker is generic over providers:
`GET /v1/hosts/{host_id}/credentials/{provider}` resolves the launch token to
the session owner and returns that provider's secret + attribution metadata
(the git credential helper and the GitHub MCP proxy pass `provider=github`).
One route (`routes/host_credentials.py`) serves every provider that registers a
`credential_resolver` on the `ConnectionProvider` registry; a provider with no
resolver — connect-only, or on-demand delivery not built yet — returns `404`. A
new provider is one registry entry, not another hand-copied route + client. The
resolver is best-effort: a fault degrades to `{"connected": false}` rather than
a 500, and the token is never persisted in the sandbox.

## Revocation & audit note

A vended GitHub token's blast radius is bounded by the launch token: the broker
resolves `(host_id, launch_token)` server-side and stops vending the moment the
launch token expires or the host row is deleted, and the raw token never touches
sandbox disk. KMS adds its own layer — CloudTrail logs every `Decrypt`, and
disabling the key stops all decrypts globally — but KMS does not know about
launch tokens. So "stops vending when the session ends" must remain a
server-side check on the broker path, independent of KMS; KMS is defence in
depth on the storage, not the session boundary.

## Dependencies

The credential store is backend-agnostic; each `SecretCipher` backend declares its
own extra, both imported lazily:

- **AWS KMS** (`KmsSecretCipher`) needs boto3 — `omnigent[kms]`.
- **HashiCorp Vault** (`VaultSecretCipher`, Transit) needs hvac — `omnigent[vault]`.

boto3 / hvac load only when the matching backend is selected
(`OMNIGENT_CREDENTIAL_KMS_KEY_ID` / `OMNIGENT_CREDENTIAL_VAULT_KEY`), so a deployment
that doesn't enable the credential store — or uses the other backend — needs neither.

`OMNIGENT_CREDENTIAL_CIPHER` (`kms` | `vault`) selects the backend explicitly per
server; the chosen backend's key env var is then required. Leave it unset to
auto-detect the single configured backend — configuring more than one without the
selector is an error (no silent precedence), and configuring none disables the store.

## Local key file (explicit opt-in)

A trial or single-machine server with neither AWS KMS nor Vault can encrypt the
store with a key the operator keeps in a file (`LocalKeySecretCipher`,
AES-256-GCM from `cryptography`, which the base install already has):

```bash
(umask 077 && openssl rand -base64 32 > /etc/omnigent/credential.key)
export OMNIGENT_CREDENTIAL_CIPHER=local
export OMNIGENT_CREDENTIAL_LOCAL_KEY_FILE=/etc/omnigent/credential.key
```

**This gives up what the store's design is for.** With KMS or Vault the key
never enters the server. Here it is in the server process and on its disk:

- Anyone who can read the key file and the database, or a backup of each, can
  read every user's stored tokens, offline.
- Nothing logs a decrypt and a leaked key cannot be disabled. The only response
  is a new key, every user reconnecting, and revoking the old tokens at each
  provider.
- There are no key versions and no re-encryption: **changing the key means every
  user reconnects.**

What still holds: a copy of the database alone yields only ciphertext, and each
ciphertext is bound to its row's `{workspace, user, provider, account}` as the
cipher's associated data, so it cannot be moved to another user's row. Secrets
are not limited to 4096 bytes as they are with KMS.

**It cannot be reached by accident.** `build_secret_cipher()` raises, which
stops a server that has a feature on the store configured, unless all of these
hold:

- `OMNIGENT_CREDENTIAL_CIPHER=local` names it. The key file variable without
  the selector is an error: the backend is never auto-detected.
- No KMS or Vault key is configured beside it (`OMNIGENT_CREDENTIAL_KMS_KEY_ID`,
  `OMNIGENT_CREDENTIAL_VAULT_KEY`). With `kms` or `vault` selected the key file
  is ignored, and a failing KMS or Vault call fails: nothing falls back to the
  local key.
- The key file exists, is a regular file, gives no access to group or others
  (`chmod 600`; a symlink's target is what is checked), and holds exactly one
  32-byte key in base64, at most 128 bytes with surrounding whitespace.
- The server runs on a POSIX system, where those file modes mean something.

The server never creates the file, generates a key or writes one anywhere, and
logs only the file's path (a warning each time the cipher is built). Keep the
file out of the database's backups; in a container, mount it as a secret with
mode `0400`.

**Stored format.** `oslocal:v1:<key id>:<base64(nonce + ciphertext + tag)>`. KMS
rows are bare base64 and Vault rows start with `osvault:`, so the three can be
told apart in the `connections` table. The key id is a truncated SHA-256
fingerprint of the key, not key material. A row from another backend, a row
read under another identity and an altered row read as disconnected
(`decrypt` returns `None`). A row written under a *different local key* raises
instead, as the Vault backend does for a repointed key: a wrong or regenerated
key file is a store-wide mistake, and showing every user as disconnected would
have their reconnects overwrite ciphertext the right key can still open.

**Changing the key.** Replace the file and restart. Each stored connection then
fails with an error naming the key mismatch until its user reconnects in
Settings, which overwrites the row under the new key; deleting the rows first
shows users as disconnected instead. Moving to KMS or Vault later is the same
step: old rows read as disconnected and users reconnect.

## MCP auth & roadmap

The store is the base for two credential needs; the encryption above is shared,
the delivery differs.

**MCP auth → Databricks Unity Gateway (AIGW), primary.** Routing MCP through AIGW
makes per-MCP OAuth *Databricks's* problem, not Omnigent's. The store then holds
only a small `provider="databricks"` exchange grant (per-user, KMS-encrypted);
the server performs the omni→databricks token exchange + refresh, and the
sandbox's MCP proxy fetches a short-lived AIGW token from the broker per
connection, never persisted. Leave an "MCP connection backend" seam (mirroring
the `SecretCipher` port) so a self-hosted OSS layer (e.g. Nango) can slot in
later.

**GitHub clone stays on the broker.** MCP can't `git clone`, so the GitHub App
token remains in the store and the broker vends it into the sandbox for git
(the credential-helper path); a wrapper `gh` CLI can do the Open-in-Omnigent PR
stamp instead of the MCP proxy.

### Phased plan

1. Generic per-user store + KMS cipher behind `SecretCipher`. *(this PR)*
2. KMS key + IRSA role provisioned in infra (Pulumi); wired into the demo
   deployment. *(connect PR / infra)*
3. AIGW MCP track: `provider="databricks"` + omni→databricks exchange/refresh +
   AIGW MCP proxy + the sandbox Databricks plugin behind the connection seam.

### Open questions

- **Envelope vs direct:** direct `Encrypt`/`Decrypt` is fine while blobs stay
  under 4 KB. If a provider's secret grows, switch that cipher to envelope
  (`GenerateDataKey` + local AES, wrapped key stored alongside) behind the same
  port — a per-`(context, process)` KMS call instead of per vend.
- **Encryption-context IAM condition:** whether to constrain the server's key
  policy with a `kms:EncryptionContext:*` condition (tighter, but couples the
  policy to the identity shape) or keep it key-scoped (simpler).
- **Databricks token exchange:** what the server exchanges the omni identity for
  (AIGW OAuth token / RFC 8693 token exchange / Databricks U2M/M2M grant) —
  drives the `provider=databricks` row shape and refresh cadence.
