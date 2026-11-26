"""Tests for the patches-branch scripts: python3 -m unittest discover -s custom/scripts/tests"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
}


SERIES_SCRIPTS = ("series-files.sh", "serieslib.py")
INDEX = "docs: index the custom patch series"


def run(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, env=GIT_ENV, capture_output=True, text=True, check=check)


def copy_scripts(custom: Path, *names: str) -> None:
    (custom / "scripts").mkdir(parents=True, exist_ok=True)
    for name in names:
        (custom / "scripts" / name).write_bytes((SCRIPTS / name).read_bytes())
        (custom / "scripts" / name).chmod(0o755)


# The hash serieslib.covers_hash gives patches that change no line, as the stubs below.
NO_LINES = "e3b0c44298fc1c14"


def note_text(name: str, needs: tuple[str, ...] = (), covers: str = NO_LINES) -> str:
    return (
        f"# {name}\n\nNeeds: {', '.join(needs) or 'none'}\nCovers: {covers}\n\nAbout {name}.\n\n"
        "- **Turn on:** on by default.\n- **Upstream:** kept here only.\n\n"
        "## Must hold\n\n- it works\n\n## Key code\n\n- none (a stub)\n\n## Tests\n\n- none (a stub)\n"
    )


def make_series(custom: Path, name: str, slugs: tuple[str, ...] = ("one",), needs: tuple[str, ...] = ()) -> None:
    """A series directory: a complete NOTE.md naming its needs, and one stub patch per slug."""
    folder = custom / "patches" / name
    folder.mkdir(parents=True)
    (folder / "NOTE.md").write_text(note_text(name, needs))
    for number, slug in enumerate(slugs, 1):
        (folder / f"{number:02d}-{slug}.patch").write_text(f"Subject: [PATCH] {slug}\n\nA stub.\n\nDocs: none (test)\n---\n")


def make_glue(custom: Path, name: str, joins: tuple[str, ...] = ("docs/table.md",), why: str = "Both add a row.") -> None:
    folder = custom / "glue" / name
    folder.mkdir(parents=True, exist_ok=True)
    joins_line = f"Joins: {', '.join(joins)}\n\n" if joins else ""
    (folder / "NOTE.md").write_text(f"# {name}\n\n{joins_line}{why}\n")


class CheckTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        run("git", "init", "-q", "-b", "main", cwd=self.repo)
        self.write("README.md", "upstream\n")
        self.write(".github/workflows/ci.yml", "on: push\n")
        self.base = self.commit("upstream base")
        run("git", "switch", "-q", "-c", "patches", cwd=self.repo)
        self.write("custom/BASE", self.base + "\n")
        self.write("custom/series", "# series: x\n")
        self.write(".github/workflows/custom-release.yml", "on: push\n")
        self.write(".github/actions/custom-build-tree/action.yml", "runs: {}\n")
        self.commit("import")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path: str, text: str) -> None:
        file = self.repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)

    def commit(self, message: str) -> str:
        run("git", "add", "-A", cwd=self.repo)
        run("git", "commit", "-q", "-m", message, cwd=self.repo)
        return run("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip()

    def check(self, *args: str) -> subprocess.CompletedProcess:
        return run(str(SCRIPTS / "check-tree.sh"), "--repo", str(self.repo), *args, check=False)

    def test_passes_with_only_our_paths(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("plus custom/", result.stdout)

    def test_fails_when_an_upstream_file_changes(self):
        self.write("README.md", "changed\n")
        self.commit("touch upstream")
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("M\tREADME.md", result.stderr)

    def test_fails_on_another_workflow(self):
        self.write(".github/workflows/extra.yml", "on: push\n")
        self.commit("add a workflow")
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("A\t.github/workflows/extra.yml", result.stderr)

    def test_many_changes_still_report_the_failure(self):
        for index in range(60):
            self.write(f"src/file{index}.txt", "x\n")
        self.commit("touch many upstream paths")
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("... and 10 more", result.stderr)
        self.assertIn("changes 60 upstream paths", result.stderr)

    def test_merging_upstream_needs_a_new_base(self):
        run("git", "switch", "-q", "main", cwd=self.repo)
        self.write("README.md", "upstream moved\n")
        new_base = self.commit("upstream moves")
        run("git", "switch", "-q", "patches", cwd=self.repo)
        run("git", "merge", "-q", "--no-edit", "main", cwd=self.repo)
        self.assertEqual(self.check().returncode, 1)
        self.write("custom/BASE", new_base + "\n")
        self.commit("refresh")
        result = self.check("--upstream", "main")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_base_must_be_an_ancestor(self):
        run("git", "switch", "-q", "main", cwd=self.repo)
        self.write("README.md", "unmerged\n")
        unmerged = self.commit("not merged")
        run("git", "switch", "-q", "patches", cwd=self.repo)
        self.write("custom/BASE", unmerged + "\n")
        self.commit("bump BASE without merging")
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("not an ancestor", result.stderr)


class SeriesFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.custom = Path(self.tmp.name)
        copy_scripts(self.custom, *SERIES_SCRIPTS)
        make_series(self.custom, "a", ("one", "two"))
        make_series(self.custom, "b", needs=("a",))
        make_series(self.custom, "c", needs=("b",))
        self.script = self.custom / "scripts" / "series-files.sh"

    def tearDown(self):
        self.tmp.cleanup()

    def names(self, *args: str) -> list[str]:
        out = run("bash", str(self.script), *args).stdout.splitlines()
        return [str(Path(line).relative_to(self.custom / "patches")) for line in out]

    def test_one_series_in_file_name_order(self):
        self.assertEqual(self.names("a"), ["a/01-one.patch", "a/02-two.patch"])

    def test_needs_are_followed_recursively(self):
        self.assertEqual(
            self.names("--needs", "c"), ["a/01-one.patch", "a/02-two.patch", "b/01-one.patch", "c/01-one.patch"]
        )

    def test_needs_decide_the_order_then_the_names(self):
        make_series(self.custom, "0-first")
        make_series(self.custom, "aa", needs=("c",))
        self.assertEqual(
            run("bash", str(self.script), "--all", "--names").stdout.split(), ["0-first", "a", "b", "c", "aa"]
        )

    def test_the_second_series_of_a_glue_pair_comes_after_the_first(self):
        make_series(self.custom, "0-first")
        make_glue(self.custom, "c+0-first")
        self.assertEqual(run("bash", str(self.script), "--all", "--names").stdout.split(), ["a", "b", "c", "0-first"])
        # Only when both are chosen.
        self.assertEqual(run("bash", str(self.script), "0-first", "a", "--names").stdout.split(), ["0-first", "a"])

    def test_unknown_series(self):
        result = run("bash", str(self.script), "nope", check=False)
        self.assertEqual(result.returncode, 2)

    def test_no_arguments_prints_the_usage(self):
        result = run("bash", str(self.script), check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("series-files.sh --all", result.stdout)


def only_layout(custom: Path) -> None:
    """a (two patches) <- b; c; d needs b and c."""
    copy_scripts(custom, *SERIES_SCRIPTS)
    (custom / "index-intro.md").write_text("# The series\n\nWhat this build holds.\n")
    make_series(custom, "a", ("one", "two"))
    make_series(custom, "b", needs=("a",))
    make_series(custom, "c")
    make_series(custom, "d", needs=("b", "c"))


class SeriesFilesOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.custom = Path(self.tmp.name)
        only_layout(self.custom)
        self.script = self.custom / "scripts" / "series-files.sh"

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_adds_needs_in_build_order(self):
        result = run("bash", str(self.script), "--only", "d,c")
        self.assertEqual(
            [str(Path(line).relative_to(self.custom / "patches")) for line in result.stdout.splitlines()],
            ["a/01-one.patch", "a/02-two.patch", "b/01-one.patch", "c/01-one.patch", "d/01-one.patch"],
        )
        self.assertIn("added a (needed by b)", result.stderr)
        self.assertIn("added b (needed by d)", result.stderr)
        self.assertNotIn("added c (", result.stderr)

    def test_only_names_and_repeated_option(self):
        result = run("bash", str(self.script), "--only", "c", "--only", "b", "--names")
        self.assertEqual(result.stdout.splitlines(), ["a", "b", "c"])

    def test_only_unknown_series(self):
        result = run("bash", str(self.script), "--only", "a,nope", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("no series named nope", result.stderr)


class SeriesFilesSet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.custom = Path(self.tmp.name)
        only_layout(self.custom)
        (self.custom / "sets").mkdir()
        self.script = self.custom / "scripts" / "series-files.sh"
        self.sets = self.custom / "sets"

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_set_is_only_with_the_series_its_file_lists(self):
        (self.sets / "small.txt").write_text("# what it is for\n\nd  # with a note\nc\n")
        by_set = run("bash", str(self.script), "--set", "small")
        by_only = run("bash", str(self.script), "--only", "d,c")
        self.assertEqual(by_set.stdout, by_only.stdout)
        names = run("bash", str(self.script), "--set", "small", "--names").stdout.splitlines()
        self.assertEqual(names, ["a", "b", "c", "d"])

    def test_a_set_that_names_an_unknown_series(self):
        (self.sets / "small.txt").write_text("a\nnope\n")
        result = run("bash", str(self.script), "--set", "small", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("no series named nope", result.stderr)

    def test_missing_and_empty_sets(self):
        result = run("bash", str(self.script), "--set", "absent", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("no set named absent", result.stderr)
        (self.sets / "empty.txt").write_text("# nothing yet\n")
        result = run("bash", str(self.script), "--set", "empty", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("lists no series", result.stderr)

    def test_names_that_would_not_fit_a_version_or_a_tag(self):
        for name in ("Small", "my-set", "my.set", "2fast", "../series", "dirty", "x" * 21, ""):
            result = run("bash", str(self.script), "--set", name, check=False)
            self.assertEqual(result.returncode, 2, name)
            self.assertIn("is not a set name", result.stderr, name)


class SeriesLint(unittest.TestCase):
    """serieslib.py lint: the rules a series directory must meet before anything is applied."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.custom = Path(self.tmp.name)
        only_layout(self.custom)

    def tearDown(self):
        self.tmp.cleanup()

    def lint(self, stamp: bool = False) -> list[str]:
        if stamp:  # the test changed a patch on purpose: its note covers the new lines
            run("python3", str(self.custom / "scripts" / "serieslib.py"), "covers", "--write")
        result = run("python3", str(self.custom / "scripts" / "serieslib.py"), "lint", check=False)
        self.assertEqual(result.returncode, 1 if result.stdout else 0, result.stderr)
        return result.stdout.splitlines()

    def test_a_well_formed_series_passes(self):
        self.assertEqual(self.lint(), [])

    def test_layout_problems(self):
        (self.custom / "patches" / "a--old.patch").write_text("x")
        (self.custom / "patches" / "b" / "NOTE.md").unlink()
        (self.custom / "patches" / "c" / "extra.txt").write_text("x")
        (self.custom / "patches" / "d" / "01-one.patch").rename(self.custom / "patches" / "d" / "one.patch")
        problems = "\n".join(self.lint())
        self.assertIn("custom/patches/a--old.patch is not in a series directory", problems)
        self.assertIn("series b has no NOTE.md", problems)
        self.assertIn("custom/patches/c/extra.txt is neither NOTE.md nor NN-<slug>.patch", problems)
        self.assertIn("custom/patches/d/one.patch is neither NOTE.md nor NN-<slug>.patch", problems)

    def test_needs_must_exist_and_not_form_a_circle(self):
        note = self.custom / "patches" / "c" / "NOTE.md"
        note.write_text(note.read_text().replace("Needs: none", "Needs: d, gone"))
        self.assertIn("series c needs gone, which does not exist", self.lint())
        note.write_text(note.read_text().replace("Needs: d, gone", "Needs: d"))
        self.assertIn("the series need (or are glued after) each other in a circle: c, d", self.lint())

    def test_the_index_intro_and_the_retired_order_file(self):
        (self.custom / "series").write_text("a\n")
        (self.custom / "index-intro.md").unlink()
        problems = "\n".join(self.lint())
        self.assertIn("custom/series is not used any more", problems)
        self.assertIn("custom/index-intro.md is missing", problems)

    def note(self, name: str, change) -> None:
        path = self.custom / "patches" / name / "NOTE.md"
        path.write_text(change(path.read_text()))

    def test_a_note_must_be_complete(self):
        self.note("a", lambda text: text.replace("- **Turn on:** on by default.\n", ""))
        self.note("b", lambda text: text.replace("kept here only", "see #123 and `#45`"))
        self.note("c", lambda text: text.replace("- it works", "- TODO(owner)").replace("- none (a stub)\n\n## Tests", "\n## Tests"))
        self.note("d", lambda text: text.replace("About d.", "TODO(owner): what the series changes."))
        self.assertEqual(self.lint(), [
            "custom/patches/a/NOTE.md has no '- **Turn on:**' line",
            "custom/patches/b/NOTE.md: write issues and pull requests as full links, [#123](https://...)",
            "custom/patches/c/NOTE.md has nothing under '## Must hold'",
            "custom/patches/c/NOTE.md has nothing under '## Key code'",
            "custom/patches/d/NOTE.md does not say what the series changes",
        ])

    def test_a_guess_marked_for_the_owner_and_a_full_link_pass(self):
        self.note("a", lambda text: text.replace("- it works", "- TODO(owner): probably keeps the old alias"))
        self.note("b", lambda text: text.replace("kept here only", "pull request [#123](https://example.com/pull/123)"))
        self.assertEqual(self.lint(), [])

    def test_a_note_is_short_and_covers_the_patches_as_they_are(self):
        self.note("a", lambda text: text + "\n".join(f"- line {number}" for number in range(60)) + "\n")
        patch = self.custom / "patches" / "b" / "01-one.patch"
        patch.write_text(patch.read_text() + "diff --git a/docs/x.md b/docs/x.md\n--- a/docs/x.md\n+++ b/docs/x.md\n@@ -1 +1 @@\n-old\n+new\n")
        problems = self.lint()
        self.assertEqual(problems[0], "custom/patches/a/NOTE.md has 81 lines; keep it to 60")
        self.assertIn("custom/patches/b/NOTE.md: the lines b changes moved since the note was written (Covers: "
                      f"{NO_LINES}, now ", problems[1])
        self.assertIn("review the note, then serieslib.py covers --write b", problems[1])
        run("python3", str(self.custom / "scripts" / "serieslib.py"), "covers", "--write", "b")
        self.assertEqual(self.lint(), problems[:1])

    def test_a_series_leaves_the_index_to_the_build(self):
        patch = self.custom / "patches" / "c" / "01-one.patch"
        patch.write_text(patch.read_text() + "diff --git a/docs/custom/README.md b/docs/custom/README.md\n")
        self.assertEqual(
            self.lint(stamp=True), ["series c changes docs/custom/README.md, which the build writes from the notes"]
        )

    def test_glue_directories(self):
        make_glue(self.custom, "a+c")
        self.assertEqual(self.lint(), [])
        make_glue(self.custom, "c+a")
        make_glue(self.custom, "a+nope")
        make_glue(self.custom, "d+a")
        make_series(self.custom, "e")
        make_glue(self.custom, "c+e", joins=(), why="")
        (self.custom / "glue" / "stray.txt").write_text("x")
        (self.custom / "glue" / "a+c" / "notes.txt").write_text("x")
        problems = "\n".join(self.lint())
        self.assertIn("custom/glue/stray.txt is not in a glue directory", problems)
        self.assertIn("custom/glue/a+c: c+a exists too; keep one directory per pair", problems)
        self.assertIn("custom/glue/a+nope: name it <first>+<second> after two series (nope?)", problems)
        self.assertIn("custom/glue/d+a: d needs a, so it is already cut on top of it; drop the glue", problems)
        self.assertIn("custom/glue/c+e has neither a 'Joins:' line nor a patch", problems)
        self.assertIn("custom/glue/c+e/NOTE.md does not say why the two series meet", problems)
        self.assertIn("custom/glue/a+c/notes.txt is neither NOTE.md nor NN-<slug>.patch", problems)

    def test_the_docs_rule(self):
        patch = self.custom / "patches" / "a" / "01-one.patch"
        patch.write_text("Subject: [PATCH] one\n\nNo trailer.\n---\ndiff --git a/omnigent/x.py b/omnigent/x.py\n")
        self.assertEqual(
            self.lint(stamp=True), ["a/01-one.patch has no usage docs and no 'Docs: none (<reason>)' trailer"]
        )
        patch.write_text("Subject: [PATCH] one\n\nNo trailer.\n---\ndiff --git a/docs/x.md b/docs/x.md\n")
        self.assertEqual(self.lint(stamp=True), [])

    def test_the_title_and_the_needs_line(self):
        self.note("a", lambda text: text.replace("# a\n\nNeeds: none\n", "# other\n\n"))
        problems = self.lint()
        self.assertIn("custom/patches/a/NOTE.md must start with '# a'", problems)
        self.assertIn("custom/patches/a/NOTE.md has no 'Needs:' line (write 'Needs: none')", problems)


