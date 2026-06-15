from dataclasses import dataclass

from Options import DefaultOnToggle, PerGameCommonOptions, Range


class IncludeTowers(DefaultOnToggle):
    """Include the 15 Sheikah Tower activations as location checks."""
    display_name = "Include Sheikah Towers"


class RequiredShrineCount(Range):
    """
    Number of shrines that must be completed (DungeonClearCounter) alongside
    the 4 Champion Abilities and Master Sword before Calamity Ganon's arena opens.
    """
    display_name = "Required Shrine Count"
    range_start = 0
    range_end = 120
    default = 20


class RandomizeChampionAbilities(DefaultOnToggle):
    """
    Shuffle the four Champion Abilities (Revali's Gale, Mipha's Grace,
    Daruk's Protection, Urbosa's Fury) into the multiworld item pool.
    When off, they are granted immediately upon completing each Divine Beast.
    """
    display_name = "Randomize Champion Abilities"


class RandomizeMasterSword(DefaultOnToggle):
    """
    Shuffle the Master Sword into the multiworld item pool.
    When off, it is obtainable by vanilla means (13 hearts at Korok Forest).
    """
    display_name = "Randomize Master Sword"


@dataclass
class BotWOptions(PerGameCommonOptions):
    include_towers: IncludeTowers
    required_shrine_count: RequiredShrineCount
    randomize_champion_abilities: RandomizeChampionAbilities
    randomize_master_sword: RandomizeMasterSword
