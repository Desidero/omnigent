import re
from pathlib import Path

from omnigent.extensions import SlotId, registry

_REPO_ROOT = Path(__file__).parents[2]
_WEB_EXTENSIONS = _REPO_ROOT / "web" / "src" / "extensions"


def _ts_record(source: str, name: str) -> dict[str, str]:
    body = re.search(rf"export const {name}[^=]*= \{{(.*?)\}};", source, re.DOTALL)
    assert body is not None, f"{name} not found in slots.ts"
    return dict(re.findall(r'"([^"]+)": "?([^",\n]+)"?,', body.group(1)))


def test_every_slot_has_a_kind_rule_and_frontend_literal() -> None:
    frontend_types = (_WEB_EXTENSIONS / "types.ts").read_text()

    assert set(registry._SLOT_KINDS) == set(SlotId)
    for slot in SlotId:
        assert f'"{slot.value}"' in frontend_types


def test_web_slot_contract_matches_the_validator() -> None:
    slots = (_WEB_EXTENSIONS / "slots.ts").read_text()

    assert _ts_record(slots, "SLOT_KINDS") == {
        slot.value: kind.value for slot, kind in registry._SLOT_KINDS.items()
    }
    assert _ts_record(slots, "SLOT_ITEM_LIMITS") == {
        slot.value: str(limit) for slot, limit in registry._SLOT_ITEM_LIMITS.items()
    }
    assert f"MAX_SLOT_TEXT_LENGTH = {registry._MAX_TEXT_LENGTH};" in slots
    assert f'CORE_ENTRY_ID_PREFIX = "{registry.RESERVED_CORE_ID_PREFIX}";' in slots
    assert registry._ID_SEGMENT in slots
