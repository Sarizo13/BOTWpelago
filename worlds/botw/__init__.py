"""
The Legend of Zelda: Breath of the Wild — Archipelago World
BotW 1.5.0 Wii U / Cemu.

Locations : 205 shrine chests (186 base + 19 DLC, DLC optional). Shrine
            completion is NOT a check — only the chests inside shrines are.
Items     : Paraglider + Master Sword + 4 Champions + armour gates (progression)
            + Spirit Orbs + filler
Goal      : Defeat Calamity Ganon (Master Sword + 4 Champions + N shrines cleared)

Generation also emits a {settings, placements} config (generate_output) consumed
by the standalone BotW Randomizer (BOTW_AP_CONFIG) to place a green-rupee
placeholder in every AP shrine chest; the client swaps it for the real AP item.
"""
from __future__ import annotations

import json
import os
from typing import Any

from BaseClasses import ItemClassification, Tutorial

from worlds.AutoWorld import WebWorld, World

from .items import BotWItem, filler_item_names, item_name_to_id, item_table
from .locations import BotWLocation, active_locations, location_name_to_id
from .options import BotWOptions
from .regions import create_regions
from .rules import set_rules

GAME_NAME = "The Legend of Zelda: Breath of the Wild"

# Actor placed by the rando in every AP shrine chest (basic green rupee — the
# in-game placeholder; the client detects the chest open and grants the real item).
PLACEHOLDER_ACTOR = "PutRupee"

# AP option attribute → rando "randomize<Category>Checkbox" settings key.
RANDO_TOGGLE_MAP = {
    "randomize_animals":      "randomizeAnimalsCheckbox",
    "randomize_armor":        "randomizeArmorCheckbox",
    "randomize_armor_shops":  "randomizeArmorShopsCheckbox",
    "randomize_arrows":       "randomizeArrowsCheckbox",
    "randomize_bows":         "randomizeBowsCheckbox",
    "randomize_enemies":      "randomizeEnemiesCheckbox",
    "randomize_fishes":       "randomizeFishesCheckbox",
    "randomize_fruits":       "randomizeFruitsCheckbox",
    "randomize_insects":      "randomizeInsectsCheckbox",
    "randomize_long_swords":  "randomizeLongSwordsCheckbox",
    "randomize_mushrooms":    "randomizeMushroomsCheckbox",
    "randomize_ores":         "randomizeOresCheckbox",
    "randomize_plants":       "randomizePlantsCheckbox",
    "randomize_rupees":       "randomizeRupeesCheckbox",
    "randomize_shields":      "randomizeShieldsCheckbox",
    "randomize_spears":       "randomizeSpearsCheckbox",
    "randomize_swords":       "randomizeSwordsCheckbox",
    "randomize_sub_bosses":   "randomizeSubBossesCheckbox",
}

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

    item_name_to_id:     dict[str, int] = item_name_to_id
    location_name_to_id: dict[str, int] = location_name_to_id

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

        pool: list[BotWItem] = []

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

    # ── Active locations helper ───────────────────────────────────────────────

    def _active(self) -> dict:
        """Locations active for this slot (game mode + DLC toggle)."""
        return active_locations(
            self.options.game_mode.current_key,
            bool(self.options.include_dlc_shrines),
        )

    # ── Slot data (sent to client at connect) ─────────────────────────────────

    def fill_slot_data(self) -> dict[str, Any]:
        """
        Sent to the BotW client via AP Connected message. The client learns which
        locations belong to the slot from the Connected packet (checked/missing);
        slot_data just carries gameplay knobs.
        """
        return {
            "game_mode":                    self.options.game_mode.current_key,
            "death_link":                   bool(self.options.death_link),
            "required_shrine_count":        self.options.required_shrine_count.value,
            "goal_mode":                    self.options.goal_mode.current_key,   # "shrines" | "full"
            "randomize_champion_abilities": bool(self.options.randomize_champion_abilities),
            "randomize_master_sword":       bool(self.options.randomize_master_sword),
            "include_dlc_shrines":          bool(self.options.include_dlc_shrines),
            # Le config du rando voyage AUSSI dans le slot_data : BOTWpelago le reçoit à
            # la connexion et construit le pack SANS fichier à télécharger (indispensable
            # pour héberger sur le site public, qui ne sert pas les patches d'un monde custom).
            "rando_config":                 self._rando_config(),
        }

    # ── Rando config (consumed by the standalone BotW Randomizer) ──────────────

    def _rando_config(self) -> dict[str, Any]:
        """`{settings, placements}` que le rando lit via BOTW_AP_CONFIG : settings = les
        toggles overworld ; placements = {hashId: rubis-vert} pour chaque coffre AP."""
        settings = {
            rando_key: bool(getattr(self.options, attr))
            for attr, rando_key in RANDO_TOGGLE_MAP.items()
        }
        # Seuls les coffres de sanctuaire ont besoin d'un placeholder ; les autres
        # catégories (complétion, tours, créatures, lieux, quêtes, souvenirs) sont
        # détectées par leurs propres flags gamedata, sans placement rando.
        placements = {
            str(d.hash_id): PLACEHOLDER_ACTOR
            for d in self._active().values()
            if d.category == "shrine_chest"
        }
        return {
            "_comment":    "BotW Archipelago rando config — feed to the rando via BOTW_AP_CONFIG.",
            "seed":        self.multiworld.seed_name,
            "player":      self.player,
            "slot":        self.multiworld.get_player_name(self.player),
            "settings":    settings,
            "placements":  placements,
        }

    def generate_output(self, output_directory: str) -> None:
        """Écrit aussi le config en fichier `.apbotw` (utile en auto-hébergement). Le
        chemin suit la convention AP `AP_{seed}_P{player}_{name}.{ext}` — le host parse
        le slot via int(filename.split("_")[2][1:]), donc split[2] DOIT valoir "P{player}"
        (un préfixe custom faisait planter le chargement de la seed : int('onfig'))."""
        config = self._rando_config()
        fname = self.multiworld.get_out_file_name_base(self.player) + ".apbotw"
        with open(os.path.join(output_directory, fname), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
