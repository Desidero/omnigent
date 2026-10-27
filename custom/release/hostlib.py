"""Helpers for the release host scripts: manifests, env files, plists, drop-ins.

Run with the omnigent uv tool's python (or any python >= 3.8); stdlib only, so
the macOS plist logic can be tested on Linux. Values of secret-looking names
are never printed.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import plistlib
import re
import shlex
import sys
import tempfile
import time
import urllib.parse
import zipfile
from pathlib import Path

# Variables `omnigent host enable` copies from an interactive shell that do not
# belong in a service environment (terminal, SSH agent and shell state).
LEFTOVER_NAMES = frozenset(
    {
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "SSH_CLIENT",
        "SSH_CONNECTION",
        "SSH_TTY",
        "TERM",
        "TERMINFO",
        "TERMINFO_DIRS",
        "TERM_PROGRAM",
        "TERM_PROGRAM_VERSION",
        "TERM_SESSION_ID",
        "COLORTERM",
        "LC_TERMINAL",
        "LC_TERMINAL_VERSION",
        "TMUX",
        "TMUX_PANE",
        "SHLVL",
        "PWD",
        "OLDPWD",
        "_",
        "__CFBundleIdentifier",
        "XPC_SERVICE_NAME",
        "XPC_FLAGS",
    }
)
LEFTOVER_PREFIXES = ("GHOSTTY_", "ITERM_", "KITTY_", "WEZTERM_", "VSCODE_")
# PATH entries that only make sense inside a terminal app or a login shell.
LEFTOVER_PATH_RE = re.compile(r"ghostty|cryptex", re.IGNORECASE)
SECRET_NAME_RE = re.compile(
    r"TOKEN|SECRET|PASSWORD|PASSWD|KEY|AUTH|CREDENTIAL|HEADERS|COOKIE|DATABASE|DSN", re.I
)
URL_CREDENTIALS_RE = re.compile(r"(://)[^/@\s:]+:[^/@\s]+@")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Keys in a host.env that configure the scripts instead of the service.
SCRIPT_KEY_PREFIX = "RELEASE_"
DATE_COMMENT_RE = re.compile(r"^#\s*created:\s*(\d{4}-\d{2}-\d{2})", re.I)


def is_leftover(name: str) -> bool:
    return name in LEFTOVER_NAMES or name.startswith(LEFTOVER_PREFIXES)


def redact(name: str, value: str) -> str:
    if SECRET_NAME_RE.search(name):
        return f"<redacted, {len(value)} chars>"
    return URL_CREDENTIALS_RE.sub(r"\1<redacted>@", value)


def fail(message: str) -> None:
    print(f"hostlib: {message}", file=sys.stderr)
    sys.exit(2)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def wheel_commit(wheel: Path) -> str:
    """Return COMMIT_SHA from the wheel's omnigent/_build_info.py, or ''."""
    with zipfile.ZipFile(wheel) as archive:
        try:
            source = archive.read("omnigent/_build_info.py").decode()
        except KeyError:
            return ""
    match = re.search(r"COMMIT_SHA[^=]*=\s*['\"]([0-9a-f]*)['\"]", source)
    return match.group(1) if match else ""


def main_wheel(folder: Path) -> Path:
    wheels = sorted(folder.glob("omnigent-[0-9]*.whl"))
    if len(wheels) != 1:
        fail(f"expected one omnigent-<version> wheel in {folder}, found {len(wheels)}")
    return wheels[0]


def read_env_file(path: Path, *, expand_home: bool) -> list[tuple[str, str]]:
    """Parse KEY=VALUE lines; '#' comments, blank lines and 'export ' are allowed."""
    entries: list[tuple[str, str]] = []
    home = os.path.expanduser("~")
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not ENV_NAME_RE.fullmatch(name):
            fail(f"{path}:{number}: not a KEY=VALUE line")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if expand_home:
            value = value.replace("${HOME}", home).replace("$HOME", home)
            parts = value.split(":")
            value = ":".join(home + part[1:] if part.startswith("~") else part for part in parts)
        entries.append((name, value))
    return entries


