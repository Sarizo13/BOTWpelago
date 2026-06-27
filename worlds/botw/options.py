"""
BotW Archipelago — per-game options.

Two families:
  - AP logic options (shrine goal, champion/sword/DLC shuffling).
  - Rando passthrough toggles — exposed here, forwarded verbatim to the
    standalone BotW Randomizer via the generated {settings} config. They control
    which *overworld* item categories the rando shuffles (independent of the AP
    shrine-chest checks, which are always placed).
"""
from dataclasses import dataclass

from Options import Choice, DeathLink, DefaultOnToggle, PerGameCommonOptions, Range, Toggle


# ── AP logic options ────────────────────────────────────────────────────────

class GameMode(Choice):
    """
    Which locations are active checks:
      - all_shrines : shrine completions + Divine Beasts only.
      - normal      : Sheikah Towers + shrine chests + memories + quests + places
                      + Divine Beasts (NOT shrine completion).
      - all         : every location (shrine completion + chests + towers + beasts
                      + places + quests + memories).
    """
    display_name = "Game Mode"
    option_all_shrines = 0
    option_normal = 1
    option_all = 2
    default = 1

class IncludeDLCShrines(Toggle):
    """
    Include the 16 DLC shrines' chests (Trial of the Sword / EX shrines) as
    location checks. Requires the BotW DLC. Off by default.
    """
    display_name = "Include DLC Shrine Chests"


class RequiredShrineCount(Range):
    """
    Number of shrines that must be completed (DungeonClearCounter) alongside
    the 4 Champion Abilities and Master Sword before Calamity Ganon's arena opens.
    Checked client-side.
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


# ── Rando passthrough toggles (overworld category shuffles) ──────────────────
# Each maps to the rando's "randomize<Category>Checkbox" setting key.

class RandomizeArmor(Toggle):
    """Shuffle armor pieces found in the overworld."""
    display_name = "Randomize Armor"

class RandomizeArmorShops(Toggle):
    """Shuffle armor sold in shops."""
    display_name = "Randomize Armor Shops"

class RandomizeSwords(Toggle):
    """Shuffle one-handed swords."""
    display_name = "Randomize Swords"

class RandomizeLongSwords(Toggle):
    """Shuffle two-handed long swords."""
    display_name = "Randomize Long Swords"

class RandomizeSpears(Toggle):
    """Shuffle spears."""
    display_name = "Randomize Spears"

class RandomizeShields(Toggle):
    """Shuffle shields."""
    display_name = "Randomize Shields"

class RandomizeBows(Toggle):
    """Shuffle bows."""
    display_name = "Randomize Bows"

class RandomizeArrows(Toggle):
    """Shuffle arrow bundles."""
    display_name = "Randomize Arrows"

class RandomizeRupees(Toggle):
    """Shuffle rupee rewards."""
    display_name = "Randomize Rupees"

class RandomizeOres(Toggle):
    """Shuffle ore deposits / gems."""
    display_name = "Randomize Ores"

class RandomizeEnemies(Toggle):
    """Shuffle overworld enemies."""
    display_name = "Randomize Enemies"

class RandomizeSubBosses(Toggle):
    """Shuffle sub-bosses (Hinox, Talus, Molduga...)."""
    display_name = "Randomize Sub-Bosses"

class RandomizeInsects(Toggle):
    """Shuffle insects / critters."""
    display_name = "Randomize Insects"

class RandomizePlants(Toggle):
    """Shuffle plants."""
    display_name = "Randomize Plants"

class RandomizeMushrooms(Toggle):
    """Shuffle mushrooms."""
    display_name = "Randomize Mushrooms"

class RandomizeFruits(Toggle):
    """Shuffle fruits."""
    display_name = "Randomize Fruits"

class RandomizeAnimals(Toggle):
    """Shuffle animals."""
    display_name = "Randomize Animals"

class RandomizeFishes(Toggle):
    """Shuffle fishes."""
    display_name = "Randomize Fishes"


@dataclass
class BotWOptions(PerGameCommonOptions):
    game_mode: GameMode
    death_link: DeathLink
    include_dlc_shrines: IncludeDLCShrines
    required_shrine_count: RequiredShrineCount
    randomize_champion_abilities: RandomizeChampionAbilities
    randomize_master_sword: RandomizeMasterSword
    # Rando passthrough toggles
    randomize_armor: RandomizeArmor
    randomize_armor_shops: RandomizeArmorShops
    randomize_swords: RandomizeSwords
    randomize_long_swords: RandomizeLongSwords
    randomize_spears: RandomizeSpears
    randomize_shields: RandomizeShields
    randomize_bows: RandomizeBows
    randomize_arrows: RandomizeArrows
    randomize_rupees: RandomizeRupees
    randomize_ores: RandomizeOres
    randomize_enemies: RandomizeEnemies
    randomize_sub_bosses: RandomizeSubBosses
    randomize_insects: RandomizeInsects
    randomize_plants: RandomizePlants
    randomize_mushrooms: RandomizeMushrooms
    randomize_fruits: RandomizeFruits
    randomize_animals: RandomizeAnimals
    randomize_fishes: RandomizeFishes
