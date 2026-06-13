"""
Save-file based GameStateProvider + ItemInjector (MVP).

Detection : polls game_data.sav every 2s, emits new location checks.
Injection : sets flag to 1 when AP delivers a progression item.
Gating    : forces ap_progression flags back to 0 while item not yet received
            ("flag retention" — prevents vanilla mechanics from bypassing AP).
Goal      : evaluates Master Sword + 4 HeroSouls + DungeonClearCounter >= N.
"""
from __future__ import annotations

import json
import logging
import struct
import time
from pathlib import Path
from typing import Optional

from ..save_parser import parse, ParsedSave, flag_id as crc32_id
from .base import GameStateProvider, ItemInjector, InjectionSpec

log = logging.getLogger("BotWClient.SaveFile")

_DATA_DIR = Path(__file__).parents[2] / "data"

SAFE_WRITE_IDLE_SECONDS = 5   # 5s idle = title screen (was 35s)


# ── Load canonical data ───────────────────────────────────────────────────────

def _load_locations() -> list[dict]:
    with open(_DATA_DIR / "locations.json", encoding="utf-8") as fh:
        return json.load(fh)

def _load_gate_items() -> dict:
    with open(_DATA_DIR / "gate_items.json", encoding="utf-8") as fh:
        return json.load(fh)

def _load_pouch_items() -> dict:
    """Table de loot des items de poche livrables en live (type/sub par actor name)."""
    try:
        with open(_DATA_DIR / "pouch_items.json", encoding="utf-8") as fh:
            return json.load(fh).get("items", {})
    except FileNotFoundError:
        return {}

_LOCATIONS   = _load_locations()
_GATE_ITEMS  = _load_gate_items()
_POUCH_ITEMS = _load_pouch_items()


def pouch_item_info(item_name: str) -> Optional[dict]:
    """Retourne {'type':int, 'sub':int?} pour un item livrable en live, ou None."""
    return _POUCH_ITEMS.get(item_name)

# flag_hash (int) → ap_id
_LOC_HASH_TO_AP_ID: dict[int, int] = {
    int(loc["flag_hash"], 16): loc["ap_id"]
    for loc in _LOCATIONS
}

# ap_id → full location dict  (for descriptive check messages)
_AP_ID_TO_LOC: dict[int, dict] = {loc["ap_id"]: loc for loc in _LOCATIONS}


def get_location_info(ap_id: int):
    """Return the location dict for an ap_id, or None if unknown."""
    return _AP_ID_TO_LOC.get(ap_id)

# ap_item_id → gate item spec (ap_progression only)
_GATE_BY_AP_ID: dict[int, dict] = {
    item["ap_item_id"]: item
    for item in _GATE_ITEMS["items"]
    if item["role"] == "ap_progression"
}

# flag_hash (int) → ap_item_id (for gate enforcement)
_GATE_HASH_TO_AP_ID: dict[int, int] = {
    int(item["flag_hash"], 16): item["ap_item_id"]
    for item in _GATE_ITEMS["items"]
    if item["role"] == "ap_progression"
}

# flag_hash (int) → item name  (for human-readable retention log messages)
_GATE_HASH_TO_NAME: dict[int, str] = {
    int(item["flag_hash"], 16): item["name"]
    for item in _GATE_ITEMS["items"]
    if item["role"] == "ap_progression"
}

# Goal
_GOAL = _GATE_ITEMS["goal"]
_GOAL_FLAG_IDS = [crc32_id(f) for f in _GOAL["require_flags"]]
_DUNGEON_COUNTER_ID = int(_GOAL["shrine_counter"]["flag_hash"], 16)


# ── Slot directory scanner ────────────────────────────────────────────────────

def _current_save_in_slot(root: Path) -> Optional[Path]:
    """
    Return the most recently modified game_data.sav inside a Cemu slot dir.
    Cemu rotates saves across numbered sub-folders (0/, 1/, 2/, …) on each
    auto-save, so we must always pick the freshest one dynamically.
    """
    try:
        candidates = [
            sub / "game_data.sav"
            for sub in root.iterdir()
            if sub.is_dir() and sub.name.isdigit() and (sub / "game_data.sav").exists()
        ]
        return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None
    except (OSError, PermissionError):
        return None