def service_entries(
    env_files: list[str], secret_files: list[str]
) -> tuple[list[tuple[str, str]], list[str]]:
    """Service variables from host.env (home-expanded) and secrets files, plus extra PATH dirs."""
    entries: list[tuple[str, str]] = []
    extra_path: list[str] = []
    for name in env_files:
        for key, value in read_env_file(Path(name), expand_home=True):
            if key == "PATH":
                fail(f"{name}: set {SCRIPT_KEY_PREFIX}EXTRA_PATH, not PATH (PATH is generated)")
            if key == SCRIPT_KEY_PREFIX + "EXTRA_PATH":
                extra_path.extend(part for part in value.split(":") if part)
            elif not key.startswith(SCRIPT_KEY_PREFIX):
                entries.append((key, value))
    for name in secret_files:
        if Path(name).is_file():
            entries.extend(read_env_file(Path(name), expand_home=False))
    return entries, extra_path


def build_path(first: list[str], extra: list[str], defaults: list[str]) -> str:
    """Join PATH dirs in order, dropping duplicates and terminal-app leftovers.

    A system dir resolved for one CLI (e.g. /usr/bin for rg) keeps its place
    among the defaults, so it cannot shadow ~/.local/bin or a node dir.
    """
    seen: list[str] = []
    defaults = [entry.rstrip("/") or "/" for entry in defaults]
    first = [entry for entry in first if (entry.rstrip("/") or "/") not in defaults]
    for entry in [*first, *extra, *defaults]:
        if not entry:
            continue
        entry = entry.rstrip("/") or "/"
        if entry not in seen and not LEFTOVER_PATH_RE.search(entry):
            seen.append(entry)
    return ":".join(seen)


def atomic_write(path: Path, content: bytes, mode: int) -> None:
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


# ---------------------------------------------------------------- commands


def cmd_manifest(args: argparse.Namespace) -> None:
    """Write manifest.json for a built release folder."""
    folder = Path(args.dir)
    wheel = main_wheel(folder)
    built = wheel_commit(wheel)
    if built and built != args.commit:
        fail(f"{wheel.name} was built from {built}, not {args.commit}")
    version = wheel.name.split("-")[1]
    built_with = {}
    for item in args.built_with:
        name, _, value = item.partition("=")
        built_with[name] = value or None
    manifest = {
        "tag": args.tag,
        "commit": args.commit,
        "short_commit": args.commit[:8],
        "version": version,
        "build_id": args.build_id or None,
        "oss_commit": args.oss_commit or None,
        "patches_commit": args.patches_commit or None,
        "patches_repo": args.patches_repo or None,
        "fork_repo": args.fork_repo or None,
        "image": args.image,
        "image_tag": args.image.rpartition(":")[2],
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": {
            path.name: sha256(path)
            for path in sorted(folder.iterdir())
            if path.suffix in (".whl", ".sh") or path.name in ("constraints.txt", "hostlib.py")
        },
        "built_with": built_with,
    }
    if args.series_json:
        manifest["series"] = json.loads(Path(args.series_json).read_text())
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def cmd_release_info(args: argparse.Namespace) -> None:
    """Print shell assignments describing a release folder (manifest or legacy)."""
    folder = Path(args.dir)
    manifest_path = folder / "manifest.json"
    wheel = main_wheel(folder)
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        commit, tag = manifest["commit"], manifest["tag"]
        version = manifest["version"]
        if args.verify:
            for name, expected in manifest.get("files", {}).items():
                actual = sha256(folder / name)
                if actual != expected:
                    fail(f"{folder / name}: sha256 {actual} does not match the manifest")
    else:
        commit, tag = wheel_commit(wheel), ""
        version = wheel.name.split("-")[1]
    values = {
        "rel_tag": tag,
        "rel_commit": commit,
        "rel_short": commit[:8],
        "rel_version": version,
        "rel_name": tag.rpartition("/")[2] if tag else "",
        "rel_has_manifest": "1" if manifest_path.is_file() else "",
    }
    for key, value in values.items():
        print(f"{key}={shlex.quote(value)}")


def cmd_wheel_commit(args: argparse.Namespace) -> None:
    print(wheel_commit(Path(args.wheel)))


def cmd_service_path(args: argparse.Namespace) -> None:
    _, extra = service_entries(args.env_file, [])
    print(build_path(args.first, extra, args.default))


def cmd_systemd_dropin(args: argparse.Namespace) -> None:
    """Render the generated drop-in: PATH, host.env, leftover unsets, secrets file."""
    entries, extra = service_entries(args.env_file, [])
    path = build_path(args.first, extra, args.default)
    unset = []
    unit = Path(args.unit)
    for line in unit.read_text().splitlines():
        if line.startswith("Environment="):
            for word in shlex.split(line[len("Environment=") :]):
                name = word.partition("=")[0]
                if is_leftover(name) and name not in unset:
                    unset.append(name)

    def quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'

    lines = [
        "# Generated by release/upgrade-host.sh; rerun it instead of editing.",
        "[Service]",
        f"Environment={quote('PATH=' + path)}",
        *(f"Environment={quote(item)}" for item in args.set),
        *(f"Environment={quote(key + '=' + value)}" for key, value in entries),
    ]
    if unset:
        lines.append("UnsetEnvironment=" + " ".join(unset))
    if args.secrets:
        lines.append(f"EnvironmentFile=-{args.secrets}")
    print("\n".join(lines))


