# BotW Randomizer — modified for BOTWpelago (GPL v3)

This directory contains a **modified version of the Melonspeedrun BotW Randomizer**
([MelonSpeedruns/BotwRandomizer](https://github.com/MelonSpeedruns/BotwRandomizer)),
licensed under the **GNU General Public License v3** (see [LICENSE](LICENSE)).

It is built into a small headless CLI (`BotwRandoCLI.exe`) that BOTWpelago drives to
generate the Cemu graphic pack for an Archipelago seed.

## Modifications (BOTWpelago, 2026)

- **`BotwRandoLib/Randomizer.cs`**
  - AP config-driven chest placements: reads `BOTW_AP_CONFIG` (`{settings, placements}`)
    and places the placeholder actor (green rupee) in each AP shrine chest, independent
    of the category toggles.
  - In AP mode (`apConfig != null`): the local paraglider chest is **disabled** (the
    paraglider is delivered as an Archipelago item), and **only the 4 Great Plateau
    shrines** are pre-cleared (`Clear_Dungeon038/041/009/065`) to avoid the
    "Isolated Plateau" intro-quest conflict — the other 116 shrines stay uncleared.
  - Writes an AP location dump (`ap-locations.json`) of every chest processed.
- **`Program.cs`** — new headless CLI: reads the rando paths from a settings JSON and
  the toggles from `BOTW_AP_CONFIG["settings"]`, then runs `Randomizer.RandomizeGame`.
- **`BotwRandoLib.csproj`** — retargeted to `net8.0-windows`, output an executable CLI.

## License boundary

BOTWpelago (the Python application) invokes this randomizer **as a separate executable**
(a subprocess). They are aggregated, not linked — the randomizer remains under **GPL v3**,
while the BOTWpelago code is under its own license. This file tree (our modified rando
source) is provided to satisfy GPL v3's source-availability requirement.

## Building

Requires the **.NET 8 SDK** (Windows). The dependency DLLs in `libs/` (Toolbox.Library,
SARCExt, ByamlExt, Syroot.\*, CsvHelper, Newtonsoft.Json, …) are third-party and are
**not redistributed here**; obtain them from the original Melonspeedrun BotW Randomizer
2.1.1 release and place them in `libs/`. Then:

```
dotnet build -c Release
# -> bin/Release/net8.0-windows/BotwRandoCLI.exe
```

BOTWpelago locates this exe automatically (or via the `BOTW_RANDO_EXE` env var).
