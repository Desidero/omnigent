"""Release notes and per-series docs for a build of the patch series.

  notes.py series --custom DIR
      Print the series as JSON: [{name, needs, patches: [{file, subject, patch_id}]}].
  notes.py render --manifest F --tree DIR --custom DIR --fork REPO --notes OUT --docs OUT
                  [--previous-manifest F] [--note TEXT]
      Write the release body (header, changes since the previous release, the
      series index with links pinned to the release tag) and custom-docs.md
      (per series, the doc sections its patches add or change).
  notes.py set-digest --manifest F --notes F --digest sha256:...
      Record the pushed image digest in both.

Stdlib only; runs with any python >= 3.11.
"""

from __future__ import annotations

import argparse
import email
import email.policy
import json
import posixpath
import re
import subprocess
import sys
from pathlib import Path

UPSTREAM = "omnigent-ai/omnigent"
DOC_PATHS_RE = re.compile(r"^(docs/|feature-map/|designs/|omnigent/server/API\.md$)")
INDEX_PATH = "docs/custom/README.md"
INDEX_SERIES = "custom-docs-index"
# GitHub rejects release bodies over 125,000 characters.
BODY_LIMIT = 120_000
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
LINK_RE = re.compile(r"(\]\()([^)\s]+)(\))")
IMAGE_LINE_PREFIX = "- **Image:** "
LIST_ITEM_RE = re.compile(r"^\s{0,1}([-*+]|\d+[.)])\s")
# A touched section longer than this shows only the blocks with added lines.
SECTION_LIMIT = 3000


# ---------------------------------------------------------------- series


def parse_series(custom_dir: Path) -> list[dict]:
    """Series in apply order; a '(continued)' block joins its earlier series."""
    order: list[str] = []
    series: dict[str, dict] = {}
    current = None
    for raw in (custom_dir / "series").read_text().splitlines():
        line = raw.strip()
        match = re.match(r"^#\s*series:\s*(\S+)", line)
        if match:
            current = match.group(1)
            if current not in series:
                series[current] = {"name": current, "needs": [], "patches": []}
                order.append(current)
            continue
        match = re.match(r"^#\s*needs:\s*(\S+)", line)
        if match and current:
            if match.group(1) not in series[current]["needs"]:
                series[current]["needs"].append(match.group(1))
            continue
        if line and not line.startswith("#") and current:
            series[current]["patches"].append(line)
    return [series[name] for name in order]


def patch_subject(path: Path) -> str:
    with path.open("rb") as handle:
        message = email.message_from_binary_file(handle, policy=email.policy.default)
    subject = str(message.get("Subject", "")).replace("\n", " ")
    return re.sub(r"^\[PATCH[^\]]*\]\s*", "", subject).strip()


def patch_id(path: Path) -> str:
    """git's stable patch id: the change, ignoring line numbers and blob ids."""
    result = subprocess.run(
        ["git", "patch-id", "--stable"],
        input=path.read_bytes(),
        capture_output=True,
        check=True,
    )
    return result.stdout.decode().split(" ", 1)[0]


def series_json(custom_dir: Path) -> list[dict]:
    patches_dir = custom_dir / "patches"
    out = []
    for entry in parse_series(custom_dir):
        out.append(
            {
                "name": entry["name"],
                "needs": entry["needs"],
                "patches": [
                    {
                        "file": name,
                        "subject": patch_subject(patches_dir / name),
                        "patch_id": patch_id(patches_dir / name),
                    }
                    for name in entry["patches"]
                ],
            }
        )
    return out


# ---------------------------------------------------------------- diffs


def doc_changes(patch_path: Path) -> dict[str, dict]:
    """Per doc path in a patch: the added lines and whether the patch creates it."""
    files: dict[str, dict] = {}
    current = None
    in_hunk = False
    for line in patch_path.read_text(errors="replace").splitlines():
        if line.startswith("diff --git "):
            match = re.match(r"^diff --git a/(.*) b/(.*)$", line)
            path = match.group(2) if match else ""
            current = files.setdefault(path, {"added": [], "new": False}) if DOC_PATHS_RE.match(path) else None
            in_hunk = False
        elif current is None:
            continue
        elif line.startswith("new file mode"):
            current["new"] = True
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line.startswith("+") and not line.startswith("+++"):
            current["added"].append(line[1:])
    return files


def significant(line: str) -> bool:
    """Lines specific enough to locate by content (not blanks, fences or rules)."""
    text = line.strip()
    return len(text) >= 12 and re.search(r"[A-Za-z]{3}", text) is not None


