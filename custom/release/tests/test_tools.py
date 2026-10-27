"""Unit tests for the release tooling: python3 -m unittest discover -s custom/release/tests"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

RELEASE = Path(__file__).resolve().parent.parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, RELEASE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


notes = load("notes")
hostlib = load("hostlib")
plan = load("plan")


class PinLinks(unittest.TestCase):
    def test_relative_links_point_at_the_fork_ref(self):
        text = "[a](../providers.md) [b](../../feature-map/x.md#anchor) [c](https://e.com) [d](#local)"
        out = notes.pin_links(text, "docs/custom/README.md", "o/r", "custom/2026-10-27.1")
        self.assertIn("(https://github.com/o/r/blob/custom/2026-10-27.1/docs/providers.md)", out)
        self.assertIn("(https://github.com/o/r/blob/custom/2026-10-27.1/feature-map/x.md#anchor)", out)
        self.assertIn("(https://e.com)", out)
        self.assertIn("(#local)", out)


class TouchedSections(unittest.TestCase):
    DOC = "\n".join(
        [
            "# Title",
            "intro",
            "## Alpha",
            "alpha text that is long enough",
            "### Alpha child",
            "child line added by the patch here",
            "## Beta",
            "beta line added by the patch here",
            "```",
            "# not a heading inside a fence",
            "```",
        ]
    )

    def test_nearest_heading_sections_with_breadcrumbs(self):
        added = ["child line added by the patch here", "beta line added by the patch here", ""]
        sections = notes.touched_sections(self.DOC, added)
        self.assertEqual([trail for trail, _ in sections], [["Title", "Alpha"], ["Title"]])
        self.assertTrue(sections[0][1].startswith("#### Alpha child"))
        self.assertIn("# not a heading inside a fence", sections[1][1])

    def test_lines_no_longer_present(self):
        self.assertIsNone(notes.touched_sections(self.DOC, ["a line some later patch rewrote"]))

    def test_long_sections_become_excerpts(self):
        filler = [f"- item {i} with enough words to be a block" for i in range(200)]
        doc = "\n".join(["## Big", *filler, "- the added item with enough words", "  continued line"])
        with mock.patch.object(notes, "SECTION_LIMIT", 100):
            [(_, body)] = notes.touched_sections(doc, ["- the added item with enough words"])
        self.assertEqual(body.splitlines(), ["#### Big", "", "- the added item with enough words", "  continued line"])


class ChangesSince(unittest.TestCase):
    def manifest(self, base, series):
        return {"tag": "t", "version": "v", "oss_commit": base, "series": series}

    def test_added_changed_dropped_and_base(self):
        old = self.manifest("a" * 40, [
            {"name": "keep", "patches": [{"patch_id": "1", "subject": "k"}]},
            {"name": "edit", "patches": [{"patch_id": "2", "subject": "old"}]},
            {"name": "gone", "patches": [{"patch_id": "3", "subject": "g"}]},
        ])
        new = self.manifest("b" * 40, [
            {"name": "keep", "patches": [{"patch_id": "1", "subject": "k"}]},
            {"name": "edit", "patches": [{"patch_id": "4", "subject": "new"}]},
            {"name": "fresh", "patches": [{"patch_id": "5", "subject": "f"}]},
        ])
        text = "\n".join(notes.changes_since(new, old))
        self.assertIn("**Base moved**", text)
        self.assertIn("**Added** `fresh`", text)
        self.assertIn("**Changed** `edit`: new or changed: new; removed: old.", text)
        self.assertIn("**Dropped** `gone`", text)
        self.assertIn("1 series unchanged", text)

    def test_first_release(self):
        self.assertIn("First release", notes.changes_since(self.manifest("a", []), None)[0])


class SeriesParsing(unittest.TestCase):
    def test_continued_blocks_join_their_series(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "series").write_text(
                "# header\n\n# series: a\n# needs: z\na--1.patch\n# series: b\nb--1.patch\n"
                "# series: a (continued)\na--2.patch\n"
            )
            parsed = notes.parse_series(Path(tmp))
        self.assertEqual([(s["name"], s["needs"], s["patches"]) for s in parsed],
                         [("a", ["z"], ["a--1.patch", "a--2.patch"]), ("b", [], ["b--1.patch"])])


class HostlibReleaseAssets(unittest.TestCase):
    def run_assets(self, release):
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(release))), redirect_stdout(out):
            hostlib.cmd_release_assets(SimpleNamespace())
        return out.getvalue().splitlines()

    def test_lists_name_and_url(self):
        lines = self.run_assets({"assets": [{"name": "a.whl", "browser_download_url": "https://x/a.whl"}]})
        self.assertEqual(lines, ["a.whl https://x/a.whl"])

    def test_rejects_unsafe_names(self):
        with self.assertRaises(SystemExit):
            self.run_assets({"assets": [{"name": "../x", "browser_download_url": "u"}]})


class PlanTags(unittest.TestCase):
    def plan(self, tags, messages=None, custom="c" * 40):
        argv = ["plan.py", "--fork", "o/r", "--custom", custom, "--patches-commit", "p" * 40, "--date", "2026-10-27"]
        out = io.StringIO()
        with mock.patch.object(plan, "remote_tags", return_value=tags), \
                mock.patch.object(plan, "tag_message", side_effect=lambda _f, t: (messages or {}).get(t, "")), \
                mock.patch.object(plan, "gh_api", return_value=[]), \
                mock.patch.object(sys, "argv", argv), redirect_stdout(out):
            plan.main()
        return dict(line.split("=", 1) for line in out.getvalue().splitlines())

    def test_counts_up_per_day(self):
        result = self.plan({"custom/2026-10-27.1": "x", "custom/2026-10-27.2": "y", "custom/2026-10-26.5": "z"})
        self.assertEqual(result["tag"], "custom/2026-10-27.3")
        self.assertEqual(result["resume"], "''")

    def test_resumes_the_same_build(self):
        tags = {"custom/2026-10-26.1": "c" * 40}
        result = self.plan(tags, {"custom/2026-10-26.1": "Patches-Commit: " + "p" * 40})
        self.assertEqual((result["tag"], result["resume"]), ("custom/2026-10-26.1", "1"))

    def test_same_commit_from_another_patches_commit_gets_a_new_tag(self):
        tags = {"custom/2026-10-27.1": "c" * 40}
        result = self.plan(tags, {"custom/2026-10-27.1": "Patches-Commit: " + "q" * 40})
        self.assertEqual(result["tag"], "custom/2026-10-27.2")


class InstalledVersion(unittest.TestCase):
    def test_a_checkout_in_the_current_directory_does_not_shadow_the_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp, "omnigent")
            package.mkdir()
            (package / "__init__.py").write_text("")
            (package / "__main__.py").write_text('print("omnigent 9.9 (deadbeef, built now)")')
            # Without isolation, `python -m omnigent` in a checkout runs the checkout.
            plain = subprocess.run([sys.executable, "-m", "omnigent"], cwd=tmp, capture_output=True, text=True)
            self.assertIn("deadbeef", plain.stdout)
            script = f'. "{RELEASE}/host-common.sh"; omnigent_short "{sys.executable}"; echo done'
            env = {**os.environ, "PYTHONPATH": tmp}
            out = subprocess.run(["bash", "-c", script], cwd=tmp, capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("deadbeef", out.stdout)
        self.assertIn("done", out.stdout)


if __name__ == "__main__":
    unittest.main()
