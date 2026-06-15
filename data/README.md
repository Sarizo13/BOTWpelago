# `data/`

Generated and static JSON data for the BotW Archipelago project.

## Why `locations.json` / `gate_items.json` are duplicated in `worlds/botw/data/`

These two files exist **twice on purpose** — they are copies, kept in sync:

- **`data/`** (this directory) is read by the **client** (`BotWClient/`): see
  `item_map.py`, `providers/save_file.py`, `rando_reader.py`.
- **`worlds/botw/data/`** is read by the **Archipelago world** (`worlds/botw/`) and must
  live *inside* the package so it ships with the distributable `.apworld`.

`tools/build_locations.py` and `tools/build_loot_table.py` write **both** copies in one
run. Always regenerate through those scripts — never hand-edit one copy, or they drift.

## Files

| File | Produced by | Consumed by |
|------|-------------|-------------|
| `locations.json` | `tools/build_locations.py` | client + (copy in) apworld |
| `gate_items.json` | `tools/build_loot_table.py` | client + (copy in) apworld |
| `botw_items.json` | `tools/build_item_db.py` | input to `build_loot_table.py` |
| `shrines.json` | `scaffold_shrines.py` | client (save parsing) |
| `dungeon_names.json` | `extract_msg_names.py` | input to `build_locations.py` |
| `location_marker.json` | `extract_msg_names.py` | input to `build_locations.py` |
| `rando_chest_map.json` | Melonspeedruns rando export | `BotWClient/rando_reader.py` |
| `pouch_items.json` | manual | `BotWClient/providers/save_file.py` |

Game-derived corpora (e.g. `flag_names.txt`) are **not** committed — they are produced
locally by `extract_flag_names.py` and gitignored (Nintendo copyright).
