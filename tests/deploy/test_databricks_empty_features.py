"""Empty Databricks Apps feature configuration remains deployable."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DEPLOY_PY = _ROOT / "deploy" / "databricks" / "deploy.py"


@pytest.fixture(scope="module")
def deploy_mod() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_databricks_deploy_features", _DEPLOY_PY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(features: str) -> Namespace:
    return Namespace(
        app_name="omnigent",
        lakebase_branch="projects/omnigent/branches/production",
        lakebase_database="projects/omnigent/branches/production/databases/databricks-postgres",
        volume_name="main.omnigent.artifacts",
        otel_table_schema="main.omnigent_logs",
        features=features,
        target="prod",
        profile=None,
    )


@pytest.mark.parametrize(
    ("features", "expected"),
    [
        ("", " "),
        ("   ", " "),
        ("usage_page,harness_install", "usage_page,harness_install"),
    ],
)
def test_bundle_env_provides_a_valid_feature_source(
    deploy_mod: ModuleType, monkeypatch: pytest.MonkeyPatch, features: str, expected: str
) -> None:
    monkeypatch.delenv("BUNDLE_VAR_features", raising=False)

    env = deploy_mod._bundle_env(_args(features))

    assert env["BUNDLE_VAR_features"] == expected
    # The deploy's own environment is left alone; only the child sees the value.
    assert "BUNDLE_VAR_features" not in os.environ
    assert env["PATH"] == os.environ["PATH"]


def test_feature_list_never_travels_as_a_var_pair(deploy_mod: ModuleType) -> None:
    """The CLI splits ``--var`` values on commas, which breaks a feature list."""
    values = deploy_mod._bundle_vars(_args("usage_page,harness_install"))

    assert not any(value.startswith("features=") for value in values)
    assert not any("," in value for value in values)


@pytest.mark.parametrize(
    ("command", "options"),
    [
        (["deployment", "bind", "omnigent", "omnigent"], ["--auto-approve"]),
        (["deploy"], []),
        (["run", "omnigent"], []),
    ],
)
def test_every_bundle_command_gets_the_features_by_environment(
    deploy_mod: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
    options: list[str],
) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(deploy_mod.subprocess, "run", fake_run)

    deploy_mod._run_bundle(_args("usage_page,canvas,-chat"), command, options, check=True)

    ((cmd, kwargs),) = calls
    assert cmd[: 2 + len(command)] == ["databricks", "bundle", *command]
    assert cmd[2 + len(command) :][:2] == ["--target", "prod"]
    assert all(option in cmd for option in options)
    assert not any("features" in part for part in cmd)
    assert kwargs["env"]["BUNDLE_VAR_features"] == "usage_page,canvas,-chat"
    assert kwargs["cwd"] == deploy_mod._deploy_dir()
    assert kwargs["check"] is True
