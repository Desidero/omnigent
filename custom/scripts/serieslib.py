#!/usr/bin/env python3
"""The patch series on disk, and the build that combines them.

  custom/BASE                              the upstream commit everything is cut from
  custom/patches/<series>/NOTE.md          what the series is; "Needs: <series>, ..."; its
                                           index text; what must hold, key code, tests
  custom/patches/<series>/NN-<slug>.patch  its patches, applied in file-name order
  custom/glue/<first>+<second>/NOTE.md     how two series fit together: "Joins: <paths>"
  custom/glue/<first>+<second>/NN-*.patch  optional patches on top of the two combined
  custom/parked/<series>/                  a series out of the build; its note says "Base: <commit>"
  custom/sets/<name>.txt                   named build sets, one series per line
  custom/index-intro.md                    the text above the sections of the built index

A series is cut from its foundation: BASE plus the series it needs, and
nothing else. A build first applies each chosen series exactly on its own
foundation (no three-way fallback, and every file must come out with the blob
the patch records), then combines the series by cherry-picking their commits
in a fixed order: a series after the ones it needs, then the second series of
a glue pair after the first, otherwise by name. The committer, the dates and
the merge settings are pinned, so the same BASE, patch files and choice of
series give the same commits everywhere. The last commit of a build is the
index, docs/custom/README.md, written from the notes of the series it holds.

Glue says how two series that do not need each other fit when both are in a
build. A join ("Joins: <path>, ...") is for insertions at the same spot of a
file: both are kept, the first-named series' lines first. A glue patch is for
edits of the same lines: it is cut on top of the two series combined and
applied after the second. Glue does nothing unless both series are built.

Every script that reads the series (build, export, check, test selection,
release notes, tracker) imports this module or runs it:

  serieslib.py files [--needs] <series>...       patch files, absolute, in build order
  serieslib.py files --only <series>[,...] | --set <name> | --all
  serieslib.py names (the same selection)         the chosen series instead
  serieslib.py lint                               the rules that need no build
  serieslib.py index [--only ... | --set N]        print the index a build would hold
  serieslib.py build [--repo R] [--only ... | --set N | --series S] [--no-index] [--reverse-ties]
                                                  build, print the tip commit
  serieslib.py verify [--repo R] [--pairs]        every series alone (and that the code and
                                                  tests its note names exist there), every glue
                                                  pair, then the whole build in both tie orders;
                                                  --pairs adds every two series that share a file
  serieslib.py export [--repo R] [--needs a,b] <series> <branch>
                                                  rewrite one series from its branch
  serieslib.py export [--repo R] --glue <first>+<second> <branch>
                                                  rewrite a glue pair's patches
  serieslib.py refresh [--repo R] [--from C]      move every series onto the BASE custom/BASE
                                                  names now; one line each: unchanged, refreshed,
                                                  landed, conflict, waits (exit 1 on the last two)
  serieslib.py park [--from C] <series>...        move series to custom/parked/, out of the build
  serieslib.py covers [--write] [<series>...]     the hash a note's "Covers:" line holds
  serieslib.py json [--names a,b]                 [{name, needs, patches: [{file, subject, patch_id}]}]

--needs also takes every series a chosen one needs, recursively. --only (which
may repeat) and --set do that too; each added series is named on stderr with
the reason.

Stdlib only; runs with any python >= 3.11 and git >= 2.40 (merge-tree --merge-base).
"""

from __future__ import annotations

import argparse
import email
import email.policy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

CUSTOM = Path(__file__).resolve().parent.parent  # custom/
INDEX_PATH = "docs/custom/README.md"
INDEX_SUBJECT = "docs: index the custom patch series"
NOTE_MAX_LINES = 60
# Paths that count as usage docs: upstream's user and agent docs, feature-map
# recipes, design docs (the telemetry variable table) and the server API reference.
DOC_PATHS_RE = re.compile(r"^(docs/|feature-map/|designs/|omnigent/server/API\.md$)")
SERIES_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
PATCH_NAME_RE = re.compile(r"^\d\d-[a-z0-9][a-z0-9-]*\.patch$")
SET_NAME_RE = re.compile(r"^[a-z][a-z0-9]{0,19}$")
NOTE_FIELD_RE = re.compile(r"^([A-Z][A-Za-z ]*):\s*(.*)$")
NOTE_SECTIONS = ("Must hold", "Key code", "Tests")


class SeriesError(Exception):
    """A problem with the series as written; the message is for the user."""


# ---------------------------------------------------------------- patch files


def slug(subject: str) -> str:
    """The file-name part of a patch, from its commit subject."""
    text = re.sub(r"^[a-z]+(\([^)]*\))?!?:\s*", "", subject.strip())
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(text) > 64:
        text = text[:64].rsplit("-", 1)[0]
    return text or "patch"


def patch_subject(path: Path) -> str:
    with path.open("rb") as handle:
        message = email.message_from_binary_file(handle, policy=email.policy.default)
    subject = str(message.get("Subject", "")).replace("\n", " ")
    return re.sub(r"^\[PATCH[^\]]*\]\s*", "", subject).strip()


def patch_message(path: Path) -> str:
    """The commit message body: after the mail headers, up to the diffstat separator."""
    lines, in_body = [], False
    for line in path.read_text(errors="replace").splitlines():
        if in_body and line == "---":
            break
        if in_body:
            lines.append(line)
        elif not line:
            in_body = True
    return "\n".join(lines)


def patch_id(path: Path) -> str:
    """git's stable patch id: the change, ignoring line numbers and blob ids."""
    result = subprocess.run(
        ["git", "patch-id", "--stable"], input=path.read_bytes(), capture_output=True, check=True
    )
    return result.stdout.decode().split(" ", 1)[0]


def touched_files(patch_text: str) -> list[str]:
    """Paths a patch touches, in the order it lists them."""
    files: list[str] = []
    for match in re.finditer(r"^diff --git a/(\S+) b/(\S+)$", patch_text, re.M):
        for path in match.groups():
            if path not in files:
                files.append(path)
    return files


def covers_hash(patches: list[Path]) -> str:
    """A hash of the lines a series adds and removes, per file, in apply order.

    Context lines, line numbers and blob ids are left out, so cutting the
    same change against another foundation keeps the hash and changing what
    the series does moves it.
    """
    digest = hashlib.sha256()
    for patch in patches:
        in_diff = False
        for raw in patch.read_bytes().split(b"\n"):
            if raw.startswith(b"diff --git "):
                in_diff = True
                digest.update(raw.split(b" b/", 1)[-1] + b"\n")
            elif not in_diff or raw.startswith((b"+++ ", b"--- ")):
                continue
            elif raw.startswith((b"+", b"-")) and raw != b"-- ":
                digest.update(raw + b"\n")
    return digest.hexdigest()[:16]


# ---------------------------------------------------------------- notes


@dataclass
class Note:
    """A series' NOTE.md: title, "Key: value" fields, the index text, the sections."""

    title: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    body: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    line_count: int = 0

    @property
    def needs(self) -> list[str]:
        value = self.fields.get("Needs", "")
        return [] if value.strip().lower() in ("", "none") else [name.strip() for name in value.split(",")]


def parse_note(text: str) -> Note:
    lines = text.splitlines()
    note = Note(line_count=len(lines))
    index = 0
    if lines and lines[0].startswith("# "):
        note.title = lines[0][2:].strip()
        index = 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    while index < len(lines) and (match := NOTE_FIELD_RE.match(lines[index])):
        note.fields[match.group(1)] = match.group(2).strip()
        index += 1
    body: list[str] = []
    current = None
    for line in lines[index:]:
        if line.startswith("## "):
            current = line[3:].strip()
            note.sections[current] = ""
        elif current is None:
            body.append(line)
        else:
            note.sections[current] += line + "\n"
    note.body = "\n".join(body).strip("\n")
    note.sections = {name: text.strip("\n") for name, text in note.sections.items()}
    return note


def render_note(name: str, needs: list[str], covers: str, body: str, sections: dict[str, str]) -> str:
    out = [f"# {name}", "", f"Needs: {', '.join(needs) if needs else 'none'}", f"Covers: {covers}", "", body.strip("\n")]
    for title in NOTE_SECTIONS:
        out += ["", f"## {title}", "", sections.get(title, "").strip("\n")]
    return "\n".join(out).rstrip("\n") + "\n"


# ---------------------------------------------------------------- the catalog


@dataclass
class Series:
    name: str
    path: Path
    patches: list[Path]
    note: Note | None

    @property
    def needs(self) -> list[str]:
        return self.note.needs if self.note else []


@dataclass
class Glue:
    """How two series fit together: custom/glue/<first>+<second>/."""

    name: str
    first: str
    second: str
    path: Path
    patches: list[Path]
    note: Note | None

    @property
    def joins(self) -> list[str]:
        value = self.note.fields.get("Joins", "") if self.note else ""
        return [path for path in re.split(r"[,\s]+", value.strip()) if path]


