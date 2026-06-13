# BotW Archipelago

Archipelago multiworld randomizer support for **The Legend of Zelda: Breath of the Wild** (Wii U / Cemu).

## Architecture

```
worlds/botw/          # .apworld — AP server-side Python logic
BotWClient/           # AP client — reads Cemu memory, talks to AP server
data/                 # Static JSON data (shrines, items)
docs/                 # Memory map, setup guide
```

## Components

| Component | Language | Role |
|-----------|----------|------|
| `worlds/botw` | Python 3.11+ | AP World: items, locations, logic, rules |
| `BotWClient/BotWClient.py` | Python 3.11+ | AP Client: reads Cemu via pymem, WebSocket to AP |
| `data/shrines.json` | JSON | All 120 shrine definitions with region and AP IDs |

## How It Works

1. **AP Server** generates a multiworld seed using the `botw` world.
2. **Player** launches BotW on Cemu, then runs `BotWClient.py`.
3. **Client** attaches to `cemu.exe` via `pymem`, polls shrine/event flags in memory.
4. When a check is detected → client sends `LocationChecked` to AP server.
5. AP server sends back items → client writes them into Cemu memory.

## Locations (checks)

| Category | Count | Notes |
|----------|-------|-------|
| Shrines (inner chest) | 120 | Core checks |
| Divine Beast completions | 4 | Vah Medoh, Vah Rudania, Vah Ruta, Vah Naboris |
| Sheikah Towers | 15 | Optional (toggle in options) |
| Major side quests | ~10 | Optional (toggle in options) |
| Korok Seeds | up to 900 | Optional, off by default |

## Key Items

- **Paraglider** — required to leave Great Plateau
- **Runes** — Magnesis, Stasis, Cryonis, Remote Bomb
- **Champion Abilities** — Revali's Gale, Mipha's Grace, Daruk's Protection, Urbosa's Fury
- **Spirit Orbs** — 4 = 1 Heart Container or Stamina Vessel at statue
- **Key Armor** — Flamebreaker (Death Mountain), Gerudo Vai Outfit (Gerudo Town), etc.

## Setup

See [docs/setup.md](docs/setup.md).

## Dependencies

```
pip install oead websockets
```

| Software | Pinned version |
|----------|----------------|
| Cemu | 2.0 – 2.4 |
| BotW (Wii U) | **1.5.0** (all regions) |

No memory scanning required — the client reads Cemu's `game_data.sav` (BYML).

## Status

> **WIP — scaffold only.** Logic rules, memory addresses, and item/location counts are incomplete.

### TODO
- [ ] Verify all 120 shrine memory flag addresses (see [docs/memory_map.md](docs/memory_map.md))
- [ ] Complete access rules for all regions
- [ ] Implement item injection (write to Cemu memory)
- [ ] Test with real Cemu session
- [ ] Submit .apworld to Archipelago upstream

## References

- [ArchipelagoMW](https://github.com/ArchipelagoMW/Archipelago) — AP framework
- [MelonSpeedruns/BotwRandomizer](https://github.com/MelonSpeedruns/BotwRandomizer) — existing BotW randomizer
- [Cemu Emulator](https://cemu.info) — Wii U emulator
