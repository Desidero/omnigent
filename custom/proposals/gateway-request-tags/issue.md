Title: [Feature] Tag Unity Gateway requests with the session id and labels

### Problem or use case

Unity Gateway logs every inference request in its usage tracking table and inference tables, but nothing in a row says which Omnigent session sent it. To answer "what did this session (or this project, or this team's sessions) cost?" or "show me the requests behind this conversation", you have to match timestamps and users by hand.

The gateway already has a field for this. Requests can carry a `Databricks-Ai-Gateway-Request-Tags` header, a JSON object of string keys and values, and the gateway logs it in the `request_tags` column of both tables ([request tagging docs](https://docs.databricks.com/aws/en/ai-gateway/request-tagging)). Gateway service policies can also evaluate the tags.

Omnigent already has the data. Every session has an id and labels, and nothing sends either to any provider today. #10410 added the `Databricks-Custom-Coding-Agent` / `Databricks-Custom-Client-Surfaces` attribution headers, but those are the same for every request a process sends.

### Proposed solution

When a harness targets a Unity Gateway URL (the same `is_databricks_ai_gateway_url` gate the attribution headers use), send `Databricks-Ai-Gateway-Request-Tags` built from the session:

- `omnigent_session_id`: the session id, so gateway rows join back to Omnigent sessions. It is runner-owned (read from the launch snapshot or init envelope), so it is as trustworthy as the attribution headers.
- The session's user labels, namespaced as `omnigent_label_<key>`. Internal labels (`omnigent.*`, `omni_project`, `cost_control.*`) are left out.
- The value is capped (4 KiB, a quarter of Node's default 16 KiB header block that Claude Code shares with its auth and beta headers). Labels are added in key order up to the first that would overflow; the session id is always kept.

Example for a session labelled `team=web`, `ticket=ENG-123`:

```
Databricks-Ai-Gateway-Request-Tags: {"omnigent_session_id":"conv_abc123","omnigent_label_team":"web","omnigent_label_ticket":"ENG-123"}
```

**Why the namespace.** Gateway service policies can evaluate `request_tags` (for example "require tag X to allow"), and any editor of a session can set its labels. Sent under raw keys, a collaborator's `team=finance` label would reach a policy running under the launching user's token and could match an organisation-defined tag. The `omnigent_label_` prefix keeps the join trivial while making it impossible for a user label to collide with a tag the organisation defines.

**Open question for maintainers: labels default-on or opt-in?** #10410, #11118 and #11099 only send values that are fixed and process-owned, so that the gateway can trust what Omnigent claims about itself. Labels are user-authored. My proposal is to send them by default under the prefix above, since the namespace removes the policy collision and the labels only go to the user's own workspace; the alternative is to send only `omnigent_session_id` by default and enable labels with something like `OMNIGENT_GATEWAY_REQUEST_TAGS=labels`. Either way, `OMNIGENT_GATEWAY_REQUEST_TAGS=0` turns the header off entirely. Which do you prefer?

The canonical builder would live next to the attribution helpers in `omnigent/databricks_ai_gateway.py`. The harnesses only transport it, in the same spots #10410 stamps attribution:

- **Claude (native and SDK):** one more line in `ANTHROPIC_CUSTOM_HEADERS`, next to the attribution lines; the Claude gateway shim forwards it unchanged.
- **Codex (native and SDK):** the provider's `env_http_headers`, taking the value from a per-launch env var the way the open #11000 turns a session label into a per-launch header.
- **Pi (SDK), pi-native and opencode-native:** the header on gateway providers in the per-session `models.json` / `opencode.json` the runner writes.

Harness processes read the tags when they start, so a label edited mid-session shows up after the next terminal launch or harness respawn. That seems acceptable for attribution. A signer-backed Codex worker would not send the header, since the signer rebuilds a fixed header set; once #11099's signer `extra_headers` lands, the runner could hand the signer the session tags the same way.

Third-party providers and gateways never get the header.

I can send a PR for this.

### Alternatives considered

- **A static tag per process** (what the closed #4326 servlet did with `{"source": "omnigent"}`): tells you the traffic came from Omnigent, but not which session.
- **Endpoint-level tags:** the same for every caller of an endpoint, so they can't tell sessions apart.
- **Raw label keys as tags:** simplest to query, but collides with organisation-defined tags that gateway policies evaluate (see above).
- **Joining on time and user downstream:** unreliable with several concurrent sessions, and needs database access from wherever the gateway tables are queried.
- **The OTel span attributes from #10794:** good for traces, but gateway usage and cost tables don't read traces.

Related: #10410 (static attribution headers, the base this builds on), #11118 and #11099 (open, extend that attribution and touch the same helpers; the PR for this would rebase on #11118 and reuse its header merge helper), #11000 (open, per-launch Codex header from a session label, the pattern used here), #10794 (session attribution on spans).

### Harness

Claude, Codex, Pi, OpenCode

### Harness mode

SDK, Native

### Platform or device

Not platform-specific

### Expected reach

A substantial user segment (Databricks deployments that route inference through Unity Gateway)

### Authentication type

Databricks