# ── Pouch item constants ──────────────────────────────────────────────────────

_PORCH_ITEM_ID      = crc32_id("PorchItem")        # 0x5F283289 — item name slots
_PORCH_VALUE1_ID    = crc32_id("PorchItem_Value1")  # 0x6A09FC59 — quantity slots
_PORCH_SLOTS        = 420   # total inventory slots
_PORCH_NAME_ENTRIES = 16    # 16 × 4 bytes = 64-byte item name per slot


def _find_first_run(data: bytes, flag_id: int) -> int:
    """Binary-search for flag_id, then walk back to first occurrence in a duplicate run."""
    n = (len(data) - 12) // 8
    needle = struct.pack(">I", flag_id)
    lo, hi = 0, n - 1
    result = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        off = 12 + mid * 8
        cmp = data[off:off+4]
        if cmp == needle:
            result = mid
            hi = mid - 1   # keep searching left for first occurrence
        elif cmp < needle:
            lo = mid + 1
        else:
            hi = mid - 1
    return result


def _read_porch_name(data: bytes, first_porch: int, slot: int) -> str:
    raw = bytearray()
    for i in range(_PORCH_NAME_ENTRIES):
        off = 12 + (first_porch + slot * _PORCH_NAME_ENTRIES + i) * 8 + 4
        raw += data[off:off+4]
    return raw.split(b'\x00')[0].decode("ascii", errors="replace")


def _add_porch_item_to_save(path: Path, item_name: str, amount: int) -> bool:
    """
    Add `amount` to a stackable item in the PouchItem inventory.

    If the item already has a slot → increment its PorchItem_Value1.
    If not found → find the first empty slot and write the name + count.
    Returns True on success.
    """
    try:
        data = bytearray(path.read_bytes())
        fp = _find_first_run(bytes(data), _PORCH_ITEM_ID)
        fv = _find_first_run(bytes(data), _PORCH_VALUE1_ID)
        if fp < 0 or fv < 0:
            log.warning("PorchItem arrays not found in save")
            return False

        name_bytes = item_name.encode("ascii") + b"\x00"

        # ── 1. Find existing slot ──────────────────────────────────────────────
        target_slot = -1
        empty_slot  = -1
        for slot in range(_PORCH_SLOTS):
            slot_name = _read_porch_name(bytes(data), fp, slot)
            if slot_name == item_name:
                target_slot = slot
                break
            if slot_name == "" and empty_slot < 0:
                empty_slot = slot

        if target_slot < 0 and empty_slot < 0:
            log.warning("PorchItem: no slot for %s and inventory full", item_name)
            return False

        # ── 2. Write new item to empty slot if needed ─────────────────────────
        if target_slot < 0:
            target_slot = empty_slot
            # Write name bytes across _PORCH_NAME_ENTRIES × 4-byte chunks
            padded = (name_bytes + b"\x00" * 64)[:64]
            for i in range(_PORCH_NAME_ENTRIES):
                off = 12 + (fp + target_slot * _PORCH_NAME_ENTRIES + i) * 8 + 4
                data[off:off+4] = padded[i*4:(i+1)*4]
            current = 0
        else:
            val_off = 12 + (fv + target_slot) * 8 + 4
            current = struct.unpack_from(">I", data, val_off)[0]

        # ── 3. Write new quantity ─────────────────────────────────────────────
        new_val = max(0, current + amount)
        val_off = 12 + (fv + target_slot) * 8 + 4
        struct.pack_into(">I", data, val_off, new_val & 0xFFFFFFFF)
        path.write_bytes(bytes(data))
        log.info("  [OK] PouchItem %s: %d -> %d", item_name, current, new_val)
        return True

    except Exception as exc:
        log.error("AddPouchItem failed for %s: %s", item_name, exc)
        return False


# ── Binary save writer ────────────────────────────────────────────────────────

