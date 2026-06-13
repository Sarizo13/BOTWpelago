"""
AP item ID → InjectionSpec.
Source of truth: data/gate_items.json.

Roles handled:
  ap_progression         — flag-injectable (Paraglider, Champions, Master Sword).
                           Client sets the flag in game_data.sav on receipt.
  ap_progression_logical — region-gate items (Flamebreaker, Snowquill, Vai Outfit).
                           No save injection — purely tracked for gate-enforcement logic.
                           AP ensures the player receives these before entering gated regions.
  starting               — ignored here (precollected by the apworld generator).
  filler (no role)       — empty actions; shown as log message only.
"""
from __future__ import annotations

import json
from pathlib import Path

from BotWClient.providers.base import InjectionSpec

_GATE_FILE = Path(__file__).parent.parent / "data" / "gate_items.json"

with open(_GATE_FILE, encoding="utf-8") as _fh:
    _GATE = json.load(_fh)

# Build map: ap_item_id → InjectionSpec
ITEM_MAP: dict[int, InjectionSpec] = {}

for _item in _GATE["items"]:
    if _item["role"] == "ap_progression":
        ITEM_MAP[_item["ap_item_id"]] = InjectionSpec(
            ap_item_id   = _item["ap_item_id"],
            ap_item_name = _item["name"],
            actions      = [InjectionSpec.SetFlag(flag_name=_item["flag_name"])],
            display_note = _item.get("note", ""),
        )
    elif _item["role"] == "ap_progression_logical":
        # No save injection — the item is tracked logically in _received set
        # so gate enforcement knows not to block the corresponding region.
        ITEM_MAP[_item["ap_item_id"]] = InjectionSpec(
            ap_item_id   = _item["ap_item_id"],
            ap_item_name = _item["name"],
            actions      = [],
            display_note = _item.get("gates", ""),
        )

def _build_actions(inject) -> list:
    """Build an actions list from a gate_items.json `inject` field (dict or list of dicts)."""
    if not inject:
        return []
    entries = inject if isinstance(inject, list) else [inject]
    actions = []
    for entry in entries:
        t = entry.get("type", "")
        if t == "set_flag":
            actions.append(InjectionSpec.SetFlag(flag_name=entry["flag"]))
        elif t == "add_s32":
            actions.append(InjectionSpec.AddS32(flag_name=entry["flag"], amount=entry.get("amount", 1)))
        elif t == "add_porch":
            actions.append(InjectionSpec.AddPouchItem(item_name=entry["item"], amount=entry.get("amount", 1)))
    return actions


# Filler items — inject if `inject` field present, else name-lookup only.
for _item in _GATE.get("filler_items", []):
    ITEM_MAP[_item["ap_item_id"]] = InjectionSpec(
        ap_item_id   = _item["ap_item_id"],
        ap_item_name = _item["name"],
        actions      = _build_actions(_item.get("inject")),
        display_note = "",
    )


def get_spec(ap_item_id: int) -> InjectionSpec:
    """Return the injection spec for the given AP item ID, or a no-op filler spec."""
    if ap_item_id in ITEM_MAP:
        return ITEM_MAP[ap_item_id]
    return InjectionSpec(
        ap_item_id   = ap_item_id,
        ap_item_name = f"Item #{ap_item_id}",
        actions      = [],
        display_note = "",
    )