def plist_env(plist_path: Path) -> dict:
    with plist_path.open("rb") as handle:
        return plistlib.load(handle)


def cmd_plist_get(args: argparse.Namespace) -> None:
    value = plist_env(Path(args.plist))
    for part in args.key.split("."):
        if isinstance(value, list):
            value = value[int(part)] if int(part) < len(value) else None
        elif isinstance(value, dict):
            value = value.get(part)
        if value is None:
            sys.exit(1)
    if isinstance(value, (dict, list)):
        fail(f"{args.key} is not a scalar")
    print(value)


def cmd_plist_merge(args: argparse.Namespace) -> None:
    """Rewrite the launchd plist's EnvironmentVariables; print changes, redacted."""
    plist_path = Path(args.plist)
    payload = plist_env(plist_path)
    old_env = dict(payload.get("EnvironmentVariables") or {})
    entries, extra = service_entries(args.env_file, args.secrets_file)
    new_env = {key: value for key, value in old_env.items() if not is_leftover(key)}
    new_env["PATH"] = build_path(args.first, extra, args.default)
    for item in args.set:
        key, _, value = item.partition("=")
        new_env[key] = value
    for key, value in entries:
        if "\n" in value or "\0" in value:
            fail(f"{key}: multiline values cannot go into a plist environment")
        new_env[key] = value
    new_env = dict(sorted(new_env.items()))
    changes = []
    for key in sorted(set(old_env) | set(new_env)):
        if key not in new_env:
            changes.append(f"  remove {key}")
        elif key not in old_env:
            changes.append(f"  add    {key}={redact(key, new_env[key])}")
        elif old_env[key] != new_env[key]:
            old, new = redact(key, old_env[key]), redact(key, new_env[key])
            changes.append(f"  change {key}: {old} -> {new}")
    if not changes:
        print("plist environment already up to date")
        return
    verb = "would update" if args.dry_run else "updating"
    print(f"{verb} {plist_path} EnvironmentVariables:")
    print("\n".join(changes))
    if args.dry_run:
        return
    if args.backup_dir:
        backup_dir = Path(args.backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(backup_dir, 0o700)
        atomic_write(backup_dir / plist_path.name, plist_path.read_bytes(), 0o600)
    payload["EnvironmentVariables"] = new_env
    atomic_write(plist_path, plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True), 0o600)
    print("CHANGED")


def cmd_env_report(args: argparse.Namespace) -> None:
    """Print KEY=VALUE pairs from a source, redacted, optionally only some keys.

    Sources: --plist (EnvironmentVariables), --proc (NUL-separated environ),
    --systemd (one `systemctl show -p Environment --value` line on stdin).
    """
    env: dict[str, str] = {}
    if args.plist:
        env = dict(plist_env(Path(args.plist)).get("EnvironmentVariables") or {})
    elif args.proc:
        for item in Path(args.proc).read_bytes().split(b"\0"):
            if b"=" in item:
                key, _, value = item.decode(errors="replace").partition("=")
                env[key] = value
    elif args.systemd:
        for word in shlex.split(sys.stdin.read()):
            key, _, value = word.partition("=")
            env[key] = value
    for key in args.unset:
        for name in key.split():
            env.pop(name, None)
    keys = args.key or sorted(env)
    for key in keys:
        if key in env:
            value = redact(key, env[key])
            print(f"{key}={value}")


def cmd_leftovers(_args: argparse.Namespace) -> None:
    """List leftover variable names and PATH entries in KEY=VALUE lines on stdin."""
    for line in sys.stdin.read().splitlines():
        key, _, value = line.partition("=")
        if is_leftover(key):
            print(f"variable {key}")
        if key == "PATH":
            for entry in value.split(":"):
                if LEFTOVER_PATH_RE.search(entry):
                    print(f"PATH entry {entry}")


