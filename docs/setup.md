# Setup Guide — BotW Archipelago

## Requirements

| Component | Version |
|-----------|---------|
| Python | 3.11+ |
| Cemu | 2.0+ |
| BotW (Wii U) | 1.5.0 |
| Archipelago | 0.5.0+ |

```
pip install archipelago pymem websockets
```

## Installing the .apworld

1. Copy the `worlds/botw/` folder into your Archipelago installation's `worlds/` directory.
2. Restart the Archipelago launcher.
3. The game "The Legend of Zelda: Breath of the Wild" should appear in the game list.

## Generating a Seed

1. Create a YAML options file:

```yaml
game: The Legend of Zelda: Breath of the Wild
The Legend of Zelda: Breath of the Wild:
  starting_runes: all_four
  divine_beasts_required: 4
  include_towers: true
  include_korok_seeds: false
```

2. Run: `python Archipelago.py generate --player_files your_options.yaml`

## Running the Client

1. Launch Cemu and load your BotW save.
2. In a separate terminal:

```
python BotWClient/BotWClient.py --server archipelago.gg:38281 --slot YourSlotName
```

3. The client will attach to Cemu automatically once BotW is running.

## Troubleshooting

**Client can't find Cemu:** Make sure `cemu.exe` is running and BotW is loaded past the title screen.

**Wrong checks detected:** Memory addresses in `BotWClient.py` are placeholders. See `docs/memory_map.md` to find the correct addresses for your Cemu version.

**Item injection not working:** Item write is a stub — see `TODO` in `BotWClient.py:CemuMemoryReader.write_received_item`.
