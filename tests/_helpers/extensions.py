"""Install Omnigent extension packages and run a server that discovers them.

Packages install the way an operator installs them: a wheel built from the
project, without dependencies, into a private target that only the test server
imports. The shared test virtualenv is never modified.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

import yaml

from tests._helpers.live_server import isolated_local_server, local_server_env


def install_extension_packages(projects: Sequence[Path], target: Path) -> Path:
    """Build and install each extension project into *target*; return *target*.

    Builds from a copy, so setuptools' ``build/`` and ``*.egg-info`` never land
    in the checkout. Frontend sources are skipped: the wheel ships the
    committed ``dist`` bundle.
    """
    for project in projects:
        source = target.parent / f"{target.name}-src" / project.name
        shutil.copytree(
            project, source, ignore=shutil.ignore_patterns("web", "build", "*.egg-info")
        )
        result = subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                sys.executable,
                "--no-deps",
                "--target",
                str(target),
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, f"installing {project.name} failed:\n{result.stderr}"
    return target


@contextmanager
def extension_server(
    root: Path,
    packages: Path,
    *,
    extensions: Mapping[str, Mapping[str, object]] | None = None,
    env: Mapping[str, str | None] | None = None,
) -> Iterator[str]:
    """Run an isolated server that imports *packages*; yield its base URL.

    :param root: A fresh directory for the config, server state and log.
    :param packages: A target from :func:`install_extension_packages`.
    :param extensions: The server config's ``extensions`` section; ``None``
        omits the section, which is how existing installs run.
    :param env: Extra server environment, as for ``isolated_local_server``.
    """
    root.mkdir(parents=True, exist_ok=True)
    config = root / "config.yaml"
    section = (
        {} if extensions is None else {"extensions": {k: dict(v) for k, v in extensions.items()}}
    )
    config.write_text(yaml.safe_dump(section), encoding="utf-8")
    pythonpath = os.pathsep.join([str(packages), local_server_env({})["PYTHONPATH"]])
    with isolated_local_server(
        root / "server",
        env={"PYTHONPATH": pythonpath, **(env or {})},
        extra_args=["--config", str(config)],
        cwd=root,
    ) as base_url:
        yield base_url
