# BotW Archipelago — BOTWpelago

Archipelago multiworld randomizer support for **The Legend of Zelda: Breath of the Wild**
(Wii U / Cemu, game version **1.5.0**).

Checks are the **chests inside Shrines**. Each AP shrine chest is filled with a green-rupee
placeholder by a modified BotW Randomizer graphic pack; the client detects the chest being
opened and delivers the real Archipelago item.

## How it works (player flow)

```
Each player writes a YAML  ─►  one host generates the seed (Archipelago + the botw .apworld)
                                          │  produces one BotW_AP_config_*.json per BotW slot
                                          ▼
BOTWpelago (the player app)  ─►  reads the config  ─►  drives the embedded BotW Randomizer
   to build a Cemu graphic pack (green rupee in every AP shrine chest)  ─►  installs it in Cemu
                                          ▼
   the player plays ; the client polls the chest-open flags and injects received AP items
```

- The **`.apworld`** (host side) places the multiworld items across the shrine-chest locations
  and emits `{settings, placements}` — the config the BotW Randomizer consumes.
- **BOTWpelago** (player side) = a Tkinter GUI + the AP client + an embedded copy of the
  randomizer. It builds the pack from the config, then runs the client during play.
- A shrine chest opening sets the gamedata flag `CDungeon_TBox_Dungeon_<Material>_<HashId>`;
  the client polls it (`flag_id = crc32(flag_name)`) and sends `LocationChecks(ap_id)`.
- Received items are injected live into Cemu's memory (rupees / pouch items) or via save
  flags (Paraglider, Champions, Master Sword) at the title screen.

## Locations & game modes

The `game_mode` YAML option selects which location categories are active checks:

| Mode | Active categories | ~Checks |
|------|-------------------|---------|
| `all_shrines` | shrine completion + Divine Beasts | 124 |
| `normal` (default) | Sheikah Towers + shrine chests + memories + quests + places + Divine Beasts | 712 |
| `all` | everything above + shrine completion | 832 |

Counts are base-game; `include_dlc_shrines` adds 19 DLC shrine chests. Each location is detected
by its gamedata flag (shrines `Clear_DungeonNNN`, chests `CDungeon_TBox_Dungeon_<Material>_<HashId>`,
towers `MapTower_NN`, beasts `Clear_Remains*`, etc.). Only **shrine chests** need the rando to place
a green-rupee placeholder; the other categories are detected directly. The client polls every known
flag and emits only the checks the server says belong to the slot, so it is mode-agnostic.

## Items & plateau

- **Paraglider** (`IsGet_PlayerStole2`) — an AP item; required to leave the Great Plateau.
- **Runes** (Magnesis, Stasis, Cryonis, Remote Bomb, Camera) — granted by the pack at game
  start (the modified Great-Plateau intro), so the Plateau shrine chests are reachable.
- **Champion Abilities**, **Master Sword** — AP items (each toggleable in the YAML).
- **Spirit Orbs** + ingredient/filler fill the remaining chests.
- The pack handles the plateau: skips the intro, gives the runes, validates the Plateau tower,
  and (in AP mode) does **not** pre-clear shrines nor hide the paraglider locally.

## Goal

Defeat Calamity Ganon: the Master Sword + the 4 Champion Abilities (when randomized) and
`DungeonClearCounter >= Required Shrine Count` (an apworld option, evaluated client-side).

## Repository layout

```
worlds/botw/        # .apworld — items, shrine-chest locations, rules, regions, config emitter
BotWClient/         # AP client — save parsing, WebSocket, Cemu live-memory injection
botwpelago/         # player app: Tkinter GUI + pack_builder (config → embedded rando → pack)
data/               # generated JSON data (shrine_chests, gate_items, flag maps…)
tools/              # build pipeline (build_apworld, build_locations…) + RE helpers; archive/ = old
docs/               # status brief, memory map, setup guide
tests/              # data-integrity + save-parser tests
```

The modified **BotW Randomizer** (GPL v3, by MelonSpeedruns) is built separately and bundled
into BOTWpelago at packaging time; it is not committed here.

## Save format

`game_data.sav` is a custom big-endian binary (**not** BYML): a 12-byte header + a sorted flat
array of `(u32 flag_id, u32 value)` pairs, where `flag_id = crc32(flag_name) & 0xFFFFFFFF`.

## Dependencies

```
pip install websockets          # runtime client
pip install oead                # data/extraction tools only (reads game packs, never the .sav)
```

`ctypes`, `tkinter`, `asyncio`, `zlib` are standard library.

| Software | Version |
|----------|---------|
| BotW (Wii U) | **1.5.0** (all regions) |
| Cemu | any version for the save path; live-memory path validated on 1.18.1 / v208 |

## References

- [ArchipelagoMW](https://github.com/ArchipelagoMW/Archipelago) — AP framework
- [MelonSpeedruns/BotwRandomizer](https://github.com/MelonSpeedruns/BotwRandomizer) — base randomizer (GPL v3)
- [Cemu](https://cemu.info) — Wii U emulator
