from pathlib import Path

from omnigent.extensions import SlotId, registry

_REPO_ROOT = Path(__file__).parents[2]


def test_every_slot_has_a_kind_rule_and_frontend_literal() -> None:
    frontend_types = (_REPO_ROOT / "web" / "src" / "extensions" / "types.ts").read_text()

    assert set(registry._SLOT_KINDS) == set(SlotId)
    for slot in SlotId:
        assert f'"{slot.value}"' in frontend_types
