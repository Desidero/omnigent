# Chat link rules

Link rules turn short references in chat messages, such as `BST-2135` or
`#123`, into links. Each user has one list of rules, saved as a shared
preference, so every session and device shows the same links.

## Setting them up

Settings → General → **Chat links** lists the rules. Each one can be turned on
or off, renamed, edited (pattern and URL for a `url` rule) or deleted; **Add
rule** adds a `url` rule, and a removed GitHub or Sessions rule can be added
back. A rule that fails a check shows why under it, and **Save** stays off
until every rule passes. **Reset to defaults** removes the saved list. The
**Preview** box renders its text with the rules being edited, before they are
saved. GitHub references don't link in the preview, which has no session.

A saved rule applies to messages as soon as the transcript refetches the
rules, in every open session.

## In the chat

Rules apply to agent and user messages alike, after item labels (`[Q2]`) and
file links have been found, and never inside links, inline code, code blocks
or raw HTML. Where two rules match overlapping text, the match that starts
first wins, then the rule listed first. A link's tooltip names its rule.

- `url` and `github` links open in a new tab like any other web link.
- A `github` reference links to the session's repository on its provider's own
  host (GitHub Enterprise included), taken from the session's git info: the
  repository URL, or the host of a known pull request. `#123` goes to
  `/pull/123` when the session knows that pull request and to `/issues/123`
  otherwise, which GitHub redirects for pull requests. `owner/repo#123` links
  on the same host. A session with no GitHub repository leaves them as text.
- A `session` reference opens the session in the app, scrolled to the message
  when one is named (`/c/<session id>?message=<message id>`, the same link
  as an item's **Show in conversation**).

## Rules

A rule has a `name` (unique, up to 64 characters), a `kind`, a `pattern`, a
`url` and `enabled`. There are three kinds:

| Kind | Matches | Links to |
| --- | --- | --- |
| `url` | The rule's `pattern` | The rule's `url` template, filled from the match |
| `github` | `#123` and `owner/repo#123` | The issue or pull request on the session's own repository host |
| `session` | `session:<session id>` and `session:<session id>/<message id>` | That Omnigent session, scrolled to the message |

The `github` and `session` kinds are built in: they take no `pattern` or `url`,
and a list can hold at most one of each. A list holds up to 32 rules.

With nothing saved, these defaults apply: GitHub and Sessions on, and two
example `url` rules off, a Jira-style short form (`ABC-{num}`) and a raw
regex (`/(ENG-\d+)/`). Edit an example's pattern and URL before turning it on.

### Patterns

A `url` rule's pattern is either a short form or a raw regex.

A **short form** is literal text with placeholders:

| Placeholder | Matches |
| --- | --- |
| `{num}` | 1 to 10 digits |
| `{key}` | An uppercase letter, then 1 to 9 uppercase letters or digits |
| `{id}` | 1 to 64 letters, digits, `_` or `-` |

For example `BST-{num}` matches `BST-2135`, and `{key}-{num}` matches any
Jira-style key. A short form has no spaces and at most four placeholders.

A **raw regex** is written between slashes, such as `/(ENG-\d+)/`. It may use
only a subset that Python and every supported browser read the same way:

- Groups are `( )` or `(?: )`, at most nine capturing. No lookahead,
  lookbehind, named groups, inline flags or backreferences; older Safari
  can't parse named groups or lookbehind.
- Escapes are `\d \w \s \b` and their capitals, plus escaped punctuation. A
  literal `{`, `}` or `[` inside a class is escaped.
- A repeated group can't contain another repeat or `|` (no `(a+)+`), there are
  at most three repeats, and every repeat stops at 64 characters (`+` reads as
  `{1,64}`).
- The pattern can't match empty text, and is at most 200 characters.

Every pattern matches whole words only: the match must start at the beginning
of the text or after a character other than a letter, digit or `_`, and must
not be followed by one. Matching is case-sensitive.

### URL templates

A `url` template is an `https:` or `http:` link of up to 500 characters with
placeholders for the match: a short form's placeholder names (`{num}`,
`{key}`, `{id}`; a repeated name means its first use), or `{1}` to `{9}` for a
regex's groups, and `{0}` for the whole match. Each value is percent-encoded
before it goes in. Everything before the first placeholder must be a complete
scheme and host followed by `/`, `?` or `#`, so a match can never choose where
the link goes:

```json
{"name": "Jira", "kind": "url", "pattern": "BST-{num}",
 "url": "https://jira.example.com/browse/BST-{num}", "enabled": true}
```

## Where rules are checked

Rules run in every viewer's browser on every message, and agents can write
them, so the server checks a rule when it is saved (the shared-preference
operation and `PUT /v1/link-rules` both run the same validator,
`omnigent/link_rules.py`) and the web client checks it again when it compiles
the rule.

## Saving rules

Rules are the `{"kind": "link_rules", "name": "default"}` shared preference:
a JSON array in a string, stored compactly. `null` removes the saved list so
the defaults apply, and `"[]"` turns every rule off. Saving needs shared
preferences on the server (`shared_preferences_authority_id` in the server
config); without them the defaults apply and can't be changed.

- [`GET` and `PUT /v1/link-rules`](../omnigent/server/API.md#chat-link-rules-v1link-rules)
  read the rules in effect (saved or default) and replace the whole list with
  a version check.
- The [shared preferences API](shared-preferences-api.md) reads and writes the
  same value, with its conflict handling.

## Agents

### The `sys_link_rules` tool

Agents can read and change the rules with `sys_link_rules`:

| `action` | Arguments | Effect |
| --- | --- | --- |
| `list` | none | Returns the rules in effect and whether they are saved |
| `add` | `name`, then `kind` (default `url`), `pattern`, `url`, `enabled` (default true) | Appends a rule |
| `update` | `name`, then any of `new_name`, `kind`, `pattern`, `url`, `enabled` | Changes one rule |
| `remove` | `name` | Deletes one rule |

Names match case-insensitively. The tool checks the changed list with the
server's validator before saving it, and saves it with the version it read, so
a change made meanwhile from Settings is refused rather than overwritten.

Every `add`, `update` and `remove` parks on an approval prompt in the session,
showing the rule's name, pattern and URL, even when no other policy applies
(the built-in `__ask_on_link_rule_change` policy, like the one for scheduled
tasks). `list` is not gated. Agents get the tool unless their spec sets
`tool_groups.link_rules: false` ([agent YAML](AGENT_YAML_SPEC.md#tool-groups)),
and native Claude and Codex sessions get it through the tool relay.

### What agents are told

Agents are told which references the chat links, so they write them as plain
text instead of code: one short framework instruction listing each enabled
rule's syntax, such as `` `#123` or `owner/repo#123` `` and `` `ABC-123`
(Jira) ``. With every rule off there is no instruction.

A rule saved mid-session renders in the chat right away. SDK harnesses read
the rules again for a later turn (the runner keeps them for up to a minute).
Native Claude and Codex sessions get their instructions once, at launch, so
they see a changed rule in their prompt only after their next launch.