def _write_flag_to_save(path: Path, flag_id_int: int, value: int) -> bool:
    """
    Find a flag entry (u32 flag_id, u32 value) in the save by binary search
    and overwrite its value field in-place. Returns True on success.

    The save is a sorted flat array starting at offset 12. Binary search is O(log n).
    """
    try:
        data = bytearray(path.read_bytes())
        n = (len(data) - 12) // 8
        lo, hi = 0, n - 1
        needle = struct.pack(">I", flag_id_int)
        while lo <= hi:
            mid = (lo + hi) // 2
            off = 12 + mid * 8
            mid_id = data[off: off + 4]
            if mid_id == needle:
                struct.pack_into(">I", data, off + 4, value & 0xFFFFFFFF)
                path.write_bytes(bytes(data))
                return True
            elif mid_id < needle:
                lo = mid + 1
            else:
                hi = mid - 1
        log.warning("Flag 0x%08X not found in save — cannot write", flag_id_int)
        return False
    except Exception as exc:
        log.error("Failed to write flag 0x%08X: %s", flag_id_int, exc)
        return False


# ── Provider ──────────────────────────────────────────────────────────────────

class SaveFileProvider(GameStateProvider):
    """
    Reads game_data.sav every poll cycle. Emits new location IDs on 0→1 flag flips.

    Accepts either:
      - An exact game_data.sav path  (--save <file>)
      - A Cemu slot directory        (--slot <id>)  ← dynamically picks the most
        containing numbered sub-dirs (0/, 1/, …)      recent sub-save on each poll,
                                                       so Cemu's rotation is handled.
    """

    def __init__(self, save_path: Path) -> None:
        self._root      = save_path          # exact file OR slot dir
        self._active:   Optional[Path] = None  # currently tracked file
        self._mtime     = 0.0
        self._save:     Optional[ParsedSave] = None
        self._reported: set[int] = set()

    def _resolve(self) -> Optional[Path]:
        """Return the game_data.sav to read (handles both exact-file and slot-dir)."""
        if self._root.is_dir():
            return _current_save_in_slot(self._root)
        return self._root if self._root.exists() else None

    @property
    def is_available(self) -> bool:
        return self._resolve() is not None

    def _reload(self) -> bool:
        p = self._resolve()
        if p is None:
            return False
        try:
            mtime = p.stat().st_mtime
        except FileNotFoundError:
            return False
        # Reload when path rotated to a new sub-save OR same file was modified.
        if p == self._active and mtime <= self._mtime:
            return False
        try:
            self._save = parse(p.read_bytes())
            self._mtime = mtime
            if p != self._active:
                log.info("Save rotated → %s", p.name)
                self._active = p
            return True
        except Exception as exc:
            log.warning("Save parse error: %s", exc)
            return False

    def poll(self) -> list[int]:
        self._reload()
        if self._save is None:
            return []
        new: list[int] = []
        for fhash, ap_id in _LOC_HASH_TO_AP_ID.items():
            if ap_id not in self._reported and self._save.get_bool(fhash):
                new.append(ap_id)
                self._reported.add(ap_id)
        return new

    def is_goal_complete(self, required_shrine_count: int) -> bool:
        if self._save is None:
            return False
        if not all(self._save.get_bool(fid) for fid in _GOAL_FLAG_IDS):
            return False
        return self._save.get_s32(_DUNGEON_COUNTER_ID) >= required_shrine_count

    def verify_flag_names(self, sample_names: list[str]) -> dict[str, bool]:
        self._reload()
        if self._save is None:
            return {}
        return {name: self._save.get_bool(crc32_id(name)) for name in sample_names}

    def get_save(self) -> Optional[ParsedSave]:
        return self._save


# ── Diagnostic helper ─────────────────────────────────────────────────────────