class Catalog:
    """The series under one custom/ folder."""

    def __init__(self, custom: Path = CUSTOM):
        self.custom = Path(custom)
        self.patches_dir = self.custom / "patches"
        self.series: dict[str, Series] = {}
        if self.patches_dir.is_dir():
            for path in sorted(self.patches_dir.iterdir()):
                if not path.is_dir():
                    continue
                note_path = path / "NOTE.md"
                note = parse_note(note_path.read_text()) if note_path.is_file() else None
                self.series[path.name] = Series(path.name, path, sorted(path.glob("*.patch")), note)
        self.glue: dict[str, Glue] = {}
        self.glue_dir = self.custom / "glue"
        if self.glue_dir.is_dir():
            for path in sorted(self.glue_dir.iterdir()):
                if not path.is_dir():
                    continue
                first, _, second = path.name.partition("+")
                note_path = path / "NOTE.md"
                note = parse_note(note_path.read_text()) if note_path.is_file() else None
                self.glue[path.name] = Glue(path.name, first, second, path, sorted(path.glob("*.patch")), note)
        self.order = self.build_order(list(self.series), strict=False)

    def build_order(self, names: list[str], *, reverse_ties: bool = False, strict: bool = True) -> list[str]:
        """The order a build combines these series in.

        A series comes after the series it needs, and the second series of a
        glue pair after the first; among the series that are ready, the one
        whose name sorts first goes first (last, with reverse_ties: the other
        order check.sh compares with). `names` must hold the needs of its
        members.
        """
        chosen = set(names)
        waiting = {
            name: {need for need in self.series[name].needs if need in chosen and need != name}
            for name in chosen
        }
        for glue in self.glue.values():
            if glue.first in waiting and glue.second in waiting and glue.first != glue.second:
                waiting[glue.second].add(glue.first)
        order: list[str] = []
        while waiting:
            ready = sorted((name for name, needs in waiting.items() if not needs), reverse=reverse_ties)
            if not ready:
                if strict:
                    raise SeriesError(
                        "the series need (or are glued after) each other in a circle: " + ", ".join(sorted(waiting))
                    )
                ready = sorted(waiting)
            order.append(ready[0])
            del waiting[ready[0]]
            for needs in waiting.values():
                needs.discard(ready[0])
        return order

    def get(self, name: str) -> Series:
        if name not in self.series:
            raise SeriesError(f"no series named {name}")
        return self.series[name]

    def base(self) -> str:
        return (self.custom / "BASE").read_text().strip()

    # -- selection

    def closure(self, names: list[str], why: dict[str, str] | None = None) -> set[str]:
        """The named series and every series they need, recursively."""
        taken: set[str] = set()
        queue = list(names)
        while queue:
            name = queue.pop(0)
            if name in taken:
                continue
            taken.add(name)
            for need in self.get(name).needs:
                if need not in self.series:
                    raise SeriesError(f"{name} needs unknown series {need}")
                if need not in taken and need not in queue:
                    if why is not None and need not in names:
                        why.setdefault(need, f"needed by {name}")
                    queue.append(need)
        return taken

    def select(
        self, names: list[str], *, needs: bool = False, everything: bool = False
    ) -> tuple[list[str], dict[str, str]]:
        """The chosen series in build order, and why each unnamed one was added."""
        why: dict[str, str] = {}
        if everything:
            return self.build_order(list(self.series)), why
        for name in names:
            self.get(name)
        taken = set(names)
        if needs:
            taken = self.closure([name for name in self.order if name in taken], why)
        return self.build_order(list(taken)), why

    def set_members(self, set_name: str) -> list[str]:
        """The series a set file lists (not yet with the ones they need)."""
        if not SET_NAME_RE.match(set_name) or set_name == "dirty":
            raise SeriesError(
                f"'{set_name}' is not a set name (lowercase letters and digits, starting with a letter, "
                "at most 20, not 'dirty')"
            )
        path = self.custom / "sets" / f"{set_name}.txt"
        if not path.is_file():
            raise SeriesError(f"no set named {set_name} (custom/sets/{set_name}.txt)")
        members = [word for raw in path.read_text().splitlines() for word in raw.split("#", 1)[0].split()]
        if not members:
            raise SeriesError(f"set {set_name} lists no series")
        return members

    def set_names(self) -> list[str]:
        return sorted(path.stem for path in (self.custom / "sets").glob("*.txt"))

    def files(self, names: list[str]) -> list[Path]:
        return [patch for name in names for patch in self.get(name).patches]

    def active_glue(self, names: list[str] | set[str]) -> list[Glue]:
        """The glue pairs with both series among these."""
        return [glue for glue in self.glue.values() if glue.first in names and glue.second in names]

    def as_json(self, only: set[str] | None = None) -> list[dict]:
        """The series with their patch ids, then the glue between them.

        `only` keeps the named series (a build set) and the glue among them.
        A glue entry has "glue": true and its "joins".
        """

        def described(folder: str, patches: list[Path]) -> list[dict]:
            return [
                {"file": f"{folder}/{patch.name}", "subject": patch_subject(patch), "patch_id": patch_id(patch)}
                for patch in patches
            ]

        names = [name for name in self.order if only is None or name in only]
        out: list[dict] = [
            {"name": name, "needs": self.series[name].needs, "patches": described(name, self.series[name].patches)}
            for name in names
        ]
        for glue in self.active_glue(names):
            out.append(
                {
                    "name": glue.name,
                    "glue": True,
                    "needs": [glue.first, glue.second],
                    "joins": glue.joins,
                    "patches": described(glue.name, glue.patches),
                }
            )
        return out

    # -- rules

    def lint(self) -> list[str]:
        """Problems with the series as written (nothing is applied)."""
        problems: list[str] = []
        if self.patches_dir.is_dir():
            for path in sorted(self.patches_dir.iterdir()):
                if not path.is_dir():
                    problems.append(f"custom/patches/{path.name} is not in a series directory")
        for name, entry in self.series.items():
            where = f"custom/patches/{name}"
            if not SERIES_NAME_RE.match(name):
                problems.append(f"{where}: a series name is lowercase letters, digits and '-'")
            if not entry.patches:
                problems.append(f"series {name} has no patches")
            for path in sorted(entry.path.iterdir()):
                if path.name != "NOTE.md" and not PATCH_NAME_RE.match(path.name):
                    problems.append(f"{where}/{path.name} is neither NOTE.md nor NN-<slug>.patch")
            if entry.note is None:
                problems.append(f"series {name} has no NOTE.md")
                continue
            if entry.note.title != name:
                problems.append(f"{where}/NOTE.md must start with '# {name}'")
            if "Needs" not in entry.note.fields:
                problems.append(f"{where}/NOTE.md has no 'Needs:' line (write 'Needs: none')")
            for need in entry.needs:
                if need not in self.series:
                    problems.append(f"series {name} needs {need}, which does not exist")
            for patch in entry.patches:
                problems += self._docs_rule(f"{name}/{patch.name}", patch)
            problems += self.note_problems(name)
        problems += self._glue_problems()
        problems += self._parked_problems()
        problems += self._order_problems()
        for set_name in self.set_names():
            try:
                self.select(self.set_members(set_name), needs=True)
            except SeriesError as error:
                problems.append(f"set {set_name}: {error}")
        return problems

    def _docs_rule(self, label: str, patch: Path) -> list[str]:
        text = patch.read_text(errors="replace")
        if any(DOC_PATHS_RE.match(path) for path in touched_files(text)):
            return []
        trailers = subprocess.run(
            ["git", "interpret-trailers", "--parse"],
            input="subject\n\n" + patch_message(patch),  # a body of trailers only is still trailers
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        if re.search(r"^Docs: none \(", trailers, re.M):
            return []
        return [f"{label} has no usage docs and no 'Docs: none (<reason>)' trailer"]

    def _glue_problems(self) -> list[str]:
        problems = []
        if self.glue_dir.is_dir():
            for path in sorted(self.glue_dir.iterdir()):
                if not path.is_dir():
                    problems.append(f"custom/glue/{path.name} is not in a glue directory")
        for name, glue in self.glue.items():
            where = f"custom/glue/{name}"
            missing = [side for side in (glue.first, glue.second) if side not in self.series]
            if not glue.second or missing:
                problems.append(f"{where}: name it <first>+<second> after two series ({', '.join(missing) or name}?)")
                continue
            if glue.first == glue.second:
                problems.append(f"{where}: a series cannot be glued to itself")
                continue
            for side, other in ((glue.first, glue.second), (glue.second, glue.first)):
                if all(need in self.series for need in self.series[side].needs) and other in self.closure([side]):
                    problems.append(f"{where}: {side} needs {other}, so it is already cut on top of it; drop the glue")
            if f"{glue.second}+{glue.first}" in self.glue:
                problems.append(f"{where}: {glue.second}+{glue.first} exists too; keep one directory per pair")
            for path in sorted(glue.path.iterdir()):
                if path.name != "NOTE.md" and not PATCH_NAME_RE.match(path.name):
                    problems.append(f"{where}/{path.name} is neither NOTE.md nor NN-<slug>.patch")
            if glue.note is None:
                problems.append(f"{where} has no NOTE.md")
                continue
            if glue.note.title != name:
                problems.append(f"{where}/NOTE.md must start with '# {name}'")
            if not glue.joins and not glue.patches:
                problems.append(f"{where} has neither a 'Joins:' line nor a patch")
            if not glue.note.body.strip():
                problems.append(f"{where}/NOTE.md does not say why the two series meet")
            for patch in glue.patches:
                problems += self._docs_rule(f"glue {name}/{patch.name}", patch)
        return problems

    def _parked_problems(self) -> list[str]:
        """custom/parked/<series>/: a series out of the build, with the BASE its patches are cut from."""
        problems = []
        parked = self.custom / "parked"
        for path in sorted(parked.iterdir()) if parked.is_dir() else []:
            where = f"custom/parked/{path.name}"
            if not path.is_dir():
                problems.append(f"{where} is not in a series directory")
                continue
            if path.name in self.series:
                problems.append(f"{where}: {path.name} is also under custom/patches/; keep one")
            note = parse_note((path / "NOTE.md").read_text()) if (path / "NOTE.md").is_file() else None
            if note is None or not re.fullmatch(r"[0-9a-f]{40}", note.fields.get("Base", "")):
                problems.append(f"{where}/NOTE.md needs a 'Base: <commit>' line: the BASE its patches are cut from")
            if not list(path.glob("*.patch")):
                problems.append(f"{where} has no patches")
        return problems

    def _order_problems(self) -> list[str]:
        problems = []
        if (self.custom / "series").exists():
            problems.append("custom/series is not used any more: the order comes from the 'Needs:' lines; delete it")
        if all(need in self.series for entry in self.series.values() for need in entry.needs):
            try:
                self.build_order(list(self.series))
            except SeriesError as error:
                problems.append(str(error))
        if not (self.custom / "index-intro.md").is_file():
            problems.append("custom/index-intro.md is missing: the text above the sections of the built index")
        return problems

    # -- notes and the index

    def note_problems(self, name: str) -> list[str]:
        """What a series' NOTE.md lacks, without building anything."""
        entry = self.series[name]
        where = f"custom/patches/{name}/NOTE.md"
        note = entry.note
        if note is None:
            return []
        problems = []
        if note.line_count > NOTE_MAX_LINES:
            problems.append(f"{where} has {note.line_count} lines; keep it to {NOTE_MAX_LINES}")
        covers = covers_hash(entry.patches)
        if note.fields.get("Covers") != covers:
            problems.append(
                f"{where}: the lines {name} changes moved since the note was written (Covers: "
                f"{note.fields.get('Covers', 'missing')}, now {covers}); review the note, then serieslib.py covers --write {name}"
            )
        body = note.body.strip()
        if not body or body.startswith("TODO(owner)"):
            problems.append(f"{where} does not say what the series changes")
        for label in ("Turn on", "Upstream"):
            if f"**{label}:**" not in body:
                problems.append(f"{where} has no '- **{label}:**' line")
        if re.search(r"(?<![\w/])#\d+", re.sub(r"`[^`]*`|\[[^\]]*\]\([^)]*\)", "", body)):
            problems.append(f"{where}: write issues and pull requests as full links, [#123](https://...)")
        for title in NOTE_SECTIONS:
            bullets = [line for line in note.sections.get(title, "").splitlines() if line.startswith("- ")]
            if not bullets or all(line.strip() == "- TODO(owner)" for line in bullets):
                problems.append(f"{where} has nothing under '## {title}'")
        if any(path == INDEX_PATH for patch in entry.patches for path in touched_files(patch.read_text(errors="replace"))):
            problems.append(f"series {name} changes {INDEX_PATH}, which the build writes from the notes")
        return problems

    def note_claims(self, name: str, section: str) -> list[tuple[str, list[str]]]:
        """(path, [names]) per bullet of 'Key code' or 'Tests': the code spans a line holds.

        Key code: `path`: `symbol`, `symbol`. Tests: `path` or `path::test_name`.
        A bullet that starts with "none" or "TODO(owner)" claims nothing.
        """
        note = self.series[name].note
        claims = []
        for line in (note.sections.get(section, "") if note else "").splitlines():
            if not line.startswith("- ") or re.match(r"^- (none\b|TODO\(owner\))", line):
                continue
            spans = re.findall(r"`([^`]+)`", line)
            if not spans:
                claims.append(("", []))
            elif section == "Tests":
                path, _, test = spans[0].partition("::")
                claims.append((path, [test] if test else []))
            else:
                claims.append((spans[0], spans[1:]))
        return claims

    def index_text(self, names: list[str]) -> str:
        """docs/custom/README.md for a build of these series: the intro, then a section each, by name."""
        intro_path = self.custom / "index-intro.md"
        parts = [intro_path.read_text().strip("\n") if intro_path.is_file() else "# The custom patch series"]
        for name in sorted(names):
            note = self.series[name].note
            parts.append(f"## {name}\n\n{note.body.strip() if note else ''}".rstrip())
        return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------- the build

# Settings that could change how a patch applies, how a merge resolves or what
# an exported patch looks like; pinned so that a build depends on BASE, the
# patch files and the git version only.
PINNED_CONFIG = (
    "commit.gpgSign=false",
    "core.autocrlf=false",
    "i18n.commitEncoding=UTF-8",
    "mailinfo.scissors=false",
    "apply.whitespace=nowarn",
    "apply.ignoreWhitespace=no",
    "merge.renames=true",
    "merge.directoryRenames=false",
    "merge.renameLimit=7000",
    "merge.conflictStyle=diff3",  # whole conflict hunks with their base: what a join reads
    "rerere.enabled=false",
    "diff.algorithm=myers",
    "diff.renames=true",
    "diff.noprefix=false",
    "diff.mnemonicPrefix=false",
    "diff.context=3",
    "diff.interHunkContext=0",
)
FORMAT_PATCH = (
    "format-patch", "-1", "--stdout", "--zero-commit", "--no-signature", "--no-numbered",
    "--full-index", "--no-color", "--encode-email-headers",
)  # fmt: skip
ZERO_ID_RE = re.compile(r"^0+$")
# Variables that would point git at another repository or index, or change who commits.
REDIRECTING_ENV = frozenset(
    ["GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE",
     "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_PREFIX", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
     "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE"]
)  # fmt: skip


class BuildError(SeriesError):
    """A series that does not apply on its foundation, or does not combine."""


def post_images(diff_text: str) -> dict[str, str]:
    """Per path a diff touches, the blob id it records for the result ('' when deleted)."""
    out: dict[str, str] = {}
    current = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            rest = line[len("diff --git ") :]
            path = rest[2 : 2 + (len(rest) - 5) // 2]
            current = path if rest == f"a/{path} b/{path}" else None
        elif line.startswith(("rename to ", "copy to ")):
            current = line.split(" to ", 1)[1]
        elif current and (match := re.match(r"^index [0-9a-f]+\.\.([0-9a-f]{40,})( \d+)?$", line)):
            out[current] = "" if ZERO_ID_RE.match(match.group(1)) else match.group(1)
    return out


@dataclass
class Built:
    tip: str
    order: list[str]
    commits: int


@dataclass
class Transplant:
    """Commits moved onto another foundation: what arrived, what was empty there, what stopped it."""

    picked: list[str] = field(default_factory=list)
    landed: list[str] = field(default_factory=list)
    conflict: str = ""
    paths: list[str] = field(default_factory=list)


class Engine:
    """Builds series in one clone, with git plumbing only: no worktree is touched."""

    def __init__(self, catalog: Catalog, repo: Path):
        self.catalog = catalog
        self.repo = Path(repo)
        self.base = catalog.base()
        self._tmp = tempfile.TemporaryDirectory(prefix="serieslib-")
        self.tmp = Path(self._tmp.name)
        self.env = {
            **{key: value for key, value in os.environ.items() if key not in REDIRECTING_ENV},
            "GIT_COMMITTER_NAME": os.environ.get("CUSTOM_COMMITTER_NAME", "github-actions[bot]"),
            "GIT_COMMITTER_EMAIL": os.environ.get(
                "CUSTOM_COMMITTER_EMAIL", "41898282+github-actions[bot]@users.noreply.github.com"
            ),
            # Attributes (merge drivers, binary files) as BASE has them, whatever is checked out.
            "GIT_ATTR_SOURCE": self.base,
        }
        self._commits: dict[str, list[str]] = {}
        self._glue_commits: dict[str, list[str]] = {}
        self._combined: dict[tuple, str] = {}
        self._touched: dict[str, set[str]] = {}
        # (glue pair, path) of every join a build had to make.
        self.joins_used: set[tuple[str, str]] = set()
        if self.run("cat-file", "-e", f"{self.base}^{{commit}}", check=False).returncode != 0:
            raise BuildError(f"BASE {self.base[:12]} is not in {self.repo}; fetch upstream")

    def run(self, *args: str, data: bytes | None = None, env: dict | None = None, index: bool = False,
            check: bool = True) -> subprocess.CompletedProcess:  # fmt: skip
        command = ["git", "-C", str(self.repo)]
        for setting in PINNED_CONFIG:
            command += ["-c", setting]
        full_env = {**self.env, **(env or {})}
        if index:
            full_env["GIT_INDEX_FILE"] = str(self.tmp / "index")
        result = subprocess.run([*command, *args], input=data, env=full_env, capture_output=True)
        if check and result.returncode != 0:
            raise BuildError(f"git {' '.join(args[:2])} failed: {result.stderr.decode(errors='replace').strip()}")
        return result

    def git(self, *args: str, **kwargs) -> str:
        return self.run(*args, **kwargs).stdout.decode(errors="replace").strip()

    # -- one series on its foundation

    def foundation_of(self, needs: list[str]) -> str:
        """BASE plus these series and the ones they need, combined."""
        return self.combine(self.catalog.build_order(sorted(self.catalog.closure(needs))))

    def foundation(self, name: str) -> str:
        return self.foundation_of(self.catalog.get(name).needs)

    def series_commits(self, name: str) -> list[str]:
        """The series' patches as commits on its foundation, applied exactly."""
        if name not in self._commits:
            parent = self.foundation(name)
            commits = []
            for patch in self.catalog.get(name).patches:
                parent = self._apply(parent, patch, f"{name}/{patch.name}")
                commits.append(parent)
            self._commits[name] = commits
        return self._commits[name]

    def glue_foundation(self, glue: Glue) -> str:
        """The two series (and what they need) combined, joins made, without the pair's own patches."""
        order = self.catalog.build_order(sorted(self.catalog.closure([glue.first, glue.second])))
        return self.combine(order, without=glue.name)

    def glue_commits(self, glue: Glue) -> list[str]:
        """A glue pair's patches as commits on the two series combined, applied exactly."""
        if glue.name not in self._glue_commits:
            parent = self.glue_foundation(glue)
            commits = []
            for patch in glue.patches:
                parent = self._apply(parent, patch, f"glue {glue.name}/{patch.name}")
                commits.append(parent)
            self._glue_commits[glue.name] = commits
        return self._glue_commits[glue.name]

    def _apply(self, parent: str, patch: Path, label: str) -> str:
        message_file, diff_file = self.tmp / "message", self.tmp / "diff"
        info = self.run("mailinfo", str(message_file), str(diff_file), data=patch.read_bytes()).stdout.decode()
        fields = dict(line.split(": ", 1) for line in info.splitlines() if ": " in line)
        if not {"Author", "Email", "Subject", "Date"} <= set(fields):
            raise BuildError(f"{label} is not a git format-patch file")
        self.run("read-tree", parent, index=True)
        applied = self.run("apply", "--cached", str(diff_file), index=True, check=False)
        if applied.returncode != 0:
            detail = applied.stderr.decode(errors="replace").strip().splitlines()
            raise BuildError(
                f"{label} does not apply on its foundation {parent[:12]}: " + "; ".join(detail[:4])
            )
        tree = self.git("write-tree", index=True)
        expected = post_images(diff_file.read_text(errors="replace"))
        if expected:
            listed = self.run("ls-tree", "-r", "-z", tree, "--", *expected).stdout.decode()
            actual = {
                entry.split("\t", 1)[1]: entry.split("\t", 1)[0].split()[2] for entry in listed.split("\0") if entry
            }
            for path, blob in expected.items():
                if actual.get(path, "") != blob:
                    raise BuildError(
                        f"{label} is not cut from its foundation {parent[:12]} ({path} comes out different); "
                        "re-export the series"
                    )
        message = self.run(
            "stripspace", data=fields["Subject"].encode() + b"\n\n" + message_file.read_bytes()
        ).stdout
        return self._commit(tree, parent, fields["Author"], fields["Email"], fields["Date"], message)

    def _commit(self, tree: str, parent: str, name: str, email: str, date: str, message: bytes) -> str:
        env = {
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_AUTHOR_DATE": date,
            "GIT_COMMITTER_DATE": date,
        }
        return self.git("commit-tree", tree, "-p", parent, data=message, env=env)

    # -- combining

    def combine(self, order: list[str], without: str | None = None) -> str:
        """Cherry-pick each series' commits, in this order, onto BASE.

        After a series that completes a glue pair come the pair's patches
        (`without` leaves one pair's patches out: the foundation they are cut from).
        """
        done = len(order)
        while done and (tuple(order[:done]), without) not in self._combined:
            done -= 1
        tip = self._combined[(tuple(order[:done]), without)] if done else self.base
        for position in range(done, len(order)):
            name, applied = order[position], order[:position]
            pairs = [glue for glue in self.catalog.glue.values() if glue.second == name and glue.first in applied]
            joins = {path: glue.name for glue in pairs for path in glue.joins}
            for commit in self.series_commits(name):
                tip = self._pick(tip, commit, name, applied, joins)
            for glue in pairs:
                if glue.name != without:
                    for commit in self.glue_commits(glue):
                        tip = self._pick(tip, commit, f"glue {glue.name}", [*applied, name], {})
            self._combined[(tuple(order[: position + 1]), without)] = tip
        return tip

    def _pick(self, tip: str, commit: str, name: str, applied: list[str], joins: dict[str, str]) -> str:
        parent = self.git("rev-parse", f"{commit}^")
        if parent == tip:
            return commit  # the pick would write this very commit
        merged = self.run("merge-tree", "--write-tree", "-z", f"--merge-base={parent}", tip, commit, check=False)
        fields = merged.stdout.decode(errors="replace").split("\0")
        tree = fields[0]
        if merged.returncode == 1:
            stages: dict[str, dict[str, str]] = {}
            for entry in fields[1:]:
                if not entry:
                    break
                meta, path = entry.split("\t", 1)
                mode, _, stage = meta.split()
                stages.setdefault(path, {})[stage] = mode
            # A declared join keeps both sides of same-spot insertions; anything else stops the build.
            joined = {
                path: self._join(tree, path, tip, commit) for path in stages if path in joins and len(stages[path]) == 3
            }
            if len(joined) != len(stages) or None in joined.values():
                left = [path for path in stages if joined.get(path) is None]
                raise BuildError(self._conflict_message(commit, name, applied, left, joins))
            self.run("read-tree", tree, index=True)
            for path, blob in joined.items():
                self.run("update-index", "--cacheinfo", f"{stages[path]['2']},{blob},{path}", index=True)
                self.joins_used.add((joins[path], path))
            tree = self.git("write-tree", index=True)
        elif merged.returncode != 0:
            raise BuildError(f"merging {name} failed: {merged.stderr.decode(errors='replace').strip()}")
        return self._commit_like(commit, tree, tip)

    def _join(self, tree: str, path: str, ours: str, theirs: str) -> str | None:
        """A merged file with each conflict replaced by both sides, ours first.

        Only insertions at the same spot join: a conflict whose base has lines
        (both sides edited them) returns None, as does a file the markers
        cannot be read from.
        """
        text = self.run("cat-file", "blob", f"{tree}:{path}").stdout
        out: list[bytes] = []
        side = None
        for line in text.splitlines(keepends=True):
            bare = line.rstrip(b"\r\n")
            if side is None and bare == b"<<<<<<< " + ours.encode():
                side = "ours"
            elif side == "ours" and bare.startswith(b"||||||| "):
                side = "base"
            elif side == "base" and bare == b"=======":
                side = "theirs"
            elif side == "theirs" and bare == b">>>>>>> " + theirs.encode():
                side = None
            elif side == "base":
                return None
            else:
                out.append(line)
        if side is not None:
            return None
        return self.git("hash-object", "-w", "--stdin", data=b"".join(out))

    def transplant(self, label: str, start: str, commits: list[str]) -> Transplant:
        """Cherry-pick commits made elsewhere onto `start`, stopping at the first conflict.

        A commit that changes nothing there (upstream has it) is left out and
        its subject kept in `landed`.
        """
        moved = Transplant()
        tip = start
        for commit in commits:
            try:
                new = self._pick(tip, commit, label, [], {})
            except BuildError as error:
                moved.conflict = str(error)
                moved.paths = [line.strip().split(" (")[0] for line in str(error).splitlines()[1:-1]]
                return moved
            if self.tree(new) == self.tree(tip):
                moved.landed.append(self.git("log", "-1", "--format=%s", commit))
                continue
            moved.picked.append(new)
            tip = new
        return moved

    def _commit_like(self, commit: str, tree: str, parent: str) -> str:
        """A commit with another commit's author, date and message."""
        raw = self.run("cat-file", "commit", commit).stdout
        head, _, message = raw.partition(b"\n\n")
        author = next(line for line in head.decode().splitlines() if line.startswith("author "))
        match = re.match(r"^author (.*) <(.*)> (\d+ [+-]\d{4})$", author)
        if not match:
            raise BuildError(f"cannot read the author of {commit[:12]}")
        return self._commit(tree, parent, match.group(1), match.group(2), match.group(3), message)

    def touched(self, name: str) -> set[str]:
        if name not in self._touched:
            self._touched[name] = {
                path
                for patch in self.catalog.get(name).patches
                for path in touched_files(patch.read_text(errors="replace"))
            }
        return self._touched[name]

    def _conflict_message(self, commit: str, name: str, applied: list[str], paths: list[str],
                          joins: dict[str, str]) -> str:  # fmt: skip
        subject = self.git("log", "-1", "--format=%s", commit)
        inside = self.catalog.closure([name]) if name in self.catalog.series else set()
        lines = [f"{name} ('{subject}') does not combine with the series before it:"]
        for path in paths:
            others = [other for other in applied if other not in inside and path in self.touched(other)]
            note = f" (also changed by {', '.join(others)})" if others else ""
            if path in joins:
                note += f" (glue {joins[path]} joins insertions at the same spot; here both series edit the same lines)"
            lines.append(f"  {path}{note}")
        lines.append(
            "Insertions at the same spot: declare a join in custom/glue/<first>+<second>/NOTE.md. "
            "Edits of the same lines: a real 'Needs:', or change one series to leave those lines alone."
        )
        return "\n".join(lines)

    # -- whole builds

    def build(self, names: list[str], *, reverse_ties: bool = False, index: bool = True) -> Built:
        """Combine the named series (with their needs already among them), then index them."""
        order = self.catalog.build_order(names, reverse_ties=reverse_ties)
        tip = self.combine(order)
        if index and order:
            tip = self._index_commit(tip, order)
        return Built(tip, order, int(self.git("rev-list", "--count", f"{self.base}..{tip}")))

    def _index_commit(self, tip: str, names: list[str]) -> str:
        """The build's last commit: docs/custom/README.md from the notes of the series built."""
        blob = self.git("hash-object", "-w", "--stdin", data=self.catalog.index_text(names).encode())
        self.run("read-tree", tip, index=True)
        self.run("update-index", "--add", "--cacheinfo", f"100644,{blob},{INDEX_PATH}", index=True)
        message = (
            f"{INDEX_SUBJECT}\n\nWritten by the build from the NOTE.md of each of the {len(names)} series it holds: "
            "what each changes, how to turn it on and where its docs are.\n"
        )
        # Dated like the commit it follows, so the same build is the same commit.
        date = self.git("log", "-1", "--format=%ad", "--date=raw", tip)
        return self._commit(
            self.git("write-tree", index=True), tip, self.env["GIT_COMMITTER_NAME"],
            self.env["GIT_COMMITTER_EMAIL"], date, message.encode(),
        )  # fmt: skip

    def tree(self, commit: str) -> str:
        return self.git("rev-parse", f"{commit}^{{tree}}")

    def verify(self, pairs: bool = False) -> list[str]:
        """Every series alone on its foundation, every glue pair, the whole build in both tie orders.

        With `pairs`, also every two series that touch a common file and do
        not need each other: they must combine, cleanly or through their glue.
        """
        problems: list[str] = []
        for name in self.catalog.order:
            try:
                self.series_commits(name)
            except BuildError as error:
                problems.append(str(error))
        if problems:
            return problems
        for name in self.catalog.order:
            problems += self._verify_note(name)
        problems += self._verify_glue()
        if pairs:
            problems += self._verify_pairs()
        if problems:
            return problems
        try:
            everything = list(self.catalog.series)
            first = self.build(everything)
            second = self.build(everything, reverse_ties=True)
            if self.tree(first.tip) != self.tree(second.tip):
                changed = self.git("diff", "--stat", first.tip, second.tip).splitlines()
                problems.append(
                    "the build depends on the order of series that do not need each other; "
                    "by name it differs from by name reversed in:\n  " + "\n  ".join(changed)
                )
        except BuildError as error:
            problems.append(str(error))
        return problems


    def _verify_note(self, name: str) -> list[str]:
        """The code and tests a note names must exist in the series' own build."""
        where = f"custom/patches/{name}/NOTE.md"
        tip = self.series_commits(name)[-1]
        problems = []
        for section in ("Key code", "Tests"):
            for path, names in self.catalog.note_claims(name, section):
                if not path:
                    problems.append(f"{where}: a '## {section}' line names no `path`")
                    continue
                shown = self.run("cat-file", "blob", f"{tip}:{path}", check=False)
                if shown.returncode != 0:
                    problems.append(f"{where}: {path} ({section}) is not in the series' build")
                    continue
                if section == "Key code" and path not in self.touched(name):
                    problems.append(f"{where}: {path} (Key code) is not a file the series changes")
                text = shown.stdout.decode(errors="replace")
                for symbol in names:
                    if not re.search(rf"(?<![\w$]){re.escape(symbol)}(?![\w$])", text):
                        problems.append(f"{where}: {symbol} is not in {path} in the series' build")
        return problems

    def _verify_glue(self) -> list[str]:
        """Each glue pair on its own: its patches apply exactly, and every join is made."""
        problems = []
        for glue in self.catalog.glue.values():
            saved = self._combined, self.joins_used
            self._combined, self.joins_used = {}, set()
            try:
                self.build(sorted(self.catalog.closure([glue.first, glue.second])), index=False)
                for path in glue.joins:
                    if (glue.name, path) not in self.joins_used:
                        problems.append(
                            f"glue {glue.name} joins {path}, but {glue.first} and {glue.second} combine there "
                            "without it; drop the path"
                        )
            except BuildError as error:
                problems.append(f"glue {glue.name}: {error}")
            finally:
                self._combined, self.joins_used = saved
        return problems


    def _verify_pairs(self) -> list[str]:
        problems = []
        names = self.catalog.order
        for position, first in enumerate(names):
            for second in names[position + 1 :]:
                if first in self.catalog.closure([second]) or second in self.catalog.closure([first]):
                    continue
                if not self.touched(first) & self.touched(second):
                    continue
                try:
                    self.build(sorted(self.catalog.closure([first, second])), index=False)
                except BuildError as error:
                    problems.append(f"{first} and {second} do not build together: {error}")
        return problems


# ---------------------------------------------------------------- export


def write_patches(engine: Engine, folder: Path, label: str, commits: list[str]) -> list[str]:
    """Write commits as NN-<slug>.patch files in a directory, removing the ones that are gone."""
    folder.mkdir(parents=True, exist_ok=True)
    notes, wanted = [], {}
    for number, commit in enumerate(commits, 1):
        subject = engine.git("log", "-1", "--format=%s", commit)
        if any(file.split("-", 1)[1] == f"{slug(subject)}.patch" for file in wanted):
            raise SeriesError(f"two commits of {label} map to {slug(subject)}; reword one subject")
        wanted[f"{number:02d}-{slug(subject)}.patch"] = engine.run(*FORMAT_PATCH, commit).stdout
    for old in sorted(folder.glob("*.patch")):
        if old.name not in wanted:
            old.unlink()
            notes.append(f"removed: {label}/{old.name}")
    for file, content in wanted.items():
        if not (folder / file).is_file() or (folder / file).read_bytes() != content:
            (folder / file).write_bytes(content)
            notes.append(f"wrote: {label}/{file}")
    return notes


def write_series(engine: Engine, name: str, commits: list[str], needs: list[str]) -> list[str]:
    """Write a series' directory from commits on its foundation; returns what changed."""
    folder = engine.catalog.patches_dir / name
    notes = write_patches(engine, folder, name, commits)
    note_path = folder / "NOTE.md"
    needs_line = f"Needs: {', '.join(needs) if needs else 'none'}"
    if not note_path.is_file():
        todo = "- TODO(owner)"
        body = "TODO(owner): what the series changes, how to turn it on, its docs, its upstream links."
        note_path.write_text(render_note(name, needs, "-", body, dict.fromkeys(NOTE_SECTIONS, todo)))
        notes.append(f"new series: fill in custom/patches/{name}/NOTE.md")
    else:
        text = note_path.read_text()
        if not re.search(rf"^{re.escape(needs_line)}$", text, re.M):
            if re.search(r"^Needs:.*$", text, re.M):
                text = re.sub(r"^Needs:.*$", needs_line, text, count=1, flags=re.M)
            else:
                text = re.sub(r"\A(# .*\n\n?)", rf"\g<1>{needs_line}\n", text, count=1)
            note_path.write_text(text)
            notes.append(f"wrote: {name}/NOTE.md ({needs_line})")
    return notes


def branch_commits(engine: Engine, foundation: str, branch: str, what: str, hint: str) -> list[str]:
    """The commits a branch holds on top of a foundation it must be built on."""
    tip = engine.git("rev-parse", "--verify", f"{branch}^{{commit}}")
    if engine.run("merge-base", "--is-ancestor", foundation, tip, check=False).returncode != 0:
        raise SeriesError(f"{branch} is not built on the foundation of {what} ({foundation[:12]}); {hint}")
    if engine.git("rev-list", "--merges", f"{foundation}..{tip}"):
        raise SeriesError(f"{foundation[:12]}..{branch} contains merge commits; rebase it instead")
    return engine.git("rev-list", "--reverse", f"{foundation}..{tip}").split()


def export_glue(custom: Path, repo: Path, name: str, branch: str) -> list[str]:
    """Rewrite the patches of custom/glue/<first>+<second>/ from a branch on the two series combined."""
    catalog = Catalog(custom)
    engine = Engine(catalog, repo)
    first, _, second = name.partition("+")
    if not second or first not in catalog.series or second not in catalog.series:
        raise SeriesError(f"'{name}' is not <first>+<second> of two series")
    folder = catalog.glue_dir / name
    glue = catalog.glue.get(name) or Glue(name, first, second, folder, [], None)
    commits = branch_commits(
        engine, engine.glue_foundation(glue), branch, f"glue {name}",
        f"start it with build-custom.sh --only {first},{second} --no-index",
    )  # fmt: skip
    notes = write_patches(engine, folder, f"glue {name}", commits)
    if not (folder / "NOTE.md").is_file():
        (folder / "NOTE.md").write_text(f"# {name}\n\nTODO(owner): why the two series meet and what the patches do.\n")
        notes.append(f"new glue: fill in custom/glue/{name}/NOTE.md")
    fresh = Engine(Catalog(custom), repo)
    built = fresh.build(sorted(fresh.catalog.closure([first, second])), index=False)
    if fresh.tree(built.tip) != fresh.tree(branch):
        raise SeriesError(f"the exported glue of {name} does not rebuild {branch}'s tree")
    notes.append(f"exported {len(commits)} glue patches of {name} onto {engine.glue_foundation(glue)[:12]}")
    return notes


def export_series(custom: Path, repo: Path, name: str, branch: str, needs: list[str] | None) -> list[str]:
    """Rewrite custom/patches/<name>/ from a branch built on the series' foundation."""
    catalog = Catalog(custom)
    engine = Engine(catalog, repo)
    if not SERIES_NAME_RE.match(name):
        raise SeriesError(f"'{name}' is not a series name (lowercase letters, digits and '-')")
    if needs is None:
        needs = catalog.series[name].needs if name in catalog.series else []
    if name in catalog.closure(needs):
        raise SeriesError(f"{name} cannot need itself (through {', '.join(needs)})")
    tip = engine.git("rev-parse", "--verify", f"{branch}^{{commit}}")
    foundation = engine.foundation_of(needs)
    commits = branch_commits(
        engine, foundation, branch, f"{name} (BASE plus {', '.join(needs)})" if needs else f"{name} (BASE)",
        f"start it with build-custom.sh --series {name}, or rebase it onto that commit",
    )  # fmt: skip
    if not commits:
        raise SeriesError(f"{branch} has no commits on the foundation of {name}; to drop a series, delete its directory")
    notes = write_series(engine, name, commits, needs)
    # What was written must build back to the branch, and the series on top of it must still fit.
    fresh = Engine(Catalog(custom), repo)
    if fresh.tree(fresh.series_commits(name)[-1]) != fresh.tree(tip):
        raise SeriesError(f"the exported patches of {name} do not rebuild {branch}'s tree")
    stale = []
    for other in fresh.catalog.order:
        if other != name and name in fresh.catalog.closure([other]):
            try:
                fresh.series_commits(other)
            except BuildError:
                stale.append(other)
    if stale:
        notes.append(f"cut on top of {name} and no longer exact, re-cut them: serieslib.py recut {' '.join(stale)}")
    entry = fresh.catalog.series[name]
    if entry.note and entry.note.fields.get("Covers") != covers_hash(entry.patches):
        notes.append(f"the changed lines of {name} moved: review its NOTE.md, then serieslib.py covers --write {name}")
    notes.append(f"exported {len(commits)} patches of {name} onto {foundation[:12]}")
    return notes


def source_engine(custom: Path, repo: Path, source: str, into: str) -> Engine:
    """An engine for the series as committed at `source`, read from the clone `repo`."""
    inside = subprocess.run(["git", "-C", str(custom), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    prefix = "custom"
    if inside.returncode == 0 and Path(custom).resolve().is_relative_to(inside.stdout.strip()):
        prefix = Path(custom).resolve().relative_to(inside.stdout.strip()).as_posix()
    wanted = [f"{prefix}/{part}" for part in ("BASE", "patches", "glue")]
    present = [
        path for path in wanted
        if subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{source}:{path}"], capture_output=True).returncode == 0
    ]  # fmt: skip
    if f"{prefix}/BASE" not in present:
        raise SeriesError(f"{source} has no {prefix}/BASE in {repo}")
    archive = subprocess.run(["git", "-C", str(repo), "archive", source, *present], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", into], input=archive, check=True)
    return Engine(Catalog(Path(into) / prefix), repo)


def recut(custom: Path, repo: Path, names: list[str], source: str) -> list[str]:
    """Move series whose foundation changed onto their new foundation.

    The old commits come from the series as committed at `source` (a commit of
    the patches branch); each is cherry-picked onto the foundation the files in
    the working tree now give, and the series' patch files are rewritten. A
    conflict leaves the series alone and says how to finish by hand.
    """
    with tempfile.TemporaryDirectory(prefix="serieslib-old-") as old_dir:
        old = source_engine(custom, repo, source, old_dir)
        notes = []
        catalog = Catalog(custom)
        for name in [name for name in catalog.order if name in names]:
            engine = Engine(Catalog(custom), repo)
            try:
                engine.series_commits(name)
                notes.append(f"{name}: already exact on its foundation")
                continue
            except BuildError:
                pass
            if name not in old.catalog.series:
                raise SeriesError(f"{name} is not a series at {source}")
            moved = engine.transplant(name, engine.foundation(name), old.series_commits(name))
            if moved.conflict:
                notes.append(f"{name}: conflicts on its new foundation {engine.foundation(name)[:12]}; finish by hand:")
                notes.append(by_hand(engine, old, name) + f"\n  ({moved.conflict.splitlines()[0]})")
                break
            notes += write_series(engine, name, moved.picked, engine.catalog.series[name].needs)
            notes.append(f"{name}: re-cut onto {engine.foundation(name)[:12]}")
    return notes


def by_hand(engine: Engine, old: Engine, name: str) -> str:
    """The commands that move one series onto its new foundation by hand."""
    return (
        f"  git switch -c work/{name} {engine.foundation(name)[:12]} && "
        f"git cherry-pick {old.foundation(name)[:12]}..{old.series_commits(name)[-1][:12]}\n"
        f"  custom/scripts/export.sh {name} work/{name}"
    )


# ---------------------------------------------------------------- refresh

STALE = ("conflict", "waits")


def remove_from_sets(custom: Path, name: str, why: str) -> list[str]:
    """Comment a series out of every set file that lists it."""
    changed = []
    for path in sorted((custom / "sets").glob("*.txt")):
        lines = path.read_text().splitlines()
        new = [f"# {line.strip()}  ({why})" if line.split("#", 1)[0].split() == [name] else line for line in lines]
        if new != lines:
            path.write_text("\n".join(new) + "\n")
            changed.append(path.stem)
    return changed


def set_needs(note_path: Path, needs: list[str]) -> None:
    text = note_path.read_text()
    note_path.write_text(re.sub(r"^Needs:.*$", f"Needs: {', '.join(needs) if needs else 'none'}", text, count=1, flags=re.M))


def drop_landed(custom: Path, name: str) -> list[str]:
    """Remove a series upstream now has: its directory, its glue, and the needs and sets that name it."""
    import shutil

    catalog = Catalog(custom)
    notes = []
    shutil.rmtree(catalog.series[name].path)
    for glue in catalog.glue.values():
        if name in (glue.first, glue.second):
            shutil.rmtree(glue.path)
            notes.append(f"glue {glue.name} removed with it")
    for other, entry in catalog.series.items():
        if other != name and name in entry.needs:
            set_needs(entry.path / "NOTE.md", [need for need in entry.needs if need != name])
            notes.append(f"{other} no longer lists it under Needs")
    sets = remove_from_sets(custom, name, "landed upstream")
    if sets:
        notes.append(f"commented out of set {', '.join(sets)}")
    return notes


def upstream_pulls(note: Note | None) -> list[tuple[str, int]]:
    """(owner/name, number) of each pull request link in a note's Upstream line."""
    body = note.body if note else ""
    match = re.search(r"^- \*\*Upstream:\*\*.*?(?=^- \*\*|\Z)", body, re.S | re.M)
    found = re.findall(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", match.group(0) if match else "")
    return [(repo, int(number)) for repo, number in dict.fromkeys(found)]


def merged_upstream(pulls: list[tuple[str, int]]) -> list[int] | None:
    """The pull requests among these that GitHub says are merged; None when gh cannot say."""
    merged = []
    for repo, number in pulls:
        try:
            shown = subprocess.run(
                ["gh", "pr", "view", str(number), "-R", repo, "--json", "state"],
                capture_output=True, text=True, timeout=30,
            )  # fmt: skip
        except (OSError, subprocess.TimeoutExpired):
            return None
        if shown.returncode != 0:
            return None
        if json.loads(shown.stdout).get("state") == "MERGED":
            merged.append(number)
    return merged


def landed_hint(engine: Engine, old: Engine | None, name: str, merged: list[int], test_cmd: str | None) -> str:
    """What the note's tests say on bare BASE, for a series whose upstream pull request merged.

    The tests are the series' own. A test file the series changes is read from
    the series' build (from `old`, the series as cut from the previous BASE,
    when it no longer applies): BASE's copy of a test the series only extends
    passes without the series.
    """
    ours = None
    for source in (engine, old):
        if ours is None and source is not None and name in source.catalog.series:
            try:
                ours = source.series_commits(name)[-1]
            except BuildError:
                pass
    present, changed = [], []
    for path, tests in engine.catalog.note_claims(name, "Tests"):
        shown = engine.run("cat-file", "blob", f"{engine.base}:{path}", check=False)
        text = shown.stdout.decode(errors="replace")
        if shown.returncode == 0 and all(re.search(rf"(?<![\w$]){re.escape(test)}(?![\w$])", text) for test in tests):
            present.append(path + "".join(f"::{test}" for test in tests))
            mine = engine.run("rev-parse", "--verify", "--quiet", f"{ours}:{path}", check=False) if ours else None
            if mine and mine.returncode == 0 and mine.stdout.decode().strip() != engine.git("rev-parse", f"{engine.base}:{path}"):
                changed.append(path)
    changed = list(dict.fromkeys(changed))
    numbers = ", ".join(f"#{number}" for number in merged)
    if not present:
        return f"upstream {numbers} merged, but none of the note's tests is on BASE: not landed as written"
    hint = f"upstream {numbers} merged and {len(present)} of the note's tests are on BASE"
    python = [test for test in present if test.split("::")[0].endswith(".py")]
    if not test_cmd or not python:
        copy = f" (the series' own copy: git checkout {ours[:12]} -- {' '.join(changed)})" if changed else ""
        return hint + f"; run them there{copy} to see whether the series can go: " + " ".join(present)
    with tempfile.TemporaryDirectory(prefix="serieslib-base-") as holder:
        tree = Path(holder) / "base"
        engine.run("worktree", "add", "--detach", str(tree), engine.base)
        try:
            if changed:
                subprocess.run(["git", "-C", str(tree), "checkout", "--quiet", ours, "--", *changed], check=True, capture_output=True)
            ran = subprocess.run(f"{test_cmd} {' '.join(python)}", shell=True, cwd=tree, capture_output=True, text=True)
        finally:
            engine.run("worktree", "remove", "--force", str(tree), check=False)
    verdict = "pass: the series looks landed, drop it" if ran.returncode == 0 else f"fail (exit {ran.returncode})"
    copy = f", in the series' own copy of {', '.join(changed)}," if changed else ""
    return f"{hint}; on bare BASE{copy} they {verdict}"


def refresh(custom: Path, repo: Path, source: str, *, upstream_check: bool = True, test_cmd: str | None = None) -> list[dict]:
    """Move every series, one by one, onto the BASE custom/BASE now names.

    `source` is the commit that holds the series as they were, cut from the
    old BASE. In build order, each series is cherry-picked onto its new
    foundation and its files are rewritten. A conflict marks that series
    stale and leaves its files alone; the series that need it wait; the rest
    go on. A patch that comes out empty landed upstream and is dropped, and a
    series with no patch left is removed with its note. Glue follows its two
    series: its patches are moved, a join the pair no longer needs is taken
    off, and glue with nothing left is deleted. Returns one row per series
    and glue pair: {name, status, detail}.
    """
    import shutil

    rows: dict[str, dict] = {}

    def row(name: str, status: str, detail: str = "") -> None:
        rows[name] = {"name": name, "status": status, "detail": detail}

    with tempfile.TemporaryDirectory(prefix="serieslib-old-") as old_dir:
        old = source_engine(custom, repo, source, old_dir)
        for name in Catalog(custom).order:
            catalog = Catalog(custom)
            if name not in catalog.series:
                continue
            blocked = sorted(need for need in catalog.closure([name]) - {name} if rows.get(need, {}).get("status") in STALE)
            if blocked:
                row(name, "waits", f"needs {', '.join(blocked)}")
                continue
            engine = Engine(catalog, repo)
            try:
                engine.series_commits(name)
                row(name, "unchanged")
                continue
            except BuildError:
                pass
            if name not in old.catalog.series:
                row(name, "conflict", f"not a series at {source}: re-export it by hand")
                continue
            moved = engine.transplant(name, engine.foundation(name), old.series_commits(name))
            if moved.conflict:
                row(name, "conflict", "; ".join(moved.paths) + "\n" + by_hand(engine, old, name))
            elif not moved.picked:
                row(name, "landed", "every patch is empty on the new BASE; " + "; ".join(drop_landed(custom, name)))
            else:
                write_series(engine, name, moved.picked, catalog.series[name].needs)
                detail = f"landed upstream and dropped: {'; '.join(moved.landed)}" if moved.landed else ""
                row(name, "refreshed", detail)

        for glue_name in sorted(Catalog(custom).glue):
            catalog = Catalog(custom)
            glue = catalog.glue.get(glue_name)
            if glue is None or glue.first not in catalog.series or glue.second not in catalog.series:
                continue
            label = f"glue {glue_name}"
            if any(rows.get(side, {}).get("status") in STALE for side in catalog.closure([glue.first, glue.second])):
                row(label, "waits", "one of its series is stale")
                continue
            engine = Engine(catalog, repo)
            try:
                foundation = engine.glue_foundation(glue)
            except BuildError as error:
                row(label, "conflict", str(error).splitlines()[0] + ": the pair no longer combines")
                continue
            notes = []
            unused = [path for path in glue.joins if (glue.name, path) not in engine.joins_used]
            if unused:
                kept = [path for path in glue.joins if path not in unused]
                text = (glue.path / "NOTE.md").read_text()
                line = f"Joins: {', '.join(kept)}\n" if kept else ""
                (glue.path / "NOTE.md").write_text(re.sub(r"^Joins:.*\n", line, text, count=1, flags=re.M))
                notes.append(f"no longer joined: {', '.join(unused)}")
            patches = len(glue.patches)
            if glue.patches:
                try:
                    engine.glue_commits(glue)
                except BuildError:
                    old_glue = old.catalog.glue.get(glue_name)
                    moved = engine.transplant(label, foundation, old.glue_commits(old_glue) if old_glue else [])
                    if moved.conflict or old_glue is None:
                        row(label, "conflict", "; ".join(moved.paths) or f"not glue at {source}")
                        continue
                    write_patches(engine, glue.path, label, moved.picked)
                    patches = len(moved.picked)
                    notes.append("patches moved" + (f", landed: {'; '.join(moved.landed)}" if moved.landed else ""))
            if patches == 0 and len(unused) == len(glue.joins):
                shutil.rmtree(glue.path)
                row(label, "removed", "the two series combine without it now")
            else:
                row(label, "refreshed" if notes else "unchanged", "; ".join(notes))

        if upstream_check:
            catalog = Catalog(custom)
            engine = Engine(catalog, repo)
            for name, entry in catalog.series.items():
                pulls = upstream_pulls(entry.note)
                if not pulls:
                    continue
                merged = merged_upstream(pulls)
                if merged is None:
                    rows["(upstream check)"] = {"name": "(upstream check)", "status": "skipped", "detail": "gh could not be asked"}
                    break
                if merged:
                    rows[name]["hint"] = landed_hint(engine, old, name, merged, test_cmd)
    return list(rows.values())


def park(custom: Path, repo: Path, names: list[str], source: str) -> list[str]:
    """Move series out of the build, to custom/parked/<series>/, as they are.

    Each keeps its patches and note, which gains "Base: <commit>": the BASE
    its patches are cut from. Glue with a parked series goes into its
    directory, and set files stop listing it. A series that needs a parked
    one has to be parked with it.
    """
    import shutil

    catalog = Catalog(custom)
    for name in names:
        catalog.get(name)
        dependents = sorted(other for other in catalog.series if other not in names and name in catalog.closure([other]))
        if dependents:
            raise SeriesError(f"{name} is needed by {', '.join(dependents)}: park them too, or drop their need")
    old_base = subprocess.run(
        ["git", "-C", str(repo), "show", f"{source}:custom/BASE"], capture_output=True, text=True
    ).stdout.strip()
    engine = Engine(catalog, repo)
    notes = []
    for name in [name for name in reversed(catalog.order) if name in names]:
        try:
            engine.series_commits(name)
            base = engine.base
        except BuildError:
            base = old_base or engine.base
        target = custom / "parked" / name
        if target.exists():
            raise SeriesError(f"custom/parked/{name} exists already")
        target.parent.mkdir(exist_ok=True)
        shutil.move(str(catalog.series[name].path), str(target))
        text = (target / "NOTE.md").read_text()
        text = re.sub(r"^Base:.*\n", "", text, flags=re.M)
        (target / "NOTE.md").write_text(re.sub(r"^(Needs:.*\n)", rf"\g<1>Base: {base}\n", text, count=1, flags=re.M))
        for glue in catalog.glue.values():
            if name in (glue.first, glue.second) and glue.path.exists():
                (target / "glue").mkdir(exist_ok=True)
                shutil.move(str(glue.path), str(target / "glue" / glue.name))
                notes.append(f"glue {glue.name} parked with {name}")
        sets = remove_from_sets(custom, name, "parked")
        notes.append(
            f"parked {name} (cut from {base[:12]})" + (f"; commented out of set {', '.join(sets)}" if sets else "")
        )
    return notes


# ---------------------------------------------------------------- command line


def chosen_series(catalog: Catalog, args: argparse.Namespace) -> list[str]:
    """The series a command line picks; added ones go to stderr."""
    only: list[str] = []
    for value in args.only or []:
        only += value.replace(",", " ").split()
    if args.set_name is not None:
        only += catalog.set_members(args.set_name)
    if not (args.all or only or args.series):
        raise SeriesError("name a series, or pass --only, --set or --all")
    if only:
        names, why = catalog.select(only + args.series, needs=True)
    else:
        names, why = catalog.select(args.series, needs=args.needs, everything=args.all)
    for name in names:
        if name in why:
            print(f"added {name} ({why[name]})", file=sys.stderr)
    return names


def build_command(catalog: Catalog, args: argparse.Namespace) -> None:
    engine = Engine(catalog, Path(args.repo))
    if args.foundation:
        print(engine.foundation(args.foundation))
        return
    if args.one_series:
        names, _ = catalog.select([args.one_series], needs=True)
    elif args.only or args.set_name is not None:
        args.all, args.series, args.needs = False, [], True
        names = chosen_series(catalog, args)
    else:
        names = list(catalog.series)
    built = engine.build(names, reverse_ties=args.reverse_ties, index=not (args.no_index or args.one_series))
    left_out = len(catalog.series) - len(built.order)
    print(
        f"{built.commits} commits for {len(built.order)} series on {engine.base[:12]}"
        + (f"; {left_out} series left out" if left_out else ""),
        file=sys.stderr,
    )
    print(built.tip)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--custom", default=str(CUSTOM), help="the custom/ folder (default: the one this file is in)")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("files", "names"):
        p = sub.add_parser(command)
        p.add_argument("--needs", action="store_true")
        p.add_argument("--all", action="store_true")
        p.add_argument("--only", action="append")
        p.add_argument("--set", dest="set_name")
        p.add_argument("--names", action="store_true", help="files: print the series' names instead")
        p.add_argument("series", nargs="*")
    sub.add_parser("lint")
    p = sub.add_parser("index")
    p.add_argument("--only", action="append")
    p.add_argument("--set", dest="set_name")
    p = sub.add_parser("build")
    p.add_argument("--repo", default=str(CUSTOM.parent))
    p.add_argument("--only", action="append")
    p.add_argument("--set", dest="set_name")
    p.add_argument("--series", dest="one_series", help="this series on its foundation, nothing else")
    p.add_argument("--foundation", help="print the foundation of this series: BASE plus what it needs")
    p.add_argument("--no-index", action="store_true", help="leave out the last commit, the index of the series built")
    p.add_argument("--reverse-ties", action="store_true")
    p = sub.add_parser("verify")
    p.add_argument("--repo", default=str(CUSTOM.parent))
    p.add_argument("--pairs", action="store_true", help="also build every two series that share a file")
    p = sub.add_parser("export")
    p.add_argument("--repo", default=str(CUSTOM.parent))
    p.add_argument("--needs", help="the series it needs, comma-separated ('none' for none); default: its NOTE.md")
    p.add_argument("--glue", action="store_true", help="<series> is a glue pair, <first>+<second>")
    p.add_argument("series")
    p.add_argument("branch")
    p = sub.add_parser("recut")
    p.add_argument("--repo", default=str(CUSTOM.parent))
    p.add_argument("--from", dest="source", default="HEAD", help="the commit that holds the series as they were")
    p.add_argument("series", nargs="+")
    p = sub.add_parser("refresh")
    p.add_argument("--repo", default=str(CUSTOM.parent))
    p.add_argument("--from", dest="source", default="HEAD", help="the commit that holds the series cut from the old BASE")
    p.add_argument("--no-upstream-check", action="store_true", help="do not ask GitHub whether a note's pull request merged")
    p.add_argument("--landed-test-cmd", help="run the note's tests that exist on bare BASE with this command, for a merged pull request")
    p.add_argument("--json", dest="json_out", help="also write the rows to this file")
    p = sub.add_parser("park")
    p.add_argument("--repo", default=str(CUSTOM.parent))
    p.add_argument("--from", dest="source", default="HEAD")
    p.add_argument("series", nargs="+")
    p = sub.add_parser("covers")
    p.add_argument("--write", action="store_true", help="update the Covers: line of each NOTE.md")
    p.add_argument("series", nargs="*")
    p = sub.add_parser("json")
    p.add_argument("--names", help="only these series, comma-separated (a build set)")
    args = parser.parse_args(argv)

    try:
        catalog = Catalog(Path(args.custom))
        if args.command in ("files", "names"):
            names = chosen_series(catalog, args)
            lines = names if args.command == "names" or args.names else [str(path) for path in catalog.files(names)]
            sys.stdout.write("".join(f"{line}\n" for line in lines))
        elif args.command == "lint":
            problems = catalog.lint()
            print("\n".join(problems), end="\n" if problems else "")
            return 1 if problems else 0
        elif args.command == "index":
            if args.only or args.set_name is not None:
                args.all, args.series, args.needs = False, [], True
                names = chosen_series(catalog, args)
            else:
                names = list(catalog.series)
            sys.stdout.write(catalog.index_text(names))
        elif args.command == "build":
            build_command(catalog, args)
        elif args.command == "verify":
            problems = Engine(catalog, Path(args.repo)).verify(pairs=args.pairs)
            print("\n".join(problems), end="\n" if problems else "")
            return 1 if problems else 0
        elif args.command == "export" and args.glue:
            print("\n".join(export_glue(Path(args.custom), Path(args.repo), args.series, args.branch)))
        elif args.command == "export":
            needs = None
            if args.needs is not None:
                needs = [] if args.needs.strip().lower() in ("", "none") else args.needs.replace(",", " ").split()
            print("\n".join(export_series(Path(args.custom), Path(args.repo), args.series, args.branch, needs)))
        elif args.command == "recut":
            print("\n".join(recut(Path(args.custom), Path(args.repo), args.series, args.source)))
        elif args.command == "refresh":
            rows = refresh(
                Path(args.custom), Path(args.repo), args.source,
                upstream_check=not args.no_upstream_check, test_cmd=args.landed_test_cmd,
            )  # fmt: skip
            if args.json_out:
                Path(args.json_out).write_text(json.dumps(rows, indent=2) + "\n")
            for entry in rows:
                first, *rest = (entry["detail"] or "").split("\n")
                print(f"{entry['name']}: {entry['status']}" + (f" ({first})" if first else ""))
                for line in rest:
                    print(line)
                if entry.get("hint"):
                    print(f"  hint: {entry['hint']}")
            counts: dict[str, int] = {}
            for entry in rows:
                counts[entry["status"]] = counts.get(entry["status"], 0) + 1
            print("refresh: " + ", ".join(f"{count} {status}" for status, count in sorted(counts.items())))
            return 1 if any(entry["status"] in STALE for entry in rows) else 0
        elif args.command == "park":
            print("\n".join(park(Path(args.custom), Path(args.repo), args.series, args.source)))
        elif args.command == "covers":
            for name in args.series or catalog.order:
                entry = catalog.get(name)
                value = covers_hash(entry.patches)
                note_path = entry.path / "NOTE.md"
                if args.write and note_path.is_file():
                    text = note_path.read_text()
                    if re.search(r"^Covers:.*$", text, re.M):
                        note_path.write_text(re.sub(r"^Covers:.*$", f"Covers: {value}", text, count=1, flags=re.M))
                print(f"{name} {value}")
        elif args.command == "json":
            only = set(filter(None, args.names.split(","))) if args.names else None
            json.dump(catalog.as_json(only), sys.stdout, indent=2)
            sys.stdout.write("\n")
    except SeriesError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
