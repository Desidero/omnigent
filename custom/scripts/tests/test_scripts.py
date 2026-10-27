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


if __name__ == "__main__":
    unittest.main()
