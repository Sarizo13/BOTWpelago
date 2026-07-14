"""
Save-file based GameStateProvider + ItemInjector (MVP).

Detection : polls game_data.sav every 2s, emits new location checks.
Injection : sets flag to 1 when AP delivers a progression item.
Gating    : forces ap_progression flags back to 0 while item not yet received
            ("flag retention" — prevents vanilla mechanics from bypassing AP).
Goal      : evaluates Master Sword + 4 HeroSouls + DungeonClearCounter >= N.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import struct
import time
from pathlib import Path
from typing import Optional

from ..memory_injector import cemu_process_running
from ..save_parser import parse, ParsedSave, LazyParsedSave, flag_id as crc32_id
from .base import GameStateProvider, ItemInjector, InjectionSpec

log = logging.getLogger("BotWClient.SaveFile")

_DATA_DIR = Path(__file__).parents[2] / "data"

SAFE_WRITE_IDLE_SECONDS = 5   # 5s idle = title screen (was 35s)

# Création d'un NOUVEAU nœud PouchItem en live (live_create_item). SÛR depuis le fix
# mCount++ : à chaque création on incrémente le compteur sead::OffsetList (tête+0x08), donc
# le jeu COMPTE le nœud -> il ne le réutilise plus (zéro corruption) et le sérialise au save
# (instantané EN JEU + persistant, validé single + multi-items).
_LIVE_CREATE_ENABLED = True
# Filler d'équipement reçu quand l'onglet est PLEIN (cap *PorchStockNum) : converti en rubis
# (retenter en boucle bloquerait la file — rafale release-all = dizaines d'armes sur 8 slots).
_GEAR_OVERFLOW_RUPEES = 100

# Throttle de livraison : un joueur qui "release" tout son monde envoie ~130 items D'UN COUP.
# Tout livrer dans un seul cycle (1) épuise le pool de nœuds libres pré-alloués de BotW (les
# créations live retombent en save-file) et (2) écrit des dizaines de slots PouchItem neufs
# dans la save en une fois -> la reconstruction de la poche au reload PLANTE. On limite donc
# les livraisons "lourdes" (pouch/rupees) par cycle ; le surplus reste en file (persistée) et
# part aux cycles suivants -> le pool a le temps de se régénérer (reload) et la save n'est
# jamais saturée. Les flags (paravoile, champions…) ne comptent pas dans la limite.
MAX_DELIVER_PER_FLUSH = 6

# ── Cap cœurs / endurance + overflow rubis ──────────────────────────────────────
# Réceptacles de Cœur / Fioles d'Endurance reçus d'AP → augmentent le MAX PERSISTANT (flag
# gamedata, reload-gated) jusqu'au plafond DUR de BotW. Chaque unité qui dépasserait le plafond
# (joueur déjà au max) est convertie en don de rubis (le réceptacle/fiole serait sinon perdu).
#
# CONSTANTES CONFIRMÉES PAR LECTURE DES SAVES RÉELLES (2026-07-13) — l'ancien candidat
# `Item_LifeMaxUp` n'existe pas dans cette version ; les VRAIS flags sont :
#   • CŒURS : `MaxHartValue` (s32, ¼-cœurs) — lu 12 sur une save 3 cœurs et 36 sur une save
#     9 cœurs (CurrentHart ≤ MaxHartValue partout). 1 réceptacle = +4 ; plafond 120 = 30 cœurs.
#   • ENDURANCE : `StaminaMax` ET `StaminaCurrentMax` (f32, TOUJOURS égaux dans les saves —
#     on écrit les DEUX via `also`) — lus 1000.0 (base) et 1200.0 (base + 1 fiole vanilla).
#     1 fiole = +200 (1/5 de roue) ; plafond 3000 = 3 roues.
# Repli sûr conservé : flag absent / valeur hors [lo, hi] → tout en rubis, aucune écriture.
# (Validation finale in-game : premier Réceptacle/Fiole reçu d'AP → +1 cœur / +1/5 roue au reload.)
_MAX_STAT: dict[str, dict] = {
    "heart":   {"flag": "MaxHartValue", "kind": "s32", "also": [],
                "per_unit": 4,     "cap": 120,    "lo": 4,     "hi": 200},
    "stamina": {"flag": "StaminaMax",   "kind": "f32", "also": ["StaminaCurrentMax"],
                "per_unit": 200.0, "cap": 3000.0, "lo": 500.0, "hi": 4000.0},
}


def _plan_max_stat(current: float, per_unit: float, cap: float, amount: int
                   ) -> tuple[float, int, int]:
    """Planifie l'application de `amount` unités (réceptacles/fioles) à un max plafonné.
    Applique chaque unité tant qu'elle NE dépasse PAS `cap` ; les unités restantes débordent.
    Retourne (nouvelle_valeur_max, unités_appliquées, unités_overflow). Pur → testable."""
    applied = 0
    val = current
    for _ in range(max(0, amount)):
        if val + per_unit <= cap + 1e-6:
            val += per_unit
            applied += 1
    return val, applied, max(0, amount) - applied


def _fmt_stat(v: float, is_f32: bool) -> str:
    return f"{v:g}" if is_f32 else str(int(v))


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
    """Base d'items de poche livrables en live (type/sub/sortKey par actor name).
    pouch_db.json (base COMPLÈTE armes/armures/matériaux depuis ActorInfo, dict plat) +
    botw_items.json / pouch_items.json (overrides curés, format {items:{…}})."""
    merged: dict = {}
    try:
        with open(_DATA_DIR / "pouch_db.json", encoding="utf-8") as fh:
            merged.update(json.load(fh))          # dict plat {actor: {type,…}}
    except FileNotFoundError:
        pass
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
    sur une nouvelle seed. Retourne le nombre de fichiers supprimés.

    NB : la BASELINE n'est PLUS supprimée ici — elle est désormais indexée par seed et gérée
    par le provider (_apply_baseline) : re-snapshotée seulement quand la seed CHANGE. Un
    --reset en cours de run (relance après crash) re-livrait les items MAIS re-snapshotait
    aussi la baseline → les checks faits pendant le trou de couverture étaient MANGÉS
    (constaté 2026-07-13 : 4 sanctuaires du Plateau + tour jamais émis)."""
    qdir = provider_root if provider_root.is_dir() else provider_root.parent
    n = 0
    for name in ("ap_pending_items.json", "ap_client_state.json"):
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
    6_080_006: ["Weapon_Sword_070"],      # Master Sword (arme type 0)
    6_080_010: ["Obj_HeroSoul_Rito"],     # Revali's Gale
    6_080_011: ["Obj_HeroSoul_Zora"],     # Mipha's Grace
    6_080_012: ["Obj_HeroSoul_Goron"],    # Daruk's Protection
    6_080_013: ["Obj_HeroSoul_Gerudo"],   # Urbosa's Fury
    # Tenues de région (Flamebreaker 6080014, Snowquill 015, Vai 016, Zora 017) + Arc de
    # Lumière (018) : AJOUTÉS plus bas depuis leur champ `inject` (source unique de vérité) —
    # TENUE COMPLÈTE (casque type 4 + torse 5 + jambes 6) et l'arc, livrés + retenus comme
    # les objets-clés companion.
}

