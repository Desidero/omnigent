"""A fake ``gh`` CLI that real host and runner processes find first on ``PATH``.

:func:`install_fake_gh` writes an executable into ``<root>/bin`` that answers
from a JSON scenario file. The test owns the scenario and changes the PR's
state (head commit, checks, reviews, comments, mergeability) with
:meth:`FakeGh.update_pull`; every later ``gh`` call reads the new state. Paths
are baked into the executable rather than passed through the environment,
because hosts pass only an allowlist of variables to runners.

The executable answers the calls the Pull Requests panel makes to read a PR
(``pr view``, the conversation ``api graphql`` query,
``api repos/<repo>/commits/<sha>/pulls``, ``auth status``, ``auth token``,
``repo view``, ``repo set-default``). Labels, merging, reviewers, changed files
and diffs are not modelled. Any other call, or a real ``--json`` field the
scenario doesn't model, is appended to :meth:`FakeGh.unhandled` and exits 1, so
a test that asserts the list is empty fails when the panel starts making a call
the fake can't answer, instead of silently reading "no PR". A field gh itself
doesn't know gets gh's own "Unknown JSON field" error and is not logged.

Like gh without a terminal to prompt on, the base repository is the remote
marked by ``gh repo set-default``, else the first remote in the order
``upstream``, ``github``, ``origin``, then the rest in ``git remote`` order.

PRs are stored in ``gh pr view --json`` field names and shapes; the builders
below (:func:`pull_request`, :func:`check_run`, :func:`comment`,
:func:`review`) produce them. Only the standard library is imported at module
level, because the executable loads this file in an isolated interpreter.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GH_VERSION = "2.63.0"

# The fields ``gh pr view --json`` accepts; anything else is refused as gh does.
PR_VIEW_FIELDS = frozenset(
    {
        "additions",
        "assignees",
        "author",
        "autoMergeRequest",
        "baseRefName",
        "baseRefOid",
        "body",
        "changedFiles",
        "closed",
        "closedAt",
        "closingIssuesReferences",
        "comments",
        "commits",
        "createdAt",
        "deletions",
        "files",
        "fullDatabaseId",
        "headRefName",
        "headRefOid",
        "headRepository",
        "headRepositoryOwner",
        "id",
        "isCrossRepository",
        "isDraft",
        "labels",
        "latestReviews",
        "maintainerCanModify",
        "mergeCommit",
        "mergeStateStatus",
        "mergeable",
        "mergedAt",
        "mergedBy",
        "milestone",
        "number",
        "potentialMergeCommit",
        "projectCards",
        "projectItems",
        "reactionGroups",
        "reviewDecision",
        "reviewRequests",
        "reviews",
        "state",
        "statusCheckRollup",
        "title",
        "updatedAt",
        "url",
    }
)
# The fields ``gh repo view --json`` accepts, and the ones this fake answers.
_REPO_VIEW_FIELDS = frozenset(
    [
        "id",
        "name",
        "nameWithOwner",
        "owner",
        "parent",
        "templateRepository",
        "description",
        "homepageUrl",
        "openGraphImageUrl",
        "usesCustomOpenGraphImage",
        "url",
        "sshUrl",
        "mirrorUrl",
        "securityPolicyUrl",
        "createdAt",
        "pushedAt",
        "updatedAt",
        "archivedAt",
        "isBlankIssuesEnabled",
        "isSecurityPolicyEnabled",
        "hasIssuesEnabled",
        "hasProjectsEnabled",
        "hasWikiEnabled",
        "hasDiscussionsEnabled",
        "mergeCommitAllowed",
        "squashMergeAllowed",
        "rebaseMergeAllowed",
        "forkCount",
        "stargazerCount",
        "watchers",
        "issues",
        "pullRequests",
        "codeOfConduct",
        "contactLinks",
        "defaultBranchRef",
        "deleteBranchOnMerge",
        "diskUsage",
        "fundingLinks",
        "isArchived",
        "isEmpty",
        "isFork",
        "isInOrganization",
        "isMirror",
        "isPrivate",
        "visibility",
        "isTemplate",
        "isUserConfigurationRepository",
        "licenseInfo",
        "viewerCanAdminister",
        "viewerDefaultCommitEmail",
        "viewerDefaultMergeMethod",
        "viewerHasStarred",
        "viewerPermission",
        "viewerPossibleCommitEmails",
        "viewerSubscription",
        "repositoryTopics",
        "primaryLanguage",
        "languages",
        "issueTemplates",
        "pullRequestTemplates",
        "labels",
        "milestones",
        "latestRelease",
        "assignableUsers",
        "mentionableUsers",
        "projects",
        "projectsV2",
    ]
)
_REPO_VIEW_MODELLED = frozenset({"name", "nameWithOwner", "owner", "url", "defaultBranchRef"})
# gh's preference among remote names when nothing was set as the default.
_REMOTE_PRIORITY = {"upstream": 3, "github": 2, "origin": 1}
_PR_URL = re.compile(r"^https://(?P<host>[^/]+)/(?P<repo>[^/]+/[^/]+)/pull/(?P<number>\d+)")
_COMMIT_PULLS = re.compile(r"^repos/(?P<repo>[^/]+/[^/]+)/commits/(?P<sha>[0-9a-f]{7,64})/pulls$")
_NO_TIME = "0001-01-01T00:00:00Z"
_MERGE_STATE = {"MERGEABLE": "CLEAN", "CONFLICTING": "DIRTY"}
# What the panel's conversation query selects of each comment.
_GRAPHQL_COMMENT_FIELDS = (
    "author",
    "authorAssociation",
    "body",
    "createdAt",
    "url",
    "isMinimized",
)


# ── Test side ─────────────────────────────────────────────────


@dataclass(frozen=True)
class FakeGh:
    """An installed fake ``gh``: its ``bin`` directory, scenario and logs."""

    bin_dir: Path
    scenario_path: Path
    calls_path: Path
    unhandled_path: Path

    def path(self, inherited: str | None = None) -> str:
        """A ``PATH`` with the fake first, ahead of *inherited* (default: this process's)."""
        rest = os.environ.get("PATH", os.defpath) if inherited is None else inherited
        return f"{self.bin_dir}{os.pathsep}{rest}"

    def read(self) -> dict[str, Any]:
        return json.loads(self.scenario_path.read_text(encoding="utf-8"))

    def write(self, scenario: Mapping[str, Any]) -> None:
        """Replace the scenario atomically, so a running ``gh`` never reads half of it."""
        staging = self.scenario_path.with_suffix(".tmp")
        staging.write_text(json.dumps(scenario, indent=2), encoding="utf-8")
        os.replace(staging, self.scenario_path)

    def update_pull(self, number: int, **fields: Any) -> dict[str, Any]:
        """Set ``gh pr view`` fields of PR *number*; returns the updated PR."""
        scenario = self.read()
        [pull] = [pull for pull in scenario["pulls"] if pull["number"] == number]
        pull.update(fields)
        self.write(scenario)
        return pull

    def calls(self) -> list[list[str]]:
        """Every invocation's arguments, in order."""
        return [entry["argv"] for entry in _read_lines(self.calls_path)]

    def unhandled(self) -> list[dict[str, Any]]:
        """Invocations the fake refused, with the reason."""
        return _read_lines(self.unhandled_path)


def install_fake_gh(root: Path, scenario: Mapping[str, Any]) -> FakeGh:
    """Write the fake ``gh`` executable and its *scenario* under *root*.

    :param root: A fresh directory owned by the caller.
    :param scenario: From :func:`scenario`.
    """
    if " " in sys.executable:
        raise ValueError("A shebang can't name an interpreter path that contains spaces")
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    fake = FakeGh(
        bin_dir=bin_dir,
        scenario_path=root / "scenario.json",
        calls_path=root / "calls.jsonl",
        unhandled_path=root / "unhandled.jsonl",
    )
    fake.write(scenario)
    executable = bin_dir / "gh"
    executable.write_text(
        f"#!{sys.executable} -I\n"
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('fake_gh', {str(Path(__file__))!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules['fake_gh'] = module\n"
        "spec.loader.exec_module(module)\n"
        "sys.exit(module.main(\n"
        "    sys.argv[1:],\n"
        f"    scenario={str(fake.scenario_path)!r},\n"
        f"    calls={str(fake.calls_path)!r},\n"
        f"    unhandled={str(fake.unhandled_path)!r},\n"
        "))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return fake


def scenario(
    pulls: Iterable[Mapping[str, Any]],
    *,
    login: str,
    repositories: Iterable[str],
    host: str = "github.com",
) -> dict[str, Any]:
    """A scenario: one signed-in account, the repositories it sees, and their PRs."""
    return {
        "accounts": {
            host: [
                {
                    "state": "success",
                    "error": "",
                    "active": True,
                    "host": host,
                    "login": login,
                    "tokenSource": "keyring",
                    "scopes": "gist, read:org, repo, workflow",
                    "gitProtocol": "https",
                }
            ]
        },
        "repositories": {name: {"defaultBranch": "main"} for name in repositories},
        "pulls": [dict(pull) for pull in pulls],
    }


def pull_request(
    *,
    url: str,
    head_ref: str,
    head_sha: str,
    author: str,
    title: str = "Fix the login redirect",
    base_ref: str = "main",
    base_sha: str = "b" * 40,
    state: str = "OPEN",
    checks: Iterable[Mapping[str, Any]] = (),
    comments: Iterable[Mapping[str, Any]] = (),
    reviews: Iterable[Mapping[str, Any]] = (),
    mergeable: str = "MERGEABLE",
) -> dict[str, Any]:
    """One PR in ``gh pr view --json`` shapes, for every field the panel reads."""
    match = _PR_URL.match(url)
    if match is None:
        raise ValueError(f"not a pull request URL: {url}")
    owner, name = match["repo"].split("/")
    reviews = list(reviews)
    return {
        "number": int(match["number"]),
        "title": title,
        "state": state,
        "url": url,
        "isDraft": False,
        "author": {"id": "U_kgDOagent", "is_bot": False, "login": author, "name": ""},
        "baseRefName": base_ref,
        "baseRefOid": base_sha,
        "headRefName": head_ref,
        "headRefOid": head_sha,
        "headRepository": {"id": "R_kgDOrepo", "name": name},
        "headRepositoryOwner": {"id": "O_kgDOowner", "login": owner},
        "statusCheckRollup": [dict(check) for check in checks],
        "body": "Redirects back to the page the person came from.",
        "comments": [dict(item) for item in comments],
        "reviews": [dict(item) for item in reviews],
        "latestReviews": _latest_reviews(reviews),
        "reviewRequests": [],
        "labels": [],
        "mergeStateStatus": _MERGE_STATE.get(mergeable, "UNKNOWN"),
        "autoMergeRequest": None,
        "mergeable": mergeable,
    }


def with_reviews(reviews: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """``reviews`` and the ``latestReviews`` gh derives from them, as update fields."""
    reviews = list(reviews)
    return {"reviews": [dict(item) for item in reviews], "latestReviews": _latest_reviews(reviews)}


def check_run(
    name: str, conclusion: str | None, *, url: str, workflow: str = "CI"
) -> dict[str, Any]:
    """A GitHub Actions check run; ``conclusion=None`` is one still in progress."""
    done = conclusion is not None
    return {
        "__typename": "CheckRun",
        "completedAt": "2026-11-04T10:05:00Z" if done else _NO_TIME,
        "conclusion": conclusion or "",
        "detailsUrl": url,
        "name": name,
        "startedAt": "2026-11-04T10:00:00Z",
        "status": "COMPLETED" if done else "IN_PROGRESS",
        "workflowName": workflow,
    }


def comment(
    author: str, body: str, *, created_at: str, association: str, url: str
) -> dict[str, Any]:
    """A PR conversation comment; *association* is GitHub's ``authorAssociation``."""
    return {
        "id": _node_id("IC_kwDO", author, created_at),
        "author": {"login": author},
        "authorAssociation": association,
        "body": body,
        "createdAt": created_at,
        "includesCreatedEdit": False,
        "isMinimized": False,
        "minimizedReason": "",
        "reactionGroups": [],
        "url": url,
        "viewerDidAuthor": False,
    }


def review(
    author: str, state: str, *, submitted_at: str, association: str, body: str = ""
) -> dict[str, Any]:
    """A submitted review, e.g. ``state="CHANGES_REQUESTED"``."""
    return {
        "id": _node_id("PRR_kwDO", author, submitted_at),
        "author": {"login": author},
        "authorAssociation": association,
        "body": body,
        "submittedAt": submitted_at,
        "includesCreatedEdit": False,
        "reactionGroups": [],
        "state": state,
        "commit": {"oid": "0" * 40},
    }


def _node_id(prefix: str, *parts: str) -> str:
    return prefix + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:12]


def _latest_reviews(reviews: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in sorted(reviews, key=lambda entry: entry["submittedAt"]):
        latest[item["author"]["login"]] = dict(item)
    return list(latest.values())


def _read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ── The executable ────────────────────────────────────────────


class _Refused(Exception):
    """A call this fake doesn't answer."""


@dataclass
class _Reply:
    code: int = 0
    stdout: str = ""
    stderr: str = ""


def main(argv: list[str], *, scenario: str, calls: str, unhandled: str) -> int:
    """Answer one ``gh`` invocation from the scenario file."""
    cwd = os.getcwd()
    _append(calls, {"argv": argv, "cwd": cwd})
    try:
        reply = _dispatch(argv, json.loads(Path(scenario).read_text(encoding="utf-8")), cwd)
    except _Refused as refused:
        _append(unhandled, {"argv": argv, "cwd": cwd, "reason": str(refused)})
        sys.stderr.write(f"fake gh: unhandled: {refused}\n")
        return 1
    sys.stdout.write(reply.stdout)
    sys.stderr.write(reply.stderr)
    return reply.code


def _append(path: str, entry: Mapping[str, Any]) -> None:
    # One O_APPEND write per line, so concurrent gh processes don't interleave.
    line = (json.dumps(entry) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(descriptor, line)
    finally:
        os.close(descriptor)


def _dispatch(argv: list[str], data: dict[str, Any], cwd: str) -> _Reply:
    if argv in (["--version"], ["version"]):
        return _Reply(stdout=f"gh version {GH_VERSION} (2024-11-27)\n")
    command, rest = tuple(argv[:2]), argv[2:]
    if command == ("pr", "view"):
        return _pr_view(rest, data, cwd)
    if command == ("auth", "status"):
        return _auth_status(rest, data)
    if command == ("auth", "token"):
        return _auth_token(rest, data)
    if command == ("repo", "view"):
        return _repo_view(rest, data, cwd)
    if command == ("repo", "set-default"):
        return _repo_set_default(rest, cwd)
    if argv[:1] == ["api"]:
        return _api(argv[1:], data, cwd)
    raise _Refused("command")


def _options(args: list[str], flags: Mapping[str, str]) -> tuple[dict[str, list[str]], list[str]]:
    """Split *args* into flag values (by canonical name) and positionals."""
    values: dict[str, list[str]] = {}
    positionals: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        name, _, inline = arg.partition("=") if arg.startswith("--") else (arg, "", "")
        if name in flags:
            if inline:
                value = inline
            else:
                index += 1
                if index >= len(args):
                    raise _Refused(f"{arg} needs a value")
                value = args[index]
            values.setdefault(flags[name], []).append(value)
        elif arg.startswith("-"):
            raise _Refused(f"flag {arg}")
        else:
            positionals.append(arg)
        index += 1
    return values, positionals


def _json_fields(values: Mapping[str, list[str]], known: frozenset[str]) -> list[str] | _Reply:
    fields = [field for field in values["json"][-1].split(",") if field]
    for field in fields:
        if field not in known:
            listing = "".join(f"  {name}\n" for name in sorted(known))
            return _Reply(1, stderr=f'Unknown JSON field: "{field}"\nAvailable fields:\n{listing}')
    return fields


def _git(cwd: str, *args: str) -> str | None:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _remotes(cwd: str) -> dict[str, str]:
    """Each git remote's ``owner/repo``, in the order gh ranks them."""
    remotes: dict[str, str] = {}
    names = (_git(cwd, "remote") or "").split()
    for name in sorted(names, key=lambda name: -_REMOTE_PRIORITY.get(name.lower(), 0)):
        url = _git(cwd, "remote", "get-url", name) or ""
        match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", url)
        if match:
            remotes[name] = match[1]
    return remotes


def _set_default(cwd: str) -> str | None:
    """The repository ``gh repo set-default`` chose, if any.

    gh stores it on a remote as ``gh-resolved``: ``base`` for that remote's
    repository, or another repository's ``owner/repo``.
    """
    for name, repo in _remotes(cwd).items():
        resolved = _git(cwd, "config", f"remote.{name}.gh-resolved")
        if resolved:
            return repo if resolved == "base" else resolved
    return None


def _current_repo(cwd: str) -> str | None:
    """The base repository gh resolves for *cwd* without prompting."""
    return _set_default(cwd) or next(iter(_remotes(cwd).values()), None)


def _repo_argument(value: str) -> tuple[str, str]:
    """``[HOST/]OWNER/REPO`` as ``(host, owner/repo)``."""
    parts = value.split("/")
    if len(parts) == 3:
        return parts[0], "/".join(parts[1:])
    if len(parts) == 2:
        return "github.com", value
    raise _Refused(f"repository {value!r}")


def _pull_repo(pull: Mapping[str, Any]) -> tuple[str, str]:
    match = _PR_URL.match(pull["url"])
    assert match is not None
    return match["host"], match["repo"]


def _pr_view(args: list[str], data: dict[str, Any], cwd: str) -> _Reply:
    values, positionals = _options(args, {"-R": "repo", "--repo": "repo", "--json": "json"})
    if "json" not in values or len(positionals) > 1:
        raise _Refused("pr view without --json, or with several selectors")
    fields = _json_fields(values, PR_VIEW_FIELDS)
    if isinstance(fields, _Reply):
        return fields
    selector = positionals[0] if positionals else None
    if selector is not None and (match := _PR_URL.match(selector)):
        host, repo, number = match["host"], match["repo"], int(match["number"])
        branch = None
    else:
        if "repo" in values:
            host, repo = _repo_argument(values["repo"][-1])
        else:
            host, repo = "github.com", _current_repo(cwd) or ""
        number = int(selector) if selector is not None and selector.isdigit() else None
        branch = None if number is not None else selector or _git(cwd, "branch", "--show-current")
    candidates = [
        pull
        for pull in data["pulls"]
        if _pull_repo(pull) == (host, repo)
        and (pull["number"] == number if number is not None else pull["headRefName"] == branch)
    ]
    # Like gh, a branch's open PR wins over its closed ones.
    candidates.sort(key=lambda pull: pull["state"] != "OPEN")
    if not candidates:
        if number is not None:
            return _Reply(
                1,
                stderr="GraphQL: Could not resolve to a PullRequest with the number of "
                f"{number}. (repository.pullRequest)\n",
            )
        return _Reply(1, stderr=f'no pull requests found for branch "{branch}"\n')
    pull = candidates[0]
    missing = [field for field in fields if field not in pull]
    if missing:
        raise _Refused(f"scenario PR #{pull['number']} has no {', '.join(missing)}")
    return _Reply(stdout=json.dumps({field: pull[field] for field in fields}) + "\n")


def _auth_status(args: list[str], data: dict[str, Any]) -> _Reply:
    if args == ["--json", "hosts"]:
        return _Reply(stdout=json.dumps({"hosts": data["accounts"]}) + "\n")
    if args:
        raise _Refused("auth status flags")
    lines = []
    for host, accounts in data["accounts"].items():
        lines.append(host)
        for account in accounts:
            lines.append(f"  ✓ Logged in to {host} account {account['login']} (keyring)")
    return _Reply(stdout="\n".join(lines) + "\n")


def _auth_token(args: list[str], data: dict[str, Any]) -> _Reply:
    values, positionals = _options(
        args, {"-h": "host", "--hostname": "host", "-u": "user", "--user": "user"}
    )
    if positionals:
        raise _Refused("auth token arguments")
    host = values.get("host", ["github.com"])[-1]
    accounts = data["accounts"].get(host, [])
    wanted = values.get("user", [None])[-1]
    login = next(
        (
            account["login"]
            for account in accounts
            if account["login"] == wanted or (wanted is None and account["active"])
        ),
        None,
    )
    if login is None:
        return _Reply(1, stderr=f"no oauth token found for {host}\n")
    return _Reply(stdout=f"gho_fake{login}\n")


def _repo_view(args: list[str], data: dict[str, Any], cwd: str) -> _Reply:
    values, positionals = _options(args, {"--json": "json"})
    if "json" not in values or len(positionals) > 1:
        raise _Refused("repo view without --json")
    fields = _json_fields(values, _REPO_VIEW_FIELDS)
    if isinstance(fields, _Reply):
        return fields
    if unmodelled := sorted(set(fields) - _REPO_VIEW_MODELLED):
        raise _Refused(f"repo view field {', '.join(unmodelled)}")
    name = _repo_argument(positionals[0])[1] if positionals else _current_repo(cwd)
    repository = data["repositories"].get(name or "")
    if repository is None:
        return _Reply(
            1,
            stderr=f"GraphQL: Could not resolve to a Repository with the name '{name}'. "
            "(repository)\n",
        )
    owner, short = str(name).split("/")
    full = {
        "name": short,
        "nameWithOwner": name,
        "owner": {"id": "O_kgDOowner", "login": owner},
        "url": f"https://github.com/{name}",
        "defaultBranchRef": {"name": repository["defaultBranch"]},
    }
    return _Reply(stdout=json.dumps({field: full[field] for field in fields}) + "\n")


def _repo_set_default(args: list[str], cwd: str) -> _Reply:
    remotes = _remotes(cwd)
    if args == ["--view"]:
        chosen = _set_default(cwd)
        if chosen is None:
            return _Reply(
                1,
                stderr="no default repository has been set; use `gh repo set-default` "
                "to select one\n",
            )
        return _Reply(stdout=chosen + "\n")
    if len(args) != 1 or args[0].startswith("-"):
        raise _Refused("repo set-default arguments")
    target = args[0]
    name = (
        target
        if target in remotes
        else next(
            (remote for remote, repo in remotes.items() if repo == _repo_argument(target)[1]), None
        )
    )
    if name is None:
        return _Reply(1, stderr=f"{target} does not correspond to any git remotes\n")
    for remote in remotes:
        _git(cwd, "config", "--unset", f"remote.{remote}.gh-resolved")
    _git(cwd, "config", f"remote.{name}.gh-resolved", "base")
    return _Reply(
        stdout=f"✓ Set {remotes[name]} as the default repository for the current directory\n"
    )


def _api(args: list[str], data: dict[str, Any], cwd: str) -> _Reply:
    values, positionals = _options(
        args,
        {
            "--hostname": "hostname",
            "--cache": "cache",
            "-f": "field",
            "--raw-field": "field",
            "-F": "field",
            "--field": "field",
        },
    )
    if len(positionals) != 1:
        raise _Refused("api endpoint")
    host = values.get("hostname", ["github.com"])[-1]
    endpoint = positionals[0]
    if endpoint == "graphql":
        return _graphql(values.get("field", []), data, host)
    if (match := _COMMIT_PULLS.match(endpoint)) and not values.get("field"):
        return _commit_pulls(match["repo"], match["sha"], data, host)
    raise _Refused(f"api {endpoint}")


def _graphql(raw_fields: list[str], data: dict[str, Any], host: str) -> _Reply:
    """The panel's conversation query: recent comments and the commit timeline."""
    fields = dict(field.partition("=")[::2] for field in raw_fields)
    query = fields.get("query", "")
    if "timelineItems" not in query or "pullRequest(number: $number)" not in query:
        raise _Refused("graphql query")
    repo, number = f"{fields.get('owner')}/{fields.get('name')}", int(fields.get("number", "0"))
    pulls = [
        pull
        for pull in data["pulls"]
        if _pull_repo(pull) == (host, repo) and pull["number"] == number
    ]
    if not pulls:
        message = f"Could not resolve to a PullRequest with the number of {number}."
        body = {"data": {"repository": {"pullRequest": None}}, "errors": [{"message": message}]}
        return _Reply(1, stdout=json.dumps(body), stderr=f"gh: {message}\n")
    pull = pulls[0]
    conversation: dict[str, Any] = {
        "timelineItems": {
            "pageInfo": {"hasPreviousPage": False},
            "nodes": [
                {
                    "__typename": "PullRequestCommit",
                    "id": f"PURC_{pull['headRefOid'][:12]}",
                    "url": f"{pull['url']}/commits/{pull['headRefOid']}",
                    "commit": {
                        "oid": pull["headRefOid"],
                        "messageHeadline": pull["title"],
                        "committedDate": "2026-11-04T09:55:00Z",
                        "author": {"name": "", "user": {"login": pull["author"]["login"]}},
                    },
                }
            ],
        }
    }
    if fields.get("includeComments") == "true":
        conversation["comments"] = {
            "nodes": [
                {key: item[key] for key in _GRAPHQL_COMMENT_FIELDS}
                for item in pull["comments"][-100:]
            ]
        }
    return _Reply(stdout=json.dumps({"data": {"repository": {"pullRequest": conversation}}}))


def _head_repo(pull: Mapping[str, Any]) -> str:
    return f"{pull['headRepositoryOwner']['login']}/{pull['headRepository']['name']}"


def _commit_pulls(repo: str, sha: str, data: dict[str, Any], host: str) -> _Reply:
    """``GET repos/{repo}/commits/{sha}/pulls``: PRs whose head is *sha* in *repo*.

    The commit is in *repo* when the PR's head (a fork's, say) or base lives there.
    """
    rows = [
        {
            "number": pull["number"],
            "state": "open" if pull["state"] == "OPEN" else "closed",
            "html_url": pull["url"],
            "head": {"ref": pull["headRefName"], "sha": pull["headRefOid"]},
            "base": {"ref": pull["baseRefName"], "repo": {"full_name": _pull_repo(pull)[1]}},
        }
        for pull in data["pulls"]
        if pull["headRefOid"].startswith(sha)
        and _pull_repo(pull)[0] == host
        and repo in (_pull_repo(pull)[1], _head_repo(pull))
    ]
    if repo not in data["repositories"]:
        return _Reply(1, stderr="gh: Not Found (HTTP 404)\n")
    return _Reply(stdout=json.dumps(rows))
