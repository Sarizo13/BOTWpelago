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

# Création d'un NOUVEAU nœud PouchItem en live (live_create_item). SÛR depuis le fix
# mCount++ : à chaque création on incrémente le compteur sead::OffsetList (tête+0x08), donc
# le jeu COMPTE le nœud -> il ne le réutilise plus (zéro corruption) et le sérialise au save
# (instantané EN JEU + persistant, validé single + multi-items).
_LIVE_CREATE_ENABLED = True

# Throttle de livraison : un joueur qui "release" tout son monde envoie ~130 items D'UN COUP.
# Tout livrer dans un seul cycle (1) épuise le pool de nœuds libres pré-alloués de BotW (les
# créations live retombent en save-file) et (2) écrit des dizaines de slots PouchItem neufs
# dans la save en une fois -> la reconstruction de la poche au reload PLANTE. On limite donc
# les livraisons "lourdes" (pouch/rupees) par cycle ; le surplus reste en file (persistée) et
# part aux cycles suivants -> le pool a le temps de se régénérer (reload) et la save n'est
# jamais saturée. Les flags (paravoile, champions…) ne comptent pas dans la limite.
MAX_DELIVER_PER_FLUSH = 6


# ── Load canonical data ───────────────────────────────────────────────────────

def _load_locations() -> list[dict]:
    # Union of every possible check: the full game catalogue (shrine completion,
    # towers, beasts, places, quests, memories) + the shrine chests. The active
    # subset depends on the seed's Game Mode — the client polls all known flags
    # and only emits checks for location ids the server says belong to the slot.
    out: list[dict] = []
    for fname in ("locations.json", "shrine_chests.json"):
        try:
            with open(_DATA_DIR / fname, encoding="utf-8") as fh:
                out += json.load(fh)
        except FileNotFoundError:
            pass
    return out

def _load_gate_items() -> dict:
    with open(_DATA_DIR / "gate_items.json", encoding="utf-8") as fh:
        return json.load(fh)

def _load_pouch_items() -> dict:
    """Base d'items de poche livrables en live (type/sub par actor name).
    botw_items.json (base complète, ~130 ingrédients) + pouch_items.json (overrides manuels)."""
    merged: dict = {}
    for fname in ("botw_items.json", "pouch_items.json"):
        try:
            with open(_DATA_DIR / fname, encoding="utf-8") as fh:
                merged.update(json.load(fh).get("items", {}))
        except FileNotFoundError:
            pass
    return merged

_LOCATIONS   = _load_locations()
_GATE_ITEMS  = _load_gate_items()
_POUCH_ITEMS = _load_pouch_items()


def pouch_item_info(item_name: str) -> Optional[dict]:
    """Retourne {'type':int, 'sub':int?} pour un item livrable en live, ou None."""
    return _POUCH_ITEMS.get(item_name)


def reset_ap_state(provider_root: Path) -> int:
    """Supprime l'état AP persisté (file d'attente + item_index) pour repartir de zéro
    sur une nouvelle seed. Retourne le nombre de fichiers supprimés."""
    qdir = provider_root if provider_root.is_dir() else provider_root.parent
    n = 0
    for name in ("ap_pending_items.json", "ap_client_state.json", "ap_baseline.json"):
        f = qdir / name
        if f.exists():
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    return n

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

