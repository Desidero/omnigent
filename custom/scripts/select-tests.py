#!/usr/bin/env python3
"""Pick the tests to run for a change to the series: the ones near what it touches.

  custom/scripts/select-tests.py --tree <built tree> --out <dir> [--since <ref> | --all] [--set <name>]

--since REF   the patches that differ from REF (a patch-id change, an added or a
              removed patch) on the patches branch; a moved custom/BASE (an
              upstream refresh) selects the whole series
--all         every patch in the series
--set NAME    only the patches of that build set (custom/sets/NAME.txt, with
              the series it needs); a change to the set file selects them all

Writes <dir>/pytest.txt (test files), <dir>/vitest-run.txt (web test files)
and <dir>/vitest-related.txt (web sources for `vitest related`), one path per
line, relative to the tree (web paths relative to web/). For each touched
Python module it takes tests/**/test_<module>.py and test_<module>_*.py; a
touched test file runs itself. Lanes that need a browser, a live server or a
benchmark rig are left to upstream's CI.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # custom/
TOP = ROOT.parent  # the Omnigent checkout of the patches branch
SKIP_TEST_DIRS = ("e2e", "e2e_ui", "e2e_live", "browser_ui", "benchmarks", "loadtest", "harness_bench")
PYTEST_LIMIT = 250
WEB_SOURCE_RE = re.compile(r"^web/src/.*\.(ts|tsx)$")
WEB_TEST_RE = re.compile(r"\.test\.(ts|tsx)$")


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


def touched_files(patch_text: str) -> set[str]:
    files = set()
    for match in re.finditer(r"^diff --git a/(\S+) b/(\S+)$", patch_text, re.M):
        files.update(match.groups())
    return files


def patch_id(text: str) -> str:
    result = subprocess.run(["git", "patch-id", "--stable"], input=text, capture_output=True, text=True, check=True)
    return result.stdout.split(" ", 1)[0]


def set_series(name: str | None) -> set[str] | None:
    """The series a build set holds, with the ones they need; None means every series."""
    if not name:
        return None
    result = subprocess.run(
        [str(ROOT / "scripts" / "series-files.sh"), "--set", name, "--names"], capture_output=True, text=True
    )
    if result.returncode != 0:
        sys.exit(result.stderr.strip().splitlines()[-1])
    return set(result.stdout.split())


def in_set(patch: str, only: set[str] | None) -> bool:
    """Whether a patch file (<series>--<subject>.patch) belongs to one of the series."""
    return only is None or Path(patch).name.split("--", 1)[0] in only


def series_patches(only: set[str] | None = None) -> list[str]:
    lines = (ROOT / "series").read_text().splitlines()
    names = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
    return [name for name in names if in_set(name, only)]


def changed_patch_texts(since: str | None, set_name: str | None = None) -> tuple[list[str], str]:
    """Texts of the patches to cover, and why."""
    only = set_series(set_name)
    current = series_patches(only)
    scope = f" of set {set_name}" if set_name else ""
    if since is None:
        return [(ROOT / "patches" / name).read_text() for name in current], f"all patches{scope}"
    # git runs in custom/, where a bare pathspec would mean custom/custom/...; anchor at the top.
    paths = [":/custom/BASE", ":/custom/series", ":/custom/patches/"]
    set_path = f"custom/sets/{set_name}.txt"
    if set_name:
        paths.append(f":/{set_path}")
    names = git("diff", "--name-only", f"{since}...HEAD", "--", *paths).split()
    if "custom/BASE" in names:
        return [(ROOT / "patches" / name).read_text() for name in current], f"BASE moved: all patches{scope}"
    if set_name and set_path in names:
        return [(ROOT / "patches" / name).read_text() for name in current], f"set {set_name} changed: all its patches"
    texts = []
    for path in names:
        if not path.endswith(".patch") or not in_set(path, only):
            continue
        new_file = TOP / path
        try:
            old_text = git("show", f"{since}:{path}")
        except subprocess.CalledProcessError:
            old_text = ""
        new_text = new_file.read_text() if new_file.is_file() else ""
        if old_text and new_text and patch_id(old_text) == patch_id(new_text):
            continue  # only blob ids or line numbers moved
        texts += [text for text in (old_text, new_text) if text]
    return texts, f"{len(texts)} patch versions{scope} changed since {since}"


def python_tests(tree: Path, files: set[str]) -> list[str]:
    tests_dir = tree / "tests"
    all_tests = [
        path.relative_to(tree).as_posix()
        for path in tests_dir.rglob("test_*.py")
        if path.relative_to(tests_dir).parts[0] not in SKIP_TEST_DIRS
    ]
    by_name: dict[str, list[str]] = {}
    for test in all_tests:
        by_name.setdefault(Path(test).name, []).append(test)
    direct, matched = [], []
    for path in sorted(files):
        if not path.endswith(".py") or not (tree / path).is_file():
            continue
        if path.startswith("tests/"):
            if Path(path).name.startswith("test_") and path in all_tests:
                direct.append(path)
            continue
        if not path.startswith(("omnigent/", "sdks/")):
            continue
        stem = Path(path).stem
        if stem == "__init__":
            stem = Path(path).parent.name
        stem = stem.lstrip("_")
        for name, tests in by_name.items():
            if name == f"test_{stem}.py" or name.startswith(f"test_{stem}_"):
                matched.extend(tests)
    ordered = list(dict.fromkeys(direct + sorted(set(matched))))
    if len(ordered) > PYTEST_LIMIT:
        print(f"note: {len(ordered)} test files matched; running the first {PYTEST_LIMIT}", file=sys.stderr)
        ordered = ordered[:PYTEST_LIMIT]
    return ordered


def web_targets(tree: Path, files: set[str]) -> tuple[list[str], list[str]]:
    tests, sources = [], []
    for path in sorted(files):
        if not WEB_SOURCE_RE.match(path) or not (tree / path).is_file():
            continue
        relative = path.removeprefix("web/")
        (tests if WEB_TEST_RE.search(path) else sources).append(relative)
    return tests, sources


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--out", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--since")
    group.add_argument("--all", action="store_true")
    parser.add_argument("--set", dest="set_name")
    args = parser.parse_args()
    tree, out = Path(args.tree), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    texts, why = changed_patch_texts(None if args.all else args.since, args.set_name)
    files: set[str] = set()
    for text in texts:
        files |= touched_files(text)
    pytest_files = python_tests(tree, files)
    vitest_run, vitest_related = web_targets(tree, files)
    (out / "pytest.txt").write_text("".join(f"{p}\n" for p in pytest_files))
    (out / "vitest-run.txt").write_text("".join(f"{p}\n" for p in vitest_run))
    (out / "vitest-related.txt").write_text("".join(f"{p}\n" for p in vitest_related))
    print(
        f"{why}: {len(files)} files touched; {len(pytest_files)} pytest files, "
        f"{len(vitest_run)} web test files, {len(vitest_related)} web sources for vitest related"
    )


if __name__ == "__main__":
    main()
