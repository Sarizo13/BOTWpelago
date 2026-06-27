"""
BotW Archipelago — location definitions.

The world ships TWO catalogues, unified here into one table keyed by name:
  - shrine_chests.json : 205 shrine chests   (category "shrine_chest")
  - locations.json     : 646 game locations  (categories shrine|tower|beast|
                         location|quest|memory) — shrine *completion*, towers,
                         Divine Beasts, places, quests, memories.

Which categories are ACTIVE checks is decided per-seed by the Game Mode option
(see MODE_CATEGORIES). Every location is detected client-side by its gamedata
flag (flag_hash = crc32(flag_name)); shrine chests additionally carry a rando
HashId used to place the green-rupee placeholder.
"""
from __future__ import annotations

import importlib.resources as _pkg
import json
from dataclasses import dataclass

from BaseClasses import Location

# Game Mode → set of active location categories.
MODE_CATEGORIES: dict[str, set[str]] = {
    "all_shrines": {"shrine", "beast"},
    "normal":      {"tower", "shrine_chest", "memory", "quest", "location", "beast"},
    "all":         {"shrine", "shrine_chest", "tower", "beast", "location", "quest", "memory"},
}


@dataclass
class BotWLocationData:
    code: int
    category: str       # shrine | shrine_chest | tower | beast | location | quest | memory
    flag_name: str      # gamedata flag set when the check is completed
    flag_hash: int      # crc32(flag_name) — the value the client polls
    region: str
    dlc: bool = False
    hash_id: int | None = None   # shrine_chest only — rando placement key


class BotWLocation(Location):
    game: str = "The Legend of Zelda: Breath of the Wild"


def _read(name: str) -> list[dict]:
    ref = _pkg.files(__package__).joinpath(f"data/{name}")
    return json.loads(ref.read_text(encoding="utf-8"))


def _load() -> dict[str, BotWLocationData]:
    result: dict[str, BotWLocationData] = {}
    for entry in _read("locations.json") + _read("shrine_chests.json"):
        result[entry["name"]] = BotWLocationData(
            code=entry["ap_id"],
            category=entry["category"],
            flag_name=entry["flag_name"],
            flag_hash=int(entry["flag_hash"], 16),
            region=entry.get("region") or "Hyrule World",
            dlc=bool(entry.get("dlc", False)),
            hash_id=int(entry["hash_id"]) if entry.get("hash_id") is not None else None,
        )
    return result


# Built at import time — fast dict, no per-call JSON parsing.
location_table: dict[str, BotWLocationData] = _load()

location_name_to_id: dict[str, int] = {
    name: data.code for name, data in location_table.items()
}


def active_locations(mode_key: str, include_dlc: bool) -> dict[str, BotWLocationData]:
    """Locations that are active checks for the given mode (+ DLC toggle)."""
    cats = MODE_CATEGORIES.get(mode_key, MODE_CATEGORIES["normal"])
    return {
        n: d for n, d in location_table.items()
        if d.category in cats and (include_dlc or not d.dlc)
    }


# crc32(flag_name) → location name (for client-side poll of gamedata)
flag_hash_to_location: dict[int, str] = {
    data.flag_hash: name for name, data in location_table.items()
}