# Companion state forced once a progression item is received — what a LEGITIMATE
# acquisition would set, which a bare flag-set skips. Found by save-diff (pure rando
# vs AP). Keyed by ap_item_id.
#   flags : extra gamedata flags to force ON in the latest save (rotation-safe).
#   pouch : key/pouch items to add if absent (the actually-usable object).
# Paraglider: IsPlayed_Demo033_1 = Great Plateau "leave" state (else dying outside
# re-traps you); PlayerStole2 = the usable paraglider key item.
_COMPANION_FLAGS: dict[int, list[str]] = {
    # Paravoile : livrée hors-séquence par AP (on saute la cutscene du Roi) → on reproduit
    # l'état que l'event aurait posé pour ne PAS softlocker la chaîne de quêtes principale :
    #   IsPlayed_Demo033_1  = cutscene du Roi (don de la paravoile) jouée
    #   Find_Impa_Activated = démarre la quête "En quête d'Impa" dans le journal ; la quête
    #                         "Le plateau Isolé" s'archive alors (pas de _Finish discret).
    # (Find_Impa_Ready est déjà posé par le jeu ; Find_Impa_Finish est un CHECK → jamais écrit.)
    6_080_000: ["IsPlayed_Demo033_1", "Find_Impa_Activated", "FindDungeon_Finish"],
    #                                                          ^ archive "Le plateau isolé"
    # (FindDungeon). RETIRÉ des checks AP (build_locations QUEST_EXCLUDE) → sûr à écrire ici : le
    # Roi ne déclenche pas la complétion hors-séquence, donc on la pose à la livraison du paravoile.
}
# Capacités de Champion : comme le paravoile, le flag IsGet_ SEUL ne rend pas la capacité
# utilisable — il faut aussi l'OBJET-CLÉ en poche (Obj_HeroSoul_<Race>, type 9). Le rando de
# base place justement cet acteur dans le coffre (BotwRandoTable.cs). On l'ajoute via la save
# (appliqué au rechargement, en même temps que le flag).
_COMPANION_POUCH: dict[int, list[str]] = {
    6_080_000: ["PlayerStole2"],          # Paraglider key item
    6_080_010: ["Obj_HeroSoul_Rito"],     # Revali's Gale
    6_080_011: ["Obj_HeroSoul_Zora"],     # Mipha's Grace
    6_080_012: ["Obj_HeroSoul_Goron"],    # Daruk's Protection
    6_080_013: ["Obj_HeroSoul_Gerudo"],   # Urbosa's Fury
}

# Goal
_GOAL = _GATE_ITEMS["goal"]
_GOAL_FLAG_IDS = [crc32_id(f) for f in _GOAL["require_flags"]]   # legacy (compat)
_DUNGEON_COUNTER_ID = int(_GOAL["shrine_counter"]["flag_hash"], 16)
# Flags requis EN PLUS du compteur de sanctuaires, par mode de goal (option goal_mode) :
#   "shrines" = [] (sanctuaires seuls) ; "full" = 4 Créatures + Master Sword + Arc de Lumière.
_GOAL_MODE_FLAG_IDS = {
    mode: [crc32_id(f) for f in flags]
    for mode, flags in _GOAL.get("modes", {}).items()
}


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
_DUNGEON_SEAL_ID    = crc32_id("DungeonClearSealNum")   # compteur gamedata d'orbes
# Items PouchItem GÉRÉS PAR LE JEU : ne JAMAIS créer un nœud live (le jeu réconcilie et crashe).
# On bump seulement s'ils existent ; persistance via gamedata + save banking.
_GAME_MANAGED_POUCH = {"Obj_DungeonClearSeal"}          # compteur d'orbes (Spirit Orbs)


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


def _pouch_has_item(data: bytes, name: str) -> bool:
    """True if `name` already occupies a PouchItem slot in the save."""
    fp = _find_first_run(data, _PORCH_ITEM_ID)
    if fp < 0:
        return False
    return any(_read_porch_name(data, fp, s) == name for s in range(_PORCH_SLOTS))


def _read_porch_value(data: bytes, item_name: str) -> Optional[int]:
    """Valeur (PorchItem_Value1) du slot pouch nommé `item_name` dans la save, ou None si absent."""
    fp = _find_first_run(data, _PORCH_ITEM_ID)
    fv = _find_first_run(data, _PORCH_VALUE1_ID)
    if fp < 0 or fv < 0:
        return None
    for slot in range(_PORCH_SLOTS):
        if _read_porch_name(data, fp, slot) == item_name:
            return struct.unpack_from(">I", data, 12 + (fv + slot) * 8 + 4)[0]
    return None


def _add_porch_item_to_save(path: Path, item_name: str, amount: int,
                            allow_create: bool = True) -> bool:
    """
    Add `amount` to a stackable item in the PouchItem inventory.

    If the item already has a slot → increment its PorchItem_Value1.
    If not found AND allow_create → find the first empty slot and write the name + count.
    If not found AND NOT allow_create → return False (caller defers).

    `allow_create=False` est utilisé pour le FILLER : créer en masse des slots PouchItem
    neufs dans la save (rafale "release all") corrompt la reconstruction de la poche au
    reload → crash. Le filler neuf passe donc UNIQUEMENT en live (live_create_item, géré
    par le jeu) ; seuls les objets-clés essentiels (champions, ≤4) créent un slot save-file.
    """
    try:
        data = bytearray(_read_shared(path))
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

        if target_slot < 0 and not allow_create:
            # Filler neuf : pas de création de slot save-file (anti-corruption). Reporté →
            # sera livré en live après un reload (le pool de nœuds libres se régénère).
            return False
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
        _write_atomic(path, bytes(data))
        log.info("  [OK] PouchItem %s: %d -> %d", item_name, current, new_val)
        return True

    except Exception as exc:
        log.error("AddPouchItem failed for %s: %s", item_name, exc)
        return False


