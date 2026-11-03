import re
from pathlib import Path

from omnigent.extensions import FieldTone, SlotId, SlotItemKind, registry

_REPO_ROOT = Path(__file__).parents[2]


def test_every_slot_has_a_kind_rule_and_frontend_literal() -> None:
    frontend_types = (_REPO_ROOT / "web" / "src" / "extensions" / "types.ts").read_text()

    assert set(registry._SLOT_KINDS) == set(SlotId)
    for slot in SlotId:
        assert f'"{slot.value}"' in frontend_types
    for kind in SlotItemKind:
        assert f'"{kind.value}"' in frontend_types


def test_approved_icons_match_the_web_icon_map() -> None:
    icons = (_REPO_ROOT / "web" / "src" / "extensions" / "icons.ts").read_text()
    body = icons.split("const ICONS", 1)[1].split("};", 1)[0]
    names = {match.strip('"') for match in re.findall(r'^\s+("?[a-z-]+"?):', body, re.MULTILINE)}

    assert names == registry.APPROVED_ICONS


def test_every_field_tone_has_a_web_class() -> None:
    rows = (_REPO_ROOT / "web" / "src" / "shell" / "sessionRowSlots.ts").read_text()

    for tone in FieldTone:
        assert re.search(rf"^\s+{tone.value}: \"text-status-", rows, re.MULTILINE), tone
