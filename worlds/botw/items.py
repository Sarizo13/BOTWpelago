"""
BotW Archipelago — item definitions.

Progression items: from data/gate_items.json (ap_progression + ap_progression_logical roles).
  - ap_progression       : flag-injectable items (Paraglider, Champions, Master Sword).
  - ap_progression_logical: logical-only gates (Flamebreaker, Snowquill, Vai Outfit).
                            No save-flag injection; purely tracked by AP for region logic.
Runes: role=starting → precollected at generation, never in the pool.
Filler: Spirit Orbs + weapons/arrows/food to fill remaining location slots.
"""
from __future__ import annotations

import json
import importlib.resources as _pkg
from dataclasses import dataclass
from typing import Dict, Optional, List

from BaseClasses import Item, ItemClassification

ITEM_BASE_ID  = 6_080_000


@dataclass
class BotWItemData:
    code: Optional[int]
    classification: ItemClassification
    flag_name: Optional[str] = None   # present only for flag-injectable items
    flag_hash: Optional[int] = None
    count: int = 1                    # pool copies


class BotWItem(Item):
    game: str = "The Legend of Zelda: Breath of the Wild"


_LOGICAL_ROLES = {"ap_progression", "ap_progression_logical"}


def _load_gate_items() -> Dict[str, BotWItemData]:
    ref = _pkg.files(__package__).joinpath("data/gate_items.json")
    raw = json.loads(ref.read_text(encoding="utf-8"))
    result: Dict[str, BotWItemData] = {}
    for entry in raw["items"]:
        if entry["role"] not in _LOGICAL_ROLES:
            continue
        fh_val = entry.get("flag_hash")
        result[entry["name"]] = BotWItemData(
            code=entry["ap_item_id"],
            classification=ItemClassification.progression,
            flag_name=entry.get("flag_name"),
            flag_hash=int(fh_val, 16) if fh_val else None,
        )
    return result


# ── Item table ────────────────────────────────────────────────────────────────

# Progression (flag-backed + logical — all ap_progression* entries from gate_items.json)
_progression: Dict[str, BotWItemData] = _load_gate_items()

def _load_filler_items() -> Dict[str, BotWItemData]:
    ref = _pkg.files(__package__).joinpath("data/gate_items.json")
    raw = json.loads(ref.read_text(encoding="utf-8"))
    result: Dict[str, BotWItemData] = {}
    for entry in raw.get("filler_items", []):
        result[entry["name"]] = BotWItemData(
            code=entry["ap_item_id"],
            classification=ItemClassification.filler,
            count=entry.get("count", 1),
        )
    return result


_filler: Dict[str, BotWItemData] = _load_filler_items()

item_table: Dict[str, BotWItemData] = {**_progression, **_filler}

item_name_to_id: Dict[str, int] = {
    name: data.code for name, data in item_table.items() if data.code is not None
}

# Public lists
progression_item_names: List[str] = list(_progression.keys())
filler_item_names:      List[str] = list(_filler.keys())
