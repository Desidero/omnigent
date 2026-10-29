# Chat link rules

Link rules turn short references in chat messages, such as `BST-2135` or
`PR #123`, into links. Each user has one list of rules, saved as a shared
preference, so every session and device shows the same links.

## Rules

A rule has a `name` (unique, up to 64 characters), a `kind`, a `pattern`, a
`url` and `enabled`; a `git` rule also has a `provider` and a `host`. There
are three kinds:

| Kind | Matches | Links to |
| --- | --- | --- |
| `url` | The rule's `pattern` | The rule's `url` template, filled from the match |
| `git` | `#123`, `issue #123`, `PR #123`, the provider's `!123` and `owner/repo#123` | The issue or pull request on the host, in sessions whose repository is there (see [Git references](#git-references)) |
| `session` | `session:<session id>` and `session:<session id>/<message id>` | That Omnigent session, scrolled to the message |

The `git` and `session` kinds take no `pattern` or `url`. A `git` rule's
`provider` is `github`, `gitlab` or `azure_devops`, and its `host` is a bare
host name with an optional port (`gitlab.example.com`,
`git.example.com:8443`): no scheme, path or credentials. Hosts are stored
lower-cased, and a list holds one `git` rule per host and at most one `session`
rule. A list holds up to 32 rules.

```json
{"name": "Our GitLab", "kind": "git", "provider": "gitlab",
 "host": "gitlab.example.com", "enabled": true}
```

With nothing saved, these defaults apply: GitHub (`github.com`), GitLab
(`gitlab.com`), Azure DevOps (`dev.azure.com`) and Sessions on, and two
example `url` rules off, a Jira-style short form (`ABC-{num}`) and a raw
regex (`/(ENG-\d+)/`). Edit an example's pattern and URL before turning it on.

A rule saved with the old `github` kind (before `git` rules) is read as the
GitHub `git` rule for `github.com`, and stored in the new form the next time
the list is saved. The validator still accepts `{"kind": "github"}` on input,
with no `provider` or `host`; that is deprecated and goes in 0.22.0.

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
