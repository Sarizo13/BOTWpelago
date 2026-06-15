# BotW Archipelago

Archipelago multiworld randomizer support for **The Legend of Zelda: Breath of the Wild**
(Wii U / Cemu, game version **1.5.0**).

Two halves: a Python `.apworld` (server-side logic) and a Python client that reads Cemu's
`game_data.sav` (and, when available, Cemu's live memory) to detect checks and inject
received items.

## Repository layout

```
worlds/botw/     # .apworld — AP server-side logic (items, locations, rules, regions)
BotWClient/      # AP client — save parsing, WebSocket to AP server, Cemu memory injection
botwpelago/      # Tkinter GUI that wraps BotWClient (python -m botwpelago)
data/            # Generated JSON data (locations, items, flag maps…)
tools/           # Build pipeline + reverse-engineering scripts
docs/            # Status brief, memory map, setup guide
```

## Components

| Component | Role |
|-----------|------|
| `worlds/botw/` | AP World: item pool, 646 locations, access rules, region graph |
| `BotWClient/BotWClient.py` | AP client: WebSocket protocol, check polling, item injection |
| `BotWClient/save_parser.py` | Parser for `game_data.sav` (custom big-endian binary — **not** BYML) |
| `BotWClient/memory_injector.py` | Optional live Cemu memory bridge (rupees + PouchItem injection) |
| `botwpelago/` | GUI launcher + desktop "item received" overlay |

## How it works

1. The **AP server** generates a multiworld seed using the `botw` world.
2. The player launches BotW on Cemu, then the client (`python -m botwpelago`, or the CLI
   `python -m BotWClient.BotWClient`).
3. The client reads `game_data.sav` and polls completion flags (`Clear_DungeonNNN`,
   `MapTower_NN`, `Clear_Remains*`, plus place / quest / memory flags).
4. On a flag flipping `0 → 1`, the client sends `LocationChecks(ap_id)` to the server.
5. Received items are injected: flag items (Paraglider, Champions, Master Sword…) by
   setting their save flag while idle at the title screen; inventory items and rupees live
   via the memory bridge when it is attached to Cemu.

Progression gating uses **flag retention**: `ap_progression` flags are forced to `0` until
AP delivers the matching item (e.g. no Paraglider ⇒ stuck on the Great Plateau).

## Locations (646 checks)

| Category | Count | Flag pattern |
|----------|-------|--------------|
| Shrines | 120 | `Clear_DungeonNNN` |
| Sheikah Towers | 15 (optional toggle) | `MapTower_NN` |
| Divine Beasts | 4 | `Clear_Remains{Wind\|Fire\|Water\|Electric}` |
| Places discovered | 318 | `Location_*` |
| Quests & side challenges | 175 | `*_Finish` |
| Memories / photos | 14 | `IsGet_MemoryPhoto_*` |

## Key items

- **Paraglider** (`IsGet_PlayerStole2`) — required to leave the Great Plateau.
- **Runes** (Magnesis, Stasis, Cryonis, Remote Bomb, Camera) — **starting items**, never in
  the pool (needed to clear the Plateau shrines, which are themselves checks).
- **Champion Abilities** — Revali's Gale, Daruk's Protection, Mipha's Grace, Urbosa's Fury.
- **Master Sword** (`Get_MasterSword_Finish`).
- **Spirit Orbs** + ingredient/filler items.

## Goal

Defeat Calamity Ganon: the Master Sword + the 4 Champion Abilities (when randomized) and
`DungeonClearCounter >= Required Shrine Count` (an apworld option, evaluated client-side).

## Setup

See [docs/setup.md](docs/setup.md). Current state, proofs and design notes live in
[docs/status.md](docs/status.md) (the authoritative handoff brief).

## Dependencies

Runtime client:

```
pip install websockets
```

(`ctypes`, `tkinter`, `asyncio`, `zlib` are part of the standard library.)

The data/extraction scripts in `tools/` additionally use `oead` — **only** for reading game
packs, never on `game_data.sav`.

| Software | Version |
|----------|---------|
| BotW (Wii U) | **1.5.0** (all regions) |
| Cemu | any version for the save-file path; live-memory path validated on 1.18.1 / v208 |

## References

- [ArchipelagoMW](https://github.com/ArchipelagoMW/Archipelago) — AP framework
- [MelonSpeedruns/BotwRandomizer](https://github.com/MelonSpeedruns/BotwRandomizer) — existing BotW randomizer
- [Cemu](https://cemu.info) — Wii U emulator
