# Codex review: telemetry-attribution (`feat/span-attribution`, PR omnigent-ai/omnigent#11380)

Command: `codex exec --sandbox read-only -` with the prompt, CLAUDE.md and `git diff upstream/main...HEAD` pasted on stdin
(`codex review --base` rejects a custom prompt, and the bubblewrap sandbox cannot run shell commands in this
environment, so the diff was supplied inline). Model: gpt-6.1-sol (codex-cli 0.159.2). Reviewed 96d379b5d on upstream/main 3f2ccf56e.

## Disposition

1. Root HTTP span lacks `omnigent.runner.id` — **not a bug, by design**. The runner is bound deep in the route
   (`routes/hosts.py`, `creation_logging.py`) once it is resolved, not in the middleware, so the root span's
   `on_start` has passed; spans started after the binding carry it. OBSERVABILITY.md says host and server frames
   name a runner "only when one is bound". The PR's Demo section states this explicitly.
2. Unauthenticated server request stamped with `OMNIGENT_USER_ID` — **dismissed**: `current_user_id` is the
   debug-log sink's policy and the server process never has `OMNIGENT_USER_ID` set (the host sets it only on the
   runners it spawns); the PR body now says so. Changing the fallback would change debug-log attribution too.
3. Host startup wiring (`_serve_host_until_exit`) untested — **acknowledged, not fixed**: every host test
   monkeypatches `_serve_host_until_exit` away; the wiring is three lines over the tested
   `set_resource_attribute` + `init` path and the PR's Test Plan says it is not unit-tested and how to check by hand.

No code change from this review.

## Raw output

codex
I would request changes for the attribution gap below. This review uses only the pasted diff; I could not run tests or inspect unchanged code.

1. **[P2] The root HTTP span misses its runner attribution.**  
   **`omnigent/runtime/telemetry.py:1153` — registration of `_make_runner_id_processor()`**  
   The processor reads the runner binding only when a span starts. The server’s root HTTP span starts before request middleware resolves attribution—the reason this patch adds `set_request_user()` and already has direct session stamping. When middleware later calls `set_current_runner_id()`, this patch provides no equivalent update to the active span. Child spans can therefore carry `omnigent.runner.id` while the HTTP span remains unattributed, contrary to the documented “every span” behavior.

   Stamp the current server span when the request’s runner resolves. Add a middleware test that starts the HTTP span before binding the runner and checks both the SERVER span and a handler child. **Unverified detail:** the unchanged runner-binding call sites were not provided; an existing direct span update elsewhere could address this.

2. **[P2, unverified] Server user attribution may fall back to the process owner after authentication fails.**  
   **`omnigent/server/app.py:2348` — `telemetry.set_request_user(current_user_id())`**, and **`omnigent/runtime/telemetry.py:412` — `current_user_id()` in the user processor**  
   The supplied documentation says `current_user_id()` can return `OMNIGENT_USER_ID`. The middleware clears the binding on authentication failure and then reads this fallback-capable accessor. If a server inherits that environment variable, an unauthenticated request may be stamped with the process owner’s email. The processor can also stamp that owner on the root span before authentication, and `set_request_user(None)` explicitly leaves an existing attribute intact.

   Verify the accessor’s behavior and keep server request attribution tied to the resolved authenticated principal. Add a case with `OMNIGENT_USER_ID` set and an unauthenticated or failed-auth request; assert that neither the root nor its children identify the process owner.

There is also a concrete coverage gap: **`omnigent/host/connect.py:5465`** introduces host startup wiring and promises inheritance into runners and harnesses, but the added test only calls `set_resource_attribute()` and `telemetry.init()` directly. It would still pass if the host startup call were removed or the launch environment dropped the attribute. Extend the nearest host-launch scenario to check the actual environment passed to a runner and, where separately constructed, a harness. Whether existing unchanged tests already cover this is **unverified**.

To verify the behavior manually, enable telemetry and `OMNIGENT_OTEL_CAPTURE_USER`, launch a host and runner, and make an authenticated runner-backed request. Inspect the exported HTTP SERVER span and its children for the same user and runner, and inspect host/runner/harness resources for the same host ID. Repeat an unauthenticated request with `OMNIGENT_USER_ID` set on the server and confirm it does not identify that owner.