# Tenues de région + Arc de Lumière (role ap_progression_logical) : on ALIMENTE les maps
# companion depuis leur `inject` (add_porch → pièces pouch, set_flag → flags IsGet_/gate) pour
# une livraison UNIQUE, idempotente et retenue chaque poll dans les deux modes. Évite le double
# routage (queue vs companion) et garde data/gate_items.json comme source unique. Les flags
# IsGet_Armor_* / mailbox de gate sont ainsi forcés ON à la réception (voie companion) et
# comptés comme écrits par le client (voir _CLIENT_WRITTEN_FLAGS plus bas).
for _lit in _GATE_ITEMS["items"]:
    if _lit.get("role") != "ap_progression_logical":
        continue
    _ap = _lit["ap_item_id"]
    for _inj in (_lit.get("inject") or []):
        if _inj.get("type") == "add_porch":
            _COMPANION_POUCH.setdefault(_ap, [])
            if _inj["item"] not in _COMPANION_POUCH[_ap]:
                _COMPANION_POUCH[_ap].append(_inj["item"])
        elif _inj.get("type") == "set_flag":
            _COMPANION_FLAGS.setdefault(_ap, [])
            if _inj["flag"] not in _COMPANION_FLAGS[_ap]:
                _COMPANION_FLAGS[_ap].append(_inj["flag"])

# Flags que le CLIENT ÉCRIT lui-même (livraison gate + companion) → à NE PAS détecter comme des
# checks joueur : sinon on envoie un faux check. Critique en lecture mémoire (nos écritures sont
# visibles au poll instantanément). Ex: Get_MasterSword_Finish = livraison Master Sword ET location
# « Get Master Sword ». On les retire du poll de locations.
_CLIENT_WRITTEN_FLAGS: set[int] = set(_GATE_HASH_TO_AP_ID.keys())
for _fnames in _COMPANION_FLAGS.values():
    _CLIENT_WRITTEN_FLAGS |= {crc32_id(f) for f in _fnames}
_LOC_HASH_TO_AP_ID = {h: a for h, a in _LOC_HASH_TO_AP_ID.items() if h not in _CLIENT_WRITTEN_FLAGS}

# Goal
_GOAL = _GATE_ITEMS["goal"]
_GOAL_FLAG_IDS = [crc32_id(f) for f in _GOAL["require_flags"]]   # legacy (compat)
_DUNGEON_COUNTER_ID = int(_GOAL["shrine_counter"]["flag_hash"], 16)
# Flags Clear_DungeonNNN des 120 sanctuaires : source de comptage FIABLE pour le goal et le
# tracker. Constat 2026-07-14 (save réelle) : `DungeonClearCounter` reste à 0 alors que des
# Clear_Dungeon* sont à 1 → un goal assis sur le seul compteur ne se déclencherait JAMAIS.
# On prend le MAX des deux (le compteur reste pris en compte s'il fonctionne sur d'autres saves).
_SHRINE_FLAG_IDS = [int(loc["flag_hash"], 16) for loc in _LOCATIONS
                    if loc.get("category") == "shrine"]
