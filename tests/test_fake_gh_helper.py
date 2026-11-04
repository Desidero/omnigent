"""The fake ``gh`` helper refuses what it doesn't model, as a running executable."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests._helpers import fake_gh


def _checkout(path: Path, remotes: dict[str, str]) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    for name, repo in remotes.items():
        url = f"https://github.com/{repo}.git"
        subprocess.run(["git", "remote", "add", name, url], cwd=path, check=True)
    return path


def _gh(fake: fake_gh.FakeGh, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(fake.bin_dir / "gh"), *args], cwd=cwd, capture_output=True, text=True, check=False
    )


def _fake(tmp_path: Path) -> fake_gh.FakeGh:
    return fake_gh.install_fake_gh(
        tmp_path / "gh",
        fake_gh.scenario([], login="agent-bot", repositories=["acme/widgets", "fork/widgets"]),
    )


def test_repo_view_logs_real_fields_it_does_not_model_and_rejects_unknown_ones(
    tmp_path: Path,
) -> None:
    fake = _fake(tmp_path)
    checkout = _checkout(tmp_path / "ws", {"origin": "acme/widgets"})

    unmodelled = _gh(fake, checkout, "repo", "view", "--json", "nameWithOwner,stargazerCount")
    assert unmodelled.returncode == 1
    [refused] = fake.unhandled()
    assert refused["argv"][-1] == "nameWithOwner,stargazerCount"
    assert refused["reason"] == "repo view field stargazerCount"

    unknown = _gh(fake, checkout, "repo", "view", "--json", "nameWithOwner,stars")
    assert unknown.returncode == 1
    assert unknown.stderr.startswith('Unknown JSON field: "stars"\nAvailable fields:\n')
    assert "  stargazerCount\n" in unknown.stderr
    assert len(fake.unhandled()) == 1


def test_the_base_repository_follows_gh_remote_order_until_a_default_is_set(
    tmp_path: Path,
) -> None:
    fake = _fake(tmp_path)
    checkout = _checkout(tmp_path / "ws", {"origin": "fork/widgets", "upstream": "acme/widgets"})

    def base() -> str:
        result = _gh(fake, checkout, "repo", "view", "--json", "nameWithOwner")
        return json.loads(result.stdout)["nameWithOwner"]

    assert base() == "acme/widgets"
    assert _gh(fake, checkout, "repo", "set-default", "--view").returncode == 1
    assert _gh(fake, checkout, "repo", "set-default", "fork/widgets").returncode == 0
    assert base() == "fork/widgets"
    assert _gh(fake, checkout, "repo", "set-default", "--view").stdout == "fork/widgets\n"
    assert fake.unhandled() == []
