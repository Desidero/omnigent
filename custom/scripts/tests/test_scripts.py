"""Tests for the patches-branch scripts: python3 -m unittest discover -s custom/scripts/tests"""

from __future__ import annotations

import os
import subprocess
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


def run(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, env=GIT_ENV, capture_output=True, text=True, check=check)


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
    SERIES = "\n".join(
        [
            "# header",
            "",
            "# series: a",
            "a--one.patch",
            "# series: b",
            "# needs: a",
            "b--one.patch",
            "# series: a (continued)",
            "a--two.patch",
            "# series: c",
            "# needs: b",
            "c--one.patch",
            "",
        ]
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "scripts").mkdir()
        (root / "scripts" / "series-files.sh").write_bytes((SCRIPTS / "series-files.sh").read_bytes())
        (root / "series").write_text(self.SERIES)
        self.script = root / "scripts" / "series-files.sh"
        self.patches = root / "patches"

    def tearDown(self):
        self.tmp.cleanup()

    def names(self, *args: str) -> list[str]:
        out = run("bash", str(self.script), *args).stdout.splitlines()
        for line in out:
            self.assertEqual(Path(line).parent, self.patches)
        return [Path(line).name for line in out]

    def test_one_series_in_apply_order_with_its_continuation(self):
        self.assertEqual(self.names("a"), ["a--one.patch", "a--two.patch"])

    def test_needs_are_followed_recursively(self):
        self.assertEqual(
            self.names("--needs", "c"), ["a--one.patch", "b--one.patch", "a--two.patch", "c--one.patch"]
        )

    def test_unknown_series(self):
        result = run("bash", str(self.script), "nope", check=False)
        self.assertEqual(result.returncode, 2)


class SeriesFilesOnly(unittest.TestCase):
    SERIES = "\n".join(
        [
            "# header",
            "",
            "# series: a",
            "a--one.patch",
            "a--two.patch",
            "# series: b",
            "# needs: a",
            "b--one.patch",
            "# series: c",
            "c--one.patch",
            "# series: d",
            "# needs: b",
            "# needs: c",
            "d--one.patch",
            "# series: custom-docs-index",
            "custom-docs-index--one.patch",
            "",
        ]
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "scripts").mkdir()
        (root / "scripts" / "series-files.sh").write_bytes((SCRIPTS / "series-files.sh").read_bytes())
        (root / "series").write_text(self.SERIES)
        self.script = root / "scripts" / "series-files.sh"

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_adds_needs_and_the_index_in_series_order(self):
        result = run("bash", str(self.script), "--only", "d,c")
        self.assertEqual(
            [Path(line).name for line in result.stdout.splitlines()],
            ["a--one.patch", "a--two.patch", "b--one.patch", "c--one.patch", "d--one.patch",
             "custom-docs-index--one.patch"],
        )
        self.assertIn("added a (needed by b)", result.stderr)
        self.assertIn("added b (needed by d)", result.stderr)
        self.assertIn("added custom-docs-index (always included)", result.stderr)
        self.assertNotIn("added c (", result.stderr)

    def test_only_names_and_repeated_option(self):
        result = run("bash", str(self.script), "--only", "c", "--only", "b", "--names")
        self.assertEqual(result.stdout.splitlines(), ["a", "b", "c", "custom-docs-index"])

    def test_only_unknown_series(self):
        result = run("bash", str(self.script), "--only", "a,nope", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("no series named nope", result.stderr)


class SeriesFilesSet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "scripts").mkdir()
        (root / "sets").mkdir()
        (root / "scripts" / "series-files.sh").write_bytes((SCRIPTS / "series-files.sh").read_bytes())
        (root / "series").write_text(SeriesFilesOnly.SERIES)
        self.script = root / "scripts" / "series-files.sh"
        self.sets = root / "sets"

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_set_is_only_with_the_series_its_file_lists(self):
        (self.sets / "small.txt").write_text("# what it is for\n\nd  # with a note\nc\n")
        by_set = run("bash", str(self.script), "--set", "small")
        by_only = run("bash", str(self.script), "--only", "d,c")
        self.assertEqual(by_set.stdout, by_only.stdout)
        self.assertIn("added custom-docs-index (always included)", by_set.stderr)
        names = run("bash", str(self.script), "--set", "small", "--names").stdout.splitlines()
        self.assertEqual(names, ["a", "b", "c", "d", "custom-docs-index"])

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


