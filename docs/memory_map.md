# BotW Cemu — Save File & Memory Reference

Target: **BotW Wii U v1.5.0** on **Cemu 2.0–2.4** (Windows).

> **Strategy: use game_data.sav, not live memory.**  
> BotW stores all event flags (shrines, beasts, quests) in a BYML save file  
> that Cemu writes to disk. No Cheat Engine needed for detection.

---

## Pinned Versions

| Software | Version | Notes |
|----------|---------|-------|
| **Cemu** | 2.0 – 2.4 | Stable branch. Avoid 1.x (different save path) |
| **BotW (Wii U)** | **1.5.0** | All regions supported. 1.3.0 has fewer patches. |

**Do not mix versions** — save format is the same across regions but flag names differ between game updates.

---

## Save File Location

```
{cemu_dir}/mlc01/usr/save/00050000/{title_id}/user/80000001/game_data.sav
```

| Region | Title ID |
|--------|----------|
| USA    | `101c9400` |
| EUR    | `101c9500` |
| JPN    | `101c9300` |

`game_data.sav` is a **BYML file** (big-endian). Parse with `oead`:

```python
import oead
root = oead.byml.from_binary(Path("game_data.sav").read_bytes())
bool_flags = {str(e["DataName"]): bool(e["Value"]) for e in root["bool_data"]}
```

---

## Shrine Completion Flag Names

Format: `Location_MainField_Dungeon{N:03d}_Enable`  
`N` = 001 … 120 (matches `data/shrines.json` id field).

| Flag | Meaning |
|------|---------|
| `Location_MainField_Dungeon001_Enable` | Oman Au inner chest collected |
| `Location_MainField_Dungeon002_Enable` | Ja Baij inner chest collected |
| … | … |
| `Location_MainField_Dungeon120_Enable` | last shrine inner chest |

**Alternate flags** (also stored in save, not used by client):

| Flag | Meaning |
|------|---------|
| `MainField_Dungeon001_Clear` | Shrine statue activated (completion, not chest) |
| `FldObj_Dungeon001_Entrance_Enable` | Shrine portal visible on map |

The client uses `_Enable` (chest) flags. These are set exactly once per playthrough.

### Verify in your save file

```bash
python BotWClient/BotWClient.py --save path/to/game_data.sav --dump-flags
```

This prints all `Location_MainField_Dungeon*` flag names and current values. Use it to:
- Confirm flag names for your region/version
- Cross-check shrine IDs against `data/shrines.json`

---

## Divine Beast Flags

These need cross-referencing — names below are community best-effort:

| Beast | Expected flag | Verified |
|-------|---------------|---------|
| Vah Medoh (Rito) | `FldObj_BeastBird_IsGet` | TODO |
| Vah Rudania (Goron) | `FldObj_BeastFire_IsGet` | TODO |
| Vah Ruta (Zora) | `FldObj_BeastWater_IsGet` | TODO |
| Vah Naboris (Gerudo) | `FldObj_BeastLightning_IsGet` | TODO |

To find the correct names, run `--dump-flags` and search for `Beast` or `Dungeon12` (Divine Beasts are sometimes in the 120+ range):

```bash
python BotWClient/BotWClient.py --save game_data.sav --dump-flags | findstr Beast
```

After defeating a Divine Beast, the flag value changes from 0 to 1. Do a before/after diff to confirm the exact flag name.

---

## Item Injection via Save File

To give Link a received AP item:

1. Map the AP item ID to a BotW flag (e.g. `Location_MainField_Equipment_Sword_001_Enable`).
2. Wait until the game is at the **title screen** (not in-world) — Cemu won't overwrite the save here.
3. Call `SaveFileReader.set_flag(name, True)`.
4. Load the game → item appears.

**Detecting "at title screen":** Poll for the save file's mtime being stable (no writes for 10+ seconds) while the Cemu window title shows the game name without "[Running]".

Alternatively, implement a **deferred queue**: collect received items during play, inject the whole batch when the player saves/quits.

### Item flag names

BotW item flags follow no single pattern — they depend on item type:
- Weapons/shields/bows: `Location_MainField_Equipment_{ActorName}_Enable`
- Key items: game-specific flags (check ZeldaMods actor database)
- Spirit Orbs: `MainField_DungeonReward_BossReward_Enable` (per shrine completion)

Full actor name list: `Actor/ActorInfo.product.sbyml` in the game dump (parse with oead).

---

## Live Memory (Optional, Advanced)

If you need sub-second detection or can't use save polling (e.g. for deathlink timing), live memory reading via `pymem` is possible but requires manual address research per Cemu version:

1. Open Cheat Engine → attach to `cemu.exe`.
2. Search for a changing value (e.g. rupee count).
3. Find the boolean flag array using the procedure in the old memory_map (archived below).
4. Document the pointer chain and Cemu version here.

> No verified pointer chains are known publicly for Cemu 2.x as of 2026-06.  
> The save-file approach covers all detection needs for an AP client.

---

## Resources

| Resource | URL |
|----------|-----|
| ZeldaMods Save File docs | `zeldamods.org/w_botw` → Save Files |
| oead (BYML parser) | `github.com/zeldamods/oead` |
| botw_flag_util | `github.com/GingerAvalanche/botw_flag_util` (PyPI) |
| BotW save editor | `github.com/marcrobledo/savegame-editors` |
| MelonSpeedruns randomizer | `github.com/MelonSpeedruns/BotwRandomizer` |
| Cemu wiki | `wiki.cemu.info` |
