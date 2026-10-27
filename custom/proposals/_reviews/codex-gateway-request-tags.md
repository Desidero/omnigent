# Codex review: gateway-request-tags (feat/gateway-request-tags)

Command: `codex exec -C <worktree> --sandbox danger-full-access "<review prompt>, reviewing the diff of \`git diff <base>...HEAD\`"` (codex-cli 0.159.2, model gpt-6.1-sol).
`codex review --base upstream/main` and `codex exec --sandbox read-only` both failed in this environment: the bundled bubblewrap sandbox cannot set up loopback (`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`), so the review ran unsandboxed with a "do not modify any file" instruction; `git status` was clean afterwards.

## Raw findings (`git diff upstream/main...HEAD`)

74,906
I would request changes for one issue:

- **[P1] Escape labels before embedding them in OpenCode config** — [provider.py:208](omnigent/harnesses/opencode_native/provider.py:208). User-controlled labels are inserted verbatim into the request-tags header and serialized into `opencode.json`. OpenCode substitutes `{env:NAME}` and `{file:path}` throughout config text before parsing it; I confirmed this in the installed binary and its [configuration documentation](https://opencode.ai/docs/config/#variables). A label such as `{"team":"{env:DATABRICKS_TOKEN}"}` can therefore send a host credential into gateway logs. A `{file:/nonexistent}` label can prevent startup. Preserve labels as literal data through OpenCode’s substitution layer, and add regression coverage through that reader—the current `json.loads` assertions miss this behavior.

To verify the fix, use a harmless environment variable containing a sentinel and a label referencing it. Launch an OpenCode gateway session and confirm the outgoing header retains the literal `{env:...}` text. Also confirm a `{file:/nonexistent}` label does not break startup.

No files were changed. I did not run tests because they can write files; `git diff --check upstream/main...HEAD` passed.

## Disposition

- P1 labels reach OpenCode's config variable substitution: **fixed**. Confirmed in the installed `opencode` bundle: the config loader runs `text.replace(/\{env:([^}]+)\}/g, ...)` and `/\{file:[^}]+\}/g` on the raw `opencode.json` text before parsing it, and offers no escape. `omnigent/harnesses/opencode_native/provider.py` now writes the request-tags header through `_literal_request_tags`, which escapes every `{` inside the JSON strings as `\u007b` (the object's own opening brace is the only structural one). The file no longer contains `{env:` or `{file:`, and the header still decodes to the same tags. Test `test_write_provider_config_keeps_request_tags_literal` applies OpenCode's two substitutions to the written text and checks the decoded header. The other harnesses are unaffected: Claude and Codex read the value from an environment variable, and Pi's `$NAME` expansion was already escaped as `$$`.
