# [Feature] Stamp session metadata, model and effort on exported spans

Labels: Feature, needs-triage

## Problem or use case

With `OMNIGENT_TELEMETRY_ENABLED=true` and an OTLP endpoint, every span carries `session.id`, but nothing about the session itself. A downstream job that wants to classify conversations ("how much of this week's traffic was the `web` team's?", "which project burns the most tokens?", "which model actually served turns left on the default?") has to join `session.id` against the Omnigent database for every span. That is a second system to keep reachable and in sync from the trace pipeline, and it is impossible when the trace backend is the only thing the analytics job can see.

The data already exists on the server: the session's title, labels, project, agent, git branch, model override, reported model and reasoning effort are all on `GET /v1/sessions/{id}`, which the runner already reads. The agent span also records only what a turn *asked for*: with no model pinned, `gen_ai.request.model` (and `llm.model_name`) fall back to the agent name, and no effort is recorded at all, so a session on the defaults never says which model or effort ran.

## Proposed solution

Standalone; related to #10794, which stamps the acting user and runner through the same span-processor mechanism but is independent of this.

1. **Session metadata on every span of a turn.** When telemetry is on, the runner resolves session-level attributes per turn and forwards them on the turn body (`telemetry_attributes` on `CreateResponseRequest`). The executor adapter binds them for the turn and a span processor (the same mechanism as `session.id` / `omnigent.skill.active`) stamps them on every span the harness emits.
2. **What the turn ran with, on the agent span.** `gen_ai.request.model` is set only when a model was requested (the turn's override, else the agent's configured model). The agent span also records the model and effort that applied, each with a `*.source` saying where the value came from (`observed`, `resolved_default`, `requested`). Harnesses that know the effort they applied report it on `TurnComplete` (Codex reports its thread default).
3. **Never at the turn's expense.** Every lookup is best-effort and bounded (a few seconds in total); a failure or timeout leaves the turn with the machine-local attributes only.

Attributes and their gates (all require `OMNIGENT_TELEMETRY_ENABLED`; a value that is unknown is omitted, never guessed):

| Attribute | Where | Source | Gate |
|---|---|---|---|
| `omnigent.session.title` | every span of the turn | session title | `OMNIGENT_OTEL_CAPTURE_CONTENT` (titles are often generated from the first message) |
| `omnigent.session.labels.<key>` | every span | session labels; internal `omnigent.*` keys skipped | none (labels are the classification keys; keys become attribute names, values are exported as-is) |
| `omnigent.project.id`, `omnigent.project.name` | every span | session's project (name looked up once per project id) | none |
| `omnigent.agent.name` | every span | bound agent | none |
| `omnigent.agent.model` | every span | the agent's configured model | none |
| `omnigent.session.model`, `omnigent.session.model.source` | every span | harness's last reported model (`observed`), else the session override (`requested`), else the configured model (`resolved_default`) | none |
| `omnigent.session.reasoning_effort` | every span | session effort override | none |
| `omnigent.git.branch` | every span | session's recorded branch, else the workspace's checked-out branch | none |
| `omnigent.git.remote` | every span | `origin` URL of the workspace repo with credentials and SSH user stripped (resolved once per session) | none |
| `omnigent.workspace` | every span | session working folder (resolved once per session) | none (metadata; the path can embed a user name) |
| `omnigent.host.name` | every span | runner host name (resolved once per session) | none |
| `gen_ai.request.model` | agent span | turn override, else configured model; unset when neither exists (was: the agent name) | none |
| `gen_ai.response.model`, `omnigent.model.source` | agent span | model from the turn's usage or the harness's own report (`observed`); else the session model | none |
| `omnigent.reasoning_effort.requested` | agent span | effort the turn asked for, as given | none |
| `omnigent.reasoning_effort`, `omnigent.reasoning_effort.source` | agent span | the level that applied, from the shared effort ladder; `observed` when the harness reports it | none |

There is no separate user attribute: the acting user is `enduser.id` as proposed in #10794.

Server-owned values are re-read each turn, so renames, label edits, project moves and `/model` or effort switches reach later spans. Nothing changes when telemetry is off.

Two PRs implement this and will be opened against this issue: the agent-span model/effort part applies to `main` on its own; the session-metadata part stacks on it. Neither depends on #10794.

## Alternatives considered

- **Join `session.id` against the database downstream.** Works only when the analytics job can reach the Omnigent database, and duplicates session lookups per span.
- **`OTEL_RESOURCE_ATTRIBUTES`.** Resource attributes are per process; one runner serves many sessions and one server serves everyone, so per-session values cannot live there.
- **Stamp only on the agent span.** Downstream filters usually run per span (tool spans, HTTP spans); having the keys on every span of the turn avoids a parent walk in the backend.
- **Gate labels behind `OMNIGENT_OTEL_CAPTURE_CONTENT`.** Labels are the classification keys the feature exists for, and they are operator- or user-assigned metadata rather than conversation content, so only the title is gated. Open to an allowlist if maintainers prefer.

## Harness

Not applicable (the session attributes apply to every harness; the observed model/effort come from whatever each harness reports: Codex reports its effort, SDK harnesses report the model in usage, native terminals via their own status reports).

## Platform or device

Not platform-specific

## Harness mode

SDK, Native

## Expected reach

Some users (operators exporting traces)

## Authentication type

Not authentication-related