class BuildSets(unittest.TestCase):
    """build-custom.sh, check.sh and select-tests.py on a small real series, whole and as a set."""

    SERIES = "\n".join(
        [
            "# series: a",
            "a--alpha-change.patch",
            "# series: b",
            "# needs: a",
            "b--beta-change.patch",
            "# series: c",
            "c--gamma-change.patch",
            "# series: custom-docs-index",
            "custom-docs-index--index-the-series.patch",
            "",
        ]
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name, "repo")
        self.repo.mkdir()
        run("git", "init", "-q", "-b", "main", cwd=self.repo)
        for name in ("alpha", "beta", "gamma"):
            self.write(f"omnigent/{name}.py", f"{name} = 1\n")
            self.write(f"tests/test_{name}.py", "def test_it():\n    pass\n")
        self.base = self.commit("upstream base")
        # The series as commits, then exported the way a contributor would.
        run("git", "switch", "-q", "-c", "work", cwd=self.repo)
        self.write("omnigent/alpha.py", "alpha = 2\n")
        self.write("docs/alpha.md", "# Alpha\n")
        self.commit("alpha change")
        self.write("omnigent/beta.py", "beta = 2\n")
        self.commit("beta change\n\nNothing to document.\n\nDocs: none (test)")
        self.write("omnigent/gamma.py", "gamma = 2\n")
        self.write("docs/gamma.md", "# Gamma\n")
        self.commit("gamma change")
        sections = "".join(f"## {name}\n\nAbout {name}.\n\n" for name in ("a", "b", "c", "custom-docs-index"))
        self.write("docs/custom/README.md", "# The series\n\n" + sections)
        self.commit("index the series")
        run("git", "switch", "-q", "-c", "patches", self.base, cwd=self.repo)
        scripts = self.repo / "custom" / "scripts"
        scripts.mkdir(parents=True)
        for script in ("build-custom.sh", "check.sh", "export.sh", "series-files.sh", "select-tests.py"):
            (scripts / script).write_bytes((SCRIPTS / script).read_bytes())
            (scripts / script).chmod(0o755)
        self.write("custom/series", self.SERIES)
        self.write("custom/sets/small.txt", "# b, and a because b needs it\nb\n")
        run(str(scripts / "export.sh"), "work", "main", cwd=self.repo)
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

    def script(self, name: str, *args: str) -> subprocess.CompletedProcess:
        return run(str(self.repo / "custom" / "scripts" / name), *args, cwd=self.repo, check=False)

    def build(self, *args: str) -> Path:
        tree = Path(tempfile.mkdtemp(dir=self.tmp.name), "tree")
        result = self.script("build-custom.sh", *args, "--worktree", str(tree))
        self.assertEqual(result.returncode, 0, result.stderr)
        return tree

    def selected(self, tree: Path, *args: str) -> tuple[list[str], str]:
        out = Path(tempfile.mkdtemp(dir=self.tmp.name))
        result = self.script("select-tests.py", "--tree", str(tree), "--out", str(out), *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return (out / "pytest.txt").read_text().split(), result.stdout

    def test_a_set_builds_its_series_what_they_need_and_a_trimmed_index(self):
        tree = self.build("--set", "small")
        subjects = run("git", "log", "--reverse", "--format=%s", f"{self.base}..HEAD", cwd=tree).stdout.splitlines()
        self.assertEqual(subjects, ["alpha change", "beta change", "index the series"])
        self.assertEqual((tree / "omnigent" / "gamma.py").read_text(), "gamma = 1\n")
        index = (tree / "docs" / "custom" / "README.md").read_text()
        self.assertIn("## b\n", index)
        self.assertNotIn("## c\n", index)
        # The same set gives the same commits again; the whole series gives others.
        again = self.build("--set", "small")
        whole = self.build()
        head = [run("git", "rev-parse", "HEAD", cwd=path).stdout for path in (tree, again, whole)]
        self.assertEqual(head[0], head[1])
        self.assertNotEqual(head[0], head[2])

    def test_check_takes_the_whole_series_or_a_set(self):
        whole = self.script("check.sh")
        self.assertEqual(whole.returncode, 0, whole.stderr)
        self.assertRegex(whole.stdout, rf"\A4 patches apply on {self.base[:12]} as [0-9a-f]{{12}}\n\Z")
        small = self.script("check.sh", "--set", "small")
        self.assertEqual(small.returncode, 0, small.stderr)
        self.assertIn("3 patches of set small apply", small.stdout)

    def test_check_tree_must_be_a_build_of_the_set(self):
        whole, small = self.build(), self.build("--set", "small")
        self.assertEqual(self.script("check.sh", "--tree", str(small), "--set", "small").returncode, 0)
        self.assertEqual(self.script("check.sh", "--tree", str(whole)).returncode, 0)
        for tree, args in ((whole, ("--set", "small")), (small, ())):
            result = self.script("check.sh", "--tree", str(tree), *args)
            self.assertEqual(result.returncode, 1)
            self.assertIn("rebuild it", result.stdout)
        # Same number of commits, other series: the index gives it away.
        self.write("custom/sets/other.txt", "a\nc\n")
        other = self.build("--set", "other")
        result = self.script("check.sh", "--tree", str(other), "--set", "small")
        self.assertEqual(result.returncode, 1)
        self.assertIn("set small leaves c out", result.stderr)

    def test_check_rejects_a_set_file_that_names_a_missing_series(self):
        self.write("custom/sets/broken.txt", "a\ndropped\n")
        result = self.script("check.sh")
        self.assertEqual(result.returncode, 1)
        self.assertIn("set broken: no series named dropped", result.stderr)

    def test_check_with_an_unknown_set(self):
        result = self.script("check.sh", "--set", "absent")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no set named absent", result.stderr)

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
        patch = self.repo / "custom" / "patches" / "c--gamma-change.patch"
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


if __name__ == "__main__":
    unittest.main()
