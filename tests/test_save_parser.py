"""
Tests for the save-flag hash recipe in BotWClient/save_parser.py.

save_parser is stdlib-only (zlib), so it imports without the Archipelago framework.
These pin the proven hashes from docs/status.md / CLAUDE.md so a refactor of the
recipe can never silently break detection.
"""
import json
from pathlib import Path

from BotWClient import save_parser

# Proven flag → crc32 pairs (see docs/status.md §1, CLAUDE.md "Key Flag Names").
KNOWN = {
    "IsGet_PlayerStole2":     0xFE4D1501,  # Paraglider
    "IsGet_Obj_Magnetglove":  0x795E7BBC,  # Magnesis rune
    "Get_MasterSword_Finish": 0x15AD023F,
    "DungeonClearCounter":    0xE605CE62,
}


def test_flag_id_matches_known_hashes():
    for name, expected in KNOWN.items():
        assert save_parser.flag_id(name) == expected, name


def test_flag_id_matches_locations_data():
    """save_parser.flag_id() must reproduce every committed location flag_hash."""
    data = Path(__file__).resolve().parents[1] / "worlds" / "botw" / "data" / "locations.json"
    locs = json.loads(data.read_text(encoding="utf-8"))
    bad = [e["flag_name"] for e in locs
           if save_parser.flag_id(e["flag_name"]) != int(e["flag_hash"], 16)]
    assert bad == [], f"{len(bad)} mismatch(es): {bad[:5]}"
