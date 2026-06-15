"""
BotW Archipelago — location definitions.
Source of truth: data/locations.json (646 entries: 120 shrines + 15 towers
+ 4 beasts + 318 lieux + 175 quêtes + 14 souvenirs).
"""
from __future__ import annotations

import importlib.resources as _pkg
import json
from dataclasses import dataclass

from BaseClasses import Location


@dataclass
class BotWLocationData:
    code: int
    category: str      # "shrine" | "tower" | "beast"
    flag_name: str
    flag_hash: int     # pre-computed crc32 value
    region: str


class BotWLocation(Location):
    game: str = "The Legend of Zelda: Breath of the Wild"


def _load() -> dict[str, BotWLocationData]:
    ref = _pkg.files(__package__).joinpath("data/locations.json")
    raw: list[dict] = json.loads(ref.read_text(encoding="utf-8"))
    result: dict[str, BotWLocationData] = {}
    for entry in raw:
        result[entry["name"]] = BotWLocationData(
            code=entry["ap_id"],
            category=entry["category"],
            flag_name=entry["flag_name"],
            flag_hash=int(entry["flag_hash"], 16),
            region=entry.get("region", ""),
        )
    return result


# Built at import time — fast dict, no per-call JSON parsing.
location_table: dict[str, BotWLocationData] = _load()

location_name_to_id: dict[str, int] = {
    name: data.code for name, data in location_table.items()
}

# Category sub-sets (used by rules and client)
shrine_locations: list[str] = [n for n, d in location_table.items() if d.category == "shrine"]
tower_locations:  list[str] = [n for n, d in location_table.items() if d.category == "tower"]
beast_locations:  list[str] = [n for n, d in location_table.items() if d.category == "beast"]

# flag_hash → location name (for client-side poll)
hash_to_location: dict[int, str] = {
    data.flag_hash: name for name, data in location_table.items()
}
