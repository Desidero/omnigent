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
