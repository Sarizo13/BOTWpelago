"""
Reads the Melonspeedruns BotwRandomizer spoiler log.

Provides two lookups:
  location_of(ap_item_name)       -> "overworld D-6" / "Ka'o Makagh Shrine"
  shrine_item_by_flag(flag_name)  -> "Mipha's Grace" for "Clear_Dungeon054"

Used by the client to annotate log messages when AP gate retention clears a
flag the player physically triggered in-game.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("BotWClient.Rando")

_CHEST_MAP_PATH = Path(__file__).parent.parent / "data" / "rando_chest_map.json"

# Relative path inside a Cemu root (must match the pack folder produced by the rando)
_SPOILER_RELATIVE = "graphicPacks/BOTWpelago/spoiler-log.txt"


def find_spoiler_log(cemu_root: Optional[Path]) -> Optional[Path]:
    """Return the spoiler-log.txt path if the BOTWpelago pack is installed."""
    if cemu_root is None:
        return None
    p = cemu_root / _SPOILER_RELATIVE
    return p if p.exists() else None


class RandoReader:
    """
    Parses the randomizer spoiler log and cross-references with the static
    rando_chest_map.json to know which in-game chest holds each AP-relevant item.
    """

    def __init__(self, spoiler_log_path: Path) -> None:
        self._seed: str = "?"
        self._item_to_loc:   dict[str, str] = {}   # item_name → location string
        self._flag_to_item:  dict[str, str] = {}   # "Clear_DungeonNNN" → item_name
        self._loaded = False
        self._load(spoiler_log_path)

    # ── Load ──────────────────────────────────────────────────────────────────

    def _load(self, path: Path) -> None:
        if not _CHEST_MAP_PATH.exists():
            log.warning("rando_chest_map.json not found — rando display disabled")
            return
        if not path.exists():
            log.warning("Spoiler log not found: %s", path)
            return

        chest_by_hid: dict[int, dict] = {
            e["hash_id"]: e
            for e in json.loads(_CHEST_MAP_PATH.read_text(encoding="utf-8"))
        }

        # Parse spoiler log ──────────────────────────────────────────────────
        hash_to_item: dict[int, str] = {}
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip()
                if line.startswith("Seed:"):
                    self._seed = line.split(":", 1)[1].strip()
                    continue
                if ":" not in line or line.startswith("==="):
                    continue
                item, _, hid_str = line.rpartition(":")
                try:
                    hash_to_item[int(hid_str.strip())] = item.strip()
                except ValueError:
                    pass

        # Cross-reference ────────────────────────────────────────────────────
        item_locs:    dict[str, list[str]] = {}
        flag_to_item: dict[str, str]       = {}

        for hid, item_name in hash_to_item.items():
            chest = chest_by_hid.get(hid)
            if not chest:
                continue
            if chest["location_type"] == "shrine":
                loc  = chest.get("shrine_name") or chest.get("clear_flag", "?")
                flag = chest.get("clear_flag")
                if flag:
                    flag_to_item[flag] = item_name
            else:
                loc = f"overworld {chest.get('tile', '?')}"
            item_locs.setdefault(item_name, []).append(loc)

        self._item_to_loc  = {n: ", ".join(locs) for n, locs in item_locs.items()}
        self._flag_to_item = flag_to_item
        self._loaded       = True

        log.info("[Rando] Seed %s - %d items located", self._seed, len(self._item_to_loc))

    # ── Public API ────────────────────────────────────────────────────────────

    def location_of(self, ap_item_name: str) -> Optional[str]:
        """Return a human-readable chest location, or None if not in spoiler log."""
        return self._item_to_loc.get(ap_item_name) if self._loaded else None

    def shrine_item_by_flag(self, flag_name: str) -> Optional[str]:
        """
        Return the notable item the randomizer placed in the shrine chest
        associated with the given AP clear flag (e.g. 'Clear_Dungeon054').
        """
        return self._flag_to_item.get(flag_name) if self._loaded else None

    def summary(self) -> str:
        """Multi-line display of all progression item placements for this seed."""
        if not self._loaded:
            return "(rando reader not loaded)"
        lines = [f"Seed: {self._seed}", "Progression item locations:"]
        prog_keys = [
            "Paraglider", "Revali", "Daruk", "Mipha", "Urbosa",
            "Master Sword", "Heart Container", "Stamina Vessel", "Bow of Light",
        ]
        shown: set[str] = set()
        for key in prog_keys:
            for name, loc in self._item_to_loc.items():
                if key in name and name not in shown:
                    lines.append(f"  {name:25s} -> {loc}")
                    shown.add(name)
        if len(shown) == 0:
            lines.append("  (no notable items found — spoiler log may be empty)")
        return "\n".join(lines)

    @property
    def seed(self) -> str:
        return self._seed

    @property
    def is_loaded(self) -> bool:
        return self._loaded