# ── Binary save writer ────────────────────────────────────────────────────────

def _read_shared(path: Path) -> bytes:
    """Lit un fichier en autorisant TOUT partage Windows (READ | WRITE | DELETE) : Cemu DOIT
    pouvoir créer/écrire game_data.sav PENDANT que le client le lit. Une lecture classique
    (read_bytes) verrouille le fichier → Cemu échoue à sauvegarder ('FSC: File create failed')
    → le jeu ne sauvegarde plus → état/inventaire incohérent → CRASH. Repli sur read_bytes()
    hors Windows ou en cas d'échec."""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        h = k32.CreateFileW(str(path), 0x80000000, 0x1 | 0x2 | 0x4, None, 3, 0, None)  # GENERIC_READ, SHARE_ALL, OPEN_EXISTING
        if not h or h == ctypes.c_void_p(-1).value:
            return path.read_bytes()
        try:
            size = path.stat().st_size
            buf = ctypes.create_string_buffer(size)
            nread = wintypes.DWORD(0)
            if not k32.ReadFile(h, buf, size, ctypes.byref(nread), None):
                return path.read_bytes()
            return buf.raw[:nread.value]
        finally:
            k32.CloseHandle(h)
    except Exception:
        return path.read_bytes()


def _write_atomic(path: Path, data: bytes) -> None:
    """Écrit la save de façon atomique (fichier temp + rename) pour minimiser la fenêtre de verrou
    exclusif. Une écriture directe (write_bytes) tronque puis tient le fichier ouvert le temps de tout
    réécrire → si Cemu sauvegarde pile à ce moment : 'FSC: File create failed' → save Cemu ratée →
    CRASH. Le rename est quasi-instantané et remplace la cible d'un coup ; on réessaie si Cemu la tient."""
    tmp = path.with_name(path.name + ".botwtmp")
    tmp.write_bytes(data)
    for _ in range(6):
        try:
            tmp.replace(path)            # rename atomique (MoveFileEx REPLACE_EXISTING) sur Windows
            return
        except OSError:
            time.sleep(0.05)
    tmp.replace(path)                    # dernier essai — laisse remonter si ça échoue vraiment