# Locations PRÉ-VRAIES sur toute NOUVELLE PARTIE moddée : le rando vendorisé force InitValue=1
# dans bootup.pack/gamedata.ssarc (rando/BotwRandoLib/Randomizer.cs · UpdateGameData) — c'est son
# « skip plateau » : 4 Clear_Dungeon du plateau, tour (MapTower_07 + Location_MapTower07),
# Souvenir 008. Constaté sur save neuve le 2026-07-14 (flags à 1 dès la 2e minute de jeu).
# Décision « Plateau OFFERT » (2026-07-14) : ces checks partent en FREEBIES — jamais baselinés
# (émis à la connexion, même sur room vierge) et EXCLUS du compteur de sanctuaires (goal+tracker),
# sinon le goal « N sanctuaires » démarrerait à 4 et la baseline les mangerait à jamais.
_RANDO_INIT_LOCATION_IDS: set[int] = {
    6_081_009,  # Owa Daim Shrine     (Clear_Dungeon009)
    6_081_038,  # Oman Au Shrine      (Clear_Dungeon038)
    6_081_041,  # Ja Baij Shrine      (Clear_Dungeon041)
    6_081_065,  # Keh Namut Shrine    (Clear_Dungeon065)
    6_081_307,  # Great Plateau Tower (MapTower_07)
    6_081_642,  # Map Tower07         (Location_MapTower07)
    6_082_508,  # Souvenir 008        (IsGet_MemoryPhoto_008)
}
# Flags des 4 sanctuaires pré-clearés — soustraits du comptage (un joueur ne peut PAS les refaire).
_RANDO_INIT_SHRINE_FLAG_IDS = [int(loc["flag_hash"], 16) for loc in _LOCATIONS
                               if loc.get("category") == "shrine"
                               and loc["ap_id"] in _RANDO_INIT_LOCATION_IDS]
