"""
BotW Archipelago — access rules.

Entrance rules:
  "Leave Great Plateau"   → requires Paraglider
  "Enter Eldin"           → requires Flamebreaker Armor
  "Enter Hebra"           → requires Snowquill Set
  "Enter Gerudo Highlands"→ requires Snowquill Set
  "Enter Gerudo Town"     → requires Vai Outfit

Goal:
  All 4 champion abilities (if randomized) + Master Sword (if randomized).
  DungeonClearCounter >= required_shrine_count is checked client-side only.

Anti-soft-lock:
  Runes are NEVER in the pool — precollected. Plateau shrines always reachable.
  Paraglider can only be placed in Great Plateau (sphere 1 guarantee).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from worlds.generic.Rules import set_rule

from .regions import (
    REGION_GREAT_PLATEAU, REGION_HYRULE_WORLD,
    REGION_ELDIN, REGION_HEBRA, REGION_GERUDO_HIGHLAND, REGION_GERUDO_TOWN,
)

if TYPE_CHECKING:
    from . import BotWWorld

CHAMPION_NAMES = [
    "Revali's Gale",
    "Daruk's Protection",
    "Mipha's Grace",
    "Urbosa's Fury",
]


def set_rules(world: "BotWWorld", regions: dict) -> None:
    player = world.player
    mw     = world.multiworld

    # ── Leave Great Plateau ──────────────────────────────────────────────────
    set_rule(
        mw.get_entrance("Leave Great Plateau", player),
        lambda state: state.has("Paraglider", player),
    )

    # ── Gated sub-regions ────────────────────────────────────────────────────
    set_rule(
        mw.get_entrance("Enter Eldin", player),
        lambda state: state.has("Flamebreaker Armor", player),
    )
    set_rule(
        mw.get_entrance("Enter Hebra", player),
        lambda state: state.has("Snowquill Set", player),
    )
    set_rule(
        mw.get_entrance("Enter Gerudo Highlands", player),
        lambda state: state.has("Snowquill Set", player),
    )
    set_rule(
        mw.get_entrance("Enter Gerudo Town", player),
        lambda state: state.has("Vai Outfit", player),
    )

    # ── Victory condition ────────────────────────────────────────────────────
    champions_required = world.options.randomize_champion_abilities
    sword_required     = world.options.randomize_master_sword

    goal_loc = mw.get_location("Defeat Calamity Ganon", player)

    def _goal(state):
        if champions_required and not all(state.has(c, player) for c in CHAMPION_NAMES):
            return False
        if sword_required and not state.has("Master Sword", player):
            return False
        return True

    set_rule(goal_loc, _goal)

    mw.completion_condition[player] = lambda state: state.has("Defeat Calamity Ganon", player)