def _write_flag_to_save(path: Path, flag_id_int: int, value: int) -> bool:
    """
    Find a flag entry (u32 flag_id, u32 value) in the save by binary search
    and overwrite its value field in-place. Returns True on success.

    The save is a sorted flat array starting at offset 12. Binary search is O(log n).
    """
    try:
        data = bytearray(_read_shared(path))
        n = (len(data) - 12) // 8
        lo, hi = 0, n - 1
        needle = struct.pack(">I", flag_id_int)
        while lo <= hi:
            mid = (lo + hi) // 2
            off = 12 + mid * 8
            mid_id = data[off: off + 4]
            if mid_id == needle:
                struct.pack_into(">I", data, off + 4, value & 0xFFFFFFFF)
                _write_atomic(path, bytes(data))
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
        qdir            = save_path if save_path.is_dir() else save_path.parent
        self._baseline_path = qdir / "ap_baseline.json"
        self._baselined = False

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
            self._raw = _read_shared(p)          # partage complet → ne bloque pas les saves Cemu
            self._save = parse(self._raw)
            self._mtime = mtime
            if p != self._active:
                log.info("Save rotated → %s", p.name)
                self._active = p
            return True
        except Exception as exc:
            log.warning("Save parse error: %s", exc)
            return False

    def _apply_baseline(self) -> None:
        """Au 1er poll : charge (ou capture) la baseline = checks déjà faits au démarrage
        du run. Ils ne seront jamais ré-émis (anti-spam au démarrage + flags d'intro).
        Effacée par « Réinitialiser (nouvelle seed) » → re-capturée au prochain run."""
        self._baselined = True
        if self._save is None:
            return
        if self._baseline_path.exists():
            try:
                ids = json.loads(self._baseline_path.read_text(encoding="utf-8"))
                self._reported.update(int(i) for i in ids)
                log.info("[Baseline] %d check(s) déjà faits ignorés (run en cours)", len(ids))
                return
            except Exception:
                pass
        done = [ap_id for fhash, ap_id in _LOC_HASH_TO_AP_ID.items()
                if self._save.get_bool(fhash)]
        self._reported.update(done)
        try:
            self._baseline_path.write_text(json.dumps(done), encoding="utf-8")
        except Exception:
            pass
        log.info("[Baseline] %d check(s) déjà faits au démarrage ignorés "
                 "(seuls les NOUVEAUX compteront)", len(done))

    def poll(self) -> list[int]:
        self._reload()
        if self._save is None:
            return []
        if not self._baselined:
            self._apply_baseline()
        new: list[int] = []
        for fhash, ap_id in _LOC_HASH_TO_AP_ID.items():
            if ap_id not in self._reported and self._save.get_bool(fhash):
                new.append(ap_id)
                self._reported.add(ap_id)
        return new

    def is_goal_complete(self, required_shrine_count: int, goal_mode: str = "shrines") -> bool:
        if self._save is None:
            return False
        # Flags exigés selon le mode ("shrines" = aucun ; "full" = créatures+sword+arc).
        flag_ids = _GOAL_MODE_FLAG_IDS.get(goal_mode)
        if flag_ids is None:                                   # mode inconnu → repli sûr
            flag_ids = _GOAL_MODE_FLAG_IDS.get("shrines", [])
        if not all(self._save.get_bool(fid) for fid in flag_ids):
            return False
        return self._save.get_s32(_DUNGEON_COUNTER_ID) >= required_shrine_count

    def get_dungeon_counter(self) -> int:
        """Nombre de sanctuaires réellement terminés (DungeonClearCounter) dans la save."""
        return self._save.get_s32(_DUNGEON_COUNTER_ID) if self._save else 0

    def get_spirit_orbs(self) -> int:
        """Vraie valeur d'orbes (Obj_DungeonClearSeal) dans le PorchItem de la save. Utilise les
        octets DÉJÀ chargés par _reload (self._raw) → PAS de relecture fichier par poll (contention)."""
        data = getattr(self, "_raw", None)
        if not data:
            return 0
        try:
            return _read_porch_value(data, "Obj_DungeonClearSeal") or 0
        except Exception:
            return 0

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
        self._last_banked_orb  = 0     # dernière valeur d'orbe (pouch) bankée dans la save
        self._last_banked_seal = 0     # dernière valeur DungeonClearSealNum bankée dans la save

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
    def _save_is_idle(self) -> bool:
        """True si la save n'a pas bougé depuis SAFE_WRITE_IDLE_SECONDS (≈ menu titre BotW).
        Indépendant du bridge — sert à savoir quand on peut écrire le DISQUE sans risque
        d'être écrasé par une auto-save du jeu."""
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

    @property
    def can_inject_now(self) -> bool:
        # Live injection (bridge) works any time; the save-file fallback (no Cemu) needs idle.
        return (self._bridge is not None and self._bridge.is_attached) or self._save_is_idle

    def flush(self) -> list[InjectionSpec]:
        """
        Every poll: reconcile gate flags (delivery force-on + retention) AND deliver
        pending items. Tout passe par le FICHIER save (seule voie qui survit au reload) :
          - flags (paraglider, abilities…) → _enforce_retention force la valeur dans la
            LATEST save chaque poll (rotation-safe) → appliqué au rechargement.
          - poche/compteur/rubis → _inject_pending écrit dans la LATEST save quand elle est
            idle (menu titre) ; différé tant que le joueur est en jeu.
        """
        self._enforce_retention()
        # Orbes : le jeu reverte le compteur → (1) on le maintient EN LIVE chaque poll, (2) on le
        # BANQUE dans la save pour qu'il survive au reload (le live seul ne persiste pas).
        if self._bridge is not None and self._bridge.has_live_inventory:
            self._bridge.maintain_persistent()
        self._bank_spirit_orbs()
        injected = self._inject_pending()
        if injected:
            is_flag = lambda s: any(isinstance(a, InjectionSpec.SetFlag) for a in s.actions)
            items = [s.ap_item_name for s in injected if not is_flag(s)]
            flags = [s.ap_item_name for s in injected if is_flag(s)]
            if items:
                log.info("[OK] Reçu(s) : %s", ", ".join(items))
            if flags:
                log.info("[ACTION] Flags écrits : %s — RECHARGE la save pour les appliquer.",
                         ", ".join(flags))
        return injected

    def _bank_spirit_orbs(self) -> None:
        """Écrit les orbes reçus d'AP DANS LA SAVE (pouch Obj_DungeonClearSeal + gamedata
        DungeonClearSealNum) pour qu'ils survivent au rechargement — le maintien live seul ne
        persiste pas (le jeu restaure le nœud à sa valeur sérialisée). Écrit UNIQUEMENT quand la
        cible augmente (pas à chaque poll) et seulement vers le HAUT (n'écrase pas les orbes
        naturels ni une dépense au sanctuaire de la déesse au-dessus de la cible AP)."""
        if self._bridge is None:
            return
        # Cemu attaché : on n'écrit PAS le fichier (contention → Cemu ne peut plus sauver → crash).
        # L'orbe est maintenu en mémoire (maintain_persistent) et l'autosave de Cemu le persiste.
        if self._bridge.is_attached:
            return
        # Cible unique = max(pouch orbe, compteur gamedata). Sur une save à 0 orbe, le nœud pouch
        # n'existe pas (orb_pouch_target=None) mais seal_target porte le compte des orbes AP.
        target = max(getattr(self._bridge, "orb_pouch_target", None) or 0,
                     getattr(self._bridge, "seal_target", None) or 0)
        if target <= self._last_banked_orb:
            return
        p = self._resolve()
        if p is None:
            return
        try:
            data = _read_shared(p)
            # Pouch : bump SEULEMENT si le slot existe (allow_create=False — créer un slot d'orbe
            # dans la save est risqué à la reconstruction). Sinon DungeonClearSealNum porte le compte.
            cur = _read_porch_value(data, "Obj_DungeonClearSeal")
            if cur is not None and cur < target and _add_porch_item_to_save(
                    p, "Obj_DungeonClearSeal", target - cur, allow_create=False):
                log.info("[Orbe] banké dans la save : %d (survit au reload)", target)
            # Compteur gamedata (survit au reload comme un flag).
            if parse(data).get_s32(_DUNGEON_SEAL_ID) < target:
                _write_flag_to_save(p, _DUNGEON_SEAL_ID, target)
            self._last_banked_orb = target
            self._last_banked_seal = target
        except Exception as exc:
            log.debug("[Orbe] banking save échoué : %s", exc)

    def _inject_pending(self) -> list[InjectionSpec]:
        if not self._queue:
            return []
        p = self._resolve()
        if p is None:
            return []
        from BotWClient.item_map import get_spec as _get_spec
        # L'inventaire a pu être réalloué/déplacé (grosse rafale d'items reçus) → re-localiser
        # une fois avant de livrer en live, sinon on écrirait dans un buffer périmé.
        if self._bridge is not None and self._bridge.has_live_inventory:
            self._bridge.refresh_inventory_if_stale()
        injected:  list[InjectionSpec] = []
        remaining: list[dict]          = []
        deferred = 0
        heavy = 0          # livraisons "lourdes" (pouch/rupees) déjà faites ce cycle
        for entry in self._queue:
            spec = _get_spec(entry["ap_item_id"])
            if not spec.actions:
                continue   # logical item — nothing to inject
            # Gate flags are delivered by _enforce_retention (forced into the latest save
            # every poll — rotation-safe, applied on reload). Just dequeue here.
            if any(isinstance(a, InjectionSpec.SetFlag) for a in spec.actions):
                injected.append(spec)
                continue
            # Throttle anti-rafale : au-delà de MAX_DELIVER_PER_FLUSH livraisons lourdes ce
            # cycle, on reporte le reste (évite d'épuiser le pool de nœuds libres et de saturer
            # la save en un coup -> crash au reload). La file est persistée, ça repart après.
            if heavy >= MAX_DELIVER_PER_FLUSH:
                remaining.append(entry)
                continue
            # Livraison LIVE (instantanée + persistante) : live_create_item crée un VRAI
            # nœud PouchItem runtime que le jeu sérialise au save -> survit au reload (validé
            # en jeu). On l'utilise dès que Cemu est attaché avec l'inventaire localisé ;
            # sinon (pas de Cemu) on écrit le FICHIER-save quand il est idle (menu titre).
            delivered = False
            if self._bridge is not None and self._bridge.has_live_inventory:
                delivered = self._apply_actions_memory(spec, p)
            # Voie FICHIER seulement si Cemu N'EST PAS attaché (sinon écrire game_data.sav bloque
            # les autosaves de Cemu → save incohérente → crash). Attaché : on livre en live, ou on
            # reporte (l'autosave de Cemu persiste ce qui est déjà en mémoire).
            attached = self._bridge is not None and self._bridge.is_attached
            if not delivered and self._save_is_idle and not attached:
                delivered = self._apply_actions_savefile(p, spec)
            if delivered:
                injected.append(spec)
                heavy += 1
            else:
                remaining.append(entry)
                if not (self._bridge is not None and self._bridge.has_live_inventory) \
                        and not self._save_is_idle:
                    deferred += 1
        if deferred:
            log.info("[Pending] %d objet(s) en attente — lance Cemu/BotW (admin) ou passe au menu titre.", deferred)
        self._queue = remaining
        self._persist_queue()
        # Une grosse rafale a pu faire réallouer l'inventaire en cours de route → BotW reset les
        # nœuds PRÉEXISTANTS à leur qty d'origine (les bumps live sont perdus, ex: l'orbe revient
        # à 22). On ré-assert les qty cibles ; quand la file est vidée, dernier passage puis on
        # oublie les cibles (le joueur peut alors dépenser ses orbes/objets librement).
        if self._bridge is not None and self._bridge.has_live_inventory:
            self._bridge.refresh_inventory_if_stale()
            self._bridge.reassert_qty_targets()
            if not self._queue:
                self._bridge.clear_qty_targets()
        return injected

    def _apply_actions_memory(self, spec: InjectionSpec, p: Optional[Path] = None) -> bool:
        """Injection LIVE dans la mémoire de Cemu : objets instantanés EN JEU + persistants
        au reload (live_create_item = vrai nœud PouchItem sérialisé). Voie de livraison
        PRINCIPALE quand Cemu est attaché (cf. _inject_pending) ; fallback = fichier-save."""
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
                # qty-bump live = SÛR + persiste (item déjà compté par le jeu). La CRÉATION
                # d'un nouveau nœud (live_create_item) est gardée derrière _LIVE_CREATE_ENABLED
                # car sans mCount++ elle corrompt la save. Si désactivé / item absent, échec ->
                # _inject_pending bascule sur la voie save-fichier (sûre, au menu titre).
                info = pouch_item_info(action.item_name)
                if action.item_name in _GAME_MANAGED_POUCH:
                    # Item géré par le JEU (compteur d'orbes Obj_DungeonClearSeal) : ne JAMAIS créer
                    # un faux nœud — le jeu le réconcilie à la sortie de sanctuaire et CRASH. On bump
                    # seulement s'il existe déjà ; la persistance passe par DungeonClearSealNum
                    # (add_s32) + le banking save. Compté LIVRÉ même si absent, sinon la spec se
                    # rejoue et re-incrémente le compteur en boucle (double comptage).
                    self._bridge.live_add_item_qty(action.item_name, action.amount)
                    ok = True
                elif self._bridge.pool_exhausted:
                    # Pool de nœuds libres épuisé : création impossible. On ne tente qu'un bump
                    # d'item déjà présent ; absent -> échec silencieux -> save-file (bump-only)
                    # ou report en file (livré en live après un reload, qui régénère le pool).
                    ok = self._bridge.live_add_item_qty(action.item_name, action.amount) is not None
                elif _LIVE_CREATE_ENABLED and info is not None:
                    ok = self._bridge.live_create_item(
                        action.item_name, info["type"], info.get("sub"), action.amount)
                else:
                    ok = self._bridge.live_add_item_qty(action.item_name, action.amount) is not None
                if ok:
                    log.info("  [Live] %s  +%d %s (instantané)",
                             spec.ap_item_name, action.amount, action.item_name)
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
                    current_save = parse(_read_shared(p))
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
                # Filler : JAMAIS de création de slot save-file (anti-crash). Bump si l'item
                # existe déjà dans la save ; sinon report → livraison live après reload.
                ok = _add_porch_item_to_save(p, action.item_name, action.amount,
                                             allow_create=False)
                if not ok:
                    all_ok = False

            else:
                log.debug("Action %s skipped (save-file injection)",
                          type(action).__name__)
        return all_ok

    def _enforce_retention(self) -> int:
        """
        Every poll, reconcile each ap_progression GATE flag in the LATEST save:
          - item RECEIVED     → force the flag to 1 (DELIVERY: survives BotW's save-slot
                                rotation since we always write the freshest save; bool
                                flags are cached at load, so it takes effect on reload).
          - item NOT received → force the flag to 0 (GATE: prevents the vanilla mechanic
                                from handing it over before AP does).
        Returns the number of flags written.
        """
        p = self._resolve()
        if p is None:
            return 0
        n = 0
        # ── Cemu ATTACHÉ : TOUT EN MÉMOIRE, zéro écriture de game_data.sav ─────────────────
        # Écrire le fichier pendant que Cemu tourne l'empêche de sauvegarder ('FSC: File create
        # failed') → la save disque devient la version du client, incohérente avec l'état mémoire
        # de Cemu → CRASH au reload (mort). En mémoire, l'AUTOSAVE de Cemu (débloquée) persiste tout.
        if self._bridge and self._bridge.is_attached:
            for fhash, ap_id in _GATE_HASH_TO_AP_ID.items():
                fn = _GATE_BY_AP_ID.get(ap_id, {}).get("flag_name")
                if not fn:
                    continue
                want = ap_id in self._received
                if bool(self._bridge.read_flag(fn)) != want:
                    self._bridge.write_flag(fn, 1 if want else 0)   # livraison (=1) OU gate (=0)
                    n += 1
            for ap_id, fnames in _COMPANION_FLAGS.items():
                if ap_id in self._received:
                    for fname in fnames:
                        if not self._bridge.read_flag(fname):
                            self._bridge.write_flag(fname, 1)
                            n += 1
            # NB: _COMPANION_POUCH (objets-clés PlayerStole2 / Obj_HeroSoul_*) NON créés en live
            # quand attaché : un create juste avant une réallocation se perd puis se re-crée =
            # DOUBLON / corruption (constaté). Le paravoile marche via son flag. Livrer l'objet-clé
            # des Champions reste un TODO (probablement inutile si le flag suffit ; à tester).
            return n
        # ── Cemu NON attaché : voie FICHIER (au menu titre → Cemu ne tourne pas, pas de contention) ──
        try:
            save = parse(_read_shared(p))
        except Exception:
            return 0
        for fhash, ap_id in _GATE_HASH_TO_AP_ID.items():
            want = ap_id in self._received
            if save.get_bool(fhash) != want:
                if _write_flag_to_save(p, fhash, 1 if want else 0):
                    name = _GATE_HASH_TO_NAME.get(fhash, f"0x{fhash:08X}")
                    if want:
                        log.debug("Livraison flag: %s = 1 (reçu) — recharge pour appliquer", name)
                    else:
                        loc = self._rando.location_of(name) if self._rando else None
                        if loc:
                            log.info("[Rando] %s trouvé en jeu (%s) — gate AP actif, attente livraison",
                                     name, loc)
                    n += 1
        for ap_id, fnames in _COMPANION_FLAGS.items():
            if ap_id in self._received:
                for fname in fnames:
                    fh = crc32_id(fname)
                    if not save.get_bool(fh) and _write_flag_to_save(p, fh, 1):
                        log.debug("Companion flag: %s = 1 (via %d reçu)", fname, ap_id)
                        n += 1
        for ap_id, items in _COMPANION_POUCH.items():
            if ap_id in self._received:
                for iname in items:
                    if not _pouch_has_item(_read_shared(p), iname) and _add_porch_item_to_save(p, iname, 1):
                        log.info("[OK] Objet clé ajouté : %s (recharge la save)", iname)
                        n += 1
        return n

    @property
    def pending_count(self) -> int:
        return len(self._queue)
