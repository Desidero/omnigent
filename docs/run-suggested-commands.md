# Run suggested commands

When an agent asks you to run a shell command, the chat shows a Run button on
it (beside Copy on a code block, titled **Run command** or **Run N commands**),
so you don't have to retype it in the composer as a `!command`.

## Where Run appears

Run is offered in claude-native and codex-native sessions, whose web composer
runs a `!command` message as a shell command on the session's host. Other
harnesses show code blocks as before. It appears on the agent's finished
messages, not on your own messages or on a reply that is still streaming:

- A fenced code block whose lines start with `!`: each such line is one
  command and the other lines are treated as commentary.
- A code block tagged `bash`, `sh`, `shell`, `zsh`, `console` or
  `shell-session`: one command per line, joining lines that end in `\`.
  Lines starting with `#` are skipped, and when some lines start with a `$ `
  prompt, only those lines count.
- Inline code written as `` `! cmd` ``.

Blocks with a heredoc (`<<`) or more than 10 commands read as scripts to study
and get no Run.

## What Run does

Run opens a confirmation that lists the exact commands, in order. Confirm, and
each one is queued as its own `!command` shell input, exactly as if you had
typed it: the first goes as soon as the agent is idle and each later one after
the previous finishes, so they never merge into one turn. Claude Code runs
them in its shell mode; Codex runs them as shell commands in the session's
thread and the chat shows each one as a terminal command.

A `!command` you type yourself in a codex-native session's web composer now
runs the same way, as a shell command rather than a prompt.

## Turn it on or off

Run suggested commands is a per-session chat feature (key `run_commands`). It
pairs the Run button with an instruction asking the agent to tag shell
commands as `bash`, one per line, so Run can find them; turning it off drops
both. New sessions start with every chat feature on unless you save another
default.

- **One session:** the **Chat features** section of the new-session
  composer's agent menu, or of a running session's configure menu. SDK
  harnesses pick up a change on the next turn. claude-native and codex-native
  read their instructions at launch, so the instruction changes after the
  session restarts (the menu says so); the Run button follows the setting at
  once.
- **Your default for new sessions:** Settings → General → **Chat features**.
  It is stored as the `chat_features` [shared preference](shared-preferences-api.md),
  so the server needs `shared_preferences_authority_id` in its config. Without
  it the switches are disabled with a note and new sessions get every feature.
  Forks keep their parent's set and sub-agents inherit it.
- **API:** `POST /v1/sessions` and `PATCH /v1/sessions/{id}` accept
  `chat_features`, a list of keys such as `["run_commands"]` (`[]` turns every
  feature off); `null` in a `PATCH` resets the session to your default.
  `GET /v1/chat-features` lists the features with their titles.
