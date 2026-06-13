"""
The Legend of Zelda: Breath of the Wild — Archipelago World
BotW 1.5.0 Wii U / Cemu.

Locations : 120 shrines + 15 towers + 4 Divine Beasts = 139 (towers optional)
Items     : Paraglider + Master Sword + 4 Champions (progression) + Spirit Orbs + filler
Goal      : Defeat Calamity Ganon (Master Sword + 4 Champions + N shrines cleared)
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from BaseClasses import Item, ItemClassification, Tutorial
from worlds.AutoWorld import World, WebWorld

from .items   import BotWItem, BotWItemData, item_table, item_name_to_id, filler_item_names
from .locations import BotWLocation, location_table, location_name_to_id, shrine_locations, tower_locations
from .regions import create_regions
from .rules   import set_rules
from .options import BotWOptions

GAME_NAME = "The Legend of Zelda: Breath of the Wild"

# Runes are starting items (precollected) — never placed in the pool.
STARTING_RUNE_NAMES = [
    "Magnesis Rune",
    "Stasis Rune",
    "Cryonis Rune",
    "Remote Bomb Rune",
    "Camera Rune",
]


class BotWWebWorld(WebWorld):
    theme = "ocean"
    tutorials = [Tutorial(
        "Multiworld Setup Guide",
        "Setting up BotW Archipelago with Cemu.",
        "English",
        "setup.md",
        "setup/en",
        ["BotW-AP contributors"],
    )]


class BotWWorld(World):
    """
    The Legend of Zelda: Breath of the Wild — open-world action-adventure.
    Explore Hyrule, complete 120 shrines, defeat the Divine Beasts, and stop
    Calamity Ganon.
    """

    game              = GAME_NAME
    options_dataclass = BotWOptions
    options:            BotWOptions
    web               = BotWWebWorld()

    item_name_to_id:     Dict[str, int] = item_name_to_id
    location_name_to_id: Dict[str, int] = location_name_to_id

    item_name_groups = {
        "Champions": {"Revali's Gale", "Daruk's Protection", "Mipha's Grace", "Urbosa's Fury"},
    }

    # ── Generation ────────────────────────────────────────────────────────────

    def create_item(self, name: str) -> BotWItem:
        data = item_table[name]
        return BotWItem(name, data.classification, data.code, self.player)

    def create_items(self) -> None:
        # Champions and Master Sword may be excluded (non-randomized).
        excluded: set[str] = set()
        if not self.options.randomize_champion_abilities:
            excluded |= {"Revali's Gale", "Daruk's Protection", "Mipha's Grace", "Urbosa's Fury"}
        if not self.options.randomize_master_sword:
            excluded.add("Master Sword")

        # Count active locations.
        active_locs = [
            loc for loc in self.multiworld.get_unfilled_locations(self.player)
            if loc.name != "Defeat Calamity Ganon"
        ]
        target = len(active_locs)

        pool: List[BotWItem] = []

        # Add all progression items (except excluded).
        for name, data in item_table.items():
            if data.classification != ItemClassification.progression:
                continue
            if name in excluded:
                continue
            for _ in range(data.count):
                pool.append(self.create_item(name))

        # Pad with filler via tirage PONDÉRÉ (count = poids) pour des quantités/items variés :
        # Spirit Orb domine (count élevé), les ~130 ingrédients apportent la variété.
        names   = [n for n in filler_item_names if n in item_table]
        weights = [max(1, item_table[n].count) for n in names]
        if names:
            while len(pool) < target:
                pool.append(self.create_item(self.random.choices(names, weights=weights)[0]))

        self.multiworld.itempool += pool[:target]

    def create_regions(self) -> None:
        self._regions = create_regions(self)

        # Add the locked goal location in Hyrule World.
        goal_region = self._regions["Hyrule World"]
        goal_loc = BotWLocation(self.player, "Defeat Calamity Ganon", None, goal_region)
        goal_region.locations.append(goal_loc)

    def set_rules(self) -> None:
        set_rules(self, self._regions)

    def generate_basic(self) -> None:
        # Precollect runes (never in pool — needed for Plateau shrines).
        rune_items = {
            "Magnesis Rune":   "IsGet_Obj_Magnetglove",
            "Stasis Rune":     "IsGet_Obj_StopTimer",
            "Cryonis Rune":    "IsGet_Obj_IceMaker",
            "Remote Bomb Rune":"IsGet_Obj_RemoteBomb",
            "Camera Rune":     "IsGet_Obj_Camera",
        }
        for name in rune_items:
            self.multiworld.push_precollected(
                BotWItem(name, ItemClassification.progression, None, self.player)
            )

        # Place the victory item.
        goal_loc = self.multiworld.get_location("Defeat Calamity Ganon", self.player)
        goal_loc.place_locked_item(
            BotWItem("Defeat Calamity Ganon", ItemClassification.progression, None, self.player)
        )

    # ── Slot data (sent to client at connect) ─────────────────────────────────

    def fill_slot_data(self) -> Dict[str, Any]:
        """
        Sent to the BotW client via AP Connected message.
        The client uses this to know which flags to poll and which gates to enforce.
        """
        return {
            "required_shrine_count":         self.options.required_shrine_count.value,
            "randomize_champion_abilities":  bool(self.options.randomize_champion_abilities),
            "randomize_master_sword":        bool(self.options.randomize_master_sword),
            "include_towers":                bool(self.options.include_towers),
        }
