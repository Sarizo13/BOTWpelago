"""
BotW Archipelago — region graph.

Region hierarchy:
  Great Plateau       — always accessible (starting area, 4 shrines + Plateau Tower)
  Hyrule World        — after Paraglider (all freely accessible areas)
  Eldin               — from Hyrule World + Flamebreaker Armor
  Hebra               — from Hyrule World + Snowquill Set
  Gerudo Highlands    — from Hyrule World + Snowquill Set
  Gerudo Town         — from Hyrule World + Vai Outfit

Access rules are wired in rules.py.
Location → region routing is driven by the "region" field in data/shrine_chests.json.
Anything with an empty or unrecognised region defaults to Hyrule World.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import Entrance, Region

from .locations import BotWLocation, location_table

if TYPE_CHECKING:
    from . import BotWWorld

# Canonical AP region names — used both here and in rules.py.
REGION_GREAT_PLATEAU   = "Great Plateau"
REGION_HYRULE_WORLD    = "Hyrule World"
REGION_ELDIN           = "Eldin"
REGION_HEBRA           = "Hebra"
REGION_GERUDO_HIGHLAND = "Gerudo Highlands"
REGION_GERUDO_TOWN     = "Gerudo Town"

_ALL_REGIONS = {
    REGION_GREAT_PLATEAU,
    REGION_HYRULE_WORLD,
    REGION_ELDIN,
    REGION_HEBRA,
    REGION_GERUDO_HIGHLAND,
    REGION_GERUDO_TOWN,
}


def create_regions(world: BotWWorld) -> dict[str, Region]:
    player = world.player
    mw = world.multiworld

    # AP requires a "Menu" region as the universal starting point.
    menu = Region("Menu", player, mw)

    # Create all game regions.
    regions: dict[str, Region] = {
        name: Region(name, player, mw) for name in _ALL_REGIONS
    }

    include_dlc = bool(world.options.include_dlc_shrines)

    # Assign each shrine-chest location to its region (region pre-baked in data).
    for loc_name, loc_data in location_table.items():
        if loc_data.dlc and not include_dlc:
            continue
        # Route to the correct region; unknown/empty → Hyrule World.
        r_name = loc_data.region if loc_data.region in _ALL_REGIONS else REGION_HYRULE_WORLD
        region = regions[r_name]
        loc = BotWLocation(player, loc_name, loc_data.code, region)
        region.locations.append(loc)

    # ── Entrances ─────────────────────────────────────────────────────────────
    # Menu → Great Plateau  (always accessible — AP standard)
    _connect(player, "To Great Plateau", menu, regions[REGION_GREAT_PLATEAU])

    # Great Plateau → Hyrule World  (Paraglider — rule in rules.py)
    _connect(player, "Leave Great Plateau",
             regions[REGION_GREAT_PLATEAU], regions[REGION_HYRULE_WORLD])

    # Hyrule World → gated sub-regions  (rules set in rules.py)
    _connect(player, "Enter Eldin",
             regions[REGION_HYRULE_WORLD], regions[REGION_ELDIN])
    _connect(player, "Enter Hebra",
             regions[REGION_HYRULE_WORLD], regions[REGION_HEBRA])
    _connect(player, "Enter Gerudo Highlands",
             regions[REGION_HYRULE_WORLD], regions[REGION_GERUDO_HIGHLAND])
    _connect(player, "Enter Gerudo Town",
             regions[REGION_HYRULE_WORLD], regions[REGION_GERUDO_TOWN])

    mw.regions.append(menu)
    for region in regions.values():
        mw.regions.append(region)

    return regions


def _connect(player: int, name: str, src: Region, dst: Region) -> Entrance:
    entrance = Entrance(player, name, src)
    src.exits.append(entrance)
    entrance.connect(dst)
    return entrance
