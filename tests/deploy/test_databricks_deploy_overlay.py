"""``deploy.py --overlay``: one untracked file holds a deployment's own settings.

A Databricks Apps deployment needs values the tracked bundle cannot hold: the
workspace host, extra ``omnigent`` extras, app env vars, secret-backed env vars
and config files for the app source. The overlay supplies them, so these tests
pin down the three things that must hold without a live workspace:

1. the file is validated strictly, and no message or log line carries a value;
2. the generated bundle target is the selected target plus the overlay, built
   from the real ``databricks.yml`` so a change there cannot silently drop the
   base env or resources;
3. files copied into the app source are removed again.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_DEPLOY_DIR = _ROOT / "deploy" / "databricks"
_DEPLOY_PY = _DEPLOY_DIR / "deploy.py"
_BUNDLE_YML = _DEPLOY_DIR / "databricks.yml"

_REQUIRED_ARGS = [
    "--app-name",
    "omnigent",
    "--lakebase-branch",
    "projects/omnigent/branches/production",
    "--lakebase-database",
    "projects/omnigent/branches/production/databases/databricks-postgres",
    "--volume-name",
    "main.omnigent.artifacts",
]

# A value that must never reach an error message or the deploy log.
_PRIVATE_VALUE = "value-that-must-not-be-printed"


@pytest.fixture(scope="module")
def deploy_mod() -> ModuleType:
    """Load ``deploy.py`` by path — ``deploy/`` is not an installed package."""
    spec = importlib.util.spec_from_file_location("_databricks_deploy_overlay", _DEPLOY_PY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bundle() -> dict[str, Any]:
    return yaml.safe_load(_BUNDLE_YML.read_text())


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "server-config.local.yml"
    path.write_text("routing:\n  provider: none\n")
    return path


def _full_overlay(config_file: Path) -> dict[str, Any]:
    return {
        "host": "https://workspace.example.com/",
        "extras": ["kms"],
        "env": {"OMNIGENT_CONFIG": "server-config.yml", "OMNIGENT_SHARING_MODE": "read_only"},
        "secret_env": {
            "OMNIGENT_DATABRICKS_CLIENT_SECRET": {
                "scope": "omnigent",
                "key": "oauth-client-secret",
                "resource": "oauth_secret",
            }
        },
        "files": {"server-config.yml": config_file.name},
    }


def test_a_full_overlay_parses(deploy_mod: ModuleType, config_file: Path) -> None:
    overlay = deploy_mod._parse_overlay(_full_overlay(config_file), config_file.parent)

    assert overlay.host == "https://workspace.example.com"
    assert overlay.extras == ("kms",)
    assert overlay.env == {
        "OMNIGENT_CONFIG": "server-config.yml",
        "OMNIGENT_SHARING_MODE": "read_only",
    }
    secret = overlay.secret_env["OMNIGENT_DATABRICKS_CLIENT_SECRET"]
    assert (secret.scope, secret.key, secret.resource) == (
        "omnigent",
        "oauth-client-secret",
        "oauth_secret",
    )
    # Sources resolve against the overlay file's directory.
    assert overlay.files == {"server-config.yml": config_file.resolve()}
    assert overlay.changes_bundle


def test_a_secret_resource_defaults_to_the_lowercased_variable_name(
    deploy_mod: ModuleType, tmp_path: Path
) -> None:
    overlay = deploy_mod._parse_overlay(
        {"secret_env": {"CLIENT_SECRET": {"scope": "omnigent", "key": "client"}}}, tmp_path
    )
    assert overlay.secret_env["CLIENT_SECRET"].resource == "client_secret"


def test_an_empty_overlay_changes_nothing(deploy_mod: ModuleType, tmp_path: Path) -> None:
    overlay = deploy_mod._parse_overlay({}, tmp_path)
    assert overlay == deploy_mod._Overlay()
    assert not overlay.changes_bundle


@pytest.mark.parametrize(
    ("data", "message"),
    [
        pytest.param(["host"], "must be a mapping", id="not-a-mapping"),
        pytest.param({"hosts": "x"}, "unknown key(s) ['hosts']", id="unknown-top-level-key"),
        pytest.param({"env": ["A=b"]}, "'env' must be a mapping", id="env-not-a-mapping"),
        pytest.param({"extras": "kms"}, "'extras' must be a list", id="extras-not-a-list"),
        pytest.param({"host": "http://workspace.example.com"}, "'host' must be", id="http-host"),
        pytest.param(
            {"host": "https://workspace.example.com/path"}, "'host' must be", id="host-with-path"
        ),
        pytest.param({"extras": ["no-such-extra"]}, "no extra named", id="unknown-extra"),
        pytest.param({"extras": ["kms", "kms"]}, "listed twice", id="repeated-extra"),
        pytest.param({"extras": ["kms]evil"]}, "not an extra name", id="malformed-extra"),
        pytest.param({"env": {"1BAD": "x"}}, "not an environment variable", id="bad-env-name"),
        pytest.param({"env": {"FLAG": False}}, "non-empty string", id="unquoted-boolean"),
        pytest.param({"env": {"FLAG": ""}}, "non-empty string", id="empty-value"),
        pytest.param(
            {"env": {"OMNIGENT_DATABRICKS_CLIENT_SECRET": _PRIVATE_VALUE}},
            "put it under secret_env",
            id="secret-as-plain-env",
        ),
        pytest.param(
            {"env": {"A": "x"}, "secret_env": {"A": {"scope": "s", "key": "k"}}},
            "both env and secret_env",
            id="name-in-both",
        ),
        pytest.param(
            {"secret_env": {"A": "scope/key"}}, "must be a mapping", id="secret-not-a-mapping"
        ),
        pytest.param(
            {"secret_env": {"A": {"scope": "s", "key": "k", "value": _PRIVATE_VALUE}}},
            "unknown key(s) ['value']",
            id="unknown-secret-key",
        ),
        pytest.param({"secret_env": {"A": {"scope": "s"}}}, "A.key", id="secret-without-key"),
        pytest.param(
            {
                "secret_env": {
                    "A": {"scope": "s", "key": "k", "resource": "shared"},
                    "B": {"scope": "s", "key": "k2", "resource": "shared"},
                }
            },
            "used twice",
            id="repeated-resource-name",
        ),
        pytest.param({"files": {"sub/config.yml": "x"}}, "plain file name", id="nested-dest"),
        pytest.param({"files": {"../config.yml": "x"}}, "plain file name", id="escaping-dest"),
        pytest.param({"files": {".env": "x"}}, "plain file name", id="hidden-dest"),
        pytest.param({"files": {"uv.lock": "x"}}, "written by deploy.py", id="generated-dest"),
        pytest.param({"files": {"extra.whl": "x"}}, "written by deploy.py", id="wheel-dest"),
        pytest.param({"files": {"config.yml": "missing.yml"}}, "is not a file", id="no-source"),
    ],
)
def test_anything_unexpected_in_the_overlay_fails(
    deploy_mod: ModuleType, tmp_path: Path, data: Any, message: str
) -> None:
    with pytest.raises(ValueError) as excinfo:
        deploy_mod._parse_overlay(data, tmp_path)
    assert message in str(excinfo.value)
    assert _PRIVATE_VALUE not in str(excinfo.value)


def test_a_gitignored_destination_is_refused(
    deploy_mod: ModuleType, monkeypatch: pytest.MonkeyPatch, config_file: Path
) -> None:
    """``bundle deploy`` skips gitignored files, so the copy would never upload."""
    monkeypatch.setattr(deploy_mod, "_is_gitignored", lambda path: path.name == "ignored.yml")

    with pytest.raises(ValueError, match="would not upload it"):
        deploy_mod._parse_overlay({"files": {"ignored.yml": str(config_file)}}, config_file.parent)
    deploy_mod._parse_overlay({"files": {"kept.yml": str(config_file)}}, config_file.parent)


def test_the_repo_ignores_overlay_files_but_not_their_copies(deploy_mod: ModuleType) -> None:
    assert deploy_mod._is_gitignored(_DEPLOY_DIR / "deploy.local.yml")
    assert deploy_mod._is_gitignored(_DEPLOY_DIR / deploy_mod._OVERLAY_BUNDLE_NAME)
    assert not deploy_mod._is_gitignored(_DEPLOY_DIR / "src" / "server-config.yml")


def test_load_overlay_names_the_file_and_never_quotes_it(
    deploy_mod: ModuleType, tmp_path: Path
) -> None:
    path = tmp_path / "deploy.local.yml"

    with pytest.raises(SystemExit, match=r"deploy\.local\.yml"):
        deploy_mod.load_overlay(path)

    path.write_text(f"env:\n  A: [{_PRIVATE_VALUE}\n")
    with pytest.raises(SystemExit) as excinfo:
        deploy_mod.load_overlay(path)
    assert "not valid YAML" in str(excinfo.value)
    assert _PRIVATE_VALUE not in str(excinfo.value)

    path.write_text("extras: [kms]\nunknown: 1\n")
    with pytest.raises(SystemExit, match=r"deploy\.local\.yml: unknown key"):
        deploy_mod.load_overlay(path)

    path.write_text("extras: [kms]\n")
    assert deploy_mod.load_overlay(path).extras == ("kms",)


@pytest.mark.parametrize("target", ["prod", "prod-no-otel"])
def test_the_overlay_target_is_the_base_target_plus_the_overlay(
    deploy_mod: ModuleType, bundle: dict[str, Any], config_file: Path, target: str
) -> None:
    overlay = deploy_mod._parse_overlay(_full_overlay(config_file), config_file.parent)
    before = yaml.safe_dump(bundle)

    name, fragment = deploy_mod.build_overlay_bundle(overlay, bundle, target)

    assert name == f"{target}-overlay"
    assert list(fragment) == ["targets"]
    block = fragment["targets"][name]
    base = bundle["targets"][target]
    base_env = (base.get("variables") or {}).get("app_env") or bundle["variables"]["app_env"][
        "default"
    ]
    # The whole base env first, then the overlay's entries in file order.
    assert block["variables"]["app_env"] == [
        *base_env,
        {"name": "OMNIGENT_CONFIG", "value": "server-config.yml"},
        {"name": "OMNIGENT_SHARING_MODE", "value": "read_only"},
        {"name": "OMNIGENT_DATABRICKS_CLIENT_SECRET", "value_from": "oauth_secret"},
    ]
    # Everything else the base target sets is carried over unchanged.
    for variable, value in (base.get("variables") or {}).items():
        if variable != "app_env":
            assert block["variables"][variable] == value
    assert block["mode"] == base["mode"]
    assert block["workspace"] == {**base["workspace"], "host": "https://workspace.example.com"}
    target_app = block["resources"]["apps"]["omnigent"]
    base_app = ((base.get("resources") or {}).get("apps") or {}).get("omnigent") or {}
    assert target_app.get("telemetry_export_destinations") == base_app.get(
        "telemetry_export_destinations"
    )
    assert target_app["resources"] == [
        {
            "name": "oauth_secret",
            "secret": {"scope": "omnigent", "key": "oauth-client-secret", "permission": "READ"},
        }
    ]
    # The parsed bundle is only read.
    assert yaml.safe_dump(bundle) == before


@pytest.mark.parametrize(
    ("data", "target", "message"),
    [
        pytest.param(
            {"env": {"OMNIGENT_FEATURES": "canvas"}}, "prod", "--features", id="features-by-env"
        ),
        pytest.param(
            {"secret_env": {"AP_LAKEBASE_ENDPOINT": {"scope": "s", "key": "k"}}},
            "prod",
            "already set by the bundle",
            id="bundle-env-as-secret",
        ),
        pytest.param(
            {"secret_env": {"A": {"scope": "s", "key": "k", "resource": "postgres"}}},
            "prod",
            "already has a resource named 'postgres'",
            id="resource-name-taken",
        ),
        pytest.param({"env": {"A": "x"}}, "staging", "not defined", id="unknown-target"),
    ],
)
def test_an_overlay_cannot_replace_what_the_bundle_sets(
    deploy_mod: ModuleType,
    bundle: dict[str, Any],
    tmp_path: Path,
    data: dict[str, Any],
    target: str,
    message: str,
) -> None:
    overlay = deploy_mod._parse_overlay(data, tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        deploy_mod.build_overlay_bundle(overlay, bundle, target)
    assert message in str(excinfo.value)


def test_the_sampler_can_be_set_only_where_the_target_leaves_it_unset(
    deploy_mod: ModuleType, bundle: dict[str, Any], tmp_path: Path
) -> None:
    overlay = deploy_mod._parse_overlay({"env": {"OTEL_TRACES_SAMPLER": "always_off"}}, tmp_path)

    with pytest.raises(SystemExit, match="OTEL_TRACES_SAMPLER"):
        deploy_mod.build_overlay_bundle(overlay, bundle, "prod")
    deploy_mod.build_overlay_bundle(overlay, bundle, "prod-no-otel")


def test_the_bundle_includes_the_generated_fragment_by_glob(
    deploy_mod: ModuleType, bundle: dict[str, Any]
) -> None:
    """A glob may match nothing; a plain name would fail every deploy without an overlay."""
    patterns = bundle["include"]
    assert any(fnmatch.fnmatch(deploy_mod._OVERLAY_BUNDLE_NAME, pattern) for pattern in patterns)
    assert all(any(char in pattern for char in "*?[") for pattern in patterns)


def test_the_fragment_is_written_logged_by_name_and_cleared(
    deploy_mod: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    (tmp_path / "databricks.yml").write_text(_BUNDLE_YML.read_text())
    monkeypatch.setattr(deploy_mod, "_deploy_dir", lambda: tmp_path)
    fragment_path = tmp_path / deploy_mod._OVERLAY_BUNDLE_NAME
    overlay = deploy_mod._parse_overlay(
        {
            "host": "https://workspace.example.com",
            "env": {"OMNIGENT_CONFIG": _PRIVATE_VALUE},
            "secret_env": {"CLIENT_SECRET": {"scope": "omnigent", "key": "client"}},
        },
        tmp_path,
    )

    assert deploy_mod.write_overlay_bundle(overlay, "prod-no-otel") == "prod-no-otel-overlay"

    text = fragment_path.read_text()
    # Self-contained YAML: no anchors or aliases left over from the copied target.
    assert "&" not in text and "*" not in text
    written = yaml.safe_load(text)["targets"]["prod-no-otel-overlay"]
    assert written["workspace"]["host"] == "https://workspace.example.com"
    assert written["variables"]["app_command"] == ["python", "app.py"]
    assert {"name": "OMNIGENT_CONFIG", "value": _PRIVATE_VALUE} in written["variables"]["app_env"]
    log = capsys.readouterr().out
    assert "OMNIGENT_CONFIG" in log and "CLIENT_SECRET" in log
    assert _PRIVATE_VALUE not in log

    # An overlay with nothing for the bundle, and no overlay at all, deploy the
    # base target and leave no stale fragment behind.
    extras_only = deploy_mod._parse_overlay({"extras": ["kms"]}, tmp_path)
    assert deploy_mod.write_overlay_bundle(extras_only, "prod") == "prod"
    assert not fragment_path.exists()
    fragment_path.write_text("stale: true\n")
    assert deploy_mod.write_overlay_bundle(None, "prod") == "prod"
    assert not fragment_path.exists()


def test_overlay_extras_join_the_standard_ones(deploy_mod: ModuleType, tmp_path: Path) -> None:
    wheels = [
        tmp_path / "omnigent-1.0-py3-none-any.whl",
        tmp_path / "omnigent_client-1.0-py3-none-any.whl",
        tmp_path / "omnigent_ui_sdk-1.0-py3-none-any.whl",
    ]
    for wheel in wheels:
        wheel.write_bytes(b"")

    standard = deploy_mod.build_uv_pyproject(wheels[0], wheels, [], "1.0")
    with_overlay = deploy_mod.build_uv_pyproject(
        wheels[0], wheels, [], "1.0", extras=("kms", "tracing")
    )

    assert '"omnigent[databricks,tracing]==1.0"' in standard
    assert '"omnigent[databricks,tracing,kms]==1.0"' in with_overlay


def test_overlay_files_are_copied_and_removed_again(
    deploy_mod: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, config_file: Path
) -> None:
    monkeypatch.setattr(deploy_mod, "_repo_root", lambda: tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("tracked")
    overlay = deploy_mod._Overlay(files={"server-config.yml": config_file, "app.py": config_file})
    copied: list[Path] = []

    # The second file would overwrite a file the app source already has.
    with pytest.raises(SystemExit, match=r"src/app\.py already exists"):
        deploy_mod.copy_overlay_files(overlay, src, copied)

    assert copied == [src / "server-config.yml"]
    assert (src / "server-config.yml").read_text() == config_file.read_text()
    deploy_mod.remove_overlay_files(copied)
    assert not (src / "server-config.yml").exists()
    assert (src / "app.py").read_text() == "tracked"


def test_the_overlay_option_takes_a_path(
    deploy_mod: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["deploy.py", *_REQUIRED_ARGS])
    assert deploy_mod._parse_args().overlay is None

    monkeypatch.setattr(sys, "argv", ["deploy.py", *_REQUIRED_ARGS, "--overlay", "x.local.yml"])
    assert deploy_mod._parse_args().overlay == Path("x.local.yml")


def test_a_deploy_carries_the_whole_overlay(
    deploy_mod: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, config_file: Path
) -> None:
    """``main`` with the workspace, the build and the CLI replaced by fakes."""
    repo = tmp_path / "repo"
    deploy_dir = repo / "deploy" / "databricks"
    src = deploy_dir / "src"
    src.mkdir(parents=True)
    (deploy_dir / "databricks.yml").write_text(_BUNDLE_YML.read_text())
    (repo / "dist").mkdir()
    for prefix in ("omnigent", "omnigent_client", "omnigent_ui_sdk"):
        (repo / "dist" / f"{prefix}-1.0-py3-none-any.whl").write_bytes(b"wheel")
    overlay_path = tmp_path / "deploy.local.yml"
    overlay_path.write_text(
        yaml.safe_dump(
            {
                "host": "https://workspace.example.com",
                "extras": ["kms"],
                "env": {"OMNIGENT_CONFIG": "server-config.yml"},
                "files": {"server-config.yml": str(config_file)},
            }
        )
    )

    app = SimpleNamespace(url="https://app.example.com", service_principal_client_id="sp")
    fake_sdk = ModuleType("databricks.sdk")
    fake_sdk.WorkspaceClient = lambda **_kwargs: SimpleNamespace(  # type: ignore[attr-defined]
        apps=SimpleNamespace(get=lambda name: app)
    )
    monkeypatch.setitem(sys.modules, "databricks.sdk", fake_sdk)
    for name, replacement in {
        "_repo_root": lambda: repo,
        "_deploy_dir": lambda: deploy_dir,
        "_src_dir": lambda: src,
        "_is_gitignored": lambda path: False,
        "_known_extras": lambda: {"kms"},
        "_clear_env_vars": lambda: None,
        "_read_base_version": lambda: "1.0",
        "run_uv_lock": lambda src: None,
        "_ensure_bound": lambda args: None,
        "_ensure_compute_size": lambda *args: None,
        "_ensure_app_sp_uc_traversal": lambda *args: None,
    }.items():
        monkeypatch.setattr(deploy_mod, name, replacement)
    at_exit: list[tuple[Any, ...]] = []
    monkeypatch.setattr(deploy_mod.atexit, "register", lambda *call: at_exit.append(call))
    bundle_runs: list[tuple[list[str], set[str]]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess:
        bundle_runs.append((cmd, {path.name for path in src.iterdir()}))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(deploy_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy.py",
            *_REQUIRED_ARGS,
            "--no-otel",
            "--skip-build",
            "--version",
            "1.0",
            "--allow-dirty",
            "--no-smoke-check",
            "--overlay",
            str(overlay_path),
        ],
    )

    assert deploy_mod.main() == 0

    # Both bundle commands ran against the overlay's target, with its file in place.
    assert [cmd[2] for cmd, _ in bundle_runs] == ["deploy", "run"]
    for cmd, source_files in bundle_runs:
        assert cmd[cmd.index("--target") + 1] == "prod-no-otel-overlay"
        assert "server-config.yml" in source_files
    assert '"omnigent[databricks,tracing,kms]==1.0"' in (src / "pyproject.toml").read_text()
    fragment = yaml.safe_load((deploy_dir / deploy_mod._OVERLAY_BUNDLE_NAME).read_text())
    assert fragment["targets"]["prod-no-otel-overlay"]["workspace"]["host"] == (
        "https://workspace.example.com"
    )
    # The copy is removed when the deploy exits.
    ((cleanup, copied),) = at_exit
    cleanup(copied)
    assert not (src / "server-config.yml").exists()
