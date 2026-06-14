# BotW Archipelago — Claude Context

## Project
Archipelago multiworld randomizer for Zelda: Breath of the Wild (Wii U / Cemu).
Two components: Python `.apworld` (server) + Python client (reads Cemu's `game_data.sav`).

## Stack
- Python 3.11+, AP framework (worlds/AutoWorld.py base classes)
- `oead` NOT used on `game_data.sav` — custom binary parser in `BotWClient/save_parser.py`
- WebSocket JSON (AP standard protocol)
- Cemu 1.18.1+ (any version for save-file path), BotW WiiU **1.5.0** (pinned, all regions)

## Key Files
| Path | Purpose |
|------|---------|
| `worlds/botw/__init__.py` | World class, AP entry point |
| `worlds/botw/items.py` | Item pool (loads from data/gate_items.json) |
| `worlds/botw/locations.py` | Location pool (loads from data/locations.json) |
| `worlds/botw/rules.py` | Access rules (Paraglider gate + goal condition) |
| `worlds/botw/regions.py` | Great Plateau + Hyrule World regions |
| `worlds/botw/options.py` | Per-game options |
| `BotWClient/BotWClient.py` | Client: save polling + AP WebSocket |
| `BotWClient/providers/save_file.py` | SaveFileProvider + DeferredSaveInjector |
| `BotWClient/save_parser.py` | Binary parser for game_data.sav |
| `BotWClient/item_map.py` | AP item ID → InjectionSpec |
| `data/locations.json` | 459 AP locations: 120 shrines + 15 towers + 4 beasts + 320 lieux (Location_*) |
| `data/gate_items.json` | Key items: Paraglider, Master Sword, 4 Champions + runes |
| `data/shrines.json` | 120 shrines indexed by dungeon_id |
| `docs/memory_map.md` | Save file format, flag hash recipe, flag names |

## Client Architecture
```
BotWClient.py (AP WebSocket only)
  ├── SaveFileProvider.poll()     → new location IDs from game_data.sav
  └── DeferredSaveInjector
        ├── queue_item()          ← received AP items
        ├── flush()               → writes flags + enforces gate retention
        └── is_goal_complete()    → DungeonClearCounter + MasterSword + HeroSouls
```

## Save Format (CONFIRMED — do not re-examine)
`game_data.sav` = custom big-endian binary, NOT BYML.
Layout: 12-byte header + N × 8-byte (u32be flag_id, u32be value) flat sorted array.
Hash recipe: `flag_id = zlib.crc32(flag_name.encode("ascii")) & 0xFFFFFFFF`
Proof: `IsGet_Obj_Magnetglove` = 0x795E7BBC matched Oman Au before/after diff;
       cross-verified against all 42,537 HashValue fields in gamedata.ssarc.

## ID Ranges
- Items: `6_080_000` (Paraglider) ... `6_080_013` (Champions) + `6_080_100`+ (filler)
- Locations: shrines `6_081_000`–`6_081_119`; beasts `6_081_201`–`6_081_204`; towers `6_081_301`+; lieux (Location_*) `6_081_400`+
- Filler items: ingrédients `6_080_200`+ (générés depuis data/botw_items.json via tools/build_loot_table.py)

## Key Flag Names (verified)
| Item | Flag | Hash |
|------|------|------|
| Paraglider | `IsGet_PlayerStole2` | `0xFE4D1501` |
| Magnesis Rune | `IsGet_Obj_Magnetglove` | `0x795E7BBC` |
| Stasis Rune | `IsGet_Obj_StopTimer` | `0x7504085D` |
| Cryonis Rune | `IsGet_Obj_IceMaker` | `0x5992B256` |
| Remote Bomb | `IsGet_Obj_RemoteBomb` | `0x191BCCF9` |
| Camera | `IsGet_Obj_Camera` | `0xF7DD3E03` |
| Master Sword | `Get_MasterSword_Finish` | `0x15AD023F` |
| Revali's Gale | `IsGet_Obj_HeroSoul_Rito` | `0x7DBA0908` |
| Daruk's Protection | `IsGet_Obj_HeroSoul_Goron` | `0xFF48AA75` |
| Mipha's Grace | `IsGet_Obj_HeroSoul_Zora` | `0x0D61D7D4` |
| Urbosa's Fury | `IsGet_Obj_HeroSoul_Gerudo` | `0x8E7188D0` |
| Shrine counter | `DungeonClearCounter` | `0xE605CE62` |
| Shrine clear | `Clear_DungeonNNN` | `crc32("Clear_DungeonNNN")` |

## Critical Rules
- **Runes are STARTING ITEMS** — never in pool. Needed to clear plateau shrines (which ARE checks).
- **Oman Au = Dungeon038** (not 001). Internal numbering ≠ play order.
- **Shrine detection flag = `Clear_DungeonNNN`** (not `Location_MainField_*`).
- **Divine Beast flags = `Clear_Remains{Wind|Fire|Water|Electric}`**.
- **Tower flags = `MapTower_NN`**.
- Never retain rune flags — would softlock the plateau.
- Outgoing item checks: client sends `LocationChecks(ap_id)`. No injection needed for outgoing.
- Incoming ap_progression items: inject by setting flag to 1 when save is idle (title screen).
- Gate enforcement: force flag to 0 until item received from AP (flag retention).

## AP Protocol
Client sends: `Connect`, `LocationChecks`, `StatusUpdate`
Server sends: `Connected`, `ReceivedItems`, `PrintJSON`
All messages: JSON arrays `[{"cmd": "...", ...}]`

## TODO (from docs/status.md)
- TODO-7: Fill `region` field in data/locations.json for full region graph
- TODO-5: Reverse PouchItem for armor/shield/weapon injection
- TODO-6: Identify quest locations via save_watch + diff
- TODO-9: Validate memory_bridge.py live against Cemu 2.x

## DO NOT
- Use `oead.byml.from_binary()` on `game_data.sav`
- Retain rune flags (IsGet_Obj_Magnetglove etc.)
- Re-litigate the hash recipe — it's proven
- Use `Location_MainField_Dungeon*` flag names (old, wrong)

## Testing
- Unit: `python -m pytest worlds/botw/test/`
- AP generation: `python Archipelago.py Generate` with a BotW YAML
- Client: `python -m BotWClient.BotWClient --debug-save --save path/to/game_data.sav`
- Diff: `python -m BotWClient.BotWClient --diff-saves before.sav after.sav`