# ---------------------------------------------------------------- markdown


def headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(line index, level, title) of each ATX heading outside code fences."""
    found, fenced = [], False
    for index, line in enumerate(lines):
        if FENCE_RE.match(line):
            fenced = not fenced
            continue
        match = None if fenced else HEADING_RE.match(line)
        if match:
            found.append((index, len(match.group(1)), match.group(2)))
    return found


def section_end(heads: list[tuple[int, int, str]], position: int, total: int) -> int:
    level = heads[position][1]
    for index, other_level, _ in heads[position + 1 :]:
        if other_level <= level:
            return index
    return total


def breadcrumb(heads: list[tuple[int, int, str]], position: int) -> list[str]:
    trail, level = [], heads[position][1]
    for index in range(position - 1, -1, -1):
        if heads[index][1] < level:
            trail.insert(0, heads[index][2])
            level = heads[index][1]
    return trail


def shift_headings(text: str, levels: int) -> str:
    out, fenced = [], False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            fenced = not fenced
        match = None if fenced else HEADING_RE.match(line)
        if match:
            level = min(6, len(match.group(1)) + levels)
            line = "#" * level + " " + match.group(2)
        out.append(line)
    return "\n".join(out)


def blocks(lines: list[str]) -> list[list[str]]:
    """Paragraphs, top-level list items and whole code fences of a section body."""
    out: list[list[str]] = []
    current: list[str] = []
    fenced = False
    for line in lines:
        if FENCE_RE.match(line):
            if not fenced and current:
                out.append(current)
                current = []
            current.append(line)
            fenced = not fenced
            if not fenced:
                out.append(current)
                current = []
            continue
        if fenced:
            current.append(line)
        elif not line.strip():
            if current:
                out.append(current)
                current = []
        elif LIST_ITEM_RE.match(line) and current:
            out.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        out.append(current)
    return out


def excerpt(body: str, wanted: set[str]) -> str:
    """The heading plus only the blocks of a long section that hold added lines."""
    lines = body.splitlines()
    head, rest = lines[0], lines[1:]
    chosen = [block for block in blocks(rest) if any(line.strip() in wanted for line in block)]
    parts = [head, ""]
    for index, block in enumerate(chosen):
        if index:
            parts += ["", "…", ""]
        parts += block
    return "\n".join(parts)


def touched_sections(text: str, added: list[str]) -> list[tuple[list[str], str]] | None:
    """Headed sections of the final file that hold any of the added lines.

    Each line maps to its nearest heading; a section inside another chosen
    section is dropped. Returns None when no added line is found any more.
    """
    lines = text.splitlines()
    heads = headings(lines)
    wanted = {line.strip() for line in added if significant(line)}
    if not wanted:
        return []
    owners: set[int] = set()
    for index, line in enumerate(lines):
        if line.strip() not in wanted:
            continue
        owner = -1
        for position, (head_index, _, _) in enumerate(heads):
            if head_index <= index:
                owner = position
            else:
                break
        owners.add(owner)
    if not owners:
        return None
    ranges = []
    for owner in sorted(owners):
        if owner < 0:
            start, end = 0, heads[0][0] if heads else len(lines)
        else:
            start, end = heads[owner][0], section_end(heads, owner, len(lines))
        ranges.append((start, end, owner))
    kept = [r for r in ranges if not any(o[0] <= r[0] and r[1] <= o[1] and o != r for o in ranges)]
    sections = []
    for start, end, owner in kept:
        trail = breadcrumb(heads, owner) if owner >= 0 else []
        body = "\n".join(lines[start:end]).strip("\n")
        if owner >= 0:
            if len(body) > SECTION_LIMIT:
                body = excerpt(body, wanted)
            # Normalize the section's own heading to level 4 under '### <path>'.
            body = shift_headings(body, 4 - heads[owner][1])
        sections.append((trail, body))
    return sections


# ---------------------------------------------------------------- links


def pin_links(text: str, source_path: str, fork: str, ref: str) -> str:
    """Rewrite relative links in a file at source_path to the fork at ref."""
    base_dir = posixpath.dirname(source_path)

    def replace(match: re.Match[str]) -> str:
        target = match.group(2)
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith(("#", "/")):
            return match.group(0)
        path, _, anchor = target.partition("#")
        resolved = posixpath.normpath(posixpath.join(base_dir, path))
        url = f"https://github.com/{fork}/blob/{ref}/{resolved}"
        if anchor:
            url += "#" + anchor
        return match.group(1) + url + match.group(3)

    return LINK_RE.sub(replace, text)


# ---------------------------------------------------------------- notes


def short(sha: str | None, length: int = 12) -> str:
    return (sha or "?")[:length]


def changes_since(current: dict, previous: dict | None) -> list[str]:
    if previous is None:
        return ["First release of this pipeline: there is no earlier release to compare with."]
    lines = [f"Compared with `{previous.get('tag')}` ({previous.get('version')})."]
    lines.append("")
    old_base, new_base = previous.get("oss_commit"), current.get("oss_commit")
    if old_base and new_base and old_base != new_base:
        lines.append(
            f"- **Base moved** from `{short(old_base)}` to `{short(new_base)}`: "
            f"[upstream changes](https://github.com/{UPSTREAM}/compare/{old_base}...{new_base})."
        )
    elif old_base:
        lines.append(f"- Base unchanged (`{short(new_base)}`).")
    if "series" not in previous:
        lines.append("- The previous manifest has no series list, so series changes are not shown.")
        return lines
    old = {entry["name"]: entry for entry in previous["series"]}
    new = {entry["name"]: entry for entry in current.get("series", [])}
    added = [name for name in new if name not in old]
    dropped = [name for name in old if name not in new]
    changed, unchanged = [], 0
    for name in new:
        if name not in old:
            continue
        old_ids = [p["patch_id"] for p in old[name]["patches"]]
        new_ids = [p["patch_id"] for p in new[name]["patches"]]
        if old_ids == new_ids:
            unchanged += 1
        else:
            changed.append(name)
    for name in added:
        count = len(new[name]["patches"])
        lines.append(f"- **Added** `{name}` ({count} patch{'es' if count != 1 else ''}).")
    for name in changed:
        old_ids = {p["patch_id"] for p in old[name]["patches"]}
        new_ids = {p["patch_id"] for p in new[name]["patches"]}
        detail = []
        detail += [f"new or changed: {p['subject']}" for p in new[name]["patches"] if p["patch_id"] not in old_ids]
        detail += [f"removed: {p['subject']}" for p in old[name]["patches"] if p["patch_id"] not in new_ids]
        if not detail:
            detail = ["patches reordered"]
        lines.append(f"- **Changed** `{name}`: " + "; ".join(detail) + ".")
    for name in dropped:
        lines.append(f"- **Dropped** `{name}` (landed upstream or retired).")
    if not (added or changed or dropped):
        lines.append("- No series changed.")
    lines.append(f"- {unchanged} series unchanged.")
    return lines


def render(args: argparse.Namespace) -> None:
    manifest = json.loads(Path(args.manifest).read_text())
    previous = json.loads(Path(args.previous_manifest).read_text()) if args.previous_manifest else None
    tree, custom_dir, fork = Path(args.tree), Path(args.custom), args.fork
    tag = manifest["tag"]
    is_release = tag.startswith("custom/")
    ref = tag if is_release else "custom"
    # Older manifests name a separate patches repository; new ones the fork.
    patches_repo = manifest.get("patches_repo") or fork

    header = [
        f"**Omnigent {manifest['version']}**: upstream Omnigent plus the patch series.",
        "",
        f"- **Version:** `{manifest['version']}` (build `{manifest.get('build_id')}`)",
        f"- **OSS base:** [`{short(manifest.get('oss_commit'))}`](https://github.com/{UPSTREAM}/commit/{manifest.get('oss_commit')})",
        f"- **Patches commit:** [`{short(manifest.get('patches_commit'))}`](https://github.com/{patches_repo}/commit/{manifest.get('patches_commit')})"
        " (the `patches` branch: `custom/BASE`, `custom/series`, the patch files)",
        f"- **Built custom commit:** [`{short(manifest['commit'])}`](https://github.com/{fork}/commit/{manifest['commit']})"
        + ("" if is_release else " (not pushed: not a release build)"),
        f"{IMAGE_LINE_PREFIX}`{manifest['image']}`" + ("" if is_release else " (not pushed)"),
        f"- **Series:** {len(manifest.get('series', []))}, "
        f"{sum(len(s['patches']) for s in manifest.get('series', []))} patches",
    ]
    if args.note:
        header.append(f"- {args.note}")
    header += [
        "",
        "Install on a host with `upgrade-host.sh --release <tag>`; `custom-docs.md` collects the "
        "doc sections each series adds or changes. See "
        f"[`custom/release/README.md`](https://github.com/{fork}/blob/patches/custom/release/README.md) "
        "on the `patches` branch.",
    ]

    index_text = (tree / INDEX_PATH).read_text() if (tree / INDEX_PATH).is_file() else ""
    index_text = pin_links(index_text, INDEX_PATH, fork, ref)
    # Drop the index's own title; its sections become level-3 under '## Series index'.
    index_lines = index_text.splitlines()
    if index_lines and index_lines[0].startswith("# "):
        index_lines = index_lines[1:]
    index_body = shift_headings("\n".join(index_lines).strip("\n"), 1)

    body = "\n".join(header)
    body += "\n\n## Changes since the previous release\n\n" + "\n".join(changes_since(manifest, previous))
    body += "\n\n## Series index\n\n" + index_body + "\n"
    if len(body) > BODY_LIMIT:
        cut = body[: BODY_LIMIT - 200].rsplit("\n## ", 1)[0]
        body = cut + "\n\n_The index is cut short here; the full text is in `custom-docs.md` and on the fork._\n"
    Path(args.notes).write_text(body)

    Path(args.docs).write_text(custom_docs(manifest, tree, custom_dir, fork, ref))


def custom_docs(manifest: dict, tree: Path, custom_dir: Path, fork: str, ref: str) -> str:
    out = [
        f"# Custom docs for Omnigent {manifest['version']}",
        "",
        f"Per series, the documentation its patches add or change, as of `{manifest['tag']}` "
        f"(custom `{short(manifest['commit'])}`). Whole files are shown when the series adds "
        "them; otherwise the headed sections that hold its added lines. Links point at the fork.",
    ]
    for entry in parse_series(custom_dir):
        name = entry["name"]
        if name == INDEX_SERIES:
            continue
        per_file: dict[str, dict] = {}
        for patch in entry["patches"]:
            for path, change in doc_changes(custom_dir / "patches" / patch).items():
                merged = per_file.setdefault(path, {"added": [], "new": False})
                merged["added"] += change["added"]
                merged["new"] = merged["new"] or change["new"]
        out += ["", f"## {name}", ""]
        if not per_file:
            out.append("_No doc changes; see the series index for why._")
            continue
        for path, change in per_file.items():
            final = tree / path
            link = f"https://github.com/{fork}/blob/{ref}/{path}"
            out += [f"### [{path}]({link})", ""]
            if not final.is_file():
                out += ["_Removed again by a later patch._", ""]
                continue
            text = pin_links(final.read_text(errors="replace"), path, fork, ref)
            if change["new"]:
                out += ["_Added by this series._", "", shift_headings(text.strip("\n"), 3), ""]
                continue
            sections = touched_sections(text, change["added"])
            if sections is None:
                out += ["_Its changes were rewritten by later patches; added lines:_", "", "```diff"]
                out += ["+" + line for line in change["added"]] + ["```", ""]
                continue
            if not sections:
                out += ["_Only whitespace or formatting changes._", ""]
                continue
            for trail, body in sections:
                if trail:
                    out += ["_In: " + " › ".join(trail) + "_", ""]
                out += [body, ""]
    return "\n".join(out).rstrip("\n") + "\n"


def set_digest(args: argparse.Namespace) -> None:
    manifest_path, notes_path = Path(args.manifest), Path(args.notes)
    manifest = json.loads(manifest_path.read_text())
    manifest["image_digest"] = args.digest
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    lines = notes_path.read_text().splitlines()
    for index, line in enumerate(lines):
        if line.startswith(IMAGE_LINE_PREFIX):
            lines[index] = f"{IMAGE_LINE_PREFIX}`{manifest['image']}` (`{args.digest}`)"
    notes_path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("series")
    p.add_argument("--custom", required=True, help="the custom/ folder: series and patches/")
    p = sub.add_parser("render")
    for name in ("--manifest", "--tree", "--custom", "--fork", "--notes", "--docs"):
        p.add_argument(name, required=True)
    p.add_argument("--previous-manifest")
    p.add_argument("--note")
    p = sub.add_parser("set-digest")
    for name in ("--manifest", "--notes", "--digest"):
        p.add_argument(name, required=True)
    args = parser.parse_args()
    if args.command == "series":
        json.dump(series_json(Path(args.custom)), sys.stdout, indent=2)
        sys.stdout.write("\n")
    elif args.command == "render":
        render(args)
    else:
        set_digest(args)


if __name__ == "__main__":
    main()