class Notes(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        import serieslib

        self.lib = serieslib

    def tearDown(self):
        sys.path.remove(str(SCRIPTS))

    def test_a_note_round_trips(self):
        text = self.lib.render_note(
            "x", ["a", "b"], "0123", "What it does.\n\n- **Turn on:** always.",
            {"Must hold": "- one", "Key code": "- `f.py`: `g`", "Tests": "- `tests/test_f.py`"},
        )
        note = self.lib.parse_note(text)
        self.assertEqual((note.title, note.needs, note.fields["Covers"]), ("x", ["a", "b"], "0123"))
        self.assertEqual(note.body, "What it does.\n\n- **Turn on:** always.")
        self.assertEqual(note.sections, {"Must hold": "- one", "Key code": "- `f.py`: `g`", "Tests": "- `tests/test_f.py`"})
        self.assertEqual(self.lib.parse_note("# y\n\nNeeds: none\n").needs, [])

    def test_covers_follows_the_changed_lines_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch = Path(tmp, "01-x.patch")
            head = "Subject: [PATCH] x\n\n---\ndiff --git a/f.py b/f.py\nindex 1..2 100644\n--- a/f.py\n+++ b/f.py\n"
            patch.write_text(head + "@@ -1,3 +1,3 @@\n context\n-old\n+new\n more\n")
            first = self.lib.covers_hash([patch])
            # Another foundation: other context, line numbers and blob ids.
            patch.write_text(head.replace("1..2", "3..4") + "@@ -7,3 +7,3 @@\n other\n-old\n+new\n lines\n")
            self.assertEqual(self.lib.covers_hash([patch]), first)
            patch.write_text(head + "@@ -1,3 +1,3 @@\n context\n-old\n+newer\n more\n")
            self.assertNotEqual(self.lib.covers_hash([patch]), first)


class BuildSets(unittest.TestCase):
    """The engine, build-custom.sh, export.sh, check.sh and select-tests.py on a small real series.

    a <- b (b needs a) and c: each exported from its own branch, then its note filled in.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name, "repo")
        self.repo.mkdir()
        run("git", "init", "-q", "-b", "main", cwd=self.repo)
        for name in ("alpha", "beta", "gamma"):
            self.write(f"omnigent/{name}.py", f"{name} = 1\n")
            self.write(f"tests/test_{name}.py", "def test_it():\n    pass\n")
        self.write("docs/table.md", "| name |\n| --- |\n| first |\n| last |\n")
        self.base = self.commit("upstream base")
        run("git", "switch", "-q", "-c", "patches", cwd=self.repo)
        custom = self.repo / "custom"
        copy_scripts(custom, "build-custom.sh", "check.sh", "check-tree.sh", "export.sh", "refresh.sh",
                     "select-tests.py", *SERIES_SCRIPTS)
        self.write("custom/BASE", self.base + "\n")
        self.write("custom/sets/small.txt", "# b, and a because b needs it\nb\n")
        self.write("custom/index-intro.md", "# The series\n\nWhat this build holds.\n")
        # Each series on its own branch, cut from BASE plus what it needs, in a second worktree.
        self.work = Path(self.tmp.name, "work")
        run("git", "worktree", "add", "-q", "--detach", str(self.work), self.base, cwd=self.repo)
        self.series("work/a", self.base, "alpha change", {"omnigent/alpha.py": "alpha = 2\n", "docs/alpha.md": "# Alpha\n"})
        self.export("a", "work/a")
        on_a = self.script("build-custom.sh", "--series", "a", "work/b-base").stdout.strip()
        self.series("work/b", on_a, "beta change\n\nNothing to document.\n\nDocs: none (test)",
                    {"omnigent/beta.py": "beta = 2\n"})
        self.export("b", "work/b", "--needs", "a")
        self.series("work/c", self.base, "gamma change", {"omnigent/gamma.py": "gamma = 2\n", "docs/gamma.md": "# Gamma\n"})
        self.export("c", "work/c")
        self.fill_notes()
        self.first = self.commit("the series")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path: str, text: str) -> None:
        file = self.repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)

    def commit(self, message: str) -> str:
        run("git", "add", "-A", cwd=self.repo)
        run("git", "commit", "-q", "-m", message, cwd=self.repo)
        return run("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip()

    def series(self, branch: str, start: str | None, message: str, files: dict[str, str]) -> None:
        """One more commit on a series' branch (new at `start`), made in the second worktree."""
        if start:
            run("git", "switch", "-q", "-C", branch, start, cwd=self.work)
        else:
            run("git", "switch", "-q", branch, cwd=self.work)
        for path, text in files.items():
            (self.work / path).parent.mkdir(parents=True, exist_ok=True)
            (self.work / path).write_text(text)
        run("git", "add", "-A", cwd=self.work)
        run("git", "commit", "-q", "-m", message, cwd=self.work)

    def script(self, name: str, *args: str) -> subprocess.CompletedProcess:
        return run(str(self.repo / "custom" / "scripts" / name), *args, cwd=self.repo, check=False)

    def fill_notes(self) -> None:
        """Complete every note the export started, keeping its Needs line, and stamp Covers."""
        for folder in sorted((self.repo / "custom" / "patches").iterdir()):
            text = (folder / "NOTE.md").read_text()
            if "TODO(owner)" in text:
                needs = tuple(name for name in re.search(r"^Needs: (.*)$", text, re.M).group(1).split(", ") if name != "none")
                (folder / "NOTE.md").write_text(note_text(folder.name, needs))
        self.script("serieslib.py", "covers", "--write")

    def export(self, series: str, branch: str, *args: str) -> subprocess.CompletedProcess:
        result = self.script("export.sh", *args, series, branch)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def build(self, *args: str) -> Path:
        tree = Path(tempfile.mkdtemp(dir=self.tmp.name), "tree")
        result = self.script("build-custom.sh", *args, "--worktree", str(tree))
        self.assertEqual(result.returncode, 0, result.stderr)
        return tree

    def subjects(self, tree: Path) -> list[str]:
        return run("git", "log", "--reverse", "--format=%s", f"{self.base}..HEAD", cwd=tree).stdout.splitlines()

    def selected(self, tree: Path, *args: str) -> tuple[list[str], str]:
        out = Path(tempfile.mkdtemp(dir=self.tmp.name))
        result = self.script("select-tests.py", "--tree", str(tree), "--out", str(out), *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return (out / "pytest.txt").read_text().split(), result.stdout

    def test_export_wrote_one_directory_per_series(self):
        custom = self.repo / "custom"
        self.assertEqual(sorted(path.name for path in (custom / "patches" / "b").iterdir()),
                         ["01-beta-change.patch", "NOTE.md"])
        self.assertIn("Subject: [PATCH] beta change", (custom / "patches" / "b" / "01-beta-change.patch").read_text())
        self.assertIn("# b\n\nNeeds: a\n", (custom / "patches" / "b" / "NOTE.md").read_text())
        self.assertIn("# c\n\nNeeds: none\n", (custom / "patches" / "c" / "NOTE.md").read_text())
        self.assertFalse((custom / "series").exists())

    def test_the_whole_build_combines_the_series_by_needs_then_name(self):
        tree = self.build()
        self.assertEqual(self.subjects(tree), ["alpha change", "beta change", "gamma change", INDEX])
        for name in ("alpha", "beta", "gamma"):
            self.assertEqual((tree / "omnigent" / f"{name}.py").read_text(), f"{name} = 2\n")

    def test_a_series_applied_exactly_is_the_commit_git_am_makes(self):
        bot = {"GIT_COMMITTER_NAME": "github-actions[bot]",
               "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com"}
        tree = Path(tempfile.mkdtemp(dir=self.tmp.name), "am")
        run("git", "worktree", "add", "-q", "--detach", str(tree), self.base, cwd=self.repo)
        patches = sorted(str(path) for name in ("a", "b") for path in (self.repo / "custom/patches" / name).glob("*.patch"))
        subprocess.run(["git", "am", "-q", "--committer-date-is-author-date", *patches], cwd=tree,
                       env={**GIT_ENV, **bot}, check=True, capture_output=True)
        by_am = run("git", "rev-parse", "HEAD", cwd=tree).stdout.strip()
        by_engine = self.script("build-custom.sh", "--series", "b", "work/only-b").stdout.strip()
        self.assertEqual(by_engine, by_am)

    def test_a_set_builds_its_series_what_they_need_and_their_index(self):
        tree = self.build("--set", "small")
        self.assertEqual(self.subjects(tree), ["alpha change", "beta change", INDEX])
        self.assertEqual((tree / "omnigent" / "gamma.py").read_text(), "gamma = 1\n")
        index = (tree / "docs" / "custom" / "README.md").read_text()
        self.assertEqual(index, "# The series\n\nWhat this build holds.\n\n" + "\n\n".join(
            f"## {name}\n\nAbout {name}.\n\n- **Turn on:** on by default.\n- **Upstream:** kept here only."
            for name in ("a", "b")) + "\n")
        self.assertEqual(index, self.script("serieslib.py", "index", "--set", "small").stdout)
        # The same set gives the same commits again; the whole series gives others.
        again = self.build("--set", "small")
        whole = self.build()
        head = [run("git", "rev-parse", "HEAD", cwd=path).stdout for path in (tree, again, whole)]
        self.assertEqual(head[0], head[1])
        self.assertNotEqual(head[0], head[2])

    def test_the_index_is_the_last_commit_written_from_the_notes(self):
        tree = self.build()
        index = (tree / "docs" / "custom" / "README.md").read_text()
        self.assertEqual(re.findall(r"^## (.*)$", index, re.M), ["a", "b", "c"])
        shown = run("git", "show", "-s", "--format=%an|%cn|%ad|%cd", "--date=raw", "HEAD", "HEAD~1", cwd=tree).stdout.splitlines()
        # Authored by the build's committer, dated like the commit before it.
        self.assertEqual(shown[0].split("|")[0], "github-actions[bot]")
        self.assertEqual(shown[0].split("|")[2:], shown[1].split("|")[2:])
        self.assertEqual(run("git", "show", "--format=", "--name-only", "HEAD", cwd=tree).stdout.split(),
                         ["docs/custom/README.md"])
        # A note's text is part of the build: changing it changes the last commit only.
        note = self.repo / "custom" / "patches" / "c" / "NOTE.md"
        note.write_text(note.read_text().replace("About c.", "About c, reworded."))
        again = self.build()
        heads = [run("git", "rev-parse", "HEAD", "HEAD~1", cwd=path).stdout.split() for path in (tree, again)]
        self.assertNotEqual(heads[0][0], heads[1][0])
        self.assertEqual(heads[0][1], heads[1][1])
        self.assertIn("About c, reworded.", (again / "docs" / "custom" / "README.md").read_text())

    def test_one_series_builds_alone_with_or_without_the_index(self):
        self.assertEqual(self.subjects(self.build("--only", "c")), ["gamma change", INDEX])
        self.assertEqual(self.subjects(self.build("--only", "b", "--no-index")), ["alpha change", "beta change"])
        self.assertEqual(self.subjects(self.build("--series", "b")), ["alpha change", "beta change"])

    def test_check_takes_the_whole_series_or_a_set(self):
        whole = self.script("check.sh")
        self.assertEqual(whole.returncode, 0, whole.stderr)
        self.assertRegex(whole.stdout, rf"\A3 patches apply on {self.base[:12]} as [0-9a-f]{{12}}\n\Z")
        small = self.script("check.sh", "--set", "small")
        self.assertEqual(small.returncode, 0, small.stderr)
        self.assertIn("2 patches of set small apply", small.stdout)

    def test_check_tree_must_be_at_the_commit_the_selection_builds(self):
        whole, small = self.build(), self.build("--set", "small")
        self.assertEqual(self.script("check.sh", "--tree", str(small), "--set", "small").returncode, 0)
        self.assertEqual(self.script("check.sh", "--tree", str(whole)).returncode, 0)
        self.write("custom/sets/other.txt", "a\nc\n")
        other = self.build("--set", "other")
        for tree, args in ((whole, ("--set", "small")), (small, ()), (other, ("--set", "small"))):
            result = self.script("check.sh", "--tree", str(tree), *args)
            self.assertEqual(result.returncode, 1)
            self.assertIn("rebuild it", result.stdout)

    def test_check_rejects_a_set_file_that_names_a_missing_series(self):
        self.write("custom/sets/broken.txt", "a\ndropped\n")
        result = self.script("check.sh")
        self.assertEqual(result.returncode, 1)
        self.assertIn("set broken: no series named dropped", result.stderr)

    def test_check_with_an_unknown_set(self):
        result = self.script("check.sh", "--set", "absent")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no set named absent", result.stderr)

    def test_a_note_names_code_and_tests_that_exist_in_the_series_own_build(self):
        note = self.repo / "custom" / "patches" / "b" / "NOTE.md"
        sections = note.read_text().split("## Key code")[0]

        def claims(key_code: str, tests: str) -> str:
            note.write_text(f"{sections}## Key code\n\n{key_code}\n\n## Tests\n\n{tests}\n")
            result = self.script("check.sh")
            return result.stderr

        self.assertEqual(claims("- `omnigent/beta.py`: `beta` — the value", "- `tests/test_beta.py::test_it`"), "")
        # b is cut on top of a, so a's code is in its build, but it is not b's key code.
        self.assertIn("omnigent/alpha.py (Key code) is not a file the series changes",
                      claims("- `omnigent/alpha.py`: `alpha`", "- `tests/test_beta.py`"))
        self.assertIn("gamma is not in omnigent/beta.py in the series' build",
                      claims("- `omnigent/beta.py`: `beta`, `gamma`", "- `tests/test_beta.py`"))
        self.assertIn("be is not in omnigent/beta.py", claims("- `omnigent/beta.py`: `be`", "- `tests/test_beta.py`"))
        stderr = claims("- `omnigent/nope.py`: `beta`", "- `tests/test_nope.py`\n- `tests/test_beta.py::test_other`")
        self.assertIn("omnigent/nope.py (Key code) is not in the series' build", stderr)
        self.assertIn("tests/test_nope.py (Tests) is not in the series' build", stderr)
        self.assertIn("test_other is not in tests/test_beta.py", stderr)
        self.assertIn("a '## Key code' line names no `path`", claims("- the beta module", "- none (no tests yet)"))
        self.assertEqual(claims("- none (docs only)", "- TODO(owner): which test covers this?"), "")

    def test_check_names_a_patch_that_is_not_cut_from_its_foundation(self):
        patch = self.repo / "custom" / "patches" / "c" / "01-gamma-change.patch"
        text = patch.read_text()
        # Other context than the foundation has: git would still place the hunk by fuzz or -3.
        patch.write_text(text.replace("@@ -1 +1 @@\n-gamma = 1", "@@ -1 +1 @@\n-gamma = 0"))
        self.script("serieslib.py", "covers", "--write", "c")
        result = self.script("check.sh")
        self.assertEqual(result.returncode, 1)
        self.assertIn("c/01-gamma-change.patch does not apply on its foundation", result.stderr)
        self.script("serieslib.py", "covers", "--write", "c")
        # It applies, but to something else than it was exported from.
        patch.write_text(re.sub(r"\.\.[0-9a-f]{40}", ".." + "1" * 40, text, count=1))
        self.script("serieslib.py", "covers", "--write", "c")
        result = self.script("check.sh")
        self.assertEqual(result.returncode, 1)
        self.assertIn("c/01-gamma-change.patch is not cut from its foundation", result.stderr)

    def add_row_series(self, name: str, row: str) -> None:
        table = f"| name |\n| --- |\n| first |\n| {row} |\n| last |\n"
        self.series(f"work/{name}", self.base, f"add the {row} row", {"docs/table.md": table})
        self.export(name, f"work/{name}")
        self.fill_notes()

    def test_series_that_change_the_same_lines_do_not_combine(self):
        self.add_row_series("d", "delta")
        self.add_row_series("e", "epsilon")
        result = self.script("check.sh")
        self.assertEqual(result.returncode, 1)
        self.assertIn("e ('add the epsilon row') does not combine with the series before it", result.stderr)
        self.assertIn("docs/table.md (also changed by d)", result.stderr)
        # Each still builds alone.
        self.assertEqual(self.subjects(self.build("--only", "e", "--no-index")), ["add the epsilon row"])

    def table(self, *args: str) -> list[str]:
        """The rows of docs/table.md in a build of d and e (or what args select)."""
        tree = self.build(*(args or ("--only", "d,e", "--no-index")))
        return [line.strip("| ") for line in (tree / "docs" / "table.md").read_text().splitlines()[2:]]

    def verify(self, *args: str) -> str:
        result = self.script("serieslib.py", "verify", *args)
        self.assertEqual(result.returncode, 1 if result.stdout else 0, result.stderr)
        return result.stdout

    def test_a_join_keeps_both_insertions_the_first_named_series_first(self):
        self.add_row_series("d", "delta")
        self.add_row_series("e", "epsilon")
        make_glue(self.repo / "custom", "d+e")
        self.assertEqual(self.verify(), "")
        self.assertEqual(self.table(), ["first", "delta", "epsilon", "last"])
        # The glue's name gives the order, not the series' names.
        (self.repo / "custom" / "glue" / "d+e").rename(self.repo / "custom" / "glue" / "e+d")
        (self.repo / "custom" / "glue" / "e+d" / "NOTE.md").write_text("# e+d\n\nJoins: docs/table.md\n\nBoth add a row.\n")
        self.assertEqual(self.table(), ["first", "epsilon", "delta", "last"])
        # Glue does nothing unless both are built.
        self.assertEqual(self.table("--only", "d", "--no-index"), ["first", "delta", "last"])

    def test_a_join_that_is_not_needed_is_reported(self):
        self.add_row_series("d", "delta")
        self.add_row_series("e", "epsilon")
        make_glue(self.repo / "custom", "d+e", joins=("docs/table.md", "docs/alpha.md"))
        self.assertEqual(
            self.verify(), "glue d+e joins docs/alpha.md, but d and e combine there without it; drop the path\n"
        )

    def test_a_join_does_not_cover_edits_of_the_same_lines(self):
        for name, word in (("d", "erste"), ("e", "premier")):
            self.series(f"work/{name}", self.base, f"call the first row {word}",
                        {"docs/table.md": f"| name |\n| --- |\n| {word} |\n| last |\n"})
            self.export(name, f"work/{name}")
        self.fill_notes()
        make_glue(self.repo / "custom", "d+e")
        problems = self.verify()
        self.assertIn("glue d+e: e ('call the first row premier') does not combine with the series before it", problems)
        self.assertIn("docs/table.md (also changed by d) (glue d+e joins insertions at the same spot; here both", problems)

    def test_pairs_finds_two_series_that_do_not_build_together(self):
        self.add_row_series("d", "delta")
        self.assertEqual(self.verify("--pairs"), "")
        self.add_row_series("zz", "zeta")
        # The whole build stops on it too; --pairs names the two series.
        self.assertIn("d and zz do not build together: zz ('add the zeta row') does not combine", self.verify("--pairs"))
        make_glue(self.repo / "custom", "d+zz")
        self.assertEqual(self.verify("--pairs"), "")

    def test_a_glue_patch_goes_on_top_of_the_two_series_combined(self):
        self.add_row_series("d", "delta")
        self.add_row_series("e", "epsilon")
        make_glue(self.repo / "custom", "d+e")
        both = self.script("build-custom.sh", "--only", "d,e", "--no-index", "work/glue-base").stdout.strip()
        self.series("work/glue", both, "say that the two rows belong together",
                    {"docs/table.md": "| name |\n| --- |\n| first |\n| delta and |\n| epsilon |\n| last |\n"})
        result = self.script("export.sh", "--glue", "d+e", "work/glue")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("wrote: glue d+e/01-say-that-the-two-rows-belong-together.patch", result.stdout)
        self.assertEqual(self.verify(), "")
        self.assertEqual(self.table(), ["first", "delta and", "epsilon", "last"])
        self.assertEqual(self.table("--only", "e", "--no-index"), ["first", "epsilon", "last"])
        tree = self.build("--only", "d,e", "--no-index")
        self.assertEqual(self.subjects(tree), ["add the delta row", "add the epsilon row",
                                               "say that the two rows belong together"])
        self.assertEqual(self.subjects(self.build("--only", "d,e"))[-1], INDEX)
        # A change to a glue patch selects tests like a change to a series' patch.
        self.commit("glue d+e")
        files, why = self.selected(tree, "--since", self.first)
        self.assertIn("3 patch versions changed", why)
        # The pair's branch already holds the patch: exporting it again changes nothing.
        self.script("build-custom.sh", "--only", "d,e", "--no-index", "work/glue-again")
        trees = run("git", "rev-parse", "work/glue^{tree}", "work/glue-again^{tree}", cwd=self.repo).stdout.split()
        self.assertEqual(trees[0], trees[1])
        self.assertNotIn("wrote:", self.script("export.sh", "--glue", "d+e", "work/glue-again").stdout)

    def test_export_adds_a_patch_and_recut_moves_the_series_on_top(self):
        on_a = self.script("build-custom.sh", "--series", "a", "work/d-base").stdout.strip()
        self.series("work/d", on_a, "rename the last row", {"docs/table.md": "| name |\n| --- |\n| first |\n| final |\n"})
        self.export("d", "work/d", "--needs", "a")
        self.fill_notes()
        self.commit("add d")
        # a changes the same file elsewhere: d, cut on top of a, has to follow.
        # recut takes the series as committed (HEAD) and moves it onto its new foundation.
        self.series("work/a", None, "alpha renames the column", {"docs/table.md": "| title |\n| --- |\n| first |\n| last |\n"})
        result = self.export("a", "work/a")
        self.assertIn("wrote: a/02-alpha-renames-the-column.patch", result.stdout)
        self.assertIn("re-cut them: serieslib.py recut d", result.stdout)
        self.script("serieslib.py", "covers", "--write", "a")
        self.assertIn("d/01-rename-the-last-row.patch does not apply on its foundation", self.script("check.sh").stderr)
        recut = self.script("serieslib.py", "recut", "d")
        self.assertEqual(recut.returncode, 0, recut.stderr)
        self.assertIn("d: re-cut onto", recut.stdout)
        tree = self.build("--only", "d", "--no-index")
        self.assertEqual((tree / "docs" / "table.md").read_text(), "| title |\n| --- |\n| first |\n| final |\n")
        self.assertIn("d: already exact", self.script("serieslib.py", "recut", "d").stdout)

    def test_recut_moves_the_series_onto_a_new_base(self):
        self.series("work/d", self.base, "rename the last row", {"docs/table.md": "| name |\n| --- |\n| first |\n| final |\n"})
        self.export("d", "work/d")
        self.fill_notes()
        old = self.commit("add d")
        # Upstream moves on and changes a file d touches, elsewhere in it.
        self.series("upstream-next", self.base, "upstream renames the column",
                    {"docs/table.md": "| title |\n| --- |\n| first |\n| last |\n"})
        new_base = run("git", "rev-parse", "upstream-next", cwd=self.repo).stdout.strip()
        self.write("custom/BASE", new_base + "\n")
        self.assertIn("d/01-rename-the-last-row.patch does not apply on its foundation", self.script("check.sh").stderr)
        recut = self.script("serieslib.py", "recut", "--from", old, "a", "b", "c", "d")
        self.assertEqual(recut.returncode, 0, recut.stderr)
        self.assertIn("a: already exact on its foundation", recut.stdout)
        self.assertIn(f"d: re-cut onto {new_base[:12]}", recut.stdout)
        verify = self.script("serieslib.py", "verify")
        self.assertEqual((verify.returncode, verify.stdout), (0, ""), verify.stderr)
        self.assertEqual((self.build() / "docs" / "table.md").read_text(), "| title |\n| --- |\n| first |\n| final |\n")

    def upstream_moves(self) -> str:
        """Upstream renames the table's column, takes c's change as it is, and changes the line b changes."""
        self.series("work/d", self.base, "rename the last row", {"docs/table.md": "| name |\n| --- |\n| first |\n| final |\n"})
        self.export("d", "work/d")
        on_b = self.script("build-custom.sh", "--series", "b", "work/g-base").stdout.strip()
        self.series("work/g", on_b, "more about beta", {"docs/beta.md": "# Beta\n"})
        self.export("g", "work/g", "--needs", "b")
        self.fill_notes()
        self.write("custom/sets/small.txt", "a\nb\nc\n")
        self.commit("add d and g")
        self.series("upstream-next", self.base, "upstream moves", {
            "docs/table.md": "| title |\n| --- |\n| first |\n| last |\n",
            "omnigent/gamma.py": "gamma = 2\n", "docs/gamma.md": "# Gamma\n", "omnigent/beta.py": "beta = 9\n",
        })
        return run("git", "rev-parse", "upstream-next", cwd=self.repo).stdout.strip()

    def test_refresh_moves_each_series_alone_parks_and_drops(self):
        new_base = self.upstream_moves()
        run("git", "switch", "-q", "-c", "refresh/test", cwd=self.repo)
        result = self.script("refresh.sh", "--no-fetch", "--upstream", "upstream-next", "--no-upstream-check")
        self.assertEqual(result.returncode, 1, result.stderr)
        for line in ("a: unchanged", "b: conflict (omnigent/beta.py)", "c: landed (every patch is empty on the new BASE; "
                     "commented out of set small)", "d: refreshed", "g: waits (needs b)",
                     "refresh: 1 conflict, 1 landed, 1 refreshed, 1 unchanged, 1 waits"):
            self.assertIn(line + "\n", result.stdout)
        self.assertIn("custom/scripts/export.sh b work/b", result.stdout)
        self.assertIn("Some series are stale", result.stderr)
        custom = self.repo / "custom"
        self.assertFalse((custom / "patches" / "c").exists())
        self.assertIn("# c  (landed upstream)", (custom / "sets" / "small.txt").read_text())
        # The stale series is as it was; nothing is committed yet.
        self.assertIn("-beta = 1", (custom / "patches" / "b" / "01-beta-change.patch").read_text())
        self.assertEqual(run("git", "log", "-1", "--format=%s", cwd=self.repo).stdout.strip(),
                         f"Merge upstream {new_base[:12]} into patches")
        # b cannot be parked from under g.
        refused = self.script("refresh.sh", "--continue", "--park", "b", "--no-upstream-check")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("b is needed by g: park them too", refused.stderr)
        done = self.script("refresh.sh", "--continue", "--park", "b", "--park", "g", "--no-upstream-check")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"parked b (cut from {self.base[:12]}); commented out of set small", done.stdout)
        self.assertIn("refresh: 2 unchanged", done.stdout)  # a and d, which the first run moved
        self.assertIn(f"Refreshed onto {new_base[:12]}", done.stdout)
        self.assertIn(f"Needs: a\nBase: {self.base}\n", (custom / "parked" / "b" / "NOTE.md").read_text())
        self.assertTrue((custom / "parked" / "g" / "01-more-about-beta.patch").is_file())
        self.assertEqual(run("git", "log", "-1", "--format=%s", cwd=self.repo).stdout.strip(),
                         f"Refresh the series onto upstream {new_base[:12]}")
        self.assertEqual(run("git", "status", "--porcelain", cwd=self.repo).stdout, "")
        tree = self.build()
        self.assertEqual(self.subjects(tree), ["upstream moves", "alpha change", "rename the last row", INDEX])
        self.assertEqual((tree / "docs" / "table.md").read_text(), "| title |\n| --- |\n| first |\n| final |\n")
        # A parked directory needs its Base line.
        note = custom / "parked" / "g" / "NOTE.md"
        note.write_text(re.sub(r"^Base:.*\n", "", note.read_text(), flags=re.M))
        self.assertIn("custom/parked/g/NOTE.md needs a 'Base: <commit>' line", self.script("serieslib.py", "lint").stdout)

    def test_refresh_rehearsal_writes_nothing(self):
        new_base = self.upstream_moves()
        result = self.script("refresh.sh", "--rehearse", "--no-fetch", "--upstream", "upstream-next", "--no-upstream-check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"rehearsal: {self.base[:12]} -> {new_base[:12]}; nothing is written", result.stdout)
        self.assertIn("b: conflict (omnigent/beta.py)", result.stdout)
        self.assertIn("c: landed", result.stdout)
        self.assertEqual(run("git", "status", "--porcelain", cwd=self.repo).stdout, "")
        self.assertEqual((self.repo / "custom" / "BASE").read_text().strip(), self.base)

    def test_refresh_keeps_glue_in_step_with_its_series(self):
        self.add_row_series("d", "delta")
        self.add_row_series("e", "epsilon")
        make_glue(self.repo / "custom", "d+e", joins=("docs/table.md", "docs/alpha.md"))
        make_glue(self.repo / "custom", "a+c", joins=("docs/alpha.md",))
        self.commit("add d, e and glue")
        self.series("upstream-next", self.base, "upstream moves", {"docs/new.md": "# New\n"})
        self.write("custom/BASE", run("git", "rev-parse", "upstream-next", cwd=self.repo).stdout)
        result = self.script("serieslib.py", "refresh", "--no-upstream-check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("glue d+e: refreshed (no longer joined: docs/alpha.md)", result.stdout)
        self.assertIn("glue a+c: removed (the two series combine without it now)", result.stdout)
        self.assertIn("Joins: docs/table.md\n", (self.repo / "custom" / "glue" / "d+e" / "NOTE.md").read_text())
        self.assertFalse((self.repo / "custom" / "glue" / "a+c").exists())
        self.assertEqual(self.verify(), "")

    def refresh_with_gh(self, gh: str, *args: str) -> str:
        """serieslib.py refresh with a `gh` that runs this shell line; returns what it printed."""
        fake = Path(self.tmp.name, "bin")
        fake.mkdir(exist_ok=True)
        (fake / "gh").write_text(f"#!/bin/sh\n{gh}\n")
        (fake / "gh").chmod(0o755)
        command = [str(self.repo / "custom/scripts/serieslib.py"), "refresh", *args]
        env = {**GIT_ENV, "PATH": f"{fake}:{GIT_ENV['PATH']}"}
        return subprocess.run(command, cwd=self.repo, env=env, capture_output=True, text=True).stdout

    def test_refresh_runs_the_series_own_copy_of_a_test_it_changes(self):
        # d extends a test upstream already has, under the same name.
        self.series("work/d", self.base, "delta change\n\nDocs: none (test)",
                    {"omnigent/delta.py": "delta = 1\n", "tests/test_alpha.py": "def test_it():\n    assert delta_only\n"})
        self.export("d", "work/d")
        self.fill_notes()
        note = self.repo / "custom" / "patches" / "d" / "NOTE.md"
        note.write_text(note.read_text()
                        .replace("kept here only.", "pull request [#7](https://github.com/o/r/pull/7).")
                        .replace("## Tests\n\n- none (a stub)", "## Tests\n\n- `tests/test_alpha.py::test_it`"))
        self.commit("add d")
        merged = """echo '{"state": "MERGED"}'"""
        tip = self.script("build-custom.sh", "--series", "d", "--no-index", "work/d-built").stdout.strip()
        self.assertIn(f"run them there (the series' own copy: git checkout {tip[:12]} -- tests/test_alpha.py) "
                      "to see whether the series can go: tests/test_alpha.py::test_it\n", self.refresh_with_gh(merged))
        # BASE's copy of the test would pass this command; the series' copy does not.
        base_copy_only = "sh -c '! grep -q delta_only tests/test_alpha.py' --"
        self.assertIn("on bare BASE, in the series' own copy of tests/test_alpha.py, they fail (exit 1)",
                      self.refresh_with_gh(merged, "--landed-test-cmd", base_copy_only))

    def test_refresh_hints_at_a_series_whose_upstream_pull_request_merged(self):
        note = self.repo / "custom" / "patches" / "c" / "NOTE.md"
        note.write_text(note.read_text()
                        .replace("kept here only.", "pull request [#7](https://github.com/o/r/pull/7).")
                        .replace("- none (a stub)\n", "- `omnigent/gamma.py`: `gamma`\n", 1)
                        .replace("## Tests\n\n- none (a stub)", "## Tests\n\n- `tests/test_gamma.py::test_it`\n- `tests/test_new.py`"))
        self.commit("c is proposed upstream")
        refresh = self.refresh_with_gh
        merged = """echo '{"state": "MERGED"}'"""
        out = refresh(merged)
        self.assertIn("c: unchanged\n  hint: upstream #7 merged and 1 of the note's tests are on BASE; run them there "
                      "to see whether the series can go: tests/test_gamma.py::test_it\n", out)
        self.assertIn("on bare BASE they pass: the series looks landed, drop it", refresh(merged, "--landed-test-cmd", "true"))
        self.assertIn("on bare BASE they fail (exit 1)", refresh(merged, "--landed-test-cmd", "false"))
        self.assertNotIn("hint", refresh("""echo '{"state": "OPEN"}'"""))
        self.assertIn("(upstream check): skipped (gh could not be asked)", refresh("exit 1"))
        self.assertNotIn("upstream check", refresh("exit 1", "--no-upstream-check"))

    def test_recut_stops_on_a_conflict_and_says_how_to_finish(self):
        self.series("work/a", None, "alpha moves beta\n\nDocs: none (test)", {"omnigent/beta.py": "beta = 5\n"})
        self.export("a", "work/a")
        recut = self.script("serieslib.py", "recut", "b")
        self.assertIn("b: conflicts on its new foundation", recut.stdout)
        self.assertIn("git cherry-pick", recut.stdout)
        self.assertIn("custom/scripts/export.sh b work/b", recut.stdout)

    def test_export_needs_the_branch_on_the_foundation(self):
        result = self.script("export.sh", "b", "work/c")
        self.assertEqual(result.returncode, 2)
        self.assertIn("work/c is not built on the foundation of b (BASE plus a) (", result.stderr)
        result = self.script("export.sh", "--needs", "b", "a", "work/a")
        self.assertEqual(result.returncode, 2)
        self.assertIn("a cannot need itself", result.stderr)

    def test_export_changes_what_a_series_needs(self):
        # c moves on top of a: rebase its branch onto that foundation, then say so.
        onto = self.script("build-custom.sh", "--series", "a", "work/c-base").stdout.strip()
        run("git", "rebase", "-q", "--onto", onto, self.base, "work/c", cwd=self.work)
        result = self.export("c", "work/c", "--needs", "a")
        self.assertIn("wrote: c/NOTE.md (Needs: a)", result.stdout)
        self.assertEqual(self.subjects(self.build("--only", "c", "--no-index")), ["alpha change", "gamma change"])

    def test_select_tests_covers_only_the_set(self):
        tree = self.build()
        files, why = self.selected(tree, "--all")
        self.assertEqual(files, ["tests/test_alpha.py", "tests/test_beta.py", "tests/test_gamma.py"])
        self.assertTrue(why.startswith("all patches: "), why)
        files, why = self.selected(tree, "--all", "--set", "small")
        self.assertEqual(files, ["tests/test_alpha.py", "tests/test_beta.py"])
        self.assertTrue(why.startswith("all patches of set small: "), why)

    def test_select_tests_since_a_commit(self):
        tree = self.build()
        patch = self.repo / "custom" / "patches" / "c" / "01-gamma-change.patch"
        patch.write_text(patch.read_text().replace("+gamma = 2", "+gamma = 3"))
        self.commit("change a patch the set leaves out")
        self.assertEqual(self.selected(tree, "--since", self.first)[0], ["tests/test_gamma.py"])
        self.assertEqual(self.selected(tree, "--since", self.first, "--set", "small")[0], [])
        # Changing what the set holds selects everything it builds.
        second = self.commit_set("small", "b\nc\n")
        files, why = self.selected(tree, "--since", self.first, "--set", "small")
        self.assertEqual(files, ["tests/test_alpha.py", "tests/test_beta.py", "tests/test_gamma.py"])
        self.assertIn("set small changed", why)
        self.assertEqual(self.selected(tree, "--since", second, "--set", "small")[0], [])

    def commit_set(self, name: str, text: str) -> str:
        self.write(f"custom/sets/{name}.txt", text)
        return self.commit(f"change set {name}")

    def test_select_tests_ignores_a_renumbered_patch(self):
        tree = self.build()
        folder = self.repo / "custom" / "patches" / "c"
        (folder / "01-gamma-change.patch").rename(folder / "02-gamma-change.patch")
        self.commit("renumber a patch")
        files, why = self.selected(tree, "--since", self.first)
        self.assertEqual(files, [])
        self.assertIn("0 patch versions changed", why)


if __name__ == "__main__":
    unittest.main()
