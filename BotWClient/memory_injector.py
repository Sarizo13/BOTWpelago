"""
CemuMemoryInjector — injection directe dans la RAM de Cemu.

Principe : game_data.sav est chargé en mémoire par BotW dans le même format
que sur disque (flat sorted array). On cherche le header de 12 bytes pour
localiser le buffer, puis on réutilise exactement la même logique que pour
l'injection fichier.

Avantage : les items apparaissent instantanément en jeu, sans reload.

Prérequis :
- Windows uniquement (ReadProcessMemory / WriteProcessMemory)
- cemu.exe doit tourner avec BotW chargé
- Si Cemu tourne en admin, ce script doit l'être aussi
"""
from __future__ import annotations

import ctypes
import json
import logging
import struct
import threading
import time
import zlib
from collections import deque
from ctypes import wintypes
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("BotWClient.MemInjector")

# ── Win32 constants ───────────────────────────────────────────────────────────

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_OPERATION      = 0x0008
PROCESS_VM_READ           = 0x0010
PROCESS_VM_WRITE          = 0x0020
PROCESS_ALL_RW = (
    PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION |
    PROCESS_VM_READ | PROCESS_VM_WRITE
)

MEM_COMMIT   = 0x1000
PAGE_GUARD   = 0x100
PAGE_NOACCESS = 0x01
PAGE_READONLY = 0x02
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE = 0x10
PAGE_EXECUTE_READ = 0x20
PAGE_READWRITE = 0x04
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_WRITECOPY = 0x80

TH32CS_SNAPPROCESS   = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_USER_ADDR        = 0x00007FFFFFFFFFFF
ULONG_PTR            = ctypes.c_size_t

# BotW 1.5.0 WiiU — taille connue du buffer game_data
SAVE_SIZE    = 1_027_208  # 12 + 128399 * 8 + 4
SAVE_HEADER  = b'\x00\x00\x47\x1B\xFF\xFF\xFF\xFF\x00\x00\x00\x01'
SCAN_CHUNK   = 32 * 1024 * 1024  # 32 MiB par lecture

# ── Inventaire live (PauseMenuDataMgr) ─────────────────────────────────────────
# Patterns portes depuis botw_editor (App.cs findRupeesAddressInMemory / FindItemsInMemory)
# -1 = wildcard. rupeesAddress = position du match + len(pattern)
_RUPEE_PATTERN = [16, -1, -1, -1, 1, 7, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 15, 66, 63]
# Item PouchItem : 10 ?? ?? ?? 00 00 00 40, items espaces de 544 bytes
_ITEM_STRIDE     = 544
_ITEM_PREFIXES   = ("Item_", "Weapon_", "Armor_", "Animal_", "Obj_", "Material_")
_EARLY_EXIT_SCORE = 5
_INV_SCAN_CHUNK   = 16 * 1024 * 1024
# prefer_free : nb MAX de vérifications "ce buffer a-t-il un nœud libre ?" par scan. Chaque check
# coûte des centaines de lectures mémoire → plafonné pour ne pas monopoliser le thread (keepalive AP).
_FREE_NODE_CHECK_CAP = 8
# Idem pour la validation d'ancre rubis d'un candidat pouch (dérive base + compare au flagobj) —
# plafonné pour la même raison ; au-delà on retombe sur la sélection historique (score/nœud libre).
_ANCHOR_CHECK_CAP = 8
# Items PouchItem GÉRÉS PAR LE JEU : ne JAMAIS créer un nœud live (compteur d'orbes) — un faux
# nœud fait crasher le jeu à la réconciliation d'inventaire (sortie de sanctuaire). Bump seulement.
_NO_LIVE_CREATE = {"Obj_DungeonClearSeal"}
# Types de poche EMPILABLES (on incrémente la quantité si déjà présent) : flèches, matériaux,
# nourriture. Les autres (armes 0, arcs 1, boucliers 3, armures 4-6, objets-clés 9) sont UNIQUES.
_STACKABLE_TYPES = {2, 7, 8}
# Pool de nœuds PouchItem libres épuisé → on ne re-tente une création qu'après ce délai (au lieu
# de marteler chaque poll, ou de bloquer DÉFINITIVEMENT jusqu'à un reload). Laisse les nouveaux
# nœuds libres (apparus quand le joueur ramasse/le jeu agrandit la poche) être utilisés.
_POOL_RETRY_COOLDOWN = 6.0
# Rubis : divergence forte entre le compteur lu et notre dernière écriture — depuis le vrai
# portefeuille (validé structurellement à chaque write, cf. _wallet_valid) ce n'est PLUS un
# signe d'adresse périmée mais une dépense/recette légitime du joueur → on LOG seulement
# (l'ancienne garde bloquait le strip ; avec le miroir AOB périmable elle évitait une
# corruption type 300 -> 2, désormais impossible par construction).
_RUPEE_STALE_DROP  = 50
# Ré-attach automatique (ensure_attached) : cooldown entre deux tentatives. Le scan gd complet
# coûte quelques secondes (thread mémoire dédié) → on ne martèle pas pendant le boot/menu titre.
_ATTACH_RETRY_COOLDOWN = 15.0
# Retry de localisation d'inventaire quand on est ATTACHÉ mais SANS inventaire (attach pendant
# la cinématique d'intro / save neuve : la poche n'existe pas encore). Sans retry, AUCUNE
# livraison ne partait jusqu'à un redémarrage du client (bug « rien avant le 1er sanctuaire »).
_INV_LOCATE_RETRY_COOLDOWN = 20.0
# Capacité des onglets d'ÉQUIPEMENT : flags gamedata (base vanilla 8/5/4, montent avec les
# bénédictions Korok). Créer un nœud AU-DELÀ du cap = onglet dans un état illégal →
# inventaire désorganisé puis FREEZE (constaté 2026-07-14, rafale release-all).
_TAB_CAP_FLAGS = {0: "WeaponPorchStockNum", 1: "BowPorchStockNum", 3: "ShieldPorchStockNum"}
_TAB_CAP_DEFAULTS = {0: 8, 1: 5, 3: 4}

# ── Vrai portefeuille (gdt live, v208) ─────────────────────────────────────────
# Le jeu tient TROIS copies de CurrentRupee (prouvé 2026-07-10, tools/hunt_wallet.py puis
# session recon : write 55555 -> achat -60 -> écran 55495 sur la copie STORAGE) :
#   1. l'entrée {hash, value} du buffer game_data sérialisé (gd_base) — persistance ;
#   2. l'objet gdt::Flag<s32> (vtable guest 0x102984C8) : value @+0x14, hash @+0x18.
#      C'est LUI que l'AOB _RUPEE_PATTERN trouve (« miroir », alimente le HUD) ;
#   3. l'entrée du STORAGE s32 live {typeinfo guest 0x10297C88, ptr flagobj, value} —
#      la copie AUTORITAIRE (le jeu débite/crédite ICI ; 2792 entrées stride 12).
# Localisateur STABLE : hash crc32("CurrentRupee") -> flagobj (vérif vtable) -> backref de
# son adresse GUEST dans le storage (vérif typeinfo) -> value = backref+4. Les constantes
# guest sont stables v208 ; les adresses host restent session-specific (rescan à l'attach).
_GDT_FLAG_S32_VTABLE    = 0x102984C8
_GDT_S32_STORE_TYPEINFO = 0x10297C88
_RUPEE_FLAG_HASH        = 0x23149BF8      # zlib.crc32(b"CurrentRupee")
_FLAG_S32_OFF_VALUE     = 0x14            # value dans l'objet gdt::Flag<s32>
_FLAG_S32_OFF_HASH      = 0x18            # hash CRC32 du nom dans l'objet
# Les adresses GUEST (Wii U) sont des u32 : host = heap_base + guest ⇒ guest ∈ [0, 4 Gio).
# Un heap_base PÉRIMÉ (dérivé d'un buffer post-réallocation) décale les guests hors de cette
# plage → sert d'ancre pour DÉTECTER une base invalide (cf. _flagobj_guest_ok).
_GUEST_MAX = 0x100000000

# Bloc CookData des PouchItem type 8 (offsets nœud host-cadré ; décodé 2026-07-10 via
# tools/dump_cook.py sur 4 plats live) :
_COOK_OFF_HEAL     = 0x68   # soin (quarts de cœur, s32)
_COOK_OFF_DURATION = 0x6C   # durée d'effet (secondes, s32)
_COOK_OFF_PRICE    = 0x70   # prix de vente (s32)
_COOK_OFF_EFFECT   = 0x74   # type d'effet (f32 CookEffectId ; -1.0 = aucun)
_COOK_OFF_LEVEL    = 0x78   # niveau/quantité d'effet (f32)

# ── ctypes bindings ───────────────────────────────────────────────────────────

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

_k32.OpenProcess.restype  = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

_k32.CloseHandle.restype  = wintypes.BOOL
_k32.CloseHandle.argtypes = [wintypes.HANDLE]

_k32.ReadProcessMemory.restype  = wintypes.BOOL
_k32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
]
_k32.WriteProcessMemory.restype  = wintypes.BOOL
_k32.WriteProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
]
_k32.VirtualQueryEx.restype  = ctypes.c_size_t
_k32.VirtualQueryEx.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
]
_k32.CreateToolhelp32Snapshot.restype  = wintypes.HANDLE
_k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress",       ctypes.c_void_p),
        ("AllocationBase",    ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("__pad",             wintypes.DWORD),
        ("RegionSize",        ctypes.c_size_t),
        ("State",             wintypes.DWORD),
        ("Protect",           wintypes.DWORD),
        ("Type",              wintypes.DWORD),
        ("__pad2",            wintypes.DWORD),
    ]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize",              wintypes.DWORD),
        ("cntUsage",            wintypes.DWORD),
        ("th32ProcessID",       wintypes.DWORD),
        ("th32DefaultHeapID",   ULONG_PTR),
        ("th32ModuleID",        wintypes.DWORD),
        ("cntThreads",          wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase",      ctypes.c_long),
        ("dwFlags",             wintypes.DWORD),
        ("szExeFile",           ctypes.c_wchar * 260),
    ]


_k32.Process32FirstW.restype  = wintypes.BOOL
_k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_k32.Process32NextW.restype   = wintypes.BOOL
_k32.Process32NextW.argtypes  = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]


def _winerr(msg: str) -> OSError:
    code = ctypes.get_last_error()
    return OSError(code, f"{msg}: [{code}] {ctypes.FormatError(code)}")


# ── Process discovery ─────────────────────────────────────────────────────────

def _find_pid(exe_name: str = "cemu.exe") -> Optional[int]:
    snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        target = exe_name.lower()
        ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == target:
                return int(entry.th32ProcessID)
            ok = _k32.Process32NextW(snap, ctypes.byref(entry))
        return None
    finally:
        _k32.CloseHandle(snap)


def cemu_process_running(exe_name: str = "cemu.exe") -> bool:
    """True si un processus Cemu EXISTE — garde ABSOLUE contre toute écriture de
    game_data.sav pendant que le jeu tourne. `bridge.is_attached` ne suffit PAS :
    un blip d'attache (boot, écran de chargement, réallocation) laisse le bridge
    décroché alors que Cemu tourne → la voie fichier écrirait → collision avec les
    autosaves → save incohérente → CRASH (constaté en jeu le 2026-07-09)."""
    try:
        return _find_pid(exe_name) is not None
    except Exception:
        return True      # doute → on suppose Cemu présent : interdiction d'écrire le fichier


# ── CemuMemoryBridge ──────────────────────────────────────────────────────────

