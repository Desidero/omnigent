# sandbox-connection-gate

Needs: none
Covers: af0d3c890d05bb32

On a server whose sandbox provider launches each sandbox as the signed-in user
(the Databricks provider), the New session host menu shows that provider
disabled until the user has connected the account, with a row under it that
opens Settings → Sandbox Integrations, and Start is blocked with the same
reason while that sandbox is the pick. Before, the option was offered to
everyone and the refusal arrived only after Start. The server's refusal is
unchanged; the gate is a hint in one picker.

- **Turn on:** on by default wherever a launchable provider declares an owner
  connection; nothing to configure.
- **Docs:** `sandbox-connection-gate` in the
  [composer feature map](../../feature-map/composer.md); "Sandbox" in the
  [Databricks Apps deploy guide](../../deploy/databricks/README.md).
- **Upstream:** not proposed, no contribution branch. No open upstream issue or
  pull request covers it (searched 2026-11-26); the nearest,
  [#11160](https://github.com/omnigent-ai/omnigent/issues/11160) (drop the
  Sandbox proxy bearer), is about something else.

## Must hold

- Creating a session still fails closed: a launch for a user without the connection is refused by the server with the 409 that says to connect, whatever the web showed, and no sandbox is created. The series changes no launch code.
- `GET /v1/info` reports only which connection a provider launches as (`sandbox_provider_owner_connections`); nothing about the caller, since the route is unauthenticated.
- The row is disabled only on a definite answer: the caller's status says not connected, or the server has no such connection set up. A loading, failed or malformed status leaves the row enabled.
- A provider that needs no owner connection, and a server without one, look and behave as before; no status request is made.
- While a blocked sandbox is the pick, Start is disabled and its tooltip gives the reason.
- TODO(owner): on a real workspace, the row re-enables after connecting and returning to New session, and a connection to another workspace than the server's is still refused at launch with the server's message (not checked: no workspace here).

## Key code

- `omnigent/server/managed_hosts.py`: `provider_owner_connections`
- `omnigent/server/app.py`: `sandbox_provider_owner_connections`
- `web/src/hooks/useSandboxConnectionBlocks.ts`: `useSandboxConnectionBlocks`, `sandboxConnectionBlockMessage`
- `web/src/shell/SandboxConnectionMenuNotices.tsx`: `SandboxConnectionMenuNotices`
- `web/src/shell/NewChatDialog.tsx`: `sandboxConnectionBlocks`, `sandboxConnectionBlock`
- `web/src/lib/capabilities.ts`: `sandbox_provider_owner_connections`, `parseProviderTextMap`

## Tests

- `tests/server/test_managed_hosts.py::test_provider_owner_connections_name_the_connection_a_provider_launches_as`
- `tests/server/test_managed_hosts.py::test_info_reports_the_connection_a_provider_launches_as`
- `tests/server/test_managed_hosts_databricks.py::test_the_databricks_provider_reports_the_connection_it_launches_as`
- `tests/server/test_managed_hosts_databricks.py::test_launch_for_an_unconnected_owner_is_a_409_connect_prompt`
- `tests/server/test_managed_hosts_databricks.py::test_build_owner_launcher_without_a_resolver_refuses_not_falls_back`
- `web/src/hooks/useSandboxConnectionBlocks.test.tsx`
- `web/src/shell/NewChatDialog.test.tsx`
- `web/src/lib/capabilities.test.ts`
