"""Unit tests for the release tooling: python3 -m unittest discover -s custom/release/tests"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
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


def make_series(custom: Path, name: str, files: tuple[str, ...] = ("01-one.patch",), needs: tuple[str, ...] = ()) -> None:
    folder = custom / "patches" / name
    folder.mkdir(parents=True)
    (folder / "NOTE.md").write_text(f"# {name}\n\nNeeds: {', '.join(needs) or 'none'}\n\nAbout {name}.\n")
    for file in files:
        (folder / file).write_text("Subject: [PATCH] x\n\n---\n")


class SeriesParsing(unittest.TestCase):
    def test_series_come_from_the_directories_in_build_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_series(Path(tmp), "a", ("01-x.patch", "02-y.patch"), needs=("z",))
            make_series(Path(tmp), "b")
            make_series(Path(tmp), "z")
            parsed = notes.parse_series(Path(tmp))
        self.assertEqual([(s["name"], s["needs"], s["patches"]) for s in parsed],
                         [("b", [], ["b/01-one.patch"]), ("z", [], ["z/01-one.patch"]),
                          ("a", ["z"], ["a/01-x.patch", "a/02-y.patch"])])


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


class InstallHostExtras(unittest.TestCase):
    def installed(self, constraints: str) -> str:
        """The requirement install-host.sh hands to a stub `uv tool install`."""
        with tempfile.TemporaryDirectory() as tmp:
            release, stubs, tools = Path(tmp, "release dir"), Path(tmp, "stubs"), Path(tmp, "tools")
            for folder in (release, stubs, tools / "omnigent" / "bin"):
                folder.mkdir(parents=True)
            (release / "install-host.sh").write_bytes((RELEASE / "install-host.sh").read_bytes())
            (release / "omnigent-1.0-py3-none-any.whl").write_text("")
            (release / "constraints.txt").write_text(constraints)
            for stub, body in ((stubs / "uv", 'for arg; do last=$arg; done; echo "$last" > "$UV_STUB_OUT"'),
                               (tools / "omnigent" / "bin" / "omnigent", "echo omnigent 1.0")):
                stub.write_text(f"#!/bin/sh\n{body}\n")
                stub.chmod(0o755)
            # HOME is the temp dir, so the PATH the script prepends holds no real uv.
            env = {"HOME": tmp, "PATH": f"{stubs}:/usr/bin:/bin", "UV_TOOL_DIR": str(tools),
                   "UV_STUB_OUT": str(Path(tmp, "requirement"))}
            result = subprocess.run(["sh", str(release / "install-host.sh")], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return Path(tmp, "requirement").read_text().strip().removeprefix(str(release) + "/")

    def test_takes_the_antigravity_extra_when_the_release_pins_the_sdk(self):
        pinned = "absl-py==2.4.0\ngoogle-antigravity==0.1.23\n    # via omnigent\nprotobuf==7.35.1\n"
        self.assertEqual(self.installed(pinned), "omnigent-1.0-py3-none-any.whl[antigravity]")

    def test_installs_the_bare_wheel_with_constraints_that_do_not_pin_it(self):
        # An older release, or a rollback copy with an empty constraints.txt.
        self.assertEqual(self.installed("protobuf==6.33.6\n"), "omnigent-1.0-py3-none-any.whl")
        self.assertEqual(self.installed(""), "omnigent-1.0-py3-none-any.whl")


GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, env=GIT_ENV, capture_output=True, text=True, check=True).stdout.strip()


class PlanSetTags(unittest.TestCase):
    """A build set's tags, custom/<date>.<n>-<set>, live beside the whole series' tags."""

    def plan(self, tags, set_name="", messages=None, releases=()):
        argv = ["plan.py", "--fork", "o/r", "--custom", "c" * 40, "--patches-commit", "p" * 40, "--date", "2026-10-27"]
        if set_name:
            argv += ["--set", set_name]
        out = io.StringIO()
        with mock.patch.object(plan, "remote_tags", return_value=tags), \
                mock.patch.object(plan, "tag_message", side_effect=lambda _f, t: (messages or {}).get(t, "")), \
                mock.patch.object(plan, "gh_api", return_value=[{"tag_name": name} for name in releases]), \
                mock.patch.object(sys, "argv", argv), redirect_stdout(out):
            plan.main()
        return dict(line.split("=", 1) for line in out.getvalue().splitlines())

    def test_a_set_counts_its_own_tags(self):
        tags = {"custom/2026-10-27.1": "x", "custom/2026-10-27.2": "y", "custom/2026-10-27.1-core": "z"}
        self.assertEqual(self.plan(tags, "core")["tag"], "custom/2026-10-27.2-core")
        self.assertEqual(self.plan(tags, "lean")["tag"], "custom/2026-10-27.1-lean")

    def test_the_whole_series_does_not_count_set_tags(self):
        tags = {"custom/2026-10-27.1": "x", "custom/2026-10-27.7-core": "z"}
        self.assertEqual(self.plan(tags)["tag"], "custom/2026-10-27.2")

    def test_a_build_resumes_only_a_tag_of_its_own_kind(self):
        # A set that holds every series builds the same commit as the whole series.
        same = "Patches-Commit: " + "p" * 40
        tags = {"custom/2026-10-26.1": "c" * 40, "custom/2026-10-26.1-core": "c" * 40}
        messages = dict.fromkeys(tags, same)
        whole, core = self.plan(tags, messages=messages), self.plan(tags, "core", messages=messages)
        self.assertEqual((whole["tag"], whole["resume"]), ("custom/2026-10-26.1", "1"))
        self.assertEqual((core["tag"], core["resume"]), ("custom/2026-10-26.1-core", "1"))
        lean = self.plan(tags, "lean", messages=messages)
        self.assertEqual((lean["tag"], lean["resume"]), ("custom/2026-10-27.1-lean", "''"))

    def test_the_previous_release_is_of_the_same_kind(self):
        releases = ["custom/2026-10-26.2-core", "custom/2026-10-26.1", "custom/2026-10-25.1-core"]
        self.assertEqual(self.plan({}, releases=releases)["previous_tag"], "custom/2026-10-26.1")
        self.assertEqual(self.plan({}, "core", releases=releases)["previous_tag"], "custom/2026-10-26.2-core")
        self.assertEqual(self.plan({}, "lean", releases=releases)["previous_tag"], "''")

    def test_a_name_that_is_not_a_set_name(self):
        for name in ("Core", "my-set", "dirty", "1st"):
            with self.assertRaises(SystemExit, msg=name), redirect_stdout(io.StringIO()):
                self.plan({}, name)


class SetSeriesAndNotes(unittest.TestCase):
    def test_series_json_keeps_only_the_named_series(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a", "b", "c"):
                make_series(Path(tmp), name)
            with mock.patch.object(notes.serieslib, "patch_id", return_value="i"):
                every = notes.series_json(Path(tmp))
                some = notes.series_json(Path(tmp), {"a", "c"})
        self.assertEqual(every[0]["patches"], [{"file": "a/01-one.patch", "subject": "x", "patch_id": "i"}])
        self.assertEqual([entry["name"] for entry in every], ["a", "b", "c"])
        self.assertEqual([entry["name"] for entry in some], ["a", "c"])

    def test_series_json_lists_the_glue_among_the_series(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a", "b", "c"):
                make_series(Path(tmp), name)
            for pair in ("a+b", "c+a"):
                Path(tmp, "glue", pair).mkdir(parents=True)
                Path(tmp, "glue", pair, "NOTE.md").write_text(f"# {pair}\n\nJoins: docs/x.md, y.py\n\nWhy.\n")
            with mock.patch.object(notes.serieslib, "patch_id", return_value="i"):
                every = notes.series_json(Path(tmp))
                some = notes.series_json(Path(tmp), {"a", "b"})
        self.assertEqual([entry["name"] for entry in every], ["c", "a", "b", "a+b", "c+a"])
        self.assertEqual(every[-1], {"name": "c+a", "glue": True, "needs": ["c", "a"], "joins": ["docs/x.md", "y.py"],
                                     "patches": []})
        self.assertEqual([entry["name"] for entry in some], ["a", "b", "a+b"])
        # Glue is not a series: the notes count and document series only.
        manifest = {"tag": "t", "version": "v", "oss_commit": "x", "series": every}
        changed = notes.changes_since({**manifest, "series": every[:3]}, manifest)
        self.assertIn("- **Dropped** glue `a+b`.", changed)

    def render(self, extra: dict) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("a", "b"):
                make_series(root / "custom", name)
            (root / "tree").mkdir()
            manifest = {"tag": "custom/2026-10-27.1-core", "version": "1.0", "commit": "c" * 40,
                        "patches_commit": "p" * 40, "image": "i:t",
                        "series": [{"name": "a", "needs": [], "patches": []}], **extra}
            (root / "manifest.json").write_text(json.dumps(manifest))
            args = SimpleNamespace(manifest=str(root / "manifest.json"), previous_manifest=None, tree=str(root / "tree"),
                                   custom=str(root / "custom"), fork="o/r", note=None,
                                   notes=str(root / "notes.md"), docs=str(root / "docs.md"))
            notes.render(args)
            return (root / "notes.md").read_text(), (root / "docs.md").read_text()

    def test_a_set_build_says_so_and_documents_only_its_series(self):
        body, docs = self.render({"set": "core"})
        self.assertIn("- **Set:** `core`", body)
        self.assertIn(f"https://github.com/o/r/blob/{'p' * 40}/custom/sets/core.txt", body)
        self.assertIn("## a", docs)
        self.assertNotIn("## b", docs)

    def test_the_whole_series_has_no_set_line(self):
        body, docs = self.render({})
        self.assertNotIn("**Set:**", body)
        self.assertIn("## b", docs)


class BuildNames(unittest.TestCase):
    """The names build.sh gives a build, read with --names-only (nothing is built)."""

    # PEP 440's own pattern for a public version with a local label (lowercase form).
    PEP440 = re.compile(r"^\d+(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?(\+[a-z0-9]+(\.[a-z0-9]+)*)?$")
    DOCKER_TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.tree = root / "tree"
        self.tree.mkdir()
        git(self.tree, "init", "-q", "-b", "main")
        (self.tree / "pyproject.toml").write_text('[project]\nname = "omnigent"\nversion = "0.24.0.dev0"\n')
        git(self.tree, "add", "-A")
        git(self.tree, "commit", "-q", "-m", "base")
        self.base = git(self.tree, "rev-parse", "HEAD")
        self.custom = root / "custom"
        for folder in ("release", "scripts", "sets"):
            (self.custom / folder).mkdir(parents=True)
        (self.custom / "release" / "build.sh").write_bytes((RELEASE / "build.sh").read_bytes())
        for name in ("series-files.sh", "serieslib.py"):
            (self.custom / "scripts" / name).write_bytes((RELEASE.parent / "scripts" / name).read_bytes())
            (self.custom / "scripts" / name).chmod(0o755)
        (self.custom / "BASE").write_text(self.base + "\n")
        # Real one-file series, each exported from its own branch on BASE.
        for name, subjects in (("a", ("one",)), ("b", ("two",)), ("c", ("x", "y")), ("d", ("z",))):
            git(self.tree, "switch", "-q", "-c", f"work/{name}", self.base)
            for subject in subjects:
                (self.tree / f"{name}-{subject}.md").write_text(subject + "\n")
                git(self.tree, "add", "-A")
                git(self.tree, "commit", "-q", "-m", f"{subject}\n\nDocs: none (test)")
            self.lib("export", "--repo", str(self.tree), name, f"work/{name}")
        (self.custom / "sets" / "core.txt").write_text("a\nb\n")
        (self.custom / "sets" / "tiny.txt").write_text("a\n")
        self.build_sh = self.custom / "release" / "build.sh"
        self.checkout()

    def tearDown(self):
        self.tmp.cleanup()

    def lib(self, *args: str) -> str:
        command = [sys.executable, str(self.custom / "scripts" / "serieslib.py"), *args]
        return subprocess.run(command, env=GIT_ENV, capture_output=True, text=True, check=True).stdout.strip()

    def checkout(self, *selection: str) -> None:
        """Put the tree at the commit the whole series, or a set, builds to."""
        git(self.tree, "checkout", "-q", "--detach", self.lib("build", "--repo", str(self.tree), *selection))

    def names(self, *args: str, check: bool = True, checkout: bool = True) -> dict[str, str]:
        if checkout:
            self.checkout(*(["--set", args[args.index("--set") + 1]] if "--set" in args else []))
        command = ["bash", str(self.build_sh), "--tree", str(self.tree), "--names-only", "--patches-commit", "0123abc" * 6,
                   "--image", "ghcr.io/o/r", *args]
        result = subprocess.run(command, env=GIT_ENV, capture_output=True, text=True)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        self.stderr = result.stderr
        return dict(line.split("=", 1) for line in result.stdout.splitlines())

    def test_the_whole_series_keeps_its_names(self):
        names = self.names()
        self.assertEqual(names["VERSION"], f"0.24.0.dev0+oss{self.base[:8]}.p0123abc")
        self.assertEqual(names["TAG"], f"build/oss{self.base[:8]}.p0123abc")
        self.assertNotIn("BUILD_SET", names)
        self.assertEqual(list(names), ["VERSION", "BUILD_ID", "TAG", "IMAGE", "CUSTOM_COMMIT", "OSS_COMMIT",
                                       "PATCHES_COMMIT", "FORK_REPO"])
        released = self.names("--tag", "custom/2026-10-27.1")
        self.assertEqual(released["IMAGE"], "ghcr.io/o/r:custom-2026-10-27.1")

    def test_a_set_is_named_in_the_version_the_tag_and_the_image(self):
        names = self.names("--set", "core")
        self.assertEqual(names["VERSION"], f"0.24.0.dev0+oss{self.base[:8]}.p0123abc.core")
        self.assertEqual(names["BUILD_ID"], f"oss{self.base[:8]}.p0123abc.core")
        self.assertEqual(names["TAG"], f"build/oss{self.base[:8]}.p0123abc.core")
        self.assertEqual(names["BUILD_SET"], "core")
        released = self.names("--set", "core", "--tag", "custom/2026-10-27.1-core")
        self.assertEqual(released["IMAGE"], "ghcr.io/o/r:custom-2026-10-27.1-core")
        self.assertNotEqual(released["IMAGE"], self.names("--tag", "custom/2026-10-27.1")["IMAGE"])

    def test_set_names_stay_valid_versions_git_tags_and_docker_tags(self):
        longest = "z" + "9" * 19
        (self.build_sh.parent.parent / "sets" / f"{longest}.txt").write_text("a\nb\n")
        for set_name in ("core", longest):
            for tag in (None, f"custom/2026-10-27.12-{set_name}"):
                names = self.names("--set", set_name, *(["--tag", tag] if tag else []))
                self.assertRegex(names["VERSION"], self.PEP440)
                self.assertRegex(names["IMAGE"].rpartition(":")[2], self.DOCKER_TAG)
                git(self.tree, "check-ref-format", f"refs/tags/{names['TAG']}")
                try:
                    from packaging.version import Version
                except ImportError:
                    continue
                # A canonical version: the wheel's file name will carry it unchanged.
                self.assertEqual(str(Version(names["VERSION"])), names["VERSION"])

    def test_the_tree_must_be_at_the_commit_the_selection_builds(self):
        self.checkout("--set", "core")
        self.assertEqual(self.names("--set", "tiny", check=False, checkout=False), {})
        self.assertIn("not the build of set tiny of the series", self.stderr)
        self.assertEqual(self.names(check=False, checkout=False), {})
        self.assertIn("not the build of the series", self.stderr)
        self.assertEqual(self.names("--set", "absent", check=False, checkout=False), {})
        self.assertIn("no set named absent", self.stderr)


class PublishSet(unittest.TestCase):
    """publish.sh as a dry run for a set build: nothing leaves the machine."""

    def publish(self, tag: str, build_set: str, prerelease: str = "true") -> subprocess.CompletedProcess:
        root = Path(self.tmp.name)
        out = root / "out"
        (out / "release").mkdir(parents=True, exist_ok=True)
        (out / "release" / "omnigent-1.0-py3-none-any.whl").write_text("")
        (out / "notes.md").write_text("notes\n")
        lines = ["VERSION=1.0+ossabc.p123", "BUILD_ID=ossabc.p123", f"TAG={tag}", "IMAGE=ghcr.io/o/r:t",
                 f"CUSTOM_COMMIT={self.commit}", "OSS_COMMIT=abc", "PATCHES_COMMIT=123", "FORK_REPO=o/r"]
        if build_set:
            lines.append(f"BUILD_SET={build_set}")
        (out / "build.env").write_text("\n".join(lines) + "\n")
        env = {key: value for key, value in GIT_ENV.items() if key not in ("GITHUB_STEP_SUMMARY", "PUSH_SSH_KEY", "PUSH_TOKEN")}
        env.update(DRY_RUN="true", PRERELEASE=prerelease, OMNIGENT_CLONE=str(self.repo), FORK_REPO="o/r")
        return subprocess.run(["bash", str(RELEASE / "publish.sh"), str(out), self.commit],
                              env=env, capture_output=True, text=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name, "repo")
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "built")
        self.commit = git(self.repo, "rev-parse", "HEAD")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_set_release_is_tagged_but_does_not_move_custom(self):
        result = self.publish("custom/2026-10-27.1-core", "core")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("custom is not moved", result.stdout)
        self.assertNotIn("refs/heads/custom", result.stdout)
        self.assertIn("refs/tags/custom/2026-10-27.1-core", result.stdout)
        self.assertIn("--prerelease", result.stdout)
        message = git(self.repo, "tag", "-l", "--format=%(contents)", "custom/2026-10-27.1-core")
        self.assertIn("\nSet: core", message)
        self.assertIn("\nPatches-Commit: 123\n", message)

    def test_a_set_release_is_never_the_latest(self):
        result = self.publish("custom/2026-10-27.1-core", "core", prerelease="false")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--latest=false", result.stdout)
        self.assertNotIn("--prerelease", result.stdout)

    def test_the_tag_and_the_set_must_agree(self):
        for tag, build_set in (("custom/2026-10-27.1", "core"), ("custom/2026-10-27.1-lean", "core"),
                               ("custom/2026-10-27.1-core", "")):
            result = self.publish(tag, build_set)
            self.assertEqual(result.returncode, 1, (tag, build_set))
            self.assertEqual(git(self.repo, "tag", "-l"), "", (tag, build_set))


if __name__ == "__main__":
    unittest.main()
