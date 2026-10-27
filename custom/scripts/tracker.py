#!/usr/bin/env python3
"""Generate the upstream tracker page from custom/series, custom/tracker.yaml and live GitHub state.

Usage: custom/scripts/tracker.py OUTPUT.html [--repo owner/name]
Needs `gh` authenticated. Reads only; never writes to GitHub.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REPO = "omnigent-ai/omnigent"
BOTS = {"github-actions", "omni-resolve-agent", "app/omni-resolve-agent", "omnigent-ci", "github-code-quality"}
TODAY = dt.date.today()


def parse_series(path: Path) -> dict[str, dict]:
    series: dict[str, dict] = {}
    current = None
    for line in path.read_text().splitlines():
        if line.startswith("# series: "):
            current = line.split(": ", 1)[1].strip()
            series[current] = {"needs": [], "patches": []}
        elif line.startswith("# needs: ") and current:
            series[current]["needs"].append(line.split(": ", 1)[1].strip())
        elif line.endswith(".patch") and current:
            series[current]["patches"].append(line.strip())
    return series


def fetch_github(numbers: set[int]) -> dict[int, dict]:
    owner, name = REPO.split("/")
    fields = """
      __typename
      ... on Issue { number title state updatedAt author { login }
        assignees(first: 3) { nodes { login } }
        comments(last: 8) { nodes { author { login } createdAt } }
        closedByPullRequestsReferences(first: 3) { nodes { number merged } } }
      ... on PullRequest { number title state updatedAt mergedAt isDraft author { login }
        assignees(first: 3) { nodes { login } }
        reviews(last: 5) { nodes { author { login } state submittedAt } }
        comments(last: 8) { nodes { author { login } createdAt } } }
    """
    out: dict[int, dict] = {}
    nums = sorted(numbers)
    for i in range(0, len(nums), 40):
        chunk = nums[i : i + 40]
        aliases = "\n".join(f"n{n}: issueOrPullRequest(number: {n}) {{ {fields} }}" for n in chunk)
        query = f'query {{ repository(owner: "{owner}", name: "{name}") {{ {aliases} }} }}'
        res = subprocess.run(["gh", "api", "graphql", "-f", f"query={query}"], capture_output=True, text=True, check=True)
        repo = json.loads(res.stdout)["data"]["repository"]
        for key, val in repo.items():
            if val:
                out[int(key[1:])] = val
    return out


def last_human(node: dict) -> dt.date | None:
    dates = []
    for c in node.get("comments", {}).get("nodes", []):
        login = (c.get("author") or {}).get("login", "")
        if login and login not in BOTS:
            dates.append(c["createdAt"][:10])
    for r in node.get("reviews", {}).get("nodes", []) if node.get("reviews") else []:
        login = (r.get("author") or {}).get("login", "")
        if login and login not in BOTS and r.get("submittedAt"):
            dates.append(r["submittedAt"][:10])
    return dt.date.fromisoformat(max(dates)) if dates else None


def days(d: dt.date | None) -> str:
    return "–" if d is None else f"{(TODAY - d).days}d"


def ref(n: int, gh: dict[int, dict]) -> str:
    node = gh.get(n)
    kind = "pull" if node and node["__typename"] == "PullRequest" else "issues"
    title = html.escape(node["title"]) if node else ""
    st = ""
    if node:
        st = "merged" if node.get("mergedAt") else node["state"].lower()
        if node.get("isDraft") and st == "open":
            st = "draft"
    return f'<a href="https://github.com/{REPO}/{kind}/{n}" title="{title}">#{n}</a><span class="st {st}">{st}</span>'


# Lifecycle states, in the order the views sort them.
STATES = [
    ("drop", "merged upstream: drop the patch"),
    ("superseded", "superseded: retire"),
    ("blocked", "blocked on upstream"),
    ("pr-open", "our PR open"),
    ("carrying", "carrying someone's PR"),
    ("issue-open", "issue open, no PR"),
    ("proposed", "proposed, nothing filed"),
    ("local", "local only"),
    ("watching", "watching"),
]
NEXT = {
    "drop": "Drop the patch on the next rebase.",
    "superseded": "Retire the series; keep local if still useful.",
    "blocked": "Nudge once; nothing to build until it moves.",
    "pr-open": "Answer review; rebase when behind.",
    "carrying": "Nothing. Drop when it merges; propose our extra fixes on it.",
    "issue-open": "Open the PR, unless the issue asked for agreement first.",
    "proposed": "File the issue or PR from proposals/.",
    "local": "Decide: keep private, or write a proposal.",
    "watching": "Comment or nudge when it goes quiet.",
}


def is_open(n, gh):
    node = gh.get(n)
    return bool(node) and node["state"] == "OPEN"


def is_merged(n, gh):
    node = gh.get(n)
    return bool(node) and (node.get("mergedAt") or any(r.get("merged") for r in node.get("closedByPullRequestsReferences", {}).get("nodes", []) or []))


def lifecycle(entry: dict, gh: dict, watch: bool) -> tuple[str, str]:
    if watch:
        return "watching", ""
    if entry.get("carries"):
        n = entry["carries"]
        if is_merged(n, gh):
            return "drop", f"#{n} merged"
        if not is_open(n, gh):
            return "proposed", f"#{n} closed unmerged; propose ours"
        return "carrying", ""
    if entry.get("our_pr"):
        n = entry["our_pr"]
        if is_merged(n, gh):
            return "drop", f"#{n} merged"
        if is_open(n, gh):
            return "pr-open", ""
    if entry.get("superseded_by") and (is_open(entry["superseded_by"], gh) or is_merged(entry["superseded_by"], gh)):
        return "superseded", f"by #{entry['superseded_by']}"
    if entry.get("blocked_by") and is_open(entry["blocked_by"], gh):
        return "blocked", f"on #{entry['blocked_by']}"
    if entry.get("issue"):
        n = entry["issue"]
        if is_merged(n, gh):
            return "drop", f"#{n} closed by a merged PR"
        if is_open(n, gh):
            return "issue-open", ""
    if entry.get("keep_local"):
        return "local", ""
    return "proposed", ""


def main() -> None:
    out_path = Path(sys.argv[1])
    data = yaml.safe_load((ROOT / "tracker.yaml").read_text())
    series = parse_series(ROOT / "series")
    base = (ROOT / "BASE").read_text().strip()[:9]
    entries: dict[str, dict] = {}
    for name, e in data["series"].items():
        e = dict(e)
        e["kind"] = "series"
        e["needs"] = series.get(name, {}).get("needs", [])
        e["patch_count"] = len(series.get(name, {}).get("patches", []))
        entries[name] = e
    for name, e in data["watch"].items():
        e = dict(e)
        e["kind"] = "watch"
        e["needs"] = []
        entries[name] = e
    missing = [s for s in series if s not in entries]
    if missing:
        print(f"warning: series without tracker entry: {missing}", file=sys.stderr)

    numbers: set[int] = set()
    for e in entries.values():
        for k in ("issue", "our_pr", "carries", "superseded_by", "blocked_by"):
            if e.get(k):
                numbers.add(int(e[k]))
        for k in ("related", "conflicts"):
            numbers.update(int(x) for x in e.get(k, []))
    gh = fetch_github(numbers)

    # Reverse dependency closure: what each series unblocks.
    dependents: dict[str, set[str]] = {n: set() for n in entries}
    for n, e in entries.items():
        for d in e["needs"]:
            dependents.setdefault(d, set()).add(n)

    def closure(n: str) -> set[str]:
        seen, stack = set(), list(dependents.get(n, ()))
        while stack:
            x = stack.pop()
            if x not in seen:
                seen.add(x)
                stack.extend(dependents.get(x, ()))
        return seen

    for n, e in entries.items():
        e["state"], e["why"] = lifecycle(e, gh, e["kind"] == "watch")
        e["unblocks"] = sorted(closure(n))
        # Inherit a block from a prerequisite.
        for d in e["needs"]:
            if entries.get(d, {}).get("state") == "blocked" and e["state"] in ("proposed", "issue-open"):
                e["state"], e["why"] = "blocked", f"via {d}"
        handles = [e.get(k) for k in ("issue", "our_pr", "carries", "superseded_by") if e.get(k)]
        acts = [last_human(gh[h]) for h in handles if h in gh]
        upd = [dt.date.fromisoformat(gh[h]["updatedAt"][:10]) for h in handles if h in gh]
        e["last_human"] = max([a for a in acts if a], default=None)
        e["last_update"] = max(upd, default=None)
        e["assignees"] = sorted({a["login"] for h in handles if h in gh for a in gh[h]["assignees"]["nodes"]})

    order = {s: i for i, (s, _) in enumerate(STATES)}
    rows = sorted(entries.items(), key=lambda kv: (order[kv[1]["state"]], -len(kv[1]["unblocks"]), kv[0]))

    def handles_html(e):
        parts = []
        for k, label in (("issue", "issue"), ("our_pr", "our PR"), ("carries", "carries"), ("superseded_by", "superseded by"), ("blocked_by", "blocked by")):
            if e.get(k):
                parts.append(f'<span class="h">{label} {ref(int(e[k]), gh)}</span>')
        if e.get("related"):
            parts.append('<span class="h">related ' + " ".join(ref(int(x), gh) for x in e["related"]) + "</span>")
        if e.get("conflicts"):
            parts.append('<span class="h">conflicts ' + " ".join(ref(int(x), gh) for x in e["conflicts"]) + "</span>")
        return " ".join(parts) or "–"

    def row_html(name, e):
        rel = []
        if e["needs"]:
            rel.append("needs " + ", ".join(f"<code>{d}</code>" for d in e["needs"]))
        if e["unblocks"]:
            rel.append(f'<strong>unblocks {len(e["unblocks"])}</strong>: ' + ", ".join(f"<code>{d}</code>" for d in e["unblocks"]))
        why = f' <span class="why">({html.escape(e["why"])})</span>' if e["why"] else ""
        note = f'<div class="note">{html.escape(e["note"])}</div>' if e.get("note") else ""
        if e.get("branch"):
            note += f'<div class="note">branch: <span class="mono">{html.escape(e["branch"])}</span></div>'
        if e.get("drafts"):
            note += '<div class="note">drafts: ' + ", ".join(f'<a href="https://github.com/Desidero/omnigent/blob/patches/custom/{d}"><code>{d.split("/")[-1]}</code></a>' for d in e["drafts"]) + "</div>"
        kind = f'<span class="kind">{e["patch_count"]} patch{"es" if e["patch_count"] != 1 else ""}</span>' if e["kind"] == "series" else '<span class="kind">no patch</span>'
        return (
            f'<tr class="s-{e["state"]}" id="row-{name}"><td class="num"><code>{name}</code><br>{kind}</td>'
            f'<td>{html.escape(e["want"])}{note}<div class="rel">{" · ".join(rel)}</div></td>'
            f'<td><span class="chip {e["state"]}">{dict(STATES)[e["state"]]}</span>{why}</td>'
            f'<td class="handles">{handles_html(e)}</td>'
            f'<td class="num">{days(e["last_human"])} / {days(e["last_update"])}<br><span class="who">{", ".join(e["assignees"]) or "–"}</span></td>'
            f'<td>{html.escape(NEXT[e["state"]])}</td></tr>'
        )

    def view(title, blurb, pred, sort_key=None):
        sel = [(n, e) for n, e in rows if pred(e)]
        if sort_key:
            sel.sort(key=sort_key)
        if not sel:
            return f'<h2 id="{title.lower().replace(" ", "-")}">{title}</h2><p class="lede">{blurb}</p><p class="empty">Nothing here right now.</p>'
        body = "".join(row_html(n, e) for n, e in sel)
        return (
            f'<h2 id="{title.lower().replace(" ", "-")}">{title} <span class="count">{len(sel)}</span></h2><p class="lede">{blurb}</p>'
            f'<div class="tablewrap"><table><thead><tr><th>Change</th><th>What and relationships</th><th>State</th><th>Upstream</th><th>Human / any activity</th><th>Next step</th></tr></thead><tbody>{body}</tbody></table></div>'
        )

    # Mermaid graph of series, needs edges, and external blockers.
    cls = {"drop": "drop", "superseded": "drop", "blocked": "blocked", "pr-open": "ok", "carrying": "ok", "issue-open": "warn", "proposed": "plain", "local": "dim", "watching": "dim"}
    lines = ["graph LR"]
    for n, e in entries.items():
        if e["kind"] != "series":
            continue
        lines.append(f'  {n.replace("-", "_")}["{n}"]:::{cls[e["state"]]}')
        for d in e["needs"]:
            lines.append(f'  {d.replace("-", "_")} --> {n.replace("-", "_")}')
        if e.get("blocked_by"):
            lines.append(f'  gh{e["blocked_by"]}(("#{e["blocked_by"]}")):::ext')
            lines.append(f'  gh{e["blocked_by"]} -.blocks.-> {n.replace("-", "_")}')
        if e.get("carries"):
            lines.append(f'  gh{e["carries"]}(("#{e["carries"]}")):::ext')
            lines.append(f'  gh{e["carries"]} -.carried.-> {n.replace("-", "_")}')
        if e.get("superseded_by"):
            lines.append(f'  gh{e["superseded_by"]}(("#{e["superseded_by"]}")):::ext')
            lines.append(f'  gh{e["superseded_by"]} -.supersedes.-> {n.replace("-", "_")}')
    lines += [
        "  classDef ok fill:#e3f1e8,stroke:#2d7a4f,color:#1d1f22",
        "  classDef warn fill:#fbf0d4,stroke:#9a6700,color:#1d1f22",
        "  classDef blocked fill:#f9e2df,stroke:#b3261e,color:#1d1f22",
        "  classDef drop fill:#e9e9e9,stroke:#6b6f76,color:#1d1f22,stroke-dasharray:4 2",
        "  classDef plain fill:#ffffff,stroke:#d9d6cc,color:#1d1f22",
        "  classDef dim fill:#eeece6,stroke:#d9d6cc,color:#5d6168",
        "  classDef ext fill:#e4e8f6,stroke:#3d4f8f,color:#1d1f22",
    ]
    graph = "\n".join(lines)

    counts = {s: sum(1 for _, e in rows if e["state"] == s) for s, _ in STATES}
    stale = lambda e: (TODAY - e["last_human"]).days if e["last_human"] else 999

    page = TEMPLATE.format(
        today=TODAY.isoformat(),
        base=base,
        counts=" ".join(f'<span class="chip {s}">{label.split(":")[0]} {c}</span>' for (s, label), c in zip(STATES, counts.values()) if c),
        graph=html.escape(graph, quote=False),
        drop=view("Drop list", "Patches to remove on the next rebase of custom, in needs order: drop prerequisites last.", lambda e: e["state"] in ("drop", "superseded")),
        mine=view("My move", "The ball is with us. Sorted by how many other series each one unblocks.", lambda e: e["state"] in ("pr-open", "issue-open", "proposed", "local"), lambda kv: (-len(kv[1]["unblocks"]), order[kv[1]["state"]], kv[0])),
        theirs=view("Their move", "Waiting on a maintainer. Sorted by days since the last human activity; the top rows are the ones to nudge.", lambda e: e["state"] in ("blocked", "carrying"), lambda kv: -stale(kv[1])),
        watching=view("Watching", "No patch of ours; interest only.", lambda e: e["state"] == "watching", lambda kv: -stale(kv[1])),
        everything="".join(row_html(n, e) for n, e in rows),
    )
    out_path.write_text(page)
    print(f"{out_path}: {len(rows)} rows, {len(gh)} GitHub items; " + ", ".join(f"{s}={c}" for s, c in counts.items() if c))


TEMPLATE = """<title>Omnigent Upstream Tracker</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: summary counts, dependency graph, then four action views and the full table. Generated; do not hand-edit. */
:root{{
  --bg:#f6f5f1; --surface:#ffffff; --surface-2:#eeece6; --line:#d9d6cc; --fg:#1d1f22; --muted:#5d6168; --accent:#19627a; --accent-ink:#ffffff;
  --ok:#2d7a4f; --ok-bg:#e3f1e8; --warn:#9a6700; --warn-bg:#fbf0d4; --crit:#b3261e; --crit-bg:#f9e2df; --info:#3d4f8f; --info-bg:#e4e8f6; --dim:#6b6f76; --dim-bg:#e9e9e9;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif; --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
}}
@media (prefers-color-scheme: dark){{ :root:not([data-theme="light"]){{
  --bg:#17191c; --surface:#1f2226; --surface-2:#272b30; --line:#373c43; --fg:#e8e6e0; --muted:#a2a6ad; --accent:#6fc0d8; --accent-ink:#0f1b20;
  --ok:#7fd29d; --ok-bg:#1d3327; --warn:#f0c15a; --warn-bg:#3a2f12; --crit:#f29b94; --crit-bg:#3d1f1c; --info:#9fb0ee; --info-bg:#232a45; --dim:#a6aab0; --dim-bg:#2e3237; color-scheme:dark }}}}
:root[data-theme="dark"]{{
  --bg:#17191c; --surface:#1f2226; --surface-2:#272b30; --line:#373c43; --fg:#e8e6e0; --muted:#a2a6ad; --accent:#6fc0d8; --accent-ink:#0f1b20;
  --ok:#7fd29d; --ok-bg:#1d3327; --warn:#f0c15a; --warn-bg:#3a2f12; --crit:#f29b94; --crit-bg:#3d1f1c; --info:#9fb0ee; --info-bg:#232a45; --dim:#a6aab0; --dim-bg:#2e3237; color-scheme:dark }}
*{{box-sizing:border-box}}
body{{background:var(--bg);color:var(--fg);font-family:var(--sans);font-size:15px;line-height:1.5;margin:0;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:0 48px}}
body::before{{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10;background:var(--bg)}}
.wrap{{max-width:1240px;margin:0 auto}}
a{{color:var(--accent);text-decoration:none}}a:hover{{text-decoration:underline}}
h1{{font-size:26px;font-weight:600;margin:26px 0 4px;text-wrap:balance}}
h2{{font-size:19px;font-weight:600;margin:36px 0 8px;scroll-margin-top:64px}}
h2 .count{{font-family:var(--mono);font-size:14px;color:var(--muted);font-weight:400;margin-left:6px}}
p{{margin:.4em 0;max-width:80ch}} .lede{{color:var(--muted)}} .empty{{color:var(--muted);font-style:italic}}
code{{font-family:var(--mono);font-size:.9em;background:var(--surface-2);padding:1px 5px;border-radius:4px}}
nav.sections{{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--bg);border-bottom:1px solid var(--line);margin:0 -16px;padding:8px 16px;display:flex;gap:4px 14px;flex-wrap:wrap;font-size:14px}}
nav.sections a{{color:var(--fg)}}
.meta{{display:flex;flex-wrap:wrap;gap:8px 18px;color:var(--muted);font-size:13px;margin:6px 0 10px}}
.counts{{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 14px}}
.chip{{display:inline-block;font-size:12px;font-weight:500;line-height:1;padding:4px 8px;border-radius:999px;white-space:nowrap;vertical-align:middle}}
.chip.drop,.chip.superseded{{background:var(--dim-bg);color:var(--dim);text-decoration:line-through}}
.chip.blocked{{background:var(--crit-bg);color:var(--crit)}}
.chip.pr-open,.chip.carrying{{background:var(--ok-bg);color:var(--ok)}}
.chip.issue-open{{background:var(--warn-bg);color:var(--warn)}}
.chip.proposed{{background:var(--surface);color:var(--fg);border:1px solid var(--line)}}
.chip.local,.chip.watching{{background:var(--surface-2);color:var(--muted)}}
.why{{color:var(--muted);font-size:13px}}
.graphwrap{{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px}}
pre.mermaid{{margin:0;font-family:var(--mono)}}
.legend{{display:flex;flex-wrap:wrap;gap:10px;font-size:13px;color:var(--muted);margin:6px 0}}
.tablewrap{{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--surface)}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top;min-width:0}}
th{{font-weight:600;color:var(--muted);font-size:12px;letter-spacing:.04em;text-transform:uppercase;background:var(--surface-2);white-space:nowrap}}
tr:last-child td{{border-bottom:0}}
td.num{{font-family:var(--mono);white-space:nowrap;font-variant-numeric:tabular-nums}}
.kind,.who{{color:var(--muted);font-size:12px;font-family:var(--sans)}}
.note{{color:var(--muted);font-size:13px;margin-top:2px}}
.rel{{font-size:12.5px;color:var(--muted);margin-top:3px}}
.handles .h{{display:block;white-space:nowrap;font-size:13px}}
.st{{font-size:10px;margin:0 6px 0 2px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}}
.st.merged{{color:var(--info)}}.st.open{{color:var(--ok)}}.st.draft{{color:var(--warn)}}.st.closed{{color:var(--crit)}}
.howto{{background:var(--surface-2);border-radius:6px;padding:10px 14px;font-size:14px;max-width:90ch}}
@media (prefers-reduced-motion: reduce){{*{{scroll-behavior:auto}}}}
</style>
<div class="wrap">
<h1>Omnigent Upstream Tracker</h1>
<p class="lede">Every change we want in Omnigent: the ones we patch, the ones we are contributing, and the ones we only watch. State and next step come from live GitHub; relationships come from <code>custom/series</code> and <code>custom/tracker.yaml</code> on the fork's <code>patches</code> branch.</p>
<div class="meta"><span>Generated {today}</span><span>Series base: upstream <code>{base}</code></span><span>Activity column: days since the last human comment or review / since any update</span></div>
<div class="counts">{counts}</div>
<nav class="sections" aria-label="Sections"><a href="#graph">Graph</a><a href="#drop-list">Drop list</a><a href="#my-move">My move</a><a href="#their-move">Their move</a><a href="#watching">Watching</a><a href="#everything">Everything</a><a href="#refresh">Refresh</a></nav>

<h2 id="graph">Dependency graph</h2>
<p class="lede">Solid arrows: apply-order dependencies between our series. Dotted arrows: upstream items that block, are carried by, or supersede a series.</p>
<div class="legend"><span class="chip pr-open">PR open / carrying</span><span class="chip issue-open">issue open</span><span class="chip blocked">blocked</span><span class="chip proposed">proposed</span><span class="chip drop">drop / superseded</span><span class="chip local">local / watching</span></div>
<div class="graphwrap"><pre class="mermaid">
{graph}
</pre></div>

{drop}
{mine}
{theirs}
{watching}

<h2 id="everything">Everything</h2>
<div class="tablewrap"><table><thead><tr><th>Change</th><th>What and relationships</th><th>State</th><th>Upstream</th><th>Human / any activity</th><th>Next step</th></tr></thead><tbody>{everything}</tbody></table></div>

<h2 id="refresh">Refresh</h2>
<div class="howto">Edit <code>custom/tracker.yaml</code> (a pull request into <code>patches</code>) when a link changes (new issue, PR opened, something merged), then run <code>custom/scripts/tracker.py out.html</code> and republish this page to the same URL. The series and needs edges are read from <code>custom/series</code>, so a new series only needs a <code>tracker.yaml</code> entry with its <code>want</code> line.</div>
</div>
"""

if __name__ == "__main__":
    main()
