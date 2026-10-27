<!-- Retired 2026-10-23: superseded by the #10519 PR stack (#10837, #10840, #10856, #10857). Kept for reference; do not file. -->

# [Feature] Run agent-suggested shell commands from chat as `!` shell inputs
<!-- dropdowns: Harness = Claude, Codex | Platform or device = Not platform-specific | Harness mode = Native | Expected reach = A substantial user segment | Authentication type = Not authentication-related -->

### Problem or use case

Agents regularly stop and ask the user to run something themselves: a login flow (`gh auth login`, `gcloud auth login`), a command their sandbox or permission mode won't let them run, or "run these three and paste me the output". In a native Claude or Codex session the user already has a way to do that from the chat: type `!command` in the composer and it runs on the session's host as a shell input, with the output mirrored into the transcript.

The gap is getting from the agent's message to that input. Today the user copies each code block, pastes it into the composer, prepends `!`, sends, waits for it to settle, and repeats for the next one. If the agent lists several commands in one block they have to be split up by hand, because one `!` input is one command. On a phone this is the worst part of a native session: select-copy inside a code block, switch to the composer, paste, fix the prefix, send, and again for the next line.

### Proposed solution

A **Run** control on shell commands in agent messages, on the web app and therefore also on desktop and the iOS/Android apps, which share the bundle. Confirming it queues each command as its own `!command` input through the existing shell-input path, so nothing new runs anything: it is the same as typing the inputs by hand, just without the copying.

**Where Run appears** (agent text only, never on the user's own messages, and not while the text is still streaming):

- On a fenced code block whose lines are written as `!command`. Each `!` line is one command; other lines in the block are treated as commentary. This is the shape agents already use when they know the harness has a `!` mode.
- On a fenced block tagged `bash`, `sh`, `shell`, `zsh`, `console` or `shell-session` with no `!` lines: one command per line, backslash continuations joined, comment lines skipped. If the block is a transcript with `$ ` prompts, only the prompted lines count and the output lines are dropped.
- On an inline code span written as `` `! cmd` ``, as a small play button next to the span.

**What it deliberately skips:** blocks containing a heredoc (`<<`), and blocks with more than 10 commands. Both read as a script to study rather than steps to run, and splitting them line by line would change what runs. `!!` lines are not commands.

**Confirmation:** tapping Run opens a dialog titled "Run this command?" or "Run N commands?" that lists the exact `!command` inputs that will be sent, in order, with Cancel and Run. Agent-written text is untrusted, so the user always sees the precise list before anything is queued; there is no one-tap-and-it-runs path.

**Execution:** on confirm, each command is enqueued as a separate message through the chat store's queue, even when the session is idle, so the queue sends the first now and each later one on its own idle edge. The commands never merge into one turn and run in the order shown. If the session is unreachable the button reconnects instead of sending.

**Per harness:** the control is only offered when the session's harness treats a `!command` message as a shell input. Today that is:

- **Claude native:** uses the composer's existing `!` path unchanged. Claude Code runs the command, mirrors it as a terminal command card, and (as it does for a typed `!cmd`) starts a model turn on the output, so the agent sees the result.
- **Codex native:** a `!command` sent from the web currently reaches Codex as an ordinary prompt, so the model gets asked to run it rather than the shell running it. The change routes a lone `!command` input to the app-server's `thread/shellCommand` RPC instead, and mirrors Codex's `userShell` items back as `terminal_command` input/output items, so the pending web bubble settles the same way it does for Claude native. Live output deltas are not streamed for these items; the full output lands when the command completes.

Every other harness (SDK harnesses, other native harnesses) shows no Run buttons, because there is no shell-input mode to hand the command to.

**Things to be upfront about:**

- Detection is heuristic. A plain `bash` block is split per line, so a multi-line `if`/`for` construct would become several inputs. The confirmation dialog shows the split, so the user can cancel, but it would be better to detect and skip those too.
- The commands go through exactly the same path as a typed `!cmd`, with the same permissions and the same lack of policy gating. This does not add an approval or audit layer; it also does not bypass one that exists today.
- Claude native starts a model turn after each command, so running N commands costs N short turns. That is existing `!` behaviour, not something the button introduces, but it is more visible when three commands go out in a row.
- Codex runs a `thread/shellCommand` alongside a turn that is already in progress and runs it outside the agent sandbox, which is how Codex's own shell mode behaves.
- Interactive commands (password prompts, y/n confirmations) fail in both harnesses because no terminal is attached. Login flows that print a URL work.
- The Claude-native chat timeline for `!` inputs is tracked in #7838 (fix in #7840, still open). Run inherits whatever state that path is in; it does not fix or worsen it.

### Alternatives considered

- **Copy and paste (today):** works, but is several steps per command and multiplied by the number of commands. The motivation above.
- **#10519, Run code blocks with notebook-style inline output.** Closely related and the larger version of this: a play button on shell blocks that executes through a new streaming run endpoint with output rendered under the block. This proposal is the small end of that spectrum: no new endpoint, no new execution path, output goes into the transcript as the existing terminal command cards, and only harnesses that already have a shell-input mode get the button. It could be read as a first increment of #10519 that works today, or as a separate feature if that proposal lands on paste-into-shell semantics instead. Happy to align the detection rules (which fence languages, `$ ` prompt stripping) with whatever #10519 settles on; they are already close.
- **Paste into the composer without sending.** Safer-looking, but the confirmation dialog gives the same review step, and pasting does not solve the multi-command case: the user would still have to send one, wait, paste the next.
- **A framework-injected instruction asking agents to tag runnable fences** (so plain code blocks without a leading `!` also get the button reliably, instead of relying on the fence language). This was considered and deliberately left out. Adding instructions on the framework's behalf is a broader question about framework-owned prompt text that deserves its own discussion, so this issue is scoped to client-side detection of what agents already write.
- **Detecting "please run" prose rather than code blocks.** Too fuzzy; the code block or `!` span is the unambiguous unit.

I have an implementation and can open a PR: a detection helper with unit tests, the Run control and confirmation dialog with component tests, the Codex-native `thread/shellCommand` routing with unit tests, and an e2e test per harness (real `claude` and `codex` CLIs with the mock model) checking that two suggested commands run as separate shell inputs, in order, with no pending input left behind.

### Harness

Claude, Codex

### Platform or device

Not platform-specific

### Harness mode

Native

### Expected reach

A substantial user segment

### Authentication type

Not authentication-related