def ap_state_report(save_path: Path) -> str:
    """
    Human-readable dump of all AP-relevant flags in a save file.
    Run with: --check-flags <path/to/game_data.sav>

    Shows:
      - Flag-injectable progression items (Paraglider, Champions, Master Sword)
      - DungeonClearCounter
      - Completed locations (shrines / towers / beasts), grouped by region
    """
    from collections import defaultdict

    try:
        data = save_path.read_bytes()
        save = parse(data)
    except Exception as exc:
        return f"ERROR: could not read {save_path}: {exc}"

    lines = ["=" * 62,
             f"BotW AP State  --  {save_path.name}",
             "=" * 62]

    # ── Progression items (flag-backed only) ──────────────────────────────
    lines.append("\nProgression items (save flags):")
    for item in _GATE_ITEMS["items"]:
        if item["role"] != "ap_progression":
            continue
        fhash = int(item["flag_hash"], 16)
        val   = save.get_bool(fhash)
        mark  = "OK" if val else "--"
        lines.append(f"  [{mark}] {item['name']:30s} ({item['flag_name']})")

    # ── Shrine counter ────────────────────────────────────────────────────
    counter = save.get_s32(_DUNGEON_COUNTER_ID)
    goal_status = "GOAL OK" if counter >= 20 else "not yet"
    lines.append(f"\nDungeonClearCounter: {counter}  "
                 f"(required_shrine_count=20 -> {goal_status})")

    # ── Completed locations ───────────────────────────────────────────────
    by_region: dict[str, list[str]] = defaultdict(list)
    total = 0
    for loc in _LOCATIONS:
        fhash = int(loc["flag_hash"], 16)
        if save.get_bool(fhash):
            by_region[loc.get("region", "?")].append(loc["name"])
            total += 1

    lines.append(f"\nCompleted AP locations: {total} / {len(_LOCATIONS)}")
    for region in sorted(by_region):
        names = by_region[region]
        lines.append(f"\n  {region} ({len(names)}):")
        for n in names:
            lines.append(f"    [OK] {n}")

    if total == 0:
        lines.append("\n  (none -- try clearing a shrine and re-running)")

    return "\n".join(lines)


# ── Injector ──────────────────────────────────────────────────────────────────