def cmd_token_age(args: argparse.Namespace) -> None:
    """Print days since the file's '# created: YYYY-MM-DD' comment, or 'none'."""
    for line in Path(args.file).read_text().splitlines():
        match = DATE_COMMENT_RE.match(line.strip())
        if match:
            created = datetime.date.fromisoformat(match.group(1))
            print((datetime.date.today() - created).days)  # noqa: DTZ011 (local date)
            return
    print("none")


def cmd_secret_names(args: argparse.Namespace) -> None:
    """Print the variable names (never values) a secrets file sets."""
    for key, _ in read_env_file(Path(args.file), expand_home=False):
        print(key)


def cmd_json_keys(args: argparse.Namespace) -> None:
    value = json.load(sys.stdin)
    for part in args.path.split(".") if args.path else []:
        value = value.get(part, {})
    for key in sorted(value):
        print(key)


def cmd_json_get(args: argparse.Namespace) -> None:
    value = json.loads(Path(args.file).read_text())
    for part in args.path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    if value is None:
        sys.exit(1)
    print(value)


def cmd_urlquote(args: argparse.Namespace) -> None:
    """Print the value percent-encoded for one URL path segment."""
    print(urllib.parse.quote(args.value, safe=""))


def cmd_release_assets(_args: argparse.Namespace) -> None:
    """Print 'name url' per asset of a GitHub release JSON read from stdin."""
    release = json.load(sys.stdin)
    assets = release.get("assets") or []
    if not assets:
        fail(f"release {release.get('tag_name', '?')} has no assets")
    for asset in assets:
        name = asset["name"]
        if "/" in name or name.startswith(".") or " " in name:
            fail(f"unexpected asset name {name!r}")
        print(name, asset["browser_download_url"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("manifest")
    p.add_argument("--dir", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--commit", required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--built-with", action="append", default=[])
    p.add_argument("--build-id", default="")
    p.add_argument("--oss-commit", default="")
    p.add_argument("--patches-commit", default="")
    p.add_argument("--patches-repo", default="")
    p.add_argument("--fork-repo", default="")
    p.add_argument("--series-json", help="series -> patches list from release/notes.py")
    p.set_defaults(func=cmd_manifest)

    p = sub.add_parser("release-info")
    p.add_argument("dir")
    p.add_argument("--verify", action="store_true")
    p.set_defaults(func=cmd_release_info)

    p = sub.add_parser("wheel-commit")
    p.add_argument("wheel")
    p.set_defaults(func=cmd_wheel_commit)

    for name, func in (
        ("service-path", cmd_service_path),
        ("systemd-dropin", cmd_systemd_dropin),
        ("plist-merge", cmd_plist_merge),
    ):
        p = sub.add_parser(name)
        p.add_argument("--first", action="append", default=[], help="PATH dirs that go first")
        p.add_argument("--default", action="append", default=[], help="PATH dirs that go last")
        p.add_argument("--env-file", action="append", default=[], help="non-secret host.env")
        p.add_argument("--set", action="append", default=[], help="KEY=VALUE always set")
        p.set_defaults(func=func)
        if name == "service-path":
            continue
        if name == "systemd-dropin":
            p.add_argument("--unit", required=True)
            p.add_argument("--secrets", help="EnvironmentFile path, written as optional")
        else:
            p.add_argument("--plist", required=True)
            p.add_argument("--secrets-file", action="append", default=[])
            p.add_argument("--backup-dir")
            p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("plist-get")
    p.add_argument("plist")
    p.add_argument("key")
    p.set_defaults(func=cmd_plist_get)

    p = sub.add_parser("env-report")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--plist")
    source.add_argument("--proc")
    source.add_argument("--systemd", action="store_true")
    p.add_argument("--unset", action="append", default=[])
    p.add_argument("--key", action="append", default=[])
    p.set_defaults(func=cmd_env_report)

    p = sub.add_parser("leftovers")
    p.set_defaults(func=cmd_leftovers)

    p = sub.add_parser("token-age")
    p.add_argument("file")
    p.set_defaults(func=cmd_token_age)

    p = sub.add_parser("secret-names")
    p.add_argument("file")
    p.set_defaults(func=cmd_secret_names)

    p = sub.add_parser("json-keys")
    p.add_argument("path", nargs="?", default="")
    p.set_defaults(func=cmd_json_keys)

    p = sub.add_parser("urlquote")
    p.add_argument("value")
    p.set_defaults(func=cmd_urlquote)

    p = sub.add_parser("release-assets")
    p.set_defaults(func=cmd_release_assets)

    p = sub.add_parser("json-get")
    p.add_argument("file")
    p.add_argument("path")
    p.set_defaults(func=cmd_json_get)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