# HORS POOL (2026-07-14, miroir de worlds/botw/locations.py RANDO_INIT_LOCATION_IDS) : ces
# locations n'existent plus côté serveur (un item de progression y arrivait « gratuit » —
# Paraglider sur Map Tower07). Le client ne les émet donc plus du tout.
_LOC_HASH_TO_AP_ID = {h: a for h, a in _LOC_HASH_TO_AP_ID.items()
                      if a not in _RANDO_INIT_LOCATION_IDS}
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
# Types de poche EMPILABLES (bump quantité). Les autres (armes 0/arcs 1/boucliers 3/armures 4-6)
# sont UNIQUES → toujours un nouveau slot, jamais de bump de durabilité.
_STACKABLE_TYPES = {2, 7, 8}


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

    def __init__(self, save_path: Path, bridge=None) -> None:
        self._root      = save_path          # exact file OR slot dir
        self._bridge    = bridge             # CemuMemoryBridge : lecture game_data EN MÉMOIRE
        self._active:   Optional[Path] = None  # currently tracked file
        self._mtime     = 0.0
        self._save:     Optional[ParsedSave] = None
        self._reported: set[int] = set()
        qdir            = save_path if save_path.is_dir() else save_path.parent
        self._baseline_path = qdir / "ap_baseline.json"
        self._baselined = False
        self._server_seed: Optional[str] = None   # seed de la room (RoomInfo.seed_name)
        self._server_checked: set[int] = set()    # checks déjà connus du serveur (Connected)

    def set_server_context(self, seed_name: Optional[str], checked: set[int]) -> None:
        """Contexte serveur transmis par le client à la connexion — utilisé par la baseline :
        (1) la baseline est indexée par SEED (re-snapshot seulement quand la seed change,
        les relances/--reset ne re-mangent plus les checks) ; (2) au snapshot d'une room EN
        COURS, seuls les checks que le serveur connaît déjà sont baselinés — un flag vrai
        mais missing côté serveur = progression non envoyée (crash/trou de couverture) →
        ÉMIS au poll suivant au lieu d'être perdu."""
        self._server_seed = seed_name
        self._server_checked = set(checked)

    def _resolve(self) -> Optional[Path]:
        """Return the game_data.sav to read (handles both exact-file and slot-dir)."""
        if self._root.is_dir():
            return _current_save_in_slot(self._root)
        return self._root if self._root.exists() else None

    @property
    def is_available(self) -> bool:
        return self._resolve() is not None

    def _reload(self) -> bool:
        # Cemu ATTACHÉ : lire game_data EN MÉMOIRE (buffer à _gd_base, même format que le fichier).
        # On n'ouvre PLUS game_data.sav → on ne bloque plus les autosaves de Cemu ('FSC: File create
        # failed' → save disque incohérente → CRASH). La mémoire est vivante : on re-parse chaque poll.
        b = self._bridge
        if b is not None and b.is_attached:
            raw = b.read_gamedata()
            if raw and len(raw) >= 12:
                try:
                    self._save = LazyParsedSave(raw)   # binary search, PAS de dict 128K (perf)
                    self._raw = raw
                    return True
                except Exception as exc:
                    log.warning("Mem game_data parse error: %s", exc)
            # repli fichier si la lecture mémoire échoue
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
            self._save = LazyParsedSave(self._raw)
            self._mtime = mtime
            if p != self._active:
                log.info("Save rotated → %s", p.name)
                self._active = p
            return True
        except Exception as exc:
            log.warning("Save parse error: %s", exc)
            return False

    def _apply_baseline(self) -> None:
        """Au 1er poll : charge (ou capture) la baseline = checks « déjà vrais » à ignorer.
        Indexée par SEED : réutilisée tant que la seed ne change pas (les relances client /
        --reset ne re-snapshotent plus — un re-snapshot en cours de run MANGEAIT les checks
        faits pendant un trou de couverture, constaté 2026-07-13). Au snapshot d'une room EN
        COURS, seuls les checks connus du serveur sont baselinés — le reste sera émis."""
        self._baselined = True
        if self._save is None:
            return
        if self._baseline_path.exists():
            try:
                data = json.loads(self._baseline_path.read_text(encoding="utf-8"))
                ids, seed = (data.get("ids", []), data.get("seed")) \
                    if isinstance(data, dict) else (data, None)   # legacy = liste nue, sans seed
                # Réutilisable si la seed correspond (ou si on n'a pas de contexte serveur —
                # usage hors-AP). Une seed différente / un fichier legacy → re-snapshot.
                if self._server_seed is None or seed == self._server_seed:
                    self._reported.update(int(i) for i in ids)
                    log.info("[Baseline] %d check(s) déjà faits ignorés (run en cours)", len(ids))
                    return
                log.info("[Baseline] seed différente (%s → %s) — re-capture",
                         seed, self._server_seed)
            except Exception:
                pass
        done = [ap_id for fhash, ap_id in _LOC_HASH_TO_AP_ID.items()
                if self._save.get_bool(fhash)]
        if self._server_checked:
            # Room EN COURS : un flag vrai que le serveur ne connaît pas = progression jamais
            # envoyée (crash / client down) → on NE le baseline PAS, il partira au poll suivant.
            missed = [i for i in done if i not in self._server_checked]
            done = [i for i in done if i in self._server_checked]
            if missed:
                log.info("[Baseline] %d check(s) faits hors-couverture seront ÉMIS "
                         "(inconnus du serveur) : %s", len(missed), missed)
        elif done:
            log.warning("[Baseline] room vierge + save déjà entamée : %d check(s) existants "
                        "IGNORÉS pour cette seed (supprime ap_baseline.json pour les émettre)",
                        len(done))
        self._reported.update(done)
        try:
            self._baseline_path.write_text(
                json.dumps({"seed": self._server_seed, "ids": done}), encoding="utf-8")
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
        return self.get_dungeon_counter() >= required_shrine_count

    def get_dungeon_counter(self) -> int:
        """Nombre de sanctuaires réellement terminés : MAX(DungeonClearCounter, nb de flags
        Clear_Dungeon* à 1). Le compteur seul reste à 0 sur certaines saves (constaté
        2026-07-14 : 4 sanctuaires clear, compteur 0) → goal/tracker assis dessus = morts."""
        if self._save is None:
            return 0
        cleared = sum(1 for fid in _SHRINE_FLAG_IDS if self._save.get_bool(fid))
        # « Plateau offert » : les 4 sanctuaires pré-clearés par le rando (InitValue=1) ne
        # comptent pas — le joueur ne peut pas les (re)faire. Le s32 du jeu reste pris tel
        # quel (observé à 0 sur save moddée ; il ne compte pas les pré-clearés).
        init_cleared = sum(1 for fid in _RANDO_INIT_SHRINE_FLAG_IDS if self._save.get_bool(fid))
        return max(self._save.get_s32(_DUNGEON_COUNTER_ID), cleared - init_cleared)

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
        self._last_not_ready_log = 0.0  # rate-limit du log « jeu pas prêt » (pré-tablette/load)
        self._last_companion_full_log = 0.0  # rate-limit « progression en attente d'un slot »

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
        # Live injection (bridge) works any time; the save-file fallback needs idle ET
        # AUCUN processus Cemu (pas seulement bridge décroché — cf. cemu_process_running).
        return (self._bridge is not None and self._bridge.is_attached) \
            or (self._save_is_idle and not cemu_process_running())

    def flush(self) -> list[InjectionSpec]:
        """
        Every poll: reconcile gate flags (delivery force-on + retention) AND deliver
        pending items. Tout passe par le FICHIER save (seule voie qui survit au reload) :
          - flags (paraglider, abilities…) → _enforce_retention force la valeur dans la
            LATEST save chaque poll (rotation-safe) → appliqué au rechargement.
          - poche/compteur/rubis → _inject_pending écrit dans la LATEST save quand elle est
            idle (menu titre) ; différé tant que le joueur est en jeu.
        """
        # Ré-attache/re-localise automatiquement : client lancé avant Cemu, Cemu relancé après
        # un crash, gd_base invalidé (buffer réalloué au load), inventaire absent à l'attach
        # (cinématique d'intro / save neuve — bug « rien livré avant le 1er sanctuaire »).
        # Cooldowns internes → appels sans coût quand tout va bien.
        if self._bridge is not None:
            self._bridge.ensure_attached()
            self._bridge.ensure_live_inventory()
        # Jeu ATTACHÉ mais PAS PRÊT (cinématique pré-tablette Sheikah, load/réallocation en
        # cours) : AUCUNE écriture mémoire — ni livraison, ni retention, ni toast. Tout reste
        # en file et repart seul dès que delivery_ready passe (crash du 2026-07-14 : écritures
        # pendant un reload → corruption de mémoire recyclée → 0xc0000005 Cemu).
        if self._bridge is not None and self._bridge.is_attached \
                and not self._bridge.delivery_ready:
            now = time.monotonic()
            if now - self._last_not_ready_log > 30.0:
                self._last_not_ready_log = now
                log.info("[Mem] jeu pas prêt (pré-tablette Sheikah / load en cours) — "
                         "écritures mémoire en pause, livraisons en file")
            return []
        self._enforce_retention()
        # Orbes : le jeu reverte le compteur → (1) on le maintient EN LIVE chaque poll, (2) on le
        # BANQUE dans la save pour qu'il survive au reload (le live seul ne persiste pas).
        if self._bridge is not None and self._bridge.has_live_inventory:
            self._bridge.maintain_persistent()
        # Bandeau natif « Vous avez gagné <item> » : au plus un par cycle (throttlé en interne).
        if self._bridge is not None and self._bridge.is_attached:
            self._bridge.toast_pump()
        self._bank_spirit_orbs()
        injected = self._inject_pending()
        # Objets-clés companion (paravoile / capacités) : ajoutés APRÈS _inject_pending (buffer
        # relocalisé/stable → pas de doublon comme quand c'était fait avant la relocation).
        self._deliver_companion_pouch()
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
        # Cemu attaché OU simplement PRÉSENT : on n'écrit PAS le fichier (contention → Cemu
        # ne peut plus sauver → crash). L'orbe est maintenu en mémoire (maintain_persistent)
        # et l'autosave de Cemu le persiste. Garde processus : un bridge décroché avec Cemu
        # en vie ne doit jamais ouvrir la voie fichier.
        if self._bridge.is_attached or cemu_process_running():
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

    def _deliver_companion_pouch(self) -> None:
        """Ajoute en LIVE les objets companion : objets-clés (paravoile PlayerStole2, capacités
        Obj_HeroSoul_* type 9) ET les TENUES de région (casque 4 + torse 5 + jambes 6) + l'Arc
        de Lumière (Weapon_Bow_071) — tous alimentés dans _COMPANION_POUCH depuis gate_items.json.
        Sans « écriture save quand attaché », c'est la SEULE voie live ; les flags associés
        (IsGet_Armor_*, mailbox de gate) sont posés par _enforce_retention (reload-gated → le mur
        de région s'ouvre au rechargement). Idempotent (create seulement si absent → pas de
        doublon). Appelé APRÈS _inject_pending (buffer stable/relocalisé)."""
        b = self._bridge
        if not (b and b.is_attached and b.has_live_inventory):
            return
        for ap_id, items in _COMPANION_POUCH.items():
            if ap_id not in self._received:
                continue
            for iname in items:
                if b.live_find_item(iname) is None:
                    info = pouch_item_info(iname) or {}
                    typ = info.get("type", 9)              # défaut objet-clé (type 9)
                    # arme/arc/bouclier : value = durabilité ; armures/objets-clés : 1
                    val = info.get("life", 1) if typ in (0, 1, 3) else 1
                    if b.live_create_item(iname, typ, info.get("sub"), val):
                        log.info("  [Live] %s livré (instantané ; flag associé au rechargement)",
                                 iname)
                        # bandeau natif (nom localisé par le jeu) — la paravoile/les capacités/
                        # tenues passaient par ce chemin SANS toast (constat 2026-07-14)
                        b.toast_enqueue(iname, 1)
                    elif getattr(b, "_last_create_overflow", False):
                        # PROGRESSION (Master Sword, Arc de Lumière…) jamais convertie en
                        # rubis : l'objet attend qu'un slot se libère (retenté chaque cycle).
                        # Les FLAGS (goal, murs) sont déjà posés par la rétention.
                        now = time.monotonic()
                        if now - self._last_companion_full_log > 60.0:
                            self._last_companion_full_log = now
                            log.info("  [Live] %s en ATTENTE : onglet plein — jette/casse un "
                                     "équipement pour libérer un slot (retenté en continu)", iname)

    @staticmethod
    def _spec_coalescible(spec: InjectionSpec) -> bool:
        """True si toutes les actions du spec s'ADDITIONNENT proprement : compteurs s32
        (rubis, orbes), stacks pouch (flèches/matériaux/nourriture simple, items gérés
        par le jeu) et max-stats (réceptacles/fioles — le planificateur gère n unités +
        overflow). Équipement (1 nœud chacun) et plats (CookData) restent unitaires."""
        if not spec.actions:
            return False
        for a in spec.actions:
            if isinstance(a, (InjectionSpec.AddS32, InjectionSpec.AddMaxStat)):
                continue
            if isinstance(a, InjectionSpec.AddPouchItem):
                info = pouch_item_info(a.item_name)
                typ = info.get("type") if info else None
                if a.item_name in _GAME_MANAGED_POUCH or typ in _STACKABLE_TYPES:
                    continue
            return False
        return True

    @staticmethod
    def _scaled_spec(spec: InjectionSpec, n: int) -> InjectionSpec:
        """Spec équivalent à n livraisons du même item (quantités × n)."""
        if n <= 1:
            return spec
        acts = [dataclasses.replace(a, amount=a.amount * n)
                if isinstance(a, (InjectionSpec.AddS32, InjectionSpec.AddPouchItem,
                                  InjectionSpec.AddMaxStat)) else a
                for a in spec.actions]
        return dataclasses.replace(spec, ap_item_name=f"{spec.ap_item_name} ×{n}",
                                   actions=acts)

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
        # COALESCENCE (2026-07-14, demande user) : les doublons EMPILABLES/compteurs de la
        # file (flèches, matériaux, rubis, orbes, réceptacles/fioles) partent EN UNE opération
        # à quantité cumulée — la rafale release-all passait 60 « Arrows x10 » un par un
        # (60 écritures + 60 toasts). En cas d'échec, les n entrées restent en file
        # (granularité d'origine préservée pour les relances).
        counts: dict[int, int] = {}
        ordered: list[dict] = []
        for entry in self._queue:
            spec = _get_spec(entry["ap_item_id"])
            if self._spec_coalescible(spec):
                if entry["ap_item_id"] in counts:
                    counts[entry["ap_item_id"]] += 1
                    continue
                counts[entry["ap_item_id"]] = 1
            ordered.append(entry)
        for entry in ordered:
            n = counts.get(entry["ap_item_id"], 1)
            spec = self._scaled_spec(_get_spec(entry["ap_item_id"]), n)
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
                remaining.extend([entry] * n)
                continue
            # Livraison LIVE (instantanée + persistante) : live_create_item crée un VRAI
            # nœud PouchItem runtime que le jeu sérialise au save -> survit au reload (validé
            # en jeu). On l'utilise dès que Cemu est attaché avec l'inventaire localisé ;
            # sinon (pas de Cemu) on écrit le FICHIER-save quand il est idle (menu titre).
            delivered = False
            if self._bridge is not None and self._bridge.has_live_inventory:
                delivered = self._apply_actions_memory(spec, p)
            # Voie FICHIER seulement si AUCUN processus Cemu ne tourne (écrire game_data.sav
            # pendant que Cemu tourne bloque ses autosaves → save incohérente → crash).
            # ⚠️ `is_attached` NE SUFFIT PAS : bridge décroché ≠ Cemu fermé (blip d'attache
            # pendant un chargement → crash constaté le 2026-07-09) → garde PROCESSUS.
            attached = self._bridge is not None and self._bridge.is_attached
            if not delivered and self._save_is_idle and not attached \
                    and not cemu_process_running():
                delivered = self._apply_actions_savefile(p, spec)
            if delivered:
                injected.append(spec)
                heavy += 1
            else:
                remaining.extend([entry] * n)
                if not (self._bridge is not None and self._bridge.has_live_inventory) \
                        and not self._save_is_idle:
                    deferred += 1
        if deferred:
            if self._bridge is not None and self._bridge.is_attached:
                log.info("[Pending] %d objet(s) en attente — inventaire live pas encore "
                         "localisé (retry auto ; charge une save si tu es au menu/cinématique).",
                         deferred)
            else:
                log.info("[Pending] %d objet(s) en attente — lance Cemu/BotW (admin) ou "
                         "passe au menu titre.", deferred)
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
        toast_actor: Optional[tuple] = None          # (actor, qty) livré → bandeau natif
        for action in spec.actions:
            if isinstance(action, InjectionSpec.SetFlag):
                ok = self._bridge.write_flag(action.flag_name, 1)
                if ok:
                    log.info("  [Mem] %s  %s = 1", spec.ap_item_name, action.flag_name)
                    # convention BotW : IsGet_<actor> → l'actor localisable du bandeau
                    if toast_actor is None and action.flag_name.startswith("IsGet_"):
                        toast_actor = (action.flag_name[len("IsGet_"):], 1)
                else:
                    all_ok = False

            elif isinstance(action, InjectionSpec.AddS32):
                if action.flag_name == "CurrentRupee" and self._bridge.has_live_inventory:
                    new_val = self._bridge.live_add_rupees(action.amount)
                    ok = new_val is not None
                else:
                    ok = self._bridge.add_s32_flag(action.flag_name, action.amount)
                if ok and action.flag_name == "CurrentRupee" and action.amount > 0:
                    # bandeau natif pour les lots de rubis (pas d'actor résolvable → texte)
                    self._bridge.toast_enqueue_text(
                        f"Vous avez reçu {action.amount} rubis.")
                if not ok:
                    all_ok = False

            elif isinstance(action, InjectionSpec.AddPouchItem):
                # qty-bump live = SÛR + persiste (item déjà compté par le jeu). La CRÉATION
                # d'un nouveau nœud (live_create_item) est gardée derrière _LIVE_CREATE_ENABLED
                # car sans mCount++ elle corrompt la save. Si désactivé / item absent, échec ->
                # _inject_pending bascule sur la voie save-fichier (sûre, au menu titre).
                info = pouch_item_info(action.item_name)
                typ = info.get("type") if info else None
                if action.item_name in _GAME_MANAGED_POUCH:
                    # Item géré par le JEU (compteur d'orbes Obj_DungeonClearSeal) : ne JAMAIS créer
                    # un faux nœud — le jeu le réconcilie à la sortie de sanctuaire et CRASH. On bump
                    # seulement s'il existe déjà ; la persistance passe par DungeonClearSealNum
                    # (add_s32) + le banking save. Compté LIVRÉ même si absent, sinon la spec se
                    # rejoue et re-incrémente le compteur en boucle (double comptage).
                    self._bridge.live_add_item_qty(action.item_name, action.amount)
                    ok = True
                elif typ is not None and typ not in _STACKABLE_TYPES:
                    # ÉQUIPEMENT UNIQUE (arme/arc/bouclier/armure) : JAMAIS de bump (ça monterait la
                    # durabilité) → toujours créer un NOUVEAU slot. Si le pool est épuisé, le create
                    # échoue proprement et l'item est reporté (livré après régénération du pool).
                    ok = bool(_LIVE_CREATE_ENABLED and self._bridge.live_create_item(
                        action.item_name, typ, info.get("sub"), action.amount))
                    # ONGLET PLEIN (cap *PorchStockNum) : un filler d'équipement ne peut PAS
                    # attendre qu'un slot se libère (rafale release-all = des dizaines au-delà
                    # du cap → retry infini). Converti en rubis, l'item AP reste « reçu ».
                    if not ok and getattr(self._bridge, "_last_create_overflow", False):
                        ok = self._bridge.live_add_rupees(_GEAR_OVERFLOW_RUPEES) is not None
                        if ok:
                            log.info("  [Live] %s — onglet plein → converti en %d rubis",
                                     spec.ap_item_name, _GEAR_OVERFLOW_RUPEES)
                            self._bridge.toast_enqueue_text(
                                f"{spec.ap_item_name} converti en {_GEAR_OVERFLOW_RUPEES} rubis.")
                            continue           # bandeau texte posé — pas de toast actor
                        all_ok = False
                        continue
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
                    # 1er item d'une catégorie VIDE : le nœud est créé + sérialisé (persiste, JAMAIS
                    # perdu) mais la grille UI ne le dessine qu'au prochain rechargement (couche
                    # ksys::ui). On le signale clairement pour que ça ne ressemble pas à une perte.
                    if getattr(self._bridge, "_last_create_empty_cat", False) \
                            and typ is not None and typ not in _STACKABLE_TYPES:
                        log.info("  [Live] %s  +%d %s (livré+persisté ; catégorie vide → VISIBLE au "
                                 "prochain rechargement)", spec.ap_item_name, action.amount, action.item_name)
                    else:
                        log.info("  [Live] %s  +%d %s (instantané)",
                                 spec.ap_item_name, action.amount, action.item_name)
                    self._bridge._last_create_empty_cat = False
                    if toast_actor is None:
                        # ÉQUIPEMENT (arme/arc/bouclier/armure) : `amount` = DURABILITÉ, pas
                        # une quantité → bandeau sans « xN » (bug « Boomerang x18 » 2026-07-14).
                        qty = max(1, action.amount) if typ in _STACKABLE_TYPES else 1
                        toast_actor = (action.item_name, qty)
                else:
                    all_ok = False

            elif isinstance(action, InjectionSpec.AddCookedItem):
                # Plat/potion (type 8 + bloc CookData) : LIVE uniquement — chaque assiette
                # est un nœud séparé (les plats ne s'empilent jamais en jeu). Échec (pool
                # épuisé, pas de template type 8...) → report en file, jamais de voie fichier.
                # sub VÉRIFIÉ sur nœuds naturels (2026-07-11) : plats CUISINÉS Item_Cook_* =
                # sub 0x8 ; grillés Item_Roast*/RoastFish = sub 0xA (la note de juin disait
                # l'inverse — corrigée).
                ok = bool(_LIVE_CREATE_ENABLED) and not self._bridge.pool_exhausted
                if ok:
                    for _ in range(max(1, action.amount)):
                        ok = ok and self._bridge.live_create_item(
                            action.item_name, 8, 0x8, 1, cook_data=action.cook_data)
                if ok:
                    log.info("  [Live] %s  %s ×%d (plat, instantané)",
                             spec.ap_item_name, action.item_name, max(1, action.amount))
                    self._bridge._last_create_empty_cat = False
                    if toast_actor is None:
                        toast_actor = (action.item_name, max(1, action.amount))
                else:
                    all_ok = False

            elif isinstance(action, InjectionSpec.AddMaxStat):
                # Réceptacle de Cœur / Fiole d'Endurance : ↑ le max persistant (reload-gated)
                # jusqu'au plafond du jeu ; overflow → rubis (live, portefeuille câblé).
                if not self._deliver_max_stat(action, spec, memory=True):
                    all_ok = False

            else:
                log.debug("Action %s not implemented for memory injection", type(action).__name__)
        if toast_actor is not None:
            self._bridge.toast_enqueue(*toast_actor)
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

            elif isinstance(action, InjectionSpec.AddCookedItem):
                # Le bloc CookData ne vit que dans le nœud pouch runtime → pas de voie
                # fichier (un plat créé en save sortirait à 0 cœur). ÉCHEC explicite pour
                # que la spec reste en file et parte en LIVE au prochain attach.
                all_ok = False

            elif isinstance(action, InjectionSpec.AddMaxStat):
                # Réceptacle/Fiole hors-ligne (menu titre) : ↑ le max dans la save + overflow
                # rubis dans CurrentRupee (tout reload-gated). Voir _deliver_max_stat.
                if not self._deliver_max_stat(action, spec, memory=False, p=p):
                    all_ok = False

            else:
                log.debug("Action %s skipped (save-file injection)",
                          type(action).__name__)
        return all_ok

    def _deliver_max_stat(self, action, spec, *, memory: bool, p: Optional[Path] = None) -> bool:
        """Livre un Réceptacle de Cœur / Fiole d'Endurance : monte le MAX persistant (flag
        gamedata, reload-gated) jusqu'au plafond DUR du jeu ; toute unité au-delà du plafond
        (joueur déjà au max) devient un don de `overflow_rupees` rubis. `memory=True` passe par
        le bridge (Cemu attaché) ; sinon par la save-fichier. SÉCURITÉ (constantes non encore
        confirmées in-game, cf. _MAX_STAT) : si le flag est absent OU sa valeur hors plage
        plausible, on ne CORROMPT rien — on convertit toute la réception en rubis et on logue.
        Retourne True si livré (stat ± rubis), False si à reporter."""
        cfg = _MAX_STAT.get(action.stat)
        if cfg is None:
            log.warning("[MaxStat] type inconnu %r — ignoré", action.stat)
            return True                       # inconnu → on ne bloque pas la file
        amount = max(1, int(action.amount))
        is_f32 = cfg["kind"] == "f32"

        # ── lecture du max courant ──
        if memory:
            cur = (self._bridge.read_flag_f32(cfg["flag"]) if is_f32
                   else self._bridge.read_flag(cfg["flag"]))
            if cur is not None and not is_f32:
                cur = struct.unpack(">i", struct.pack(">I", cur & 0xFFFFFFFF))[0]  # s32 signé
        else:
            if p is None:
                return False
            try:
                save = parse(_read_shared(p))
                fid = crc32_id(cfg["flag"])
                if not save.has_id(fid):                 # get_s32 renvoie 0 si absent → piège :
                    cur = None                           # on distingue explicitement l'absence
                else:
                    raw = save.get_s32(fid)
                    cur = (struct.unpack(">f", struct.pack(">I", raw & 0xFFFFFFFF))[0]
                           if is_f32 else raw)
            except Exception:
                cur = None

        # flag introuvable / valeur aberrante → repli SÛR = tout en rubis (jamais de write hasardeux)
        plausible = cur is not None and cfg["lo"] <= cur <= cfg["hi"]
        if not plausible:
            rupees = amount * action.overflow_rupees
            log.warning("[MaxStat] %s : max '%s' introuvable/hors plage (lu=%r) — converti en "
                        "%d rubis (aucune écriture du flag)",
                        spec.ap_item_name, cfg["flag"], cur, rupees)
            ok = self._award_rupees(rupees, memory=memory, p=p)
            if ok and memory:
                self._bridge.toast_enqueue_text(
                    f"{spec.ap_item_name} converti en {rupees} rubis.")
            return ok

        new_val, applied, overflow = _plan_max_stat(cur, cfg["per_unit"], cfg["cap"], amount)

        ok = True
        if applied > 0:
            flags = [cfg["flag"]] + list(cfg.get("also", []))
            if memory:
                for fn in flags:
                    ok = ok and (self._bridge.write_flag_f32(fn, new_val) if is_f32
                                 else self._bridge.write_flag(fn, int(new_val) & 0xFFFFFFFF))
            else:
                bits = (struct.unpack(">I", struct.pack(">f", new_val))[0] if is_f32
                        else int(new_val) & 0xFFFFFFFF)
                for fn in flags:
                    ok = ok and _write_flag_to_save(p, crc32_id(fn), bits)
            if ok:
                log.info("  [MaxStat] %s : +%d %s (max %s %s→%s, RECHARGE pour appliquer)",
                         spec.ap_item_name, applied, action.stat, cfg["flag"],
                         _fmt_stat(cur, is_f32), _fmt_stat(new_val, is_f32))
                if memory:
                    # bandeau natif : nom localisé par le jeu (actor du réceptacle / de la fiole)
                    actor = "Obj_HeartUtuwa_A_01" if action.stat == "heart" \
                        else "Obj_StaminaUtuwa_A_01"
                    self._bridge.toast_enqueue(actor, applied)
        if ok and overflow > 0:
            rupees = overflow * action.overflow_rupees
            log.info("  [MaxStat] %s : %d unité(s) au-delà du plafond → +%d rubis",
                     spec.ap_item_name, overflow, rupees)
            ok = self._award_rupees(rupees, memory=memory, p=p)
            if ok and memory:
                self._bridge.toast_enqueue_text(
                    f"{spec.ap_item_name} au max — converti en {rupees} rubis.")
        return ok

    def _award_rupees(self, amount: int, *, memory: bool, p: Optional[Path] = None) -> bool:
        """Crédite `amount` rubis : live (portefeuille câblé) si Cemu attaché, sinon dans la
        save (CurrentRupee, reload-gated)."""
        if amount <= 0:
            return True
        if memory and self._bridge is not None and self._bridge.has_live_inventory:
            return self._bridge.live_add_rupees(amount) is not None
        if not memory and p is not None:
            try:
                cur = parse(_read_shared(p)).get_s32(crc32_id("CurrentRupee"))
                return _write_flag_to_save(p, crc32_id("CurrentRupee"),
                                           max(0, min(999999, cur + amount)) & 0xFFFFFFFF)
            except Exception:
                return False
        return False

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
        # ── Cemu PRÉSENT mais bridge décroché (boot, chargement, réallocation…) : ne JAMAIS
        # toucher le fichier — on retentera l'attache au prochain poll. (Crash du 2026-07-09.)
        if cemu_process_running():
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
