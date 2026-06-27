"""
BotW Archipelago — location definitions.

Locations are SHRINE CHESTS (205: 186 base + 19 DLC). Shrine *completion* is no
longer a check — the player still explores shrines freely, but only the chests
inside them are randomized checks. Each chest is identified by its rando HashId
(used both to drive item placement in the rando config and to detect the chest
being opened, client-side).

Source of truth: data/shrine_chests.json (region pre-baked by tools).
"""
from __future__ import annotations

import importlib.resources as _pkg
import json
from dataclasses import dataclass

from BaseClasses import Location


@dataclass
class BotWLocationData:
    code: int
    category: str       # "shrine_chest"
    hash_id: int        # rando HashId — drives item placement in the rando config
    flag_name: str      # CDungeon_TBox_Dungeon_<Material>_<HashId> — set when opened
    flag_hash: int      # crc32(flag_name) — the value the client polls in gamedata
    dungeon_id: int
    region: str
    dlc: bool
    vanilla: str        # original chest content actor (reference only)


class BotWLocation(Location):
    game: str = "The Legend of Zelda: Breath of the Wild"


def _load() -> dict[str, BotWLocationData]:
    ref = _pkg.files(__package__).joinpath("data/shrine_chests.json")
    raw: list[dict] = json.loads(ref.read_text(encoding="utf-8"))
    result: dict[str, BotWLocationData] = {}
    for entry in raw:
        result[entry["name"]] = BotWLocationData(
            code=entry["ap_id"],
            category=entry["category"],
            hash_id=int(entry["hash_id"]),
            flag_name=entry["flag_name"],
            flag_hash=int(entry["flag_hash"], 16),
            dungeon_id=int(entry["dungeon_id"]),
            region=entry.get("region", "Hyrule World"),
            dlc=bool(entry.get("dlc", False)),
            vanilla=entry.get("vanilla", ""),
        )
    return result


# Built at import time — fast dict, no per-call JSON parsing.
location_table: dict[str, BotWLocationData] = _load()

location_name_to_id: dict[str, int] = {
    name: data.code for name, data in location_table.items()
}

# Category sub-sets
shrine_chest_locations: list[str] = [
    n for n, d in location_table.items() if d.category == "shrine_chest"
]

# crc32(flag_name) → location name (for client-side chest-open poll of gamedata)
flag_hash_to_location: dict[int, str] = {
    data.flag_hash: name for name, data in location_table.items()
}

# rando HashId → location name (placement-side reference)
hash_to_location: dict[int, str] = {
    data.hash_id: name for name, data in location_table.items()
}