class DeferredSaveInjector(ItemInjector):
    """
    Manages item injection and flag retention.

    On every flush() call (called from inject_loop every 5s):
      1. If save is idle (title-screen heuristic): inject queued items.
      2. Enforce retention: force ap_progression flags to 0 if item not yet received.

    Accepts either an exact save file or a slot directory (same as SaveFileProvider).
    When a slot directory is given, always operates on the most recent sub-save.
    """

    def __init__(self, save_path: Path, rando=None, bridge=None) -> None:
        self._root       = save_path
        self._rando      = rando    # Optional[RandoReader]
        self._bridge     = bridge   # Optional[CemuMemoryBridge] — live injection
        # Store queue + state files alongside the root (in the slot dir or save's parent).
        queue_dir           = save_path if save_path.is_dir() else save_path.parent
        self._queue_path    = queue_dir / "ap_pending_items.json"
        self._state_path    = queue_dir / "ap_client_state.json"
        self._queue:        list[dict] = self._load_queue()
        self._received:     set[int]   = set()
        self._last_mtime    = 0.0
        self._last_change_time = time.monotonic()

    def _resolve(self) -> Optional[Path]:
        """Return the current game_data.sav (slot-dir aware)."""
        if self._root.is_dir():
            return _current_save_in_slot(self._root)
        return self._root if self._root.exists() else None

    def _load_queue(self) -> list[dict]:
        if self._queue_path.exists():
            try:
                return json.loads(self._queue_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _persist_queue(self) -> None:
        self._queue_path.write_text(
            json.dumps(self._queue, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_item_index(self) -> int:
        """Return the last saved item_index (0 if no state file exists)."""
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text(encoding="utf-8")).get("item_index", 0)
            except Exception:
                pass
        return 0

    def persist_item_index(self, index: int) -> None:
        """Persist item_index so restarts don't re-queue already-processed items."""
        self._state_path.write_text(
            json.dumps({"item_index": index}, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Public: called by client ──────────────────────────────────────────────

    def queue_item(self, spec: InjectionSpec) -> None:
        self._received.add(spec.ap_item_id)
        if not spec.actions:
            # Logical item (e.g. Flamebreaker, Snowquill, Vai Outfit) — no save flag
            # to inject. Just tracking receipt is enough for region-gate enforcement.
            log.info("[Received] %s (logical — no save injection)", spec.ap_item_name)
            return
        entry = {"ap_item_id": spec.ap_item_id, "ap_item_name": spec.ap_item_name}
        self._queue.append(entry)
        self._persist_queue()
        log.info("[Queue +%d] %s", len(self._queue), spec.ap_item_name)

    def mark_received(self, ap_item_id: int) -> None:
        """Mark item as received (for gate enforcement) without queuing injection."""
        self._received.add(ap_item_id)

    @property
    def can_inject_now(self) -> bool:
        # Memory bridge attached = injection always possible (no reload needed)
        if self._bridge and self._bridge.is_attached:
            return True
        p = self._resolve()
        if p is None:
            return False
        try:
            mtime = p.stat().st_mtime
        except FileNotFoundError:
            return False
        if mtime != self._last_mtime:
            self._last_mtime = mtime
            self._last_change_time = time.monotonic()
        return (time.monotonic() - self._last_change_time) >= SAFE_WRITE_IDLE_SECONDS

    def flush(self) -> list[InjectionSpec]:
        """
        Inject queued items AND enforce flag retention.
        Safe to call even when not can_inject_now — will skip item injection
        but still log pending count.
        """
        retained  = self._enforce_retention()
        injected  = self._inject_pending() if self.can_inject_now else []

        if self._queue and not self.can_inject_now:
            log.info(
                "[Pending] %d item(s) waiting — retournez au menu titre BotW pour les recevoir",
                len(self._queue),
            )
        if injected:
            names = ", ".join(s.ap_item_name for s in injected)
            log.info("[ACTION] Items injectes : %s — rechargez votre sauvegarde !", names)
        return injected

    def _inject_pending(self) -> list[InjectionSpec]:
        if not self._queue:
            return []
        p = self._resolve()
        if p is None:
            return []
        from BotWClient.item_map import get_spec as _get_spec
        log.info("Save idle — injecting %d item(s) into %s", len(self._queue), p.name)
        injected:  list[InjectionSpec] = []
        remaining: list[dict]          = []
        for entry in self._queue:
            ap_id = entry["ap_item_id"]
            spec  = _get_spec(ap_id)
            if not spec.actions:
                log.warning("No injection actions for %s (id=%d) — skipped", spec.ap_item_name, ap_id)
                continue
            ok = self._apply_actions(p, spec)
            if ok:
                injected.append(spec)
            else:
                remaining.append(entry)
        self._queue = remaining
        self._persist_queue()
        return injected

    def _apply_actions(self, p: Path, spec: InjectionSpec) -> bool:
        """
        Apply all actions in a spec.
        When memory bridge is attached: inject directly into Cemu's RAM (instant, no reload).
        Otherwise: write to save file (requires game reload).
        """
        if self._bridge and self._bridge.is_attached:
            return self._apply_actions_memory(spec)
        return self._apply_actions_savefile(p, spec)

    def _apply_actions_memory(self, spec: InjectionSpec) -> bool:
        """Inject directly into Cemu's live memory — items appear immediately in-game."""
        all_ok = True
        for action in spec.actions:
            if isinstance(action, InjectionSpec.SetFlag):
                ok = self._bridge.write_flag(action.flag_name, 1)
                if ok:
                    log.info("  [Mem] %s  %s = 1", spec.ap_item_name, action.flag_name)
                else:
                    all_ok = False

            elif isinstance(action, InjectionSpec.AddS32):
                if action.flag_name == "CurrentRupee" and self._bridge.has_live_inventory:
                    new_val = self._bridge.live_add_rupees(action.amount)
                    ok = new_val is not None
                else:
                    ok = self._bridge.add_s32_flag(action.flag_name, action.amount)
                if not ok:
                    all_ok = False

            elif isinstance(action, InjectionSpec.AddPouchItem):
                ok = False
                if self._bridge.has_live_inventory:
                    # 1) item déjà présent → on incrémente la quantité (instantané)
                    new_val = self._bridge.live_add_item_qty(action.item_name, action.amount)
                    ok = new_val is not None
                    # 2) sinon, création d'un nouvel item live (insertion dans la liste)
                    if not ok:
                        info = pouch_item_info(action.item_name)
                        if info:
                            ok = self._bridge.live_create_item(
                                action.item_name, info["type"], info.get("sub"), action.amount)
                # 3) dernier recours : save-file (nécessite reload)
                if not ok:
                    ok = self._bridge.add_porch_item(action.item_name, action.amount)
                if ok:
                    log.info("  [Mem] %s  +%d %s", spec.ap_item_name, action.amount, action.item_name)
                else:
                    all_ok = False

            else:
                log.debug("Action %s not implemented for memory injection", type(action).__name__)
        return all_ok

    def _apply_actions_savefile(self, p: Path, spec: InjectionSpec) -> bool:
        """Fallback: write to game_data.sav (requires reload to take effect)."""
        all_ok = True
        for action in spec.actions:
            if isinstance(action, InjectionSpec.SetFlag):
                fhash = crc32_id(action.flag_name)
                ok = _write_flag_to_save(p, fhash, 1)
                if ok:
                    log.info("  [OK] %s  flag %s = 1", spec.ap_item_name, action.flag_name)
                else:
                    all_ok = False

            elif isinstance(action, InjectionSpec.AddS32):
                fhash = crc32_id(action.flag_name)
                try:
                    current_save = parse(p.read_bytes())
                    current = current_save.get_s32(fhash)
                    new_val = max(0, current + action.amount)
                    ok = _write_flag_to_save(p, fhash, new_val)
                    if ok:
                        log.info("  [OK] %s  %s: %d -> %d",
                                 spec.ap_item_name, action.flag_name, current, new_val)
                    else:
                        all_ok = False
                except Exception as exc:
                    log.error("AddS32 failed for %s: %s", spec.ap_item_name, exc)
                    all_ok = False

            elif isinstance(action, InjectionSpec.AddPouchItem):
                ok = _add_porch_item_to_save(p, action.item_name, action.amount)
                if not ok:
                    all_ok = False

            else:
                log.debug("Action %s skipped (save-file injection)",
                          type(action).__name__)
        return all_ok

    def _enforce_retention(self) -> int:
        """
        For each ap_progression gate flag currently set to 1 in the save:
        if the corresponding item has NOT been received via AP, force it back to 0.
        Returns number of flags cleared.
        """
        p = self._resolve()
        if p is None:
            return 0
        try:
            save = parse(p.read_bytes())
        except Exception:
            return 0
        cleared = 0
        for fhash, ap_id in _GATE_HASH_TO_AP_ID.items():
            if save.get_bool(fhash) and ap_id not in self._received:
                ok = _write_flag_to_save(p, fhash, 0)
                if ok:
                    item_name = _GATE_HASH_TO_NAME.get(fhash, f"0x{fhash:08X}")
                    rando_loc = self._rando.location_of(item_name) if self._rando else None
                    if rando_loc:
                        log.info(
                            "[Rando] %s trouve en jeu (%s) — gate AP actif, attente livraison",
                            item_name, rando_loc,
                        )
                    else:
                        log.debug("Retention: cleared 0x%08X (%s not received)", fhash, item_name)
                    cleared += 1
        # Also enforce retention in Cemu memory (immediate effect in-game)
        if self._bridge and self._bridge.is_attached:
            for fhash, ap_id in _GATE_HASH_TO_AP_ID.items():
                if ap_id not in self._received:
                    item_name = _GATE_HASH_TO_NAME.get(fhash, f"0x{fhash:08X}")
                    flag_name = _GATE_BY_AP_ID.get(ap_id, {}).get("flag_name")
                    if flag_name:
                        val = self._bridge.read_flag(flag_name)
                        if val:
                            self._bridge.write_flag(flag_name, 0)
                            log.debug("[Mem] Retention: %s = 0 (not received)", flag_name)
        return cleared

    @property
    def pending_count(self) -> int:
        return len(self._queue)
