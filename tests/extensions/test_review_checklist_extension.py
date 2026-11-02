"""The review checklist example package passes the manifest and bundle checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from omnigent.extensions import (
    ExtensionManifest,
    ExtensionPermission,
    SlotId,
    check_extension_package,
)
from omnigent.extensions.assets import ASSET_SCRIPT

_REPO_ROOT = Path(__file__).parents[2]
_EXAMPLE_ROOT = _REPO_ROOT / "examples" / "extensions" / "review-checklist"
_PACKAGE_ROOT = _EXAMPLE_ROOT / "src" / "omnigent_review_checklist_extension"


def _load_manifest() -> ExtensionManifest:
    spec = importlib.util.spec_from_file_location(
        "omnigent_review_checklist_extension.plugin", _PACKAGE_ROOT / "plugin.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    assert isinstance(module, ModuleType)
    spec.loader.exec_module(module)
    return module.get_manifest()


def test_package_passes_conformance_with_its_committed_bundle() -> None:
    manifest = _load_manifest()
    bundle = check_extension_package(
        manifest, package_root=_PACKAGE_ROOT, project_root=_EXAMPLE_ROOT
    )
    assert bundle is not None
    assert b"Saved in this browser only" in bundle.assets[ASSET_SCRIPT].content


def test_manifest_contributes_header_composer_and_settings_links_only() -> None:
    manifest = _load_manifest()
    assert {(item.slot, item.page) for item in manifest.slot_items} == {
        (SlotId.CHAT_HEADER_ACTIONS, "omnigent.review-checklist.review"),
        (SlotId.COMPOSER_ACTIONS, "omnigent.review-checklist.review"),
        (SlotId.SETTINGS_SECTIONS, "omnigent.review-checklist.templates"),
    }
    assert manifest.primary_navigation == ()
    assert ExtensionPermission.SESSIONS_READ in manifest.permissions
    assert ExtensionPermission.STORAGE_USER in manifest.permissions
