"""
BotW Archipelago — access rules.

Entrance rules (alignées sur les MURS physiques du mod V2) :
  "Leave Great Plateau"   → requires Paraglider
  "Enter Eldin"           → requires Flamebreaker Armor
  "Enter Hebra"           → requires Snowquill Set
  "Enter Zora"            → requires Zora Armor
  "Enter Gerudo"          → requires Vai Outfit
  "Enter Gerudo Town"     → requires Vai Outfit

Goal (aligné sur l'option goal_mode et sur is_goal_complete côté client) :
  shrines : aucune exigence d'item.
  full    : Bow of Light (mur physique du Sanctum, mod V2 région "Ganon")
            + Master Sword (si randomisée) + les 4 Créatures atteignables.
  DungeonClearCounter >= required_shrine_count is checked client-side only.

Anti-soft-lock:
  Runes are NEVER in the pool — precollected. Plateau shrines always reachable.
  Paraglider can only be placed in Great Plateau (sphere 1 guarantee).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from worlds.generic.Rules import set_rule

if TYPE_CHECKING:
    from . import BotWWorld

BEAST_LOCATIONS = [
    "Divine Beast Vah Medoh",
    "Divine Beast Vah Rudania",
    "Divine Beast Vah Ruta",
    "Divine Beast Vah Naboris",
]


def goal_reached(state, player: int, full: bool, sword_required: bool) -> bool:
    """Victoire au sens de la génération — miroir de is_goal_complete (client) : en "full",
    le client exige Clear_Remains* (4 Créatures battues), Get_MasterSword_Finish et
    IsGet_Weapon_Bow_071 (posé pendant Dark Beast, derrière le mur du Sanctum)."""
    if not full:
        return True
    if not state.has("Bow of Light", player):
        return False
    if sword_required and not state.has("Master Sword", player):
        return False
    return all(state.can_reach_location(name, player) for name in BEAST_LOCATIONS)


def set_rules(world: BotWWorld, regions: dict) -> None:
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
        mw.get_entrance("Enter Zora", player),
        lambda state: state.has("Zora Armor", player),
    )
    set_rule(
        mw.get_entrance("Enter Gerudo", player),
        lambda state: state.has("Vai Outfit", player),
    )
    set_rule(
        mw.get_entrance("Enter Gerudo Town", player),
        lambda state: state.has("Vai Outfit", player),
    )

    # ── Victory condition ────────────────────────────────────────────────────
    full           = world.options.goal_mode.current_key == "full"
    sword_required = bool(world.options.randomize_master_sword)

    goal_loc = mw.get_location("Defeat Calamity Ganon", player)
    set_rule(goal_loc, lambda state: goal_reached(state, player, full, sword_required))

    mw.completion_condition[player] = lambda state: state.has("Defeat Calamity Ganon", player)