class CemuMemoryBridge:
    """
    Ouvre cemu.exe en lecture/écriture mémoire et localise le buffer game_data.

    Utilisation :
        bridge = CemuMemoryBridge()
        bridge.attach()          # OpenProcess + scan
        bridge.write_flag(...)   # injection immédiate
        bridge.detach()
    """

    def __init__(self, exe_name: str = "cemu.exe",
                 template_store: Optional[Path] = None) -> None:
        self.exe_name   = exe_name
        self._pid:      Optional[int]   = None
        self._handle:   Optional[int]   = None
        self._gd_base:  Optional[int]   = None  # adresse host du début du buffer
        self._rupees_addr: Optional[int] = None  # adresse live du compteur de rubis
        self._inv_base:    Optional[int] = None  # adresse live du tableau PouchItem
        self._playerinfo:  Optional[int] = None  # singleton PlayerInfo (host), via vtable
        self._prev_hp:     Optional[int] = None  # dernier HP courant lu (détection de mort)
        self._last_inv_relocate: float = 0.0     # cooldown re-localisation inventaire
        self._last_base_warn:    float = 0.0     # rate-limit du warning "base douteuse"
        self._last_wallet_warn:  float = 0.0     # rate-limit du warning "flagobj hors mapping guest"
        self._pool_exhausted:    bool  = False   # plus de nœud libre → créations impossibles
        self._pool_exhausted_at: float = 0.0     # instant du dernier épuisement (retry après cooldown)
        self._last_freenode_warn: float = 0.0    # rate-limit du warning "aucun nœud libre"
        self._last_create_empty_cat = False      # dernier live_create_item : 1er item d'une catégorie VIDE ? (visible au reload)
        self._rupee_shadow: Optional[int] = None # dernière valeur de rubis qu'on a ÉCRITE (log de divergence)
        self._wallet_addr: Optional[int] = None    # VRAI portefeuille : value de l'entrée storage gdt s32
        self._wallet_flagobj: Optional[int] = None # objet gdt::Flag<s32> CurrentRupee (host) — miroir HUD
        self._heap_base: Optional[int] = None      # mapping guest->host (fixe pour la vie du process)
        # Identité du buffer gd VIVANT : les 16 premiers flag_ids (constants pour une save BotW —
        # le SET de flags ne change jamais, seules les valeurs bougent). Si le jeu RÉALLOUE le
        # buffer (load, nouvelle partie), l'ancien est libéré/réutilisé → header/canari cassés →
        # on INVALIDE tout au lieu d'écrire dans de la mémoire recyclée (corruption heap → crash
        # Cemu différé, constaté « avant menu » / « cinématique d'intro » le 2026-07-13).
        self._gd_canary: Optional[bytes] = None
        self._gd_invalid_logged = False          # log d'invalidation émis une fois par épisode
        self._last_attach_try: float = 0.0       # cooldown ensure_attached
        self._last_inv_locate_try: float = 0.0   # cooldown ensure_live_inventory
        # Ancrage STATIQUE de la poche (fix crash 2026-07-14) : le scan AOB peut se verrouiller
        # sur une COPIE freed de la poche (staging de save) — un splice y part « dans le vide »
        # puis corrompt la mémoire recyclée par le jeu (liste pouch massacrée, tablette Sheikah
        # perdue, 0xc0000005 au reload — prouvé par le diff des autosaves du run du 14/07).
        # Remède : après UNE localisation VALIDÉE, on résout par backref un pointeur STATIQUE
        # (section data guest 0x10xxxxxx, l'équivalent du sInstance du gestionnaire de poche)
        # qui désigne le buffer vivant. Chaque accès poche RELIT ce pointeur : on suit toujours
        # la poche vivante, une copie freed n'est plus adressable par construction.
        self._pouch_static_host: Optional[int] = None  # adresse HOST du slot statique (constante/process)
        self._pouch_buf_off: Optional[int] = None      # inv_guest − valeur du slot (offset dans l'objet)
        self._pouch_static_val: Optional[int] = None   # dernière valeur suivie (détection de mouvement)
        self._last_inv_refresh: float = 0.0            # cooldown du refresh par pointeur statique
        self._last_refresh_ok: bool = False            # dernier verdict du refresh (rejoué au cooldown)
        # Tablette Sheikah vue en poche : tant qu'elle n'y est pas (cinématique d'intro, tout
        # début de partie), AUCUNE écriture mémoire — le jeu initialise/réalloue agressivement.
        # Re-vérifiée après chaque invalidation gd (load / nouvelle partie).
        self._slate_seen: bool = False
        # Dernier live_create_item refusé pour ONGLET PLEIN (cap *PorchStockNum) : l'appelant
        # convertit le filler en rubis au lieu de retenter en boucle. + rate-limit du log.
        self._last_create_overflow: bool = False
        self._last_capfull_warn: float = 0.0
        # Anti-course RAMASSAGE (crashs des 7e/8e runs : le jeu crashe en insérant un ramassage
        # dans une liste que nos splices viennent de toucher) : (a) fenêtre CALME — pas de
        # création dans le même cycle qu'un changement de poche non provoqué par nous ;
        # (b) INTÉGRITÉ — liste vérifiée avant chaque batch ; incohérente → créations
        # SUSPENDUES jusqu'au prochain rechargement (le jeu reconstruit une liste propre).
        self._last_pouch_sig: Optional[tuple] = None
        self._creates_suspended: bool = False
        self._suspend_logged: bool = False
        self._last_integrity_check: float = 0.0
        # Qty cibles des items LIVRÉS cette rafale. BotW restaure les nœuds PRÉEXISTANTS à leur
        # qty d'origine lors d'une réallocation (les bumps live sont perdus, seules les créations
        # survivent) → on ré-assert ces cibles jusqu'à stabilisation. Effacé quand la file vide.
        self._qty_targets: dict[str, int] = {}
        # Cibles PERSISTANTES (jamais oubliées) : compteurs que le jeu reverte en continu — les
        # Spirit Orbs (pouch Obj_DungeonClearSeal + gamedata DungeonClearSealNum). Contrairement à
        # un stack de nourriture (consommable → on oublie la cible), un orbe reçu d'AP doit tenir.
        # Cumulatif (max) : chaque orbe = +1 par-dessus la valeur déjà maintenue.
        self._persistent_qty: dict[str, int] = {}   # item_id pouch -> qty mini à maintenir
        self._seal_target: Optional[int] = None      # DungeonClearSealNum (gamedata) mini à maintenir
        # Cache local des templates PouchItem (par type) — survit aux sessions et permet
        # la création live même quand l'inventaire courant n'a aucun item du même type.
        self._template_store = template_store or (
            Path.home() / ".botwpelago" / "pouch_templates.json")
        self._templates: dict[str, dict] = self._load_templates()
        # Table {nom_item: sortKey} (ActorInfo, via tools/build_sort_keys.py) : le pouch est trié
        # par sortKey au sein d'une catégorie → on ancre un nouvel item après le dernier nœud dont
        # le (type, sortKey) est ≤ le sien (position triée exacte, sinon inventaire désorganisé = crash).
        self._sort_keys: dict[str, int] = self._load_sort_keys()
        # Toast natif « item reçu » (file du HUD, docs/status.md §6c — validé in-game 2026-07-12)
        self._toast_reqmgr: Optional[int] = None      # request manager du HUD (guest, session)
        # redirection MSBT : None = pas préparée ; {} = introuvable (texte vanilla) ;
        # sinon {entry: addr table, entry_val: offset custom, victim: addr zone,
        #        suffix: addr du suffixe qty, budget: octets dispo}
        self._toast_msbt: Optional[dict] = None
        self._toast_last_push: float = 0.0            # throttle (~1 bandeau / 4 s)
        # entrées : {"actor_name": str, "qty": int} (item reçu, nom localisé par le jeu)
        #        ou {"text": str} (texte libre, ex. « X envoyé à Y. »)
        self._toast_pending: deque[dict] = deque(maxlen=20)
        self._toast_prep_thread: Optional[threading.Thread] = None  # heap_base + MSBT

    @staticmethod
    def _load_sort_keys() -> dict[str, int]:
        p = Path(__file__).resolve().parent.parent / "data" / "item_sort_keys.json"
        try:
            return {str(k): int(v) for k, v in json.loads(p.read_text(encoding="utf-8")).items()}
        except Exception:
            return {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def attach(self) -> bool:
        """Ouvre le process et localise game_data en mémoire. Retourne True si OK."""
        self._pid = _find_pid(self.exe_name)
        if self._pid is None:
            log.warning("[Mem] %s introuvable — injection save-file uniquement", self.exe_name)
            return False
        h = _k32.OpenProcess(PROCESS_ALL_RW, False, self._pid)
        if not h:
            log.warning("[Mem] OpenProcess echec (pid=%d) — admin requis si Cemu l'est", self._pid)
            return False
        self._handle = h
        self._gd_base = self._scan_for_gamedata()
        if self._gd_base is None:
            log.warning("[Mem] game_data buffer introuvable en memoire")
            return False
        self._snapshot_gd_canary()
        log.info("[Mem] game_data localise @ 0x%012X (pid=%d)", self._gd_base, self._pid)
        self._locate_live_inventory()
        self._auto_capture_templates()
        return True

    def ensure_attached(self) -> bool:
        """(Ré)attache automatiquement, avec cooldown — sûr d'appeler à chaque cycle.
        Couvre : client lancé avant Cemu, Cemu relancé après un crash, buffer gd RÉALLOUÉ
        par le jeu (load / nouvelle partie → gd_base invalidé par le canari). Sans ça, un
        gd_base perdu bloquait TOUTE livraison jusqu'au redémarrage du client."""
        if self.is_attached:
            return True
        now = time.monotonic()
        if now - self._last_attach_try < _ATTACH_RETRY_COOLDOWN:
            return False
        self._last_attach_try = now
        pid = _find_pid(self.exe_name)
        if pid is None:
            return False                        # Cemu éteint — rien à tenter
        if self._handle is not None and pid != self._pid:
            log.info("[Mem] Cemu relancé (pid %s → %d) — ré-attache", self._pid, pid)
            self.detach()                       # handle du process mort → tout re-scanner
        if self._handle is None:
            ok = self.attach()
        else:
            # Même process, gd_base perdu/invalidé : re-scan sans réouvrir le handle.
            self._gd_base = self._scan_for_gamedata()
            ok = self._gd_base is not None
            if ok:
                self._snapshot_gd_canary()
                log.info("[Mem] game_data re-localisé @ 0x%012X (buffer réalloué par le jeu)",
                         self._gd_base)
                self._locate_live_inventory()
                self._auto_capture_templates()
        if ok:
            self._gd_invalid_logged = False
        return ok

    def ensure_live_inventory(self) -> bool:
        """Re-tente la localisation de l'inventaire live quand l'attach l'a manquée (attach
        pendant la cinématique d'intro / save neuve : poche pas encore allouée). Cooldown
        interne — le scan AOB coûte quelques secondes (thread mémoire dédié)."""
        if not self.is_attached:
            return False
        if self._inv_base is not None:
            return True
        now = time.monotonic()
        if now - self._last_inv_locate_try < _INV_LOCATE_RETRY_COOLDOWN:
            return False
        self._last_inv_locate_try = now
        self._locate_live_inventory()
        if self._inv_base is not None:
            self._auto_capture_templates()
            return True
        return False

    # ── Validation du buffer gd (anti buffer réalloué) ────────────────────────

    def _snapshot_gd_canary(self) -> None:
        """Capture l'identité du buffer gd : les 16 premiers flag_ids (constants par save)."""
        raw = self._read(self._gd_base + 12, 16 * 8) if self._gd_base else None
        self._gd_canary = bytes(b"".join(raw[i * 8:i * 8 + 4] for i in range(16))) if raw else None

    def _gd_head_ok(self, head: bytes) -> bool:
        """Valide header + canari sur les 140 premiers octets du buffer (header 12 + 16 entrées)."""
        if len(head) < 12 + 16 * 8 or head[:12] != SAVE_HEADER:
            return False
        if self._gd_canary is None:
            return True
        return bytes(b"".join(head[12 + i * 8:12 + i * 8 + 4] for i in range(16))) == self._gd_canary

    def _invalidate_gd(self) -> None:
        """Le buffer gd a été réalloué (load/nouvelle partie) : on jette TOUTES les adresses qui
        dépendent de l'état du jeu — écrire dessus corromprait de la mémoire recyclée (crash
        Cemu différé). heap_base (mapping process-wide) et les templates sont conservés ;
        ensure_attached re-scannera au prochain cycle."""
        if not self._gd_invalid_logged:
            log.warning("[Mem] buffer game_data invalidé (réalloué par le jeu — load / nouvelle "
                        "partie ?) — écritures suspendues, ré-attache auto en cours")
            self._gd_invalid_logged = True
        self._gd_base = None
        self._gd_canary = None
        self._inv_base = None
        self._rupees_addr = None
        self._wallet_addr = None
        self._wallet_flagobj = None
        self._toast_reqmgr = None
        # L'ancre statique poche SURVIT (slot de la section data, constant pour le process) ;
        # la tablette est re-vérifiée (une nouvelle partie n'en a pas encore).
        self._slate_seen = False
        # Reload = liste pouch reconstruite PROPRE par le jeu → suspension levée.
        self._creates_suspended = False
        self._suspend_logged = False
        self._last_pouch_sig = None

    def detach(self) -> None:
        if self._handle:
            _k32.CloseHandle(self._handle)
            self._handle = None
        self._gd_base = None
        self._rupees_addr = None
        self._inv_base = None
        self._rupee_shadow = None
        self._wallet_addr = None
        self._wallet_flagobj = None
        self._heap_base = None
        self._toast_reqmgr = None
        self._toast_msbt = None           # adresses de session ; _toast_pending survit
        self._pouch_static_host = None    # adresse host → morte avec le process
        self._pouch_buf_off = None
        self._pouch_static_val = None
        self._slate_seen = False
        # NB: _persistent_qty / _seal_target ne sont PAS effacés (valeurs, pas adresses) : sur un
        # ré-attach le compteur d'orbes en jeu est inchangé et les orbes ne sont pas re-livrés →
        # les oublier stopperait la maintenance et l'orbe reverterait.

    @property
    def has_live_inventory(self) -> bool:
        return self._inv_base is not None

    @property
    def pool_exhausted(self) -> bool:
        """True quand le pool de nœuds PouchItem libres est épuisé → aucune création live possible.
        EXPIRE après un cooldown : on re-tente périodiquement une création (des nœuds libres
        apparaissent quand le joueur ramasse des objets / le jeu agrandit la poche). Sans ça, un
        seul épuisement transitoire bloquerait DÉFINITIVEMENT toutes les livraisons (bug constaté :
        save fraîche → 'je ne reçois pas les items')."""
        if not self._pool_exhausted:
            return False
        if time.monotonic() - self._pool_exhausted_at >= _POOL_RETRY_COOLDOWN:
            self._pool_exhausted = False          # cooldown écoulé → on autorise une nouvelle tentative
            return False
        return True

    @property
    def delivery_ready(self) -> bool:
        """Écritures mémoire AUTORISÉES : gd vivant (canari re-validé à l'instant), poche
        suivie par l'ancre statique, et TABLETTE SHEIKAH en poche. Avant la tablette
        (cinématique / tout début de partie) le jeu initialise et réalloue agressivement →
        aucune écriture (livraisons, flags, toasts) tant que ce n'est pas prêt ; tout est
        déjà en file et repartira seul. Re-vérifié après chaque load (invalidation gd)."""
        if not self.is_attached:
            return False
        head = self._read(self._gd_base, 12 + 16 * 8)
        if head is None or not self._gd_head_ok(head):
            self._invalidate_gd()
            return False
        if not self.has_live_inventory or not self._refresh_inv_from_static():
            return False
        if not self._slate_seen:
            if self.live_find_item("Obj_DRStone_Get") is None:
                # Tablette introuvable = soit vraiment pré-tablette, soit poche PÉRIMÉE (le
                # début de partie réalloue agressivement, et l'early-return « pas prêt » du
                # flush court-circuite la re-localisation de _inject_pending — bug du run du
                # 14/07 soir : gate jamais levée). On re-localise ici, avec cooldown, via
                # l'oracle rubis (seule validation qui distingue le buffer VIVANT).
                now = time.monotonic()
                if now - self._last_inv_locate_try >= _INV_LOCATE_RETRY_COOLDOWN:
                    self._last_inv_locate_try = now
                    self._relocate_inventory()
                    if self.live_find_item("Obj_DRStone_Get") is None:
                        return False
                else:
                    return False
            self._slate_seen = True
            log.info("[Mem] tablette Sheikah détectée en poche — livraisons AUTORISÉES")
        return True

    @property
    def is_attached(self) -> bool:
        return self._handle is not None and self._gd_base is not None

    # ── Raw memory I/O ────────────────────────────────────────────────────────

    def _read(self, addr: int, size: int) -> Optional[bytes]:
        buf = ctypes.create_string_buffer(size)
        n   = ctypes.c_size_t(0)
        ok  = _k32.ReadProcessMemory(self._handle, ctypes.c_void_p(addr),
                                      buf, size, ctypes.byref(n))
        return buf.raw if ok and n.value == size else None

    def _write(self, addr: int, data: bytes) -> bool:
        n  = ctypes.c_size_t(0)
        ok = _k32.WriteProcessMemory(self._handle, ctypes.c_void_p(addr),
                                      data, len(data), ctypes.byref(n))
        return bool(ok) and n.value == len(data)

    # ── DeathLink (pur-Python) ──────────────────────────────────────────────────
    # Aucun codecave (le hook natif bute sur le mur du recompilateur Cemu).
    # DETECTION : le HP courant (en quarts de coeur) est le flag GameData
    #   "CurrentHart" (typo officielle BotW) qui suit la vie EN TEMPS REEL et tombe
    #   a 0 a la mort (toutes causes : degats, chute, vide...). Lu par recherche
    #   binaire dans gd_base -> adresse stable entre sessions, comme les autres flags.
    # KILL : on ecrit 0.0 dans le HP MAX du singleton PlayerInfo (float a +0x64,
    #   localise par son vtable 0x101E486C, pose par l'init @ 0x02D495D8). Mettre le
    #   max a 0 force la vie a 0 -> Link meurt (prouve en jeu). Le flag GameData HP
    #   n'est qu'un miroir : l'ecrire ne tuerait pas (le jeu lit l'acteur, pas gd).
    _HP_FLAG      = "CurrentHart"    # flag GameData "HP courant" (quarts de coeur)
    _HP_FLAG_ID   = zlib.crc32(_HP_FLAG.encode("ascii")) & 0xFFFFFFFF   # 0xBE9BC993
    _PI_VTABLE    = 0x101E486C       # *(PlayerInfo+0x10)
    _PI_MAXHP_OFF = 0x64             # HP MAX (float) dans PlayerInfo ; 0 => mort

    def _pi_maxhp(self, pi: int) -> Optional[float]:
        r = self._read(pi + self._PI_MAXHP_OFF, 4)
        return struct.unpack(">f", r)[0] if r else None

    def _find_playerinfo(self) -> Optional[int]:
        """Localise le singleton PlayerInfo via son vtable. Cache + revalide."""
        if self._playerinfo is not None:
            if self._pi_maxhp(self._playerinfo) is not None:
                return self._playerinfo
            self._playerinfo = None          # cache invalide (jeu ferme/recharge) -> re-scan
        if not self.is_attached:
            return None
        sig = struct.pack(">I", self._PI_VTABLE)
        CH = 16 * 1024 * 1024
        for base, size in self._iter_regions():
            addr, end = base, base + size
            while addr < end:
                n = min(CH, end - addr)
                chunk = self._read(addr, n)
                if chunk:
                    i = chunk.find(sig)
                    while i >= 0:
                        cand = (addr + i) - 0x10           # vtable est a PlayerInfo+0x10
                        hp = self._pi_maxhp(cand)
                        if hp is not None and 0.0 <= hp <= 2000.0:
                            self._playerinfo = cand
                            return cand
                        i = chunk.find(sig, i + 1)
                addr += max(n - 4, 1)
        return None

    def read_hp(self) -> Optional[int]:
        """HP courant (quarts de coeur) via le flag GameData. None si indisponible."""
        if not self.is_attached:
            return None
        off = self._find_flag_offset(self._HP_FLAG_ID)
        if off is None:
            return None
        raw = self._read(self._gd_base + off + 4, 4)
        return struct.unpack(">i", raw)[0] if raw else None

    def poll_player_death(self) -> bool:
        """True une seule fois quand Link meurt (HP passe de >0 a <=0)."""
        hp = self.read_hp()
        if hp is None:
            return False
        prev, self._prev_hp = self._prev_hp, hp
        # n'arme qu'apres avoir vu un HP>0 ; la mort = transition >0 -> <=0
        # (evite le faux positif au chargement ou le HP vaut 0 puis remonte).
        return prev is not None and prev > 0 and hp <= 0

    def kill_player(self) -> bool:
        """Ecrit 0 dans le HP MAX du PlayerInfo -> tue Link. False si introuvable."""
        pi = self._find_playerinfo()
        if pi is None:
            return False
        ok = self._write(pi + self._PI_MAXHP_OFF, struct.pack(">f", 0.0))
        if ok:
            self._prev_hp = 0               # evite de renvoyer notre propre mort
        return ok

    # ── Memory region scan ────────────────────────────────────────────────────

    def _iter_regions(self):
        mbi  = MEMORY_BASIC_INFORMATION()
        addr = 0
        sz   = ctypes.sizeof(mbi)
        while addr < MAX_USER_ADDR:
            res = _k32.VirtualQueryEx(self._handle, ctypes.c_void_p(addr),
                                       ctypes.byref(mbi), sz)
            if not res:
                break
            base = mbi.BaseAddress or 0
            rsz  = mbi.RegionSize
            if rsz == 0:
                break
            protect = mbi.Protect
            readable_mask = (
                PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY |
                PAGE_EXECUTE | PAGE_EXECUTE_READ |
                PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY
            )
            readable = protect & readable_mask
            guarded  = protect & PAGE_GUARD or protect & PAGE_NOACCESS
            if mbi.State == MEM_COMMIT and readable and not guarded:
                yield base, rsz
            addr = base + rsz

    def _scan_for_gamedata(self) -> Optional[int]:
        """
        Cherche SAVE_HEADER (12 bytes) dans la memoire de Cemu.
        Parcourt les regions >= SAVE_SIZE en chunks de SCAN_CHUNK.
        Verifie la validite du buffer trouve (sorted flag array).
        """
        log.debug("[Mem] Scan du buffer game_data en memoire...")
        for base, rsz in self._iter_regions():
            if rsz < SAVE_SIZE:
                continue
            off = 0
            while off < rsz:
                n     = min(SCAN_CHUNK, rsz - off)
                chunk = self._read(base + off, n)
                if chunk is None:
                    off += n
                    continue
                idx = chunk.find(SAVE_HEADER)
                if idx >= 0:
                    candidate = base + off + idx
                    if self._verify_gamedata(candidate):
                        return candidate
                off += n
        return None

    def _verify_gamedata(self, addr: int) -> bool:
        """Vérifie que l'adresse pointe bien sur un buffer game_data valide."""
        data = self._read(addr, 12 + 32)  # header + 4 premières entrées
        if data is None or len(data) < 12 + 32:
            return False
        # Les premières entrées doivent être triées par flag_id
        try:
            ids = [struct.unpack_from(">I", data, 12 + i * 8)[0] for i in range(4)]
            return ids[0] < ids[1] < ids[2] < ids[3]
        except Exception:
            return False

    # ── Inventaire live (PauseMenuDataMgr) ────────────────────────────────────

    def _find_rupees_addresses(self) -> list[int]:
        """Scan AOB (porte de botw_editor) pour toutes les occurrences du pattern rupees."""
        pattern = _RUPEE_PATTERN
        plen = len(pattern)
        fixed = [(i, b) for i, b in enumerate(pattern) if b != -1]
        idx0, val0 = fixed[0]
        results: list[int] = []
        for base, size in self._iter_regions():
            if size < plen:
                continue
            off = 0
            while off < size:
                n = min(_INV_SCAN_CHUNK, size - off)
                read_n = min(n + plen - 1, size - off)
                chunk = self._read(base + off, read_n)
                if chunk:
                    arr = np.frombuffer(chunk, dtype=np.uint8)
                    cands = np.where(arr == val0)[0]
                    for c in cands:
                        pos = int(c) - idx0
                        if pos < 0 or pos + plen > len(arr):
                            continue
                        if all(arr[pos + i] == b for i, b in fixed):
                            results.append(base + off + pos + plen)
                off += n
        return results

    def _scan_u32be(self, value: int):
        """Génère les adresses ALIGNÉES-4 contenant `value` (u32 big-endian), dans l'ordre
        mémoire — l'appelant peut s'arrêter au premier hit validé (économise le reste du scan)."""
        needle = struct.pack(">I", value & 0xFFFFFFFF)
        for base, size in self._iter_regions():
            off = 0
            while off < size:
                n = min(_INV_SCAN_CHUNK, size - off)
                chunk = self._read(base + off, min(n + 8, size - off))
                if chunk:
                    start = 0
                    while True:
                        i = chunk.find(needle, start)
                        if i < 0 or i >= n:
                            break
                        if ((base + off + i) & 3) == 0:
                            yield base + off + i
                        start = i + 1
                off += n

    def _flagobj_guest_ok(self, rupees_addr: Optional[int],
                          heap_base: Optional[int]) -> Optional[int]:
        """ANCRE EXTERNE de validité du heap_base. L'objet gdt::Flag<s32> CurrentRupee vit à
        `rupees_addr - 0x14` (adresse LIVE trouvée par AOB, indépendante du buffer pouch).
        Si sa vtable + son hash matchent ET que son guest (= host - heap_base) tombe dans la
        plage 32-bit valide, alors heap_base est cohérent avec CE flagobj → retourne le flagobj
        host. Un heap_base dérivé d'un buffer pouch PÉRIMÉ (copie post-réallocation, cas du 1er
        attach après un load) est décalé → guest hors plage → None (couple à écarter)."""
        if rupees_addr is None or heap_base is None:
            return None
        flagobj = rupees_addr - _FLAG_S32_OFF_VALUE
        head = self._read(flagobj, 4)
        h = self._read(flagobj + _FLAG_S32_OFF_HASH, 4)
        if not (head and h):
            return None
        if struct.unpack(">I", head)[0] != _GDT_FLAG_S32_VTABLE \
                or struct.unpack(">I", h)[0] != _RUPEE_FLAG_HASH:
            return None
        guest = flagobj - heap_base
        return flagobj if 0 < guest < _GUEST_MAX else None

    def _find_wallet(self) -> bool:
        """Localise le VRAI portefeuille (entrée CurrentRupee du storage gdt s32 live).
        Topologie/preuve : bloc de constantes _GDT_* en tête de fichier. Nécessite la base
        heap (dérivée des nœuds pouch) pour convertir host <-> guest."""
        if self._heap_base is None:
            nodes = self._scan_pouch_nodes()
            self._heap_base = self._derive_heap_base(nodes) if nodes else None
        if self._heap_base is None:
            log.debug("[Mem] wallet: base heap indisponible (inventaire non localisé ?)")
            return False
        flagobj = None
        # Raccourci (économise un full-scan, ~45 s) : l'AOB _RUPEE_PATTERN résolu à la
        # localisation d'inventaire matche le champ value du Flag<s32> CurrentRupee →
        # flagobj = _rupees_addr - 0x14. VALIDÉ (vtable + hash) avant usage — MAIS ce peut
        # être une COPIE freed encore mappée (fréquent sur save neuve) : on ne l'adopte que
        # si son guest est plausible avec la base courante (self-pointer, fiable).
        if self._rupees_addr is not None:
            cand = self._rupees_addr - _FLAG_S32_OFF_VALUE
            head = self._read(cand, 4)
            h = self._read(cand + _FLAG_S32_OFF_HASH, 4)
            if head and h and struct.unpack(">I", head)[0] == _GDT_FLAG_S32_VTABLE \
                    and struct.unpack(">I", h)[0] == _RUPEE_FLAG_HASH:
                if 0 < cand - self._heap_base < _GUEST_MAX:
                    flagobj = cand
                else:
                    # guest hors plage : soit la BASE est périmée (re-dérive une fois), soit
                    # le flagobj AOB est une copie morte → on cherchera le VIVANT par hash.
                    fresh = self._derive_heap_base(self._scan_pouch_nodes())
                    if fresh is not None and fresh != self._heap_base \
                            and 0 < cand - fresh < _GUEST_MAX:
                        self._heap_base = fresh
                        flagobj = cand
        if flagobj is None:
            # Scan du hash CurrentRupee (lourd, ~45 s pire cas) → SEULE la copie dont le guest
            # est plausible avec la base est retenue (le flagobj VIVANT). Cooldown 30 s — appelé
            # potentiellement à chaque write rubis (strip/award), le scan ne doit pas marteler.
            now = time.monotonic()
            if now - self._last_wallet_warn < 30.0:
                return False
            self._last_wallet_warn = now
            for a in self._scan_u32be(_RUPEE_FLAG_HASH):
                head = self._read(a - _FLAG_S32_OFF_HASH, 4)
                if head and struct.unpack(">I", head)[0] == _GDT_FLAG_S32_VTABLE:
                    cand = a - _FLAG_S32_OFF_HASH
                    if 0 < cand - self._heap_base < _GUEST_MAX:
                        flagobj = cand
                        break
        if flagobj is None:
            log.info("[Mem] wallet: objet gdt::Flag<s32> CurrentRupee (vivant) introuvable "
                     "ce cycle — réessai différé")
            return False
        guest = flagobj - self._heap_base
        for a in self._scan_u32be(guest):
            head = self._read(a - 4, 4)
            if head and struct.unpack(">I", head)[0] == _GDT_S32_STORE_TYPEINFO:
                raw = self._read(a + 4, 4)
                v = struct.unpack(">i", raw)[0] if raw else -1
                if 0 <= v <= 999999:
                    self._wallet_addr = a + 4
                    self._wallet_flagobj = flagobj
                    log.info("[Mem] Portefeuille (storage gdt) @ 0x%012X = %d rubis "
                             "(flagobj @ 0x%012X)", a + 4, v, flagobj)
                    return True
        log.info("[Mem] wallet: entrée storage introuvable pour flagobj 0x%012X", flagobj)
        return False

    def _wallet_valid(self) -> bool:
        """Re-validation structurelle (3 lectures) avant chaque écriture rubis : l'entrée
        storage référence TOUJOURS notre flagobj (typeinfo + ptr) et le flagobj porte
        toujours le hash CurrentRupee. Rend l'adresse périmée impossible par construction."""
        if self._wallet_addr is None or self._wallet_flagobj is None or self._heap_base is None:
            return False
        raw = self._read(self._wallet_addr - 8, 8)
        if not raw or len(raw) < 8:
            return False
        ti, ptr = struct.unpack(">II", raw)
        if ti != _GDT_S32_STORE_TYPEINFO or ptr != self._wallet_flagobj - self._heap_base:
            return False
        h = self._read(self._wallet_flagobj + _FLAG_S32_OFF_HASH, 4)
        return h is not None and struct.unpack(">I", h)[0] == _RUPEE_FLAG_HASH

    @staticmethod
    def _matches_item_pattern(buf: Optional[bytes]) -> bool:
        return bool(buf) and len(buf) >= 8 and buf[0] == 16 and buf[4] == 0 and buf[5] == 0 and buf[6] == 0 and buf[7] == 64

    def _score_inventory_candidate(self, addr: int, n_slots: int = 10) -> int:
        score = 0
        for slot in range(n_slots):
            a = addr + slot * _ITEM_STRIDE
            head = self._read(a, 8)
            if not self._matches_item_pattern(head):
                return score
            item_addr = a + 7
            raw = self._read(item_addr + 1, 64) or b""
            item_id = raw.split(b"\x00")[0].decode("ascii", errors="replace")
            if item_id.startswith(_ITEM_PREFIXES) or item_id.endswith("Arrow"):
                score += 1
        return score

    def _addr_has_free_node(self, addr: int, max_slots: int = 200) -> bool:
        """True si le tableau PouchItem à `addr` contient un nœud LIBRE (type 0xFFFFFFFF, sans nom)
        → un buffer VIVANT avec de la marge, pas un ancien buffer exactement dimensionné (freed)."""
        for slot in range(max_slots):
            a = addr + slot * _ITEM_STRIDE
            head = self._read(a, 8)
            if not self._matches_item_pattern(head):
                return False
            raw = self._read(a - self._NODE_HEADER_OFF, _ITEM_STRIDE)
            if not raw:
                return False
            typ = struct.unpack_from(">I", raw, self._NODE_OFF_TYPE)[0]
            name = raw[self._NODE_OFF_NAME:self._NODE_OFF_NAME + 40].split(b"\x00")[0]
            if typ == 0xFFFFFFFF and not name:
                return True
        return False

    def _find_inventory_start(self, rupees_addr: int, prefer_free: bool = False) -> Optional[int]:
        """Scanne la region contenant rupees_addr pour le tableau PouchItem (stride 544).
        prefer_free=True : préfère un buffer qui possède un nœud LIBRE (le jeu réalloue la poche
        → l'ancien buffer paraît encore valide mais n'a PLUS de nœud libre ; on veut le VIVANT).

        SÉLECTION PAR ANCRE (fix bug 1er attach) : le flagobj rubis (gdt) n'est PAS réalloué avec
        la poche → adresse fixe/live. On retient EN PRIORITÉ le candidat pouch dont la base tas
        (dérivée de ses nœuds) place ce flagobj à un guest valide : c'est le buffer VIVANT, à
        l'exclusion de l'ANCIEN buffer freed (base décalée) qui, juste après un load, marque
        souvent un meilleur score et était renvoyé à tort → wallet cassé + créations ratées."""
        region_base, region_size = None, None
        for base, size in self._iter_regions():
            if base <= rupees_addr < base + size:
                region_base, region_size = base, size
                break
        if region_base is None:
            return None

        off = 0
        best, best_score = None, -1
        free_checks = 0
        anchor_checks = 0
        anchor_done = False        # plafond d'ancre atteint → repli sur la sélection historique
        while off < region_size:
            n = min(_INV_SCAN_CHUNK, region_size - off)
            read_n = min(n + _ITEM_STRIDE + 8, region_size - off)
            chunk = self._read(region_base + off, read_n)
            if chunk:
                arr = np.frombuffer(chunk, dtype=np.uint8)
                cands = np.where(arr == 16)[0]
                for c in cands:
                    pos = int(c)
                    if pos + _ITEM_STRIDE + 8 > len(arr):
                        continue
                    if not (arr[pos+4] == 0 and arr[pos+5] == 0 and arr[pos+6] == 0 and arr[pos+7] == 64):
                        continue
                    p2 = pos + _ITEM_STRIDE
                    if not (arr[p2] == 16 and arr[p2+4] == 0 and arr[p2+5] == 0 and arr[p2+6] == 0 and arr[p2+7] == 64):
                        continue
                    addr = region_base + off + pos
                    s = self._score_inventory_candidate(addr)
                    if s > best_score:
                        best, best_score = addr, s
                    # early-exit sur un candidat FORT (≥ seuil). Les checks (ancre / nœud libre)
                    # sont coûteux (~centaines de lectures) → réservés aux forts ET plafonnés,
                    # sinon ils monopolisent le thread et font tomber le keepalive AP (1011).
                    if s >= _EARLY_EXIT_SCORE:
                        # PRIORITÉ 1 : base cohérente avec l'ancre rubis = buffer VIVANT prouvé.
                        if not anchor_done:
                            if anchor_checks < _ANCHOR_CHECK_CAP:
                                anchor_checks += 1
                                b = self._derive_heap_base(self._scan_pouch_nodes(addr))
                                if b is not None and \
                                        self._flagobj_guest_ok(rupees_addr, b) is not None:
                                    return addr
                                # ancre non tranchée sur CE candidat → on CONTINUE de scanner
                                # (le buffer vivant est peut-être plus loin) sans early-return.
                                continue
                            anchor_done = True     # plafond atteint → repli historique ci-dessous
                        # PRIORITÉ 2 (repli) : comportement historique score / nœud libre.
                        if not prefer_free:
                            return best
                        if free_checks < _FREE_NODE_CHECK_CAP:
                            free_checks += 1
                            if self._addr_has_free_node(addr):
                                return addr        # candidat fort AVEC nœud libre = buffer vivant
            off += n
        # aucun candidat tranché par l'ancre / nœud libre → on retombe sur `best` (fallback).
        return best if best_score > 0 else None

    def _locate_live_inventory(self, prefer_free: bool = False) -> None:
        """Trouve rupeesAddress + inventoryStartAddress live. Echec silencieux (fallback save-file).

        VALIDATION DE COUPLE (fix bug 1er attach) : l'AOB rubis peut matcher PLUSIEURS objets
        (le buffer live + des copies périmées encore mappées, fréquentes juste après un load où
        le jeu réalloue la poche). On adopte en PRIORITÉ le couple (rupees, pouch) dont la base
        tas — dérivée du pouch — place le flagobj rubis (ancre live indépendante) à un guest
        valide : ça garantit un buffer VIVANT (heap_base correct → wallet trouvé + créations OK).
        Repli sur le 1er couple parsable si aucun n'est validé (save sans objet rubis distinct)."""
        fallback: Optional[tuple[int, int]] = None    # (rupees_addr, inv_base) non validé
        for rupees_addr in self._find_rupees_addresses():
            inv_base = self._find_inventory_start(rupees_addr, prefer_free=prefer_free)
            if inv_base is None:
                continue
            base = self._derive_heap_base(self._scan_pouch_nodes(inv_base))
            if base is not None and self._flagobj_guest_ok(rupees_addr, base) is not None:
                self._rupees_addr = rupees_addr
                self._inv_base = inv_base
                self._heap_base = base                # base VALIDÉE par l'ancre → fixe/correcte
                log.info("[Mem] Inventaire live localise @ 0x%012X (rupees @ 0x%012X, base validée)",
                         inv_base, rupees_addr)
                # COHÉRENCE de l'ancre statique : si elle existe mais ne désigne PAS le buffer
                # qu'on vient de VALIDER (oracle rubis), c'était un faux positif (mot de données
                # quelconque) → on la jette et on re-résout depuis le buffer validé.
                if self._pouch_static_host is not None:
                    r = self._read(self._pouch_static_host, 4)
                    cur = struct.unpack(">I", r)[0] if r else None
                    if cur is None or base + cur + (self._pouch_buf_off or 0) != inv_base:
                        log.info("[Mem] ancre statique poche incohérente avec le buffer validé "
                                 "— re-résolution")
                        self._pouch_static_host = None
                        self._pouch_buf_off = None
                        self._pouch_static_val = None
                # Localisation VALIDÉE → on résout (one-shot) l'ancre statique qui suivra
                # désormais le buffer vivant à chaque accès (anti copie-freed).
                self._find_pouch_static()
                if not self._wallet_valid():
                    self._find_wallet()
                return
            if fallback is None:
                fallback = (rupees_addr, inv_base)
        if fallback is not None:
            # Aucun couple validé par l'ancre rubis (flagobj AOB périmé/copie — fréquent sur
            # save neuve où la poche n'a que 1-2 nœuds). On adopte le pouch ET on dérive quand
            # même sa base (self-pointer du nom → exacte dès un nœud) : wallet/toast peuvent
            # fonctionner (_find_wallet re-scanne le VRAI flagobj par hash si l'AOB est périmé).
            self._rupees_addr, self._inv_base = fallback
            self._heap_base = self._derive_heap_base(self._scan_pouch_nodes(fallback[1]))
            log.info("[Mem] Inventaire live localise @ 0x%012X (rupees @ 0x%012X, non validé)",
                     fallback[1], fallback[0])
            if not self._wallet_valid():
                self._find_wallet()
            return
        log.info("[Mem] Inventaire live introuvable — injection PorchItem (save-file) uniquement")

    def _relocate_inventory(self, prefer_free: bool = False) -> bool:
        """L'inventaire a pu être réalloué/déplacé (grosse rafale d'items) → _inv_base périmé.
        On re-localise (cooldown pour ne pas re-scanner en boucle). True si re-trouvé.
        prefer_free=True : cible un buffer AVEC nœuds libres (cas réallocation → ancien buffer sans
        marge, ce que ferait un reconnect client, mais sans reconnect)."""
        now = time.monotonic()
        if now - self._last_inv_relocate < 3.0:
            return False
        self._last_inv_relocate = now
        prev = self._inv_base
        self._inv_base = None
        self._rupees_addr = None
        # heap_base + wallet dérivés du buffer PÉRIMÉ → on les jette : _locate_live_inventory
        # re-valide un couple vivant et re-dérive une base correcte (sinon le wallet reste cassé
        # après relocation — c'était le cœur du bug « items pas livrés au 1er attach »).
        self._heap_base = None
        self._wallet_addr = None
        self._wallet_flagobj = None
        self._locate_live_inventory(prefer_free=prefer_free)
        if self._inv_base is not None and self._inv_base != prev:
            log.info("[Mem] Inventaire re-localisé (réallocation détectée) → 0x%012X", self._inv_base)
        return self._inv_base is not None

    # ── Ancre statique de la poche (suivi du buffer VIVANT, anti copie-freed) ──

    # Section data guest (globals) : nos statiques connus y vivent (vtables 0x101E486C /
    # 0x1021B5D4, ctx toast *(0x1047B054), dirty *(0x1046BDD8)) → on cherche le pointeur
    # de poche dans cette fenêtre. Offset objet max : le buffer PouchItem est porté par un
    # gestionnaire unique — on tolère un pointeur vers l'objet englobant (≤ 0x8000).
    _POUCH_STATIC_LO = 0x10000000
    _POUCH_STATIC_HI = 0x10C00000
    _POUCH_MAX_OBJ_OFF = 0x8000

    def _find_pouch_static(self) -> None:
        """Backref ONE-SHOT (après une localisation VALIDÉE) : cherche dans la section data
        guest un slot statique dont la valeur désigne la poche courante (le buffer même, ou
        l'objet qui le contient à offset < _POUCH_MAX_OBJ_OFF). Relire ce slot à chaque accès
        suit les réallocations SANS re-scan AOB — et n'adresse jamais une copie freed (aucun
        statique ne pointe sur du staging). Échec silencieux → comportement historique."""
        if self._pouch_static_host is not None \
                or self._inv_base is None or self._heap_base is None:
            return
        inv_g = self._inv_base - self._heap_base
        if not (0x02000000 <= inv_g < _GUEST_MAX):
            return                                # base/inventaire incohérents → pas d'ancre
        lo_val = max(0x02000000, inv_g - self._POUCH_MAX_OBJ_OFF)
        prefixes = {struct.pack(">I", v)[:2] for v in (lo_val, inv_g)}
        # les valeurs candidates partagent 1-2 préfixes 16 bits → recherche par bytes.find
        best: Optional[tuple[int, int]] = None      # (offset_objet, host_addr_du_slot)
        chunk_sz = 1 << 20
        for g in range(self._POUCH_STATIC_LO, self._POUCH_STATIC_HI, chunk_sz):
            chunk = self._read(self._heap_base + g, chunk_sz)
            if not chunk:
                continue
            for pfx in prefixes:
                pos = chunk.find(pfx)
                while pos != -1:
                    if pos % 4 == 0 and pos + 4 <= len(chunk):    # slots alignés u32
                        val = struct.unpack_from(">I", chunk, pos)[0]
                        # offset objet ALIGNÉ requis : un vrai pointeur de gestionnaire est
                        # aligné 4 — le faux positif du 2026-07-14 (offset +0x24B1, un mot de
                        # données quelconque) « confirmait » à vie un buffer périmé.
                        if lo_val <= val <= inv_g and (inv_g - val) % 4 == 0:
                            off = inv_g - val
                            if best is None or off < best[0]:
                                best = (off, self._heap_base + g + pos)
                    pos = chunk.find(pfx, pos + 1)
        if best is None:
            log.debug("[Mem] ancre statique poche introuvable (backref) — suivi AOB conservé")
            return
        self._pouch_buf_off, self._pouch_static_host = best
        self._pouch_static_val = inv_g - best[0]
        log.info("[Mem] ancre statique poche @ host 0x%012X (guest 0x%08X, offset objet +0x%X)",
                 self._pouch_static_host,
                 self._pouch_static_host - self._heap_base, self._pouch_buf_off)

    def _refresh_inv_from_static(self) -> bool:
        """Suit le pointeur statique de la poche AVANT tout accès : True si l'inventaire
        courant est le buffer VIVANT (re-ciblé au besoin), False si le jeu est en plein
        load/réallocation (→ l'appelant REPORTE ses écritures au lieu de corrompre de la
        mémoire recyclée — cause du crash 0xc0000005 du 2026-07-14)."""
        if self._pouch_static_host is None or self._heap_base is None:
            return self._inv_base is not None     # ancre non résolue → comportement historique
        now = time.monotonic()
        if now - self._last_inv_refresh < 0.5:
            # cooldown : on rejoue le DERNIER verdict (un échec récent reste un échec —
            # renvoyer True ici rouvrirait la fenêtre d'écriture sur mémoire recyclée)
            return self._last_refresh_ok and self._inv_base is not None
        self._last_inv_refresh = now
        self._last_refresh_ok = False
        r = self._read(self._pouch_static_host, 4)
        if not r:
            return False
        val = struct.unpack(">I", r)[0]
        if not (0x02000000 <= val < _GUEST_MAX):
            return False                          # pointeur nul/transitoire : load en cours
        new_base = self._heap_base + val + (self._pouch_buf_off or 0)
        if val == self._pouch_static_val and self._inv_base == new_base:
            self._last_refresh_ok = True
            return True                           # rien n'a bougé (ni l'ancre ni notre cible)
        nodes = self._scan_pouch_nodes(new_base)
        if nodes and self._count_selfref(nodes, self._heap_base) >= 1:
            if new_base != self._inv_base:
                log.info("[Mem] poche re-suivie via l'ancre statique → 0x%012X", new_base)
                self._rupee_shadow = None
            self._inv_base = new_base
            self._pouch_static_val = val
            self._last_refresh_ok = True
            return True
        return False                              # buffer pas encore peuplé → écritures reportées

    def refresh_inventory_if_stale(self) -> None:
        """Re-localise l'inventaire quand il est périmé. Trois signaux :
          1. base périmée « dure » : plus aucun nœud cohérent (0 self-ref) ;
          2. réallocation « douce » : le pool paraît épuisé (aucun nœud LIBRE dans le buffer
             courant) alors que le jeu a réalloué la poche ailleurs → on est collé sur l'ANCIEN
             buffer (il paraît encore valide, d'où non-détection par le seul test self-ref). Sans
             ça, les créations ne repartaient qu'après une déco/reco client. On re-localise en
             PRÉFÉRANT un buffer avec nœuds libres.
          3. DÉRIVE DE BASE (fix bug 1er attach) : le buffer courant reste self-cohérent mais la
             base qu'il implique diverge de la base VALIDÉE (self._heap_base) → c'est une COPIE
             périmée (post-réallocation, encore mappée) sur laquelle on est resté collé ; ses
             guests sont décalés (wallet + toast cassés) → re-localiser vers le buffer vivant.
        À appeler une fois par cycle de livraison (pas par item)."""
        if self._inv_base is None:
            return
        nodes = self._scan_pouch_nodes()
        fresh_base = self._derive_heap_base(nodes) if nodes else None
        hard_stale = fresh_base is None
        base_drift = (not hard_stale and self._heap_base is not None
                      and fresh_base != self._heap_base)
        has_free = any(n["type"] == 0xFFFFFFFF and not n["name"] for n in nodes)
        need_free = self._pool_exhausted and not has_free
        if not hard_stale and not need_free and not base_drift:
            return                                   # inventaire frais → on GARDE _pool_exhausted
        # Re-localise (réarme les créations si un buffer avec nœuds libres est trouvé).
        if self._relocate_inventory(prefer_free=need_free or base_drift):
            self._pool_exhausted = False

    def reassert_qty_targets(self) -> int:
        """Ré-applique les qty cibles des items livrés cette rafale. BotW restaure les nœuds
        PRÉEXISTANTS à leur qty d'origine quand l'inventaire réalloue (les bumps live sont
        perdus) → sans ça, l'orbe/les stacks reviennent à leur valeur d'avant-rafale. Un seul
        passage sur l'inventaire. Ne fait QUE remonter (cur < cible) pour ne pas écraser une
        dépense légitime du joueur. Retourne le nombre de nœuds corrigés."""
        if not self._qty_targets or self._inv_base is None:
            return 0
        fixed = 0
        for _, item_addr, iid in self._iter_inventory_slots():
            target = self._qty_targets.get(iid)
            if target is None:
                continue
            raw = self._read(item_addr - 19, 4)
            cur = struct.unpack(">i", raw)[0] if raw else 0
            if cur < target:
                self._write(item_addr - 19, struct.pack(">i", target & 0xFFFFFFFF))
                fixed += 1
        if fixed:
            log.info("[Mem] (live) %d qty ré-assertée(s) après réallocation", fixed)
        return fixed

    def clear_qty_targets(self) -> None:
        """Oublie les qty cibles TRANSITOIRES (rafale terminée) : le joueur peut dépenser ces
        stacks. Les cibles PERSISTANTES (orbes) ne sont PAS effacées (voir maintain_persistent)."""
        self._qty_targets.clear()

    @property
    def seal_target(self) -> Optional[int]:
        """Cible DungeonClearSealNum (orbes reçus d'AP) à banker dans la save. None si aucun orbe."""
        return self._seal_target

    @property
    def orb_pouch_target(self) -> Optional[int]:
        """Cible pouch Obj_DungeonClearSeal (orbes) à banker dans la save. None si aucun orbe."""
        return self._persistent_qty.get("Obj_DungeonClearSeal")

    def maintain_persistent(self) -> int:
        """Ré-assert EN CONTINU (chaque poll) les compteurs d'orbes que le jeu reverte :
        - pouch Obj_DungeonClearSeal (restauré à sa valeur sérialisée à chaque réallocation),
        - gamedata DungeonClearSealNum.
        Ne remonte QUE vers le haut (bump-up) → n'écrase pas les orbes NATURELS (clear de
        sanctuaire) au-dessus de la cible. Retourne le nombre de corrections. Sans ça, un orbe
        reçu d'AP « retombe à un nombre d'avant » (bug constaté)."""
        if not self.has_live_inventory:
            return 0
        fixed = 0
        if self._persistent_qty:
            for slot, item_addr, iid in self._iter_inventory_slots():
                target = self._persistent_qty.get(iid)
                if target is None:
                    continue
                raw = self._read(item_addr - 19, 4)
                cur = struct.unpack(">i", raw)[0] if raw else 0
                if cur < target:
                    self._write(item_addr - 19, struct.pack(">i", target & 0xFFFFFFFF))
                    fixed += 1
        if self._seal_target is not None:
            cur = self.read_flag("DungeonClearSealNum")
            if cur is not None and cur < self._seal_target:
                self.write_flag("DungeonClearSealNum", self._seal_target)
                fixed += 1
        return fixed

    def _iter_inventory_slots(self, max_slots: int = 420):
        """Itere (slot, item_addr, item_id) sur le tableau PouchItem live. Suit d'abord
        l'ancre statique : si le jeu a réalloué la poche, on itère le buffer VIVANT (et si
        le jeu est en plein load, on n'itère RIEN plutôt que de la mémoire recyclée)."""
        if not self._refresh_inv_from_static():
            return
        if self._inv_base is None:
            return
        for slot in range(max_slots):
            addr = self._inv_base + slot * _ITEM_STRIDE
            head = self._read(addr, 8)
            if not self._matches_item_pattern(head):
                return
            item_addr = addr + 7
            raw = self._read(item_addr + 1, 64) or b""
            item_id = raw.split(b"\x00")[0].decode("ascii", errors="replace")
            yield slot, item_addr, item_id

    def live_find_item(self, item_id: str) -> Optional[int]:
        """Retourne itemAddress du slot contenant item_id, ou None."""
        for _, item_addr, iid in self._iter_inventory_slots():
            if iid == item_id:
                return item_addr
        return None

    def live_get_item_qty(self, item_id: str) -> Optional[int]:
        item_addr = self.live_find_item(item_id)
        if item_addr is None:
            return None
        raw = self._read(item_addr - 19, 4)
        return struct.unpack(">i", raw)[0] if raw else None

    def live_add_item_qty(self, item_id: str, amount: int) -> Optional[int]:
        """Ajoute `amount` a la quantite/durabilite live d'un item deja en inventaire."""
        item_addr = self.live_find_item(item_id)
        if item_addr is None:
            # Cas attendu quand le pool est épuisé (création impossible) : on défère
            # silencieusement vers la file/le save-file plutôt que de spammer.
            log.debug("[Mem] (live) Item %s introuvable en inventaire", item_id)
            return None
        addr = item_addr - 19
        raw = self._read(addr, 4)
        current = struct.unpack(">i", raw)[0] if raw else 0
        new_val = max(0, current + amount)
        self._write(addr, struct.pack(">i", new_val & 0xFFFFFFFF))
        self._qty_targets[item_id] = new_val      # à ré-asserter si une réallocation reset le nœud
        if item_id == "Obj_DungeonClearSeal":
            # Orbe : le jeu restaure ce nœud à sa valeur sérialisée → cible PERSISTANTE (cumulatif)
            # maintenue chaque poll, sinon l'orbe reçu retombe.
            self._persistent_qty[item_id] = max(self._persistent_qty.get(item_id, 0), new_val)
        log.info("[Mem] (live) %s: %d -> %d", item_id, current, new_val)
        return new_val

    def live_get_rupees(self) -> Optional[int]:
        """Lit le VRAI portefeuille (storage gdt) ; repli LECTURE sur le flagobj/miroir AOB."""
        addr = self._wallet_addr if self._wallet_addr is not None else self._rupees_addr
        if addr is None:
            return None
        raw = self._read(addr, 4)
        return struct.unpack(">i", raw)[0] if raw else None

    def live_add_rupees(self, amount: int) -> Optional[int]:
        # ÉCRIRE exige le VRAI portefeuille (storage gdt) : écrire le seul miroir (flagobj)
        # est inefficace — le jeu resynchronise depuis le storage (rubis « ajoutés puis
        # disparus », bug historique de l'AOB). Validation structurelle avant CHAQUE write ;
        # re-localisation lazy en cas d'échec (l'appelant reporte, la dette est rejouée).
        if not self._wallet_valid():
            self._wallet_addr = None
            if not self._find_wallet():
                log.debug("[Mem] (live) rubis: portefeuille non localisé — reporté")
                return None
        raw = self._read(self._wallet_addr, 4)
        current = struct.unpack(">i", raw)[0] if raw else None
        # Garde-fou bornes jeu (0..999999) : hors bornes = état transitoire → on n'écrit pas.
        if current is None or not (0 <= current <= 999999):
            return None
        # Divergence forte vs notre dernière écriture : dépense/recette légitime du joueur
        # (l'adresse, elle, est validée structurellement) — on trace pour le débogage.
        if self._rupee_shadow is not None and abs(current - self._rupee_shadow) >= _RUPEE_STALE_DROP:
            log.debug("[Mem] (live) rubis: %d vs shadow %d (activité joueur)", current, self._rupee_shadow)
        new_val = max(0, min(999999, current + amount))
        if not self._write(self._wallet_addr, struct.pack(">i", new_val)):
            return None
        # Miroir HUD : l'objet gdt::Flag<s32> alimente l'affichage — on l'aligne pour que le
        # compteur à l'écran soit juste sans attendre la resync du jeu.
        if self._wallet_flagobj is not None:
            self._write(self._wallet_flagobj + _FLAG_S32_OFF_VALUE, struct.pack(">i", new_val))
        # gd_base (buffer de sérialisation) : le jeu ne resérialise que ses flags « dirty »
        # (prouvé le 2026-07-12 sur un bool : write storage + save manuelle → .sav resté à 0).
        # Nos writes storage ne sont donc PAS repris au save tant que le joueur ne fait pas
        # de transaction ; le buffer gd_base, lui, est flushé intégralement au fichier → on
        # y écrit AUSSI la valeur pour que les rubis livrés survivent à un save/reload sec.
        self.write_flag("CurrentRupee", new_val & 0xFFFFFFFF)
        self._rupee_shadow = new_val
        log.info("[Mem] (live) Rubis: %d -> %d", current, new_val)
        return new_val

    # ── Toast natif « item reçu » ─────────────────────────────────────────────
    # Canal RE 2026-07-12 (docs/status.md §6c, VALIDÉ in-game) : la boucle UI draine la
    # file de requêtes du HUD MainScreen (écran registre 0x25) → écran MessageGet_00.
    # push_toast reproduit l'enqueue natif FUN_02ed1f7c : pop freelist → nœud
    # {type 0xA, FixedSafeString<64> = nom d'actor} → splice front sur le sentinel →
    # count++ → nom d'actor au contexte + bit « HUD dirty ». Le message du type 0xA est
    # REDIRIGÉ en RAM (offset TXT2 du MSBT → string placeholder de dev réécrite) vers
    # « Vous avez reçu {item} xN. » — nom LOCALISÉ sans article (tag {201,1} omis),
    # quantité réinscrite avant chaque bandeau. Validé in-game (flèche en bois x5).

    _TOAST_REG_PTR = 0x1047E650      # registre des écrans (guest)
    _TOAST_CTX_PTR = 0x1047B054      # contexte toast (nom d'actor @ctx+0x2C)
    _TOAST_UIROOT_PTR = 0x1046BDD8   # uiroot (bit dirty @+0x4075C, cf. FUN_03058b44)
    _TOAST_HUD_ID = 0x25
    _TOAST_REQMGR_OFF = 0x1B84
    _TOAST_DIRTY_OFF = 0x4075C
    _TOAST_NODE_VT = 0x1021D0FC      # vtable FixedSafeString<64> finale du nœud
    _TOAST_TYPE = 0xA                # message à placeholder {item} (redirigé)
    # offsets reqMgr : sentinel {next=head @+0x14C, prev=tail @+0x150}, count, freelist, cap
    _TOAST_SENT, _TOAST_TAIL = 0x14C, 0x150
    _TOAST_COUNT, _TOAST_FREE, _TOAST_CAP = 0x154, 0x158, 0x160
    # Le bandeau reste ~3 s à l'écran ET le texte (string MSBT partagée) est re-résolu pendant
    # l'affichage : écrire le suffixe « xN » du bandeau suivant trop tôt le fait FUIR sur le
    # bandeau encore affiché (élixir montrant la qty d'un autre item — constat 2026-07-14).
    _TOAST_MIN_INTERVAL = 5.0
    # — redirection MSBT (mêmes constantes que tools/toast_msbt_redirect.py) —
    _TOAST_NEEDLES = ("Vous avez lâché".encode("utf-16-be"),
                      "Vous avez gagné".encode("utf-16-be"))   # vanilla / ancien patch-mot
    _TOAST_VICTIM_MARK = "TESHEIKAHSLATE".encode("utf-16-be")  # placeholder dev (~0xC6 o)
    _TOAST_PREFIX = "Vous avez reçu ".encode("utf-16-be")
    _TOAST_TAG_NOART = bytes.fromhex("000E00C900040000")       # {201,4} : nom sans article
    _TOAST_TAG_ITEM = (bytes.fromhex("000E0002000B001C0018")
                       + "UiInfoString".encode("utf-16-be") + b"\x00\x00")
    _TOAST_DOT_NUL = ".".encode("utf-16-be") + b"\x00\x00"

    def _toast_rd32(self, guest: int) -> int:
        raw = self._read(self._heap_base + guest, 4) if self._heap_base else None
        return struct.unpack(">I", raw)[0] if raw else 0

    def _toast_wr32(self, guest: int, val: int) -> bool:
        return self._write(self._heap_base + guest, struct.pack(">I", val & 0xFFFFFFFF))

    def _toast_locate(self) -> Optional[int]:
        """Localise (cache session) le request manager du HUD ; revalidé par sa capacité."""
        if self._toast_reqmgr and self._toast_rd32(self._toast_reqmgr + self._TOAST_CAP) == 3:
            return self._toast_reqmgr
        self._toast_reqmgr = None
        reg = self._toast_rd32(self._TOAST_REG_PTR)
        arr = self._toast_rd32(reg + 0x18) if reg else 0
        hud = self._toast_rd32(arr + self._TOAST_HUD_ID * 4) if arr else 0
        mgr = self._toast_rd32(hud + self._TOAST_REQMGR_OFF) if hud else 0
        if mgr and self._toast_rd32(mgr + self._TOAST_CAP) == 3:
            self._toast_reqmgr = mgr
        return self._toast_reqmgr

    def _toast_prepare(self) -> None:
        """Thread de préparation (1×/session) : dérive heap_base si absent, localise le
        MSBT en RAM (scan needle → header MsgStdBn → TXT2), écrit la phrase custom dans
        la string placeholder de dev et REDIRIGE l'offset du message 0xA dessus. Scans
        lourds (~1 min au pire) — les toasts s'accumulent dans _toast_pending en attendant."""
        try:
            if self._heap_base is None:
                nodes = self._scan_pouch_nodes()
                self._heap_base = self._derive_heap_base(nodes) if nodes else None
            if self._heap_base is None:
                log.info("[Toast] base heap indisponible — bandeaux désactivés cette session")
                self._toast_msbt = {}
                return
            hit = None
            chunk_sz = 16 << 20
            for base, size in self._iter_regions():
                off = 0
                while off < size and hit is None:
                    n = min(chunk_sz, size - off)
                    chunk = self._read(base + off, min(n + 0x40, size - off))
                    if chunk:
                        for needle in self._TOAST_NEEDLES:
                            i = chunk.find(needle)
                            if 0 <= i < n:
                                hit = base + off + i
                                break
                    off += n
                if hit is not None:
                    break
            if hit is None:
                log.info("[Toast] string MSBT introuvable (langue ≠ FR ?) — texte vanilla")
                self._toast_msbt = {}
                return
            # header MsgStdBn en amont, puis section TXT2
            hdr = None
            for back in range(0, 4 << 20, 0x10000):
                lo = hit - back - 0x10000
                blob = self._read(lo, 0x10010) or b""
                i = blob.rfind(b"MsgStdBn")
                if i >= 0:
                    hdr = lo + i
                    break
            if hdr is None:
                raise RuntimeError("header MsgStdBn introuvable")
            nsec, = struct.unpack(">H", self._read(hdr + 14, 2))
            off, txt2, txt2_size = 0x20, None, 0
            for _ in range(nsec):
                sh = self._read(hdr + off, 8) or b""
                magic, size = sh[:4], struct.unpack(">I", sh[4:8])[0]
                if magic == b"TXT2":
                    txt2, txt2_size = hdr + off + 0x10, size
                    break
                off = (off + 0x10 + size + 0xF) & ~0xF
            if txt2 is None:
                raise RuntimeError("section TXT2 introuvable")
            count, = struct.unpack(">I", self._read(txt2, 4))
            offs = struct.unpack(f">{count}I", self._read(txt2 + 4, 4 * count))
            toast_idx = victim_idx = None
            for k in range(count):
                head = self._read(txt2 + offs[k], 0x20) or b""
                if toast_idx is None and any(head.startswith(nd[:0x20])
                                             for nd in self._TOAST_NEEDLES):
                    toast_idx = k
                if victim_idx is None and head.startswith(self._TOAST_VICTIM_MARK[:0x20]):
                    victim_idx = k
            if toast_idx is not None and victim_idx is None:
                # zone victime déjà réécrite par une session précédente du client (même
                # boot de Cemu). Redirection active → la victime est l'entrée (≠ toast)
                # qui partage l'offset du toast ; sinon, celle qui porte notre préfixe.
                for k in range(count):
                    if k == toast_idx:
                        continue
                    if offs[k] == offs[toast_idx]:
                        victim_idx = k
                        break
                    head = self._read(txt2 + offs[k], len(self._TOAST_PREFIX)) or b""
                    if head == self._TOAST_PREFIX:
                        victim_idx = k
                        break
            if toast_idx is None or victim_idx is None:
                raise RuntimeError(f"entrées TXT2 introuvables ({toast_idx}/{victim_idx})")
            victim = txt2 + offs[victim_idx]
            vic_end = offs[victim_idx + 1] if victim_idx + 1 < count else txt2_size
            budget = vic_end - offs[victim_idx]
            fixed = self._TOAST_PREFIX + self._TOAST_TAG_NOART + self._TOAST_TAG_ITEM
            if len(fixed) + 0x10 > budget:
                raise RuntimeError(f"budget victime trop petit (0x{budget:X})")
            m = {
                "entry": txt2 + 4 + 4 * toast_idx,
                "entry_val": offs[victim_idx],
                "victim": victim,
                "fixed": fixed,          # préfixe+tags du mode « reçu » (réécrit à chaque bandeau)
                "budget": budget,
                "written": b"",          # dernier contenu écrit (revalidation reload MSBT)
            }
            self._toast_write_victim(m, fixed + self._TOAST_DOT_NUL)
            self._write(txt2 + 4 + 4 * toast_idx, struct.pack(">I", offs[victim_idx]))
            self._toast_msbt = m
            log.info("[Toast] message custom installé (MSBT @0x%012X, victime idx %d)",
                     hdr, victim_idx)
        except Exception as exc:                       # le toast ne doit JAMAIS casser le client
            log.debug("[Toast] préparation échouée: %s", exc)
            self._toast_msbt = {}

    def _toast_start_prep(self) -> None:
        if self._toast_prep_thread is None or not self._toast_prep_thread.is_alive():
            self._toast_prep_thread = threading.Thread(
                target=self._toast_prepare, name="toast-prep", daemon=True)
            self._toast_prep_thread.start()

    def _toast_write_victim(self, m: dict, payload: bytes) -> bool:
        """Écrit `payload` dans la zone victime, TOUJOURS paddée sur tout le budget (NUL) —
        aucun résidu d'un message précédent plus long. Mémorise le contenu (revalidation)."""
        data = payload[:m["budget"] - 2].ljust(m["budget"], b"\x00")
        if not self._write(m["victim"], data):
            return False
        m["written"] = data
        return True

    def toast_enqueue(self, actor_name: str, qty: int = 1) -> None:
        """File un bandeau « Vous avez reçu <item> xN. » (émis par toast_pump, throttlé).
        Lance la préparation (heap_base + redirection MSBT) au premier appel."""
        if not actor_name:
            return
        self._toast_pending.append({"actor_name": actor_name, "qty": max(1, int(qty))})
        if self._toast_msbt is None:
            self._toast_start_prep()

    def toast_enqueue_text(self, text: str) -> None:
        """File un bandeau à TEXTE LIBRE (ex. « Master Sword envoyé à Bob. ») — même canal
        MessageGet que les « reçus », même throttle. Nécessite la redirection MSBT (sinon le
        bandeau afficherait le texte vanilla) → silencieusement ignoré si non préparée après
        coup (toast_pump saute les entrées texte quand _toast_msbt == {})."""
        if not text:
            return
        self._toast_pending.append({"text": text})
        if self._toast_msbt is None:
            self._toast_start_prep()

    def toast_pump(self) -> None:
        """Émet AU PLUS UN bandeau en attente (appelé à chaque cycle poll/flush).
        Best-effort intégral : tout état inattendu = on retentera au cycle suivant."""
        if not self._toast_pending or self._toast_msbt is None:
            return                                    # rien à faire / préparation en cours
        if time.monotonic() - self._toast_last_push < self._TOAST_MIN_INTERVAL:
            return
        m = self._toast_msbt
        if not m:
            # Redirection MSBT indisponible (langue ≠ FR…) : les bandeaux « reçu » passent en
            # texte vanilla ; les bandeaux TEXTE LIBRE, eux, sont impossibles → on les purge.
            while self._toast_pending and "text" in self._toast_pending[0]:
                self._toast_pending.popleft()
            if not self._toast_pending:
                return
        else:                                         # revalide la redirection (rechargeable)
            entry = self._read(m["entry"], 4)
            cur = self._read(m["victim"], 16)
            if not entry or struct.unpack(">I", entry)[0] != m["entry_val"] \
                    or not m["written"] or cur != m["written"][:16]:
                self._toast_msbt = None               # MSBT rechargé → re-préparation
                self._toast_start_prep()
                return
        if self.push_toast(**self._toast_pending[0]):
            self._toast_pending.popleft()

    def push_toast(self, actor_name: str = "", qty: int = 1,
                   text: Optional[str] = None) -> bool:
        """Affiche le bandeau natif MessageGet. Deux modes :
          - actor_name/qty : « Vous avez reçu <item localisé> xN. » (tag résolu par le jeu) ;
          - text : message COMPLET à texte libre (aucun tag — ex. « X envoyé à Y. »).
        True si enfilé. Exige la file AU REPOS (vide, freelist saine) — sinon échec silencieux."""
        try:
            if not self.is_attached or self._heap_base is None:
                return False
            if text is not None and not self._toast_msbt:
                return True                           # texte libre impossible sans redirection → drop
            mgr = self._toast_locate()
            if not mgr:
                return False
            # message écrit AVANT l'enqueue — la victime est réécrite EN ENTIER à chaque bandeau
            # (mode « reçu » : préfixe+tags+suffixe qty ; mode texte : la phrase complète)
            if self._toast_msbt:
                m = self._toast_msbt
                if text is not None:
                    payload = text.encode("utf-16-be", "replace") + b"\x00\x00"
                else:
                    sfx = (f" x{qty}".encode("utf-16-be") if qty > 1 else b"") + self._TOAST_DOT_NUL
                    payload = m["fixed"] + sfx
                if not self._toast_write_victim(m, payload):
                    return False
            sent = mgr + self._TOAST_SENT
            head = self._toast_rd32(sent)
            tail = self._toast_rd32(mgr + self._TOAST_TAIL)
            count = self._toast_rd32(mgr + self._TOAST_COUNT)
            node = self._toast_rd32(mgr + self._TOAST_FREE)
            if head != sent or tail != sent or count != 0 \
                    or not (0x02000000 <= node < 0x80000000) or node % 4:
                return False                          # toast du jeu en cours / état inattendu
            name = (actor_name or "AP").encode("ascii", "ignore")[:0x3F].ljust(0x40, b"\x00")
            # nom d'actor au contexte (consommé par le refresh de l'écran)
            ctx = self._toast_rd32(self._TOAST_CTX_PTR)
            if ctx and self._toast_rd32(ctx + 0x20) == ctx + 0x2C:
                self._write(self._heap_base + ctx + 0x2C, name)
            # enqueue natif (FUN_02ed1f7c) — publication head/count en dernier
            self._toast_wr32(mgr + self._TOAST_FREE, self._toast_rd32(node))
            self._toast_wr32(node + 0x00, self._TOAST_TYPE)
            self._toast_wr32(node + 0x04, node + 0x10)
            self._toast_wr32(node + 0x08, self._TOAST_NODE_VT)
            self._toast_wr32(node + 0x0C, 0x40)
            self._write(self._heap_base + node + 0x10, name)
            self._write(self._heap_base + node + 0x50, b"\x00")
            self._toast_wr32(node + 0x58, sent)       # link.prev = sentinel
            self._toast_wr32(node + 0x54, head)       # link.next = sentinel (file vide)
            self._toast_wr32(head + 4, node + 0x54)   # tail = link
            self._toast_wr32(sent, node + 0x54)       # head = link (publication)
            self._toast_wr32(mgr + self._TOAST_COUNT, count + 1)
            uiroot = self._toast_rd32(self._TOAST_UIROOT_PTR)
            if uiroot:
                w = self._toast_rd32(uiroot + self._TOAST_DIRTY_OFF)
                self._toast_wr32(uiroot + self._TOAST_DIRTY_OFF, w | 1)
            self._toast_last_push = time.monotonic()
            if text is not None:
                log.info("[Toast] bandeau natif (texte) : %s", text)
            else:
                log.info("[Toast] bandeau natif : %s x%d", actor_name, qty)
            return True
        except Exception as exc:
            log.debug("[Toast] push échoué: %s", exc)
            return False

    # ── Flag read/write ───────────────────────────────────────────────────────

    def _find_flag_offset(self, flag_id: int) -> Optional[int]:
        """Binary search dans le buffer mémoire. Retourne l'offset depuis gd_base.
        Revalide header + canari à CHAQUE accès (1 lecture de 140 o) : un buffer gd réalloué
        par le jeu est détecté ici → invalidation au lieu d'un write dans la mémoire recyclée."""
        if not self.is_attached:
            return None
        head = self._read(self._gd_base, 12 + 16 * 8)
        if head is None or not self._gd_head_ok(head):
            self._invalidate_gd()
            return None
        n = (SAVE_SIZE - 12) // 8
        needle = struct.pack(">I", flag_id)
        lo, hi = 0, n - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            off = 12 + mid * 8
            chunk = self._read(self._gd_base + off, 4)
            if chunk is None:
                return None
            if chunk == needle:
                return off
            elif chunk < needle:
                lo = mid + 1
            else:
                hi = mid - 1
        return None

    def read_gamedata(self) -> Optional[bytes]:
        """Lit TOUT le buffer game_data EN MÉMOIRE (même format que le fichier save). Permet au
        provider de détecter les checks SANS ouvrir game_data.sav → ne bloque plus les autosaves
        de Cemu (cause du 'FSC: File create failed' → crash au reload).
        Valide header + canari : un buffer réalloué (load/nouvelle partie) rendrait des données
        recyclées → checks fantômes. Invalidé → repli fichier, ré-attache auto ensuite."""
        if not self.is_attached:
            return None
        raw = self._read(self._gd_base, SAVE_SIZE)
        if raw is not None and not self._gd_head_ok(raw[:12 + 16 * 8]):
            self._invalidate_gd()
            return None
        return raw

    def read_flag(self, flag_name: str) -> Optional[int]:
        """Lit la valeur d'un flag par son nom."""
        fid = zlib.crc32(flag_name.encode("ascii")) & 0xFFFFFFFF
        off = self._find_flag_offset(fid)
        if off is None:
            return None
        raw = self._read(self._gd_base + off + 4, 4)
        return struct.unpack(">I", raw)[0] if raw else None

    def write_flag(self, flag_name: str, value: int) -> bool:
        """Ecrit la valeur d'un flag directement en mémoire."""
        fid = zlib.crc32(flag_name.encode("ascii")) & 0xFFFFFFFF
        off = self._find_flag_offset(fid)
        if off is None:
            log.warning("[Mem] Flag %s (0x%08X) introuvable", flag_name, fid)
            return False
        ok = self._write(self._gd_base + off + 4,
                          struct.pack(">I", value & 0xFFFFFFFF))
        if ok:
            log.debug("[Mem] %s = %d", flag_name, value)
        return ok

    def read_flag_f32(self, flag_name: str) -> Optional[float]:
        """Lit un flag GameData de type f32 (ex: StaminaMax). None si absent."""
        raw = self.read_flag(flag_name)
        if raw is None:
            return None
        return struct.unpack(">f", struct.pack(">I", raw))[0]

    def write_flag_f32(self, flag_name: str, value: float) -> bool:
        """Écrit un flag GameData de type f32 (bits float en big-endian)."""
        bits = struct.unpack(">I", struct.pack(">f", value))[0]
        return self.write_flag(flag_name, bits)

    def add_s32_flag(self, flag_name: str, amount: int) -> bool:
        """Incrémente un compteur S32 (ex: DungeonClearSealNum, CurrentRupee)."""
        current = self.read_flag(flag_name)
        if current is None:
            return False
        signed = struct.unpack(">i", struct.pack(">I", current))[0]
        new_val = max(0, signed + amount)
        ok = self.write_flag(flag_name, new_val)
        if ok and flag_name == "DungeonClearSealNum":
            # Orbe : le jeu reverte ce compteur → on mémorise la cible (cumulatif) pour la
            # re-asserter chaque poll (maintain_persistent) et la banker dans la save.
            self._seal_target = max(self._seal_target or 0, new_val)
        return ok

    # ── PouchItem injection ───────────────────────────────────────────────────

    _PORCH_ID      = zlib.crc32(b"PorchItem")        & 0xFFFFFFFF  # 0x5F283289
    _PORCH_VAL1_ID = zlib.crc32(b"PorchItem_Value1") & 0xFFFFFFFF  # 0x6A09FC59
    _PORCH_SLOTS        = 420
    _PORCH_NAME_ENTRIES = 16

    def _find_first_in_memory(self, flag_id: int) -> Optional[int]:
        """Comme _find_flag_offset mais remonte à la PREMIERE occurrence."""
        off = self._find_flag_offset(flag_id)
        if off is None:
            return None
        needle = struct.pack(">I", flag_id)
        # Remonte
        while off >= 12 + 8:
            prev = self._read(self._gd_base + off - 8, 4)
            if prev == needle:
                off -= 8
            else:
                break
        return off

    def add_porch_item(self, item_name: str, amount: int) -> bool:
        """
        Ajoute `amount` au slot PouchItem correspondant à item_name.
        Crée le slot si l'item n'est pas encore en inventaire.
        """
        fp = self._find_first_in_memory(self._PORCH_ID)
        fv = self._find_first_in_memory(self._PORCH_VAL1_ID)
        if fp is None or fv is None:
            log.warning("[Mem] PorchItem arrays introuvables")
            return False

        name_enc = item_name.encode("ascii") + b"\x00"
        padded   = (name_enc + b"\x00" * 64)[:64]

        target_slot = -1
        empty_slot  = -1

        for slot in range(self._PORCH_SLOTS):
            # Lire le nom du slot (16 entrées × 4 bytes = 64 bytes)
            raw = bytearray()
            for i in range(self._PORCH_NAME_ENTRIES):
                chunk = self._read(
                    self._gd_base + fp + (slot * self._PORCH_NAME_ENTRIES + i) * 8 + 4, 4
                )
                raw += chunk or b"\x00\x00\x00\x00"
            slot_name = raw.split(b"\x00")[0].decode("ascii", errors="replace")

            if slot_name == item_name:
                target_slot = slot
                break
            if slot_name == "" and empty_slot < 0:
                empty_slot = slot

        if target_slot < 0 and empty_slot < 0:
            log.warning("[Mem] Inventaire plein, pas de slot pour %s", item_name)
            return False

        if target_slot < 0:
            # Nouveau slot — écrire le nom
            target_slot = empty_slot
            for i in range(self._PORCH_NAME_ENTRIES):
                chunk = padded[i*4:(i+1)*4]
                self._write(
                    self._gd_base + fp + (target_slot * self._PORCH_NAME_ENTRIES + i) * 8 + 4,
                    chunk,
                )
            current = 0
        else:
            # Lire quantité actuelle
            raw_val = self._read(self._gd_base + fv + target_slot * 8 + 4, 4)
            current = struct.unpack(">I", raw_val)[0] if raw_val else 0

        new_val = max(0, current + amount)
        val_addr = self._gd_base + fv + target_slot * 8 + 4
        ok = self._write(val_addr, struct.pack(">I", new_val & 0xFFFFFFFF))
        if ok:
            log.info("[Mem] PouchItem %s: %d -> %d", item_name, current, new_val)
        return ok

    # ── Création LIVE d'un nouvel item (insertion dans la liste PauseMenuDataMgr) ──
    # CADRAGE CORRIGÉ (2026-06-14, via hexdump) : le VRAI début de nœud est 0x20 AVANT le
    # motif du nom (FixedSafeString @+0x20). Le header PouchItem (vtable/liens/type/value)
    # précède le nom. Offsets depuis le vrai début S = (motif - 0x20) :
    _NODE_HEADER_OFF = 0x20    # le motif "10 ?? ?? ?? 00 00 00 40" est à +0x20 du vrai début
    _NODE_OFF_VTABLE = 0x00    # vtable PouchItem 0x1021B5D4
    _POUCH_VTABLE = 0x1021B5D4  # vtable de la classe PouchItem (à +0x00 d'un nœud BIEN cadré)
    _NODE_OFF_NEXT = 0x04
    _NODE_OFF_PREV = 0x08
    _NODE_OFF_TYPE = 0x0C
    _NODE_OFF_SUB  = 0x10
    _NODE_OFF_VAL  = 0x14
    _NODE_OFF_EQUIPPED = 0x18  # bool mEquipped (+ mInInventory) — 0 = non équipé
    _NODE_OFF_SEC  = 0x1C      # liste secondaire (intrusive) : champ "next"
    _NODE_OFF_SECHOOK = 0x28   # cible des pointeurs de la liste secondaire (= région du nom, vérifié hexdump)
    _NODE_OFF_NAME = 0x28      # buffer du FixedSafeString

    def _scan_pouch_nodes(self, inv_base: Optional[int] = None) -> list[dict]:
        """Liste les nœuds PouchItem (host=vrai début, name, type, sub, raw 0x220).

        On détecte toujours le motif du nom (FixedSafeString), mais on cadre le nœud sur
        son vrai début (motif - 0x20) pour lire type/value/liens du BON item.
        `inv_base` explicite : scanne un buffer candidat AVANT de l'adopter (validation de
        couple à la localisation) ; par défaut = self._inv_base (buffer courant)."""
        base = inv_base if inv_base is not None else self._inv_base
        if base is None:
            return []
        nodes = []
        for slot in range(self._PORCH_SLOTS):
            a = base + slot * _ITEM_STRIDE          # position du motif (nom)
            head = self._read(a, 8)
            if not self._matches_item_pattern(head):
                break
            host = a - self._NODE_HEADER_OFF                  # vrai début du nœud
            raw = self._read(host, _ITEM_STRIDE)
            if not raw:
                break
            name = raw[self._NODE_OFF_NAME:self._NODE_OFF_NAME + 40] \
                .split(b"\x00")[0].decode("ascii", errors="replace")
            typ = struct.unpack_from(">I", raw, self._NODE_OFF_TYPE)[0]
            sub = struct.unpack_from(">I", raw, self._NODE_OFF_SUB)[0]
            nodes.append(dict(slot=slot, host=host, name=name, type=typ, sub=sub, raw=raw))
        return nodes

    def _count_selfref(self, nodes: list[dict], base: int) -> int:
        """Nombre de nœuds dont le pointeur interne +0x64 est cohérent avec `base`."""
        return sum(1 for n in nodes
                   if self._node_is_selfref(n["raw"], n["host"] - base))

    def _derive_heap_base(self, nodes: list[dict]) -> Optional[int]:
        """cemu_mem_base tel que guest = host - base.

        Candidats par DEUX voies, puis on RETIENT celui qui maximise la cohérence interne
        (nb de nœuds self-ref via les pointeurs du nom) :
          1. SELF-POINTER (+0x1C) : chaque nœud (même LIBRE) porte le pointeur de buffer de sa
             FixedSafeString → node_guest+0x28. b = host + 0x28 − mot(+0x1C) — EXACT dès UN
             nœud. Indispensable sur une poche quasi-vide (save neuve, 1-2 items) où
             l'adjacence n'a qu'un couple et dérivait une base GARBAGE (guests négatifs →
             wallet « hors mapping », créations impossibles — bug du 2026-07-14).
          2. ADJACENCE tableau/liste (next @+0x04 / prev @+0x08 du VRAI début) — historique.
        Filtre de PLAUSIBILITÉ : les guests sont des u32 de heap → on rejette tout candidat
        plaçant le 1er nœud hors [0x02000000, 4 Gio) (élimine les bases garbage d'adjacence)."""
        from collections import Counter
        if not nodes:
            return None
        cands: Counter = Counter()
        for n in nodes:
            # self-pointer du nom : mot(+0x1C) == node_guest + 0x28 sur tout nœud bien formé
            w = struct.unpack_from(">I", n["raw"], self._NODE_OFF_SEC)[0]
            cands[n["host"] + self._NODE_OFF_NAME - w] += 1
        for i in range(len(nodes) - 1):
            nxt = struct.unpack_from(">I", nodes[i]["raw"], self._NODE_OFF_NEXT)[0]
            cands[nodes[i + 1]["host"] + self._NODE_OFF_NEXT - nxt] += 1
            prv = struct.unpack_from(">I", nodes[i + 1]["raw"], self._NODE_OFF_PREV)[0]
            cands[nodes[i]["host"] + self._NODE_OFF_NEXT - prv] += 1
        h0 = nodes[0]["host"]
        plausible = [b for b in cands if 0x02000000 <= h0 - b < _GUEST_MAX]
        if not plausible:
            return None
        # candidat qui maximise les nœuds self-ref ; départage par fréquence de votes
        best = max(plausible, key=lambda b: (self._count_selfref(nodes, b), cands[b]))
        n_sr = self._count_selfref(nodes, best)
        if n_sr == 0:
            now = time.monotonic()
            if now - self._last_base_warn > 5.0:
                self._last_base_warn = now
                log.warning("[Mem] inventaire déplacé/réalloué (0 nœud self-ref sur %d) "
                            "— re-localisation", len(nodes))
            return None
        log.debug("[Mem] base tas 0x%X (%d/%d nœuds self-ref)", best, n_sr, len(nodes))
        return best

    @staticmethod
    def _node_is_selfref(raw: bytes, guest_base: int) -> bool:
        """Au moins 3 pointeurs internes de la structure du nom (>=0x20) retombent dans
        [guest_base, guest_base+stride) — robuste au cadrage exact."""
        cnt = 0
        for off in range(0x20, _ITEM_STRIDE, 4):
            w = struct.unpack_from(">I", raw, off)[0]
            if guest_base <= w < guest_base + _ITEM_STRIDE:
                cnt += 1
                if cnt >= 3:
                    return True
        return False

    def _load_templates(self) -> dict[str, dict]:
        try:
            raw = json.loads(self._template_store.read_text(encoding="utf-8"))
        except Exception:
            return {}
        # PURGE des templates PÉRIMÉS/MAL CADRÉS : d'anciennes captures (avant le fix de cadrage
        # 0x20) stockaient le nœud cadré au MOTIF du nom → vtable 0x1021B524 (FixedSafeString) à
        # l'offset 0x00 au lieu de la vtable PouchItem 0x1021B5D4, et un champ "type" lu dans les
        # octets du nom (clés aberrantes type=grand nombre). Cloner un tel template produit un nœud
        # malformé (le jeu le rejette à la réallocation → item invisible, ex: bouclier). On ne garde
        # que les entrées dont (a) la clé est un petit type valide 0..9 et (b) la vtable @0x00 est
        # bien celle du PouchItem. Les autres sont re-capturées proprement au prochain attach.
        clean: dict[str, dict] = {}
        for key, v in (raw.items() if isinstance(raw, dict) else []):
            if not (key.isdigit() and 0 <= int(key) <= 9):
                continue
            try:
                b = bytes.fromhex(v.get("hex", ""))
                if len(b) == _ITEM_STRIDE and \
                        struct.unpack_from(">I", b, self._NODE_OFF_VTABLE)[0] == self._POUCH_VTABLE:
                    clean[key] = v
            except Exception:
                continue
        if len(clean) != len(raw):
            log.info("[Mem] templates: %d périmé(s)/mal cadré(s) purgé(s) (re-capture au prochain "
                     "inventaire peuplé)", len(raw) - len(clean))
        return clean

    def _save_templates(self) -> None:
        try:
            self._template_store.parent.mkdir(parents=True, exist_ok=True)
            self._template_store.write_text(
                json.dumps(self._templates), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            log.debug("[Mem] sauvegarde templates impossible: %s", exc)

    def _auto_capture_templates(self) -> None:
        """Met en cache un nœud-template propre par type présent dans l'inventaire live.
        Appelé à chaque attach : jouer une fois avec des matériaux suffit à alimenter le
        cache, qui sert ensuite à créer ces types même sur une save vide."""
        if self._inv_base is None:
            return
        nodes = self._scan_pouch_nodes()
        if not nodes:
            return
        base = self._derive_heap_base(nodes)
        if base is None:
            return
        added = []
        for n in nodes:
            if not n["name"] or n["type"] >= 0x20 or n["sub"] == 0xA:
                continue  # type valide = 0..~9 ; >=0x20 (ou 0xFFFFFFFF) = nœud aberrant/libre
            g = n["host"] - base
            if not self._node_is_selfref(n["raw"], g):
                continue
            key = str(n["type"])
            if key in self._templates:
                continue
            self._templates[key] = {"base": g, "hex": n["raw"].hex()}
            added.append(n["type"])
        if added:
            self._save_templates()
            log.info("[Mem] Templates PouchItem mis en cache (types %s) — création live "
                     "possible même sur inventaire vide", sorted(set(added)))

    def live_create_item(self, item_name: str, item_type: int,
                          subtype: Optional[int] = None, value: int = 1,
                          cook_data: Optional[dict] = None) -> bool:
        """
        Crée un NOUVEL item live dans la poche (l'item ne doit pas déjà exister).
        Retourne True si l'insertion a réussi. Nécessite qu'au moins un item du même
        type soit déjà présent (sert de template). Sinon retourne False (fallback appelant).

        cook_data (plats/potions type 8 uniquement) : dict {heal, duration, price,
        effect_type, effect_level} écrit dans le bloc CookData (+0x68..+0x78). Un plat
        cuisiné ne s'empile JAMAIS (chaque assiette = un nœud, comme en jeu).
        """
        self._last_create_overflow = False       # signal « onglet plein » de CET appel
        if not self.has_live_inventory:
            return False
        if self._creates_suspended:
            return False                         # liste incohérente → attendre le reload
        # Suivi de l'ancre statique AVANT tout splice : poche réallouée → re-ciblée ; jeu en
        # plein load → création REPORTÉE (splicer une copie freed corrompt la mémoire recyclée).
        if not self._refresh_inv_from_static():
            log.debug("[Mem] (live) poche instable (load ?) — création %s reportée", item_name)
            return False
        # GARDE DUR : items gérés par le jeu (orbes) — jamais de création live (crash). Bump si présent.
        if item_name in _NO_LIVE_CREATE:
            return self.live_add_item_qty(item_name, value) is not None
        # Item DÉJÀ en poche : selon le type —
        #   EMPILABLE (flèches 2 / matériaux 7 / nourriture 8) → on incrémente la quantité ;
        #   objet-clé (9) → idempotent (on ne duplique pas) ;
        #   ÉQUIPEMENT UNIQUE (armes 0 / arcs 1 / boucliers 3 / armures 4-6) → on NE bump PAS
        #   (ça monterait la durabilité) : on continue pour créer un NOUVEAU slot (2e exemplaire).
        if self.live_find_item(item_name) is not None:
            if item_type in _STACKABLE_TYPES and cook_data is None:
                log.info("[Mem] (live) %s déjà présent — incrément quantité (+%d)", item_name, value)
                return self.live_add_item_qty(item_name, value) is not None
            if item_type == 9:
                return True                              # objet-clé déjà là → rien à faire
            # plat cuisiné (cook_data) déjà présent : on CONTINUE → nouveau nœud (2e assiette)
        nodes = self._scan_pouch_nodes()
        base = self._derive_heap_base(nodes) if nodes else None
        if base is None:
            # base périmée (inventaire déplacé/réalloué) → re-localise + réessaie une fois
            if self._relocate_inventory():
                nodes = self._scan_pouch_nodes()
                base = self._derive_heap_base(nodes) if nodes else None
            if base is None:
                return False

        def g2h(g): return g + base
        def h2g(h): return h - base

        def is_selfref(n):
            return self._node_is_selfref(n["raw"], h2g(n["host"]))

        # ── 1) CONTENU (clone) + ANCRE : OBLIGATOIREMENT un nœud live du MÊME type ──
        # SÛRETÉ : on n'insère QUE derrière un item du même type. Insérer après un type
        # différent met le nœud dans la mauvaise catégorie/liste -> crash + corruption
        # inter-catégories (constaté sur un objet-clé type 9 ancré derrière des matériaux).
        # Sans ancre du même type, on échoue -> voie save-fichier (le 1er item d'un type
        # arrive au rechargement, les suivants en live).
        selfref = [n for n in nodes if n["name"] and is_selfref(n)]
        # ONGLET VERROUILLÉ : une section de sacoche n'EXISTE pas tant que le joueur n'a jamais
        # possédé d'item de son onglet ; y splicer CORROMPT/CRASH (flèches sans arc constaté
        # 2026-07-03 ; plat sans aliment → crash Cemu 2026-07-14 sur save neuve). Le kit de
        # départ du mod (starter-kit, greffé sur Demo003_0·CommonFirst) devait tout débloquer
        # au socle de la tablette, mais cette entry ne JOUE PAS sur partie moddée (le rando
        # pré-valide démos d'intro + première tour → variante Common jouée) → garde GÉNÉRALE :
        # création reportée (retry auto, jamais perdue) tant qu'aucun item du même ONGLET
        # n'est en poche. Onglets : armes 0 · arcs/flèches 1-2 · boucliers 3 · armures 4-6 ·
        # matériaux 7 · nourriture 8 · objets-clés 9 (toujours OK : la tablette y est).
        _TAB_TYPES = {0: (0,), 1: (1, 2), 2: (1, 2), 3: (3,), 4: (4, 5, 6),
                      5: (4, 5, 6), 6: (4, 5, 6), 7: (7,), 8: (8,), 9: (9,)}
        tab = _TAB_TYPES.get(item_type, (item_type,))
        if not any(n["type"] in tab for n in selfref):
            log.info("[Mem] (live) onglet de sacoche (types %s) encore verrouillé — %s "
                     "reporté (retry auto au prochain ramassage)", tab, item_name)
            return False
        # CAPACITÉ D'ONGLET (armes 0 / arcs 1 / boucliers 3) : le jeu n'a que *PorchStockNum
        # slots (8/5/4 de base, +bénédictions Korok). Créer AU-DELÀ met l'onglet dans un état
        # illégal → inventaire désorganisé puis FREEZE (constaté 2026-07-14, rafale release-all :
        # des dizaines d'armes créées sur 8 slots). Au cap : _last_create_overflow signale
        # l'appelant (filler → converti en rubis ; progression companion → retenté quand un
        # slot se libère).
        if item_type in _TAB_CAP_FLAGS:
            cap = self.read_flag(_TAB_CAP_FLAGS[item_type])
            if not cap or not (0 < cap <= 60):          # flag absent/aberrant → base vanilla
                cap = _TAB_CAP_DEFAULTS[item_type]
            have = sum(1 for n in selfref if n["type"] == item_type)
            if have >= cap:
                self._last_create_overflow = True
                now = time.monotonic()
                if now - self._last_capfull_warn > 30.0:
                    self._last_capfull_warn = now
                    log.info("[Mem] (live) onglet plein (%d/%d, type %d) — création %s en "
                             "overflow", have, cap, item_type, item_name)
                return False
        # FENÊTRE CALME (anti-course ramassage, crashs 7e/8e runs) : la poche a changé depuis
        # notre dernier passage (ramassage joueur, réallocation) → on laisse le jeu finir son
        # insertion, création différée d'UN cycle. Nos propres créations remettent la
        # signature à jour en fin de splice → un batch de livraisons reste fluide.
        sig = tuple(n["name"] for n in nodes)
        if sig != self._last_pouch_sig:
            self._last_pouch_sig = sig
            log.debug("[Mem] (live) poche active — création %s différée d'un cycle", item_name)
            return False
        # INTÉGRITÉ de la liste (1×/4 s) : réciprocité next/prev + mCount sur la marche réelle.
        # Une liste incohérente = le précurseur des crashs « ramassage » → plus AUCUN splice
        # jusqu'au prochain RECHARGEMENT (le jeu reconstruit une liste propre depuis la save).
        now = time.monotonic()
        if now - self._last_integrity_check > 4.0:
            self._last_integrity_check = now
            if not self._list_integrity_ok(selfref, base):
                time.sleep(0.25)                       # peut-être une insertion du jeu EN COURS
                nodes2 = self._scan_pouch_nodes()
                selfref2 = [n for n in nodes2 if n["name"] and is_selfref(n)]
                if not selfref2 or not self._list_integrity_ok(selfref2, base):
                    self._creates_suspended = True
                    if not self._suspend_logged:
                        self._suspend_logged = True
                        log.error("[Mem] liste pouch INCOHÉRENTE — créations live SUSPENDUES "
                                  "jusqu'au prochain RECHARGEMENT de la save (items en file, "
                                  "rien n'est perdu)")
                    return False
        # ANCRE par ORDRE DE TRI (sortKey) : la poche est UNE liste chaînée triée par (type, puis
        # sortKey au sein du type). On insère à la position triée EXACTE (voir la détection de sens
        # ci-dessous). Insérer ailleurs désorganise l'inventaire → catégories fracturées / crash.
        _BIG = 1 << 30
        new_sk = self._sort_keys.get(item_name, _BIG)
        # Sécurité : matériau (type 7) sans sortKey connu (table absente/incomplète) → on ne sait pas
        # où l'insérer sans désorganiser → on REPORTE plutôt que risquer un crash.
        if item_type == 7 and new_sk == _BIG:
            log.debug("[Mem] (live) sortKey inconnu pour matériau %s — reporté (anti-désorganisation)", item_name)
            return False
        def _spos(n):
            return (n["type"], self._sort_keys.get(n["name"], _BIG))
        target = (item_type, new_sk)
        # ANCRE via l'ADJACENCE RÉELLE de la liste (PAS via notre table sortKey — elle diverge de
        # l'ordre du jeu : un matériau à sortKey inconnue est rangé au max, ou l'ordre interne d'un
        # type ne colle pas → `min{≥cible}` ancrait AU MILIEU des matériaux → bouclier type 3 coincé
        # entre deux type 7). On reconstruit les liens next(0x04) parmi les nœuds scannés (le champ
        # next d'un nœud pointe vers le +0x04 du suivant) et on cherche la PAIRE ADJACENTE (P→S) qui
        # ENCADRE la cible. La frontière de TYPE est sans ambiguïté (tout type>cible d'un côté, tout
        # type<cible de l'autre), donc ça place correctement même le 1er item d'une catégorie vide.
        by_next = {h2g(n["host"]) + self._NODE_OFF_NEXT: n for n in selfref}
        succ_of = {}                                   # node -> son successeur dans la liste (0x04)
        for n in selfref:
            s = by_next.get(struct.unpack_from(">I", n["raw"], self._NODE_OFF_NEXT)[0])
            if s is not None:
                succ_of[id(n)] = s
        # SENS DU TRI : constaté sur la 1re paire adjacente de clés différentes (défaut décroissant,
        # comme tous les dumps le montrent : flèches type 2 → armes type 0 en suivant 0x04).
        descending = True
        for n in selfref:
            s = succ_of.get(id(n))
            if s is not None and _spos(s) != _spos(n):
                descending = _spos(s) < _spos(n)
                break
        # PRÉDÉCESSEUR = le P d'une paire adjacente (P→S) telle que F tombe entre les deux :
        #   décroissant → _spos(P) ≥ cible > _spos(S) ;  croissant → _spos(P) ≤ cible < _spos(S).
        anchor = None
        for n in selfref:
            s = succ_of.get(id(n))
            if s is None:
                continue
            if (descending and _spos(n) >= target > _spos(s)) or \
               (not descending and _spos(n) <= target < _spos(s)):
                anchor = n
                break
        if anchor is None:
            # Frontière hors des paires scannées (F aux extrêmes, ou successeur non scanné) → repli
            # sur la borne par clé (moins fiable mais rare : F plus grand/petit que tout le scan).
            if descending:
                cands = [n for n in selfref if _spos(n) >= target]
                anchor = min(cands, key=_spos) if cands else None
            else:
                cands = [n for n in selfref if _spos(n) <= target]
                anchor = max(cands, key=_spos) if cands else None
        # ANCRE = un LINK (adresse guest du champ next du prédécesseur) : nœud → N_g+0x04 ;
        # SENTINELLE de l'OffsetList → S_g+0x00 (permet l'insertion en TÊTE/queue).
        anchor_link_g: Optional[int] = None
        anchor_name = ""
        if anchor is not None:
            anchor_link_g = h2g(anchor["host"]) + self._NODE_OFF_NEXT
            anchor_name = anchor["name"]
        elif selfref:
            # POCHE QUASI-VIDE (save neuve : 1-2 nœuds, ni paire encadrante ni borne — bug
            # 2026-07-14 « pas d'ancre triée … reporté » en boucle, paravoile incluse) :
            # on ancre sur la LISTE RÉELLE en marchant depuis la sentinelle — l'insertion en
            # tête (cible > tout) ou en queue (cible < tout) devient possible dès UN nœud.
            sent = self._find_list_sentinel(selfref, base)
            if sent is not None:
                anchor_link_g = self._find_insert_link(
                    sent, base, target, descending,
                    {h2g(n["host"]): n for n in selfref})
                anchor_name = "liste réelle (sentinelle)"
        if anchor_link_g is None:
            log.debug("[Mem] (live) pas d'ancre triée pour %s (sortKey=%s, desc=%s) — reporté",
                      item_name, new_sk, descending)
            return False
        # CONTENU (clone) : nœud live du MÊME type, le plus PROCHE en sortKey (icône/structure/clé de
        # tri cohérentes ; on évite les grillés sub=0xA), sinon le TEMPLATE caché du type.
        # NB sub VÉRIFIÉ sur nœuds naturels (2026-07-11) : plats CUISINÉS Item_Cook_* = sub 0x8,
        # GRILLÉS Item_Roast*/RoastFish = sub 0xA (l'ancienne note de juin disait l'inverse).
        # Pour un PLAT (cook_data) : idéal = cloner un autre plat sub 0x8 (bloc CookData déjà
        # conforme) — c'est ce que la préférence par défaut fait déjà.
        same_type = [n for n in selfref if n["type"] == item_type and n["sub"] != 0xA] \
            or [n for n in selfref if n["type"] == item_type]
        # CATÉGORIE VIDE = aucun nœud vivant de ce type. Le nœud sera créé + sérialisé (persiste),
        # mais la GRILLE UI ne rend le 1er item d'une catégorie vide qu'au prochain rechargement
        # (couche ksys::ui, cf. [[project_live_memory_injection]]). On l'expose pour un log clair
        # côté appelant (l'item n'est PAS perdu, juste visible au reload).
        self._last_create_empty_cat = not same_type
        sub_match = [n for n in same_type if subtype is not None and n["sub"] == subtype]
        pool = sub_match or same_type
        content = (min(pool, key=lambda n: abs(self._sort_keys.get(n["name"], _BIG) - new_sk))
                   if pool else None)
        retype = False
        if content is not None:
            content_raw, content_Tg = content["raw"], h2g(content["host"])
        elif item_type <= 6:
            # ÉQUIPEMENT sans exemplaire du MÊME type (catégorie vide, ex: 1er bouclier alors que
            # Link n'en a aucun) → on clone N'IMPORTE QUEL autre équipement VIVANT (arme/arc/bouclier/
            # armure : même classe PouchItem, même structure) et on le RE-TYPE. On PRÉFÈRE un nœud
            # VIVANT au template caché : un nœud vivant est TOUJOURS bien cadré et à jour, alors qu'un
            # template peut manquer. (Bug constaté : un template type-3 PÉRIMÉ masquait ce chemin →
            # bouclier cloné depuis un nœud malformé → rejeté à la réallocation → invisible.) Le
            # template ne sert QUE de dernier recours si Link n'a AUCUN équipement.
            gear = [n for n in selfref if n["name"] and n["type"] <= 6 and n["sub"] != 0xA]
            if gear:
                src = min(gear, key=lambda n: abs(self._sort_keys.get(n["name"], _BIG) - new_sk))
                content_raw, content_Tg = src["raw"], h2g(src["host"])
                retype = True                          # forcer le champ type au type cible
            else:
                tpl = self._templates.get(str(item_type))
                if not tpl:
                    log.debug("[Mem] (live) aucun équipement ni template pour %s — reporté", item_name)
                    return False
                content_raw, content_Tg = bytes.fromhex(tpl["hex"]), int(tpl["base"])
        else:
            # matériaux/nourriture (7/8) : pas de re-typage possible → template caché obligatoire.
            tpl = self._templates.get(str(item_type))
            if not tpl:
                log.debug("[Mem] (live) pas de template type %d pour %s — reporté", item_type, item_name)
                return False
            content_raw, content_Tg = bytes.fromhex(tpl["hex"]), int(tpl["base"])

        # ── 2) Nœud libre cible ──
        free = next((n for n in nodes if n["type"] == 0xFFFFFFFF and not n["name"]), None)
        if free is None:
            # Pool de nœuds libres épuisé : on le mémorise pour que l'appelant arrête de tenter
            # des créations pendant un cooldown (évite de marteler le scan), PAS définitivement —
            # la property pool_exhausted ré-autorise une tentative après _POOL_RETRY_COOLDOWN.
            self._pool_exhausted = True
            now = time.monotonic()
            self._pool_exhausted_at = now
            if now - self._last_freenode_warn > 5.0:
                self._last_freenode_warn = now
                log.warning("[Mem] (live) pool de nœuds libres épuisé — créations en attente "
                            "(repartiront après un reload)")
            return False

        F_h = free["host"]
        F_g = h2g(F_h)

        # ── 3) Clone + re-base des pointeurs internes auto-référents (content_Tg -> F_g) ──
        raw = bytearray(content_raw)
        for off in range(0, _ITEM_STRIDE, 4):
            w = struct.unpack_from(">I", raw, off)[0]
            if content_Tg <= w < content_Tg + _ITEM_STRIDE:
                struct.pack_into(">I", raw, off, F_g + (w - content_Tg))
        # identité
        nb = item_name.encode("ascii")[:63]; nb += b"\x00" * (64 - len(nb))
        raw[self._NODE_OFF_NAME:self._NODE_OFF_NAME + 64] = nb
        # VALEUR (VAL, 0x14) selon le type :
        #   EMPILABLE (flèches/matériaux/nourriture) → quantité voulue ;
        #   ARME/ARC/BOUCLIER (0/1/3) → durabilité = life × 100 (le pouch stocke la durabilité ×100 ;
        #     dump live confirmé : bouclier vie 12 → VAL 1200, épée vie 36 → VAL 3600) ;
        #   ARMURE (4/5/6) → 0 (état de base, pas de durabilité).
        if item_type in _STACKABLE_TYPES:
            struct.pack_into(">i", raw, self._NODE_OFF_VAL, value)
        elif item_type in (0, 1, 3):
            struct.pack_into(">i", raw, self._NODE_OFF_VAL, max(1, int(value)) * 100)
        elif item_type in (4, 5, 6):
            struct.pack_into(">i", raw, self._NODE_OFF_VAL, 0)
        if subtype is not None:
            struct.pack_into(">i", raw, self._NODE_OFF_SUB, subtype)   # ItemUse (bouclier=4, etc.)
        if retype:                                     # clone d'un autre équipement → re-typer
            struct.pack_into(">I", raw, self._NODE_OFF_TYPE, item_type)
        if cook_data is not None:
            # Bloc CookData : soin (quarts de cœur), durée (s), prix, effet {type f32
            # CookEffectId, -1.0 = aucun ; niveau f32}. Offsets décodés le 2026-07-10.
            struct.pack_into(">i", raw, _COOK_OFF_HEAL,     int(cook_data.get("heal", 0)))
            struct.pack_into(">i", raw, _COOK_OFF_DURATION, int(cook_data.get("duration", 0)))
            struct.pack_into(">i", raw, _COOK_OFF_PRICE,    int(cook_data.get("price", 2)))
            struct.pack_into(">f", raw, _COOK_OFF_EFFECT,   float(cook_data.get("effect_type", -1.0)))
            struct.pack_into(">f", raw, _COOK_OFF_LEVEL,    float(cook_data.get("effect_level", 0.0)))
        # Flag ÉQUIPÉ = OCTET à +0x18 (mEquipped). On l'efface, mais SANS toucher +0x19 (mInInventory,
        # doit rester 1). Dump live : non équipé = 0x00 01 00 00, équipé = 0x01 01 00 00. Effacer le
        # MOT entier mettait mInInventory=0 → l'item disparaissait de l'inventaire.
        raw[self._NODE_OFF_EQUIPPED] = 0

        # ── 4) Splice F juste après l'ancre A, dans la SEULE liste (OffsetList primaire) ──
        # IMPORTANT : il n'y a PAS de "liste secondaire". Le dump du nœud (544o) montre que
        # 0x1C est le POINTEUR DE BUFFER de la FixedSafeString du nom (-> 0x28), et 0x28 le
        # buffer du nom — PAS des liens de liste. L'ancien code splicait une fausse liste
        # secondaire à 0x1C/0x28 et CORROMPAIT le nom (=> "No Image" + inventaire cassé).
        # Le re-basing (étape 3) a déjà fixé F.0x1C -> F+0x28, on n'y touche plus.
        # RE-VALIDATION anti-crash : la liste `nodes` a été scannée au DÉBUT ; si le jeu a ALLOUÉ
        # ce nœud libre (ou déplacé l'ancre) entre-temps, écrire dessus corrompt la liste chaînée
        # du jeu → CRASH. Juste avant d'écrire, on revérifie que F est TOUJOURS libre (type 0xFFFF..)
        # et que l'ancre pointe toujours vers un nœud connu. Sinon on reporte (livré au poll suivant).
        f_now = self._read(F_h + self._NODE_OFF_TYPE, 4)
        if not f_now or struct.unpack(">I", f_now)[0] != 0xFFFFFFFF:
            log.debug("[Mem] (live) nœud libre alloué entre-temps — %s reporté", item_name)
            return False
        link_h = g2h(anchor_link_g)                       # champ next du prédécesseur (nœud/sentinelle)
        a_links = self._read(link_h, 4)
        if not a_links:
            return False
        old_next = struct.unpack(">I", a_links)[0]        # link du suivant (X_g+4) ou sentinelle (S_g)
        # Le suivant doit être PLAUSIBLE et lisible (son champ prev est à old_next+4) — sinon la
        # liste a bougé sous nos pieds → ne pas splicer (write sur pointeur périmé = crash).
        if not (0x02000000 <= old_next < _GUEST_MAX) or self._read(g2h(old_next), 8) is None:
            log.debug("[Mem] (live) ancre %s instable — %s reporté", anchor_name, item_name)
            return False
        struct.pack_into(">I", raw, self._NODE_OFF_NEXT, old_next)         # F.next = suivant
        struct.pack_into(">I", raw, self._NODE_OFF_PREV, anchor_link_g)    # F.prev = link prédécesseur

        ok = self._write(F_h, bytes(raw))
        ok &= self._write(link_h, struct.pack(">I", F_g + self._NODE_OFF_NEXT))
        # prev du suivant : old_next+4 (nœud → N_g+0x08 ; sentinelle → S_g+0x04 — même arithmétique)
        ok &= self._write(g2h(old_next) + 4, struct.pack(">I", F_g + self._NODE_OFF_NEXT))
        if ok:
            # mCount += 1 (sead::OffsetList, à tête+0x08) : le jeu COMPTE notre nœud -> il ne
            # réutilise plus ce nœud libre (plus de corruption en rafale) et le sérialise au
            # save (persistance fiable). Sentinelle = on suit la liste jusqu'à sortir du pool.
            bumped = self._bump_pouch_count(nodes, base, F_g)
            if cook_data is None:                     # cible qty à ré-asserter après réallocation
                self._qty_targets[item_name] = value  # (pas pour un plat : 1 nœud = 1 assiette)
            # la signature « fenêtre calme » intègre NOTRE création → le batch suivant du même
            # cycle n'est pas différé par notre propre changement (seuls les ramassages le sont)
            self._last_pouch_sig = tuple(n["name"] for n in self._scan_pouch_nodes())
            log.info("[Mem] (live) NOUVEL item %s (type=%d val=%d) insere apres %s%s",
                     item_name, item_type, value, anchor_name,
                     "" if bumped else "  (!! mCount NON incrémenté)")
        return bool(ok)

    def _find_list_sentinel(self, selfref: list, base: int) -> Optional[int]:
        """Adresse guest de la SENTINELLE (sead::OffsetList.mStartEnd {next@0, prev@4,
        mCount@8}) de la liste pouch active : suit next depuis un nœud self-ref jusqu'à
        sortir du pool scanné. Validation stricte : prev(S+4) == link du dernier nœud
        traversé (on est bien arrivé au BOUT), head plausible, mCount ∈ [0, 2000). Un nœud
        actif NON scanné rencontré en route échoue cette validation → None (reporté)."""
        node_links = {(n["host"] - base) + self._NODE_OFF_NEXT for n in selfref}
        cur = (selfref[0]["host"] - base) + self._NODE_OFF_NEXT
        for _ in range(2048):
            r = self._read(base + cur, 4)
            if not r:
                return None
            nxt = struct.unpack(">I", r)[0]
            if nxt in node_links:
                cur = nxt
                continue
            hdr = self._read(base + nxt, 12)          # candidat sentinelle : head, tail, count
            if not hdr or len(hdr) < 12:
                return None
            head, tail, cnt = struct.unpack(">IIi", hdr)
            if tail == cur and 0 <= cnt < 2000 and 0x02000000 <= head < _GUEST_MAX:
                return nxt
            return None
        return None

    def _list_integrity_ok(self, selfref: list, base: int) -> bool:
        """Marche la liste RÉELLE (sentinelle → sentinelle) et vérifie : réciprocité
        next/prev de CHAQUE maillon + mCount == nombre de nœuds traversés. Une liste
        incohérente (course avec un ramassage, splice raté, mémoire recyclée) est le
        précurseur des crashs « ramassage » des 7e/8e runs — on n'y splice PLUS RIEN."""
        sent = self._find_list_sentinel(selfref, base)
        if sent is None:
            return False
        cur, count = sent, 0
        for _ in range(600):
            r = self._read(base + cur, 4)
            if not r:
                return False
            nxt = struct.unpack(">I", r)[0]
            if not (0x02000000 <= nxt < _GUEST_MAX):
                return False
            r2 = self._read(base + nxt + 4, 4)          # prev du suivant doit repointer cur
            if not r2 or struct.unpack(">I", r2)[0] != cur:
                return False
            if nxt == sent:
                r3 = self._read(base + sent + 8, 4)     # mCount de la sentinelle
                cnt = struct.unpack(">i", r3)[0] if r3 else -1
                return count == cnt
            cur = nxt
            count += 1
        return False                                    # jamais rebouclé → cycle cassé

    def _find_insert_link(self, sentinel_g: int, base: int, target: tuple,
                          descending: bool, known_by_g: dict) -> Optional[int]:
        """Marche la liste RÉELLE depuis la sentinelle et renvoie le LINK (adresse guest du
        champ next) du PRÉDÉCESSEUR à la position triée de `target` — sentinelle elle-même
        pour une insertion en TÊTE, link du dernier nœud pour la QUEUE. Fonctionne dès UN
        nœud dans la liste (poche de save neuve). Nœud illisible/aberrant → None (reporté)."""
        _BIG = 1 << 30
        prev_link = sentinel_g
        r = self._read(base + sentinel_g, 4)
        if not r:
            return None
        link = struct.unpack(">I", r)[0]
        for _ in range(600):
            if link == sentinel_g:
                return prev_link                      # fin de liste → insertion en queue
            ng = link - self._NODE_OFF_NEXT
            n = known_by_g.get(ng)
            if n is not None:
                spos = (n["type"], self._sort_keys.get(n["name"], _BIG))
            else:                                     # nœud actif hors scan → lecture directe
                raw = self._read(base + ng, self._NODE_OFF_NAME + 40)
                if not raw or len(raw) < self._NODE_OFF_NAME + 40:
                    return None
                typ = struct.unpack_from(">I", raw, self._NODE_OFF_TYPE)[0]
                if typ > 0x20:                        # aberrant (libre dans la liste active ?)
                    return None
                name = raw[self._NODE_OFF_NAME:self._NODE_OFF_NAME + 40].split(b"\x00")[0] \
                    .decode("ascii", errors="replace")
                spos = (typ, self._sort_keys.get(name, _BIG))
            if (descending and spos < target) or (not descending and spos > target):
                return prev_link                      # insérer AVANT ce nœud
            prev_link = link
            r = self._read(base + link, 4)
            if not r:
                return None
            link = struct.unpack(">I", r)[0]
        return None

    def _bump_pouch_count(self, nodes: list, base: int, start_g: int) -> bool:
        """Suit la liste primaire depuis start_g jusqu'à la sentinelle (tête) et fait
        mCount += 1 (à tête+0x08). Garde-fou : n'écrit que si le compteur est plausible."""
        node_bases = {n["host"] - base for n in nodes}
        node_bases.add(start_g)
        cur = start_g
        for _ in range(2048):
            r = self._read(cur + base + self._NODE_OFF_NEXT, 4)
            if not r:
                return False
            nxt = struct.unpack(">I", r)[0]
            nb = nxt - self._NODE_OFF_NEXT
            if nb in node_bases:
                cur = nb
                continue
            # nxt = adresse de la sentinelle (tête) ; mCount à tête+0x08
            head_h = nxt + base
            cnt_r = self._read(head_h + 0x08, 4)
            if not cnt_r:
                return False
            cnt = struct.unpack(">i", cnt_r)[0]
            if not (0 <= cnt < 2000):
                log.warning("[Mem] (live) mCount=%d implausible — non incrémenté", cnt)
                return False
            return self._write(head_h + 0x08, struct.pack(">i", cnt + 1))
        return False
