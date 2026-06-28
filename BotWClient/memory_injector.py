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
import zlib
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
        # Cache local des templates PouchItem (par type) — survit aux sessions et permet
        # la création live même quand l'inventaire courant n'a aucun item du même type.
        self._template_store = template_store or (
            Path.home() / ".botwpelago" / "pouch_templates.json")
        self._templates: dict[str, dict] = self._load_templates()

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
        log.info("[Mem] game_data localise @ 0x%012X (pid=%d)", self._gd_base, self._pid)
        self._locate_live_inventory()
        self._auto_capture_templates()
        return True

    def detach(self) -> None:
        if self._handle:
            _k32.CloseHandle(self._handle)
            self._handle = None
        self._gd_base = None
        self._rupees_addr = None
        self._inv_base = None

    @property
    def has_live_inventory(self) -> bool:
        return self._inv_base is not None

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

    def _find_inventory_start(self, rupees_addr: int) -> Optional[int]:
        """Scanne la region contenant rupees_addr pour le tableau PouchItem (stride 544)."""
        region_base, region_size = None, None
        for base, size in self._iter_regions():
            if base <= rupees_addr < base + size:
                region_base, region_size = base, size
                break
        if region_base is None:
            return None

        off = 0
        best, best_score = None, -1
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
                        if s >= _EARLY_EXIT_SCORE:
                            return best
            off += n
        return best if best_score > 0 else None

    def _locate_live_inventory(self) -> None:
        """Trouve rupeesAddress + inventoryStartAddress live. Echec silencieux (fallback save-file)."""
        for rupees_addr in self._find_rupees_addresses():
            inv_base = self._find_inventory_start(rupees_addr)
            if inv_base is not None:
                self._rupees_addr = rupees_addr
                self._inv_base = inv_base
                log.info("[Mem] Inventaire live localise @ 0x%012X (rupees @ 0x%012X)",
                         inv_base, rupees_addr)
                return
        log.info("[Mem] Inventaire live introuvable — injection PorchItem (save-file) uniquement")

    def _iter_inventory_slots(self, max_slots: int = 420):
        """Itere (slot, item_addr, item_id) sur le tableau PouchItem live."""
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
            log.warning("[Mem] (live) Item %s introuvable en inventaire", item_id)
            return None
        addr = item_addr - 19
        raw = self._read(addr, 4)
        current = struct.unpack(">i", raw)[0] if raw else 0
        new_val = max(0, current + amount)
        self._write(addr, struct.pack(">i", new_val & 0xFFFFFFFF))
        log.info("[Mem] (live) %s: %d -> %d", item_id, current, new_val)
        return new_val

    def live_get_rupees(self) -> Optional[int]:
        if self._rupees_addr is None:
            return None
        raw = self._read(self._rupees_addr, 4)
        return struct.unpack(">i", raw)[0] if raw else None

    def live_add_rupees(self, amount: int) -> Optional[int]:
        if self._rupees_addr is None:
            return None
        current = self.live_get_rupees()
        if current is None:
            return None
        new_val = max(0, current + amount)
        self._write(self._rupees_addr, struct.pack(">i", new_val))
        log.info("[Mem] (live) Rupees: %d -> %d", current, new_val)
        return new_val

    # ── Flag read/write ───────────────────────────────────────────────────────

    def _find_flag_offset(self, flag_id: int) -> Optional[int]:
        """Binary search dans le buffer mémoire. Retourne l'offset depuis gd_base."""
        if not self.is_attached:
            return None
        header = self._read(self._gd_base, 12)
        if header is None:
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

    def add_s32_flag(self, flag_name: str, amount: int) -> bool:
        """Incrémente un compteur S32 (ex: DungeonClearSealNum, CurrentRupee)."""
        current = self.read_flag(flag_name)
        if current is None:
            return False
        signed = struct.unpack(">i", struct.pack(">I", current))[0]
        new_val = max(0, signed + amount)
        return self.write_flag(flag_name, new_val)

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
    _NODE_OFF_NEXT = 0x04
    _NODE_OFF_PREV = 0x08
    _NODE_OFF_TYPE = 0x0C
    _NODE_OFF_SUB  = 0x10
    _NODE_OFF_VAL  = 0x14
    _NODE_OFF_SEC  = 0x1C      # liste secondaire (intrusive) : champ "next"
    _NODE_OFF_SECHOOK = 0x28   # cible des pointeurs de la liste secondaire (= région du nom, vérifié hexdump)
    _NODE_OFF_NAME = 0x28      # buffer du FixedSafeString

    def _scan_pouch_nodes(self) -> list[dict]:
        """Liste les nœuds PouchItem (host=vrai début, name, type, sub, raw 0x220).

        On détecte toujours le motif du nom (FixedSafeString), mais on cadre le nœud sur
        son vrai début (motif - 0x20) pour lire type/value/liens du BON item."""
        if self._inv_base is None:
            return []
        nodes = []
        for slot in range(self._PORCH_SLOTS):
            a = self._inv_base + slot * _ITEM_STRIDE          # position du motif (nom)
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

        On collecte des candidats par adjacence tableau/liste (next @+0x204 et prev @+0x208),
        puis on RETIENT celui qui maximise la cohérence interne (nb de nœuds self-ref via
        +0x64). L'adjacence seule échoue sur inventaire fragmenté (slot[i].next ≠ slot[i+1]) ;
        le critère self-ref tranche de façon fiable."""
        from collections import Counter
        cands: Counter = Counter()
        for i in range(len(nodes) - 1):
            nxt = struct.unpack_from(">I", nodes[i]["raw"], self._NODE_OFF_NEXT)[0]
            cands[nodes[i + 1]["host"] + self._NODE_OFF_NEXT - nxt] += 1
            prv = struct.unpack_from(">I", nodes[i + 1]["raw"], self._NODE_OFF_PREV)[0]
            cands[nodes[i]["host"] + self._NODE_OFF_NEXT - prv] += 1
        if not cands:
            return None
        # candidat qui maximise les nœuds self-ref ; départage par fréquence d'adjacence
        best = max(cands, key=lambda b: (self._count_selfref(nodes, b), cands[b]))
        n_sr = self._count_selfref(nodes, best)
        if n_sr == 0:
            log.warning("[Mem] base du tas douteuse (0 nœud self-ref sur %d)", len(nodes))
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
            return json.loads(self._template_store.read_text(encoding="utf-8"))
        except Exception:
            return {}

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
                          subtype: Optional[int] = None, value: int = 1) -> bool:
        """
        Crée un NOUVEL item live dans la poche (l'item ne doit pas déjà exister).
        Retourne True si l'insertion a réussi. Nécessite qu'au moins un item du même
        type soit déjà présent (sert de template). Sinon retourne False (fallback appelant).
        """
        if not self.has_live_inventory:
            return False
        # DÉFENSIF : si l'item est déjà en poche, on incrémente sa quantité au lieu de créer
        # un doublon (garantit "pas de double stack" même en appel direct).
        if self.live_find_item(item_name) is not None:
            log.info("[Mem] (live) %s déjà présent — incrément quantité (+%d)", item_name, value)
            return self.live_add_item_qty(item_name, value) is not None
        nodes = self._scan_pouch_nodes()
        if not nodes:
            return False
        base = self._derive_heap_base(nodes)
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
        same_type = [n for n in nodes if n["name"] and n["type"] == item_type and is_selfref(n)]
        if not same_type:
            log.info("[Mem] (live) pas d'item de type %d en poche pour ancrer %s "
                     "— fallback save-file", item_type, item_name)
            return False
        # éviter les plats cuisinés (sub=0xA) comme template (icône calculée depuis la recette)
        content = (
            (subtype is not None and next((n for n in same_type if n["sub"] == subtype), None))
            or next((n for n in same_type if n["sub"] != 0xA), None)
            or same_type[0]
        )
        content_raw, content_Tg = content["raw"], h2g(content["host"])
        anchor = content                              # splice après ce même nœud (même catégorie)

        # ── 2) Nœud libre cible ──
        free = next((n for n in nodes if n["type"] == 0xFFFFFFFF and not n["name"]), None)
        if free is None:
            log.warning("[Mem] (live) aucun nœud libre pour %s — fallback save-file", item_name)
            return False

        F_h = free["host"]
        F_g = h2g(F_h)
        A_h = anchor["host"]
        A_g = h2g(A_h)

        # ── 3) Clone + re-base des pointeurs internes auto-référents (content_Tg -> F_g) ──
        raw = bytearray(content_raw)
        for off in range(0, _ITEM_STRIDE, 4):
            w = struct.unpack_from(">I", raw, off)[0]
            if content_Tg <= w < content_Tg + _ITEM_STRIDE:
                struct.pack_into(">I", raw, off, F_g + (w - content_Tg))
        # identité
        nb = item_name.encode("ascii")[:63]; nb += b"\x00" * (64 - len(nb))
        raw[self._NODE_OFF_NAME:self._NODE_OFF_NAME + 64] = nb
        struct.pack_into(">i", raw, self._NODE_OFF_VAL, value)
        if subtype is not None:
            struct.pack_into(">i", raw, self._NODE_OFF_SUB, subtype)

        # ── 4) Splice F juste après l'ancre A, dans la SEULE liste (OffsetList primaire) ──
        # IMPORTANT : il n'y a PAS de "liste secondaire". Le dump du nœud (544o) montre que
        # 0x1C est le POINTEUR DE BUFFER de la FixedSafeString du nom (-> 0x28), et 0x28 le
        # buffer du nom — PAS des liens de liste. L'ancien code splicait une fausse liste
        # secondaire à 0x1C/0x28 et CORROMPAIT le nom (=> "No Image" + inventaire cassé).
        # Le re-basing (étape 3) a déjà fixé F.0x1C -> F+0x28, on n'y touche plus.
        a_links = self._read(A_h + self._NODE_OFF_NEXT, 4)
        if not a_links:
            return False
        A_next = struct.unpack(">I", a_links)[0]
        on_node_h = g2h(A_next - self._NODE_OFF_NEXT)                 # nœud suivant (liste primaire)
        struct.pack_into(">I", raw, self._NODE_OFF_NEXT, A_next)              # F.next = A.next
        struct.pack_into(">I", raw, self._NODE_OFF_PREV, A_g + self._NODE_OFF_NEXT)  # F.prev = &A.next

        ok = self._write(F_h, bytes(raw))
        ok &= self._write(A_h + self._NODE_OFF_NEXT, struct.pack(">I", F_g + self._NODE_OFF_NEXT))
        ok &= self._write(on_node_h + self._NODE_OFF_PREV, struct.pack(">I", F_g + self._NODE_OFF_NEXT))
        if ok:
            # mCount += 1 (sead::OffsetList, à tête+0x08) : le jeu COMPTE notre nœud -> il ne
            # réutilise plus ce nœud libre (plus de corruption en rafale) et le sérialise au
            # save (persistance fiable). Sentinelle = on suit la liste jusqu'à sortir du pool.
            bumped = self._bump_pouch_count(nodes, base, F_g)
            log.info("[Mem] (live) NOUVEL item %s (type=%d val=%d) insere apres %s%s",
                     item_name, item_type, value, anchor["name"],
                     "" if bumped else "  (!! mCount NON incrémenté)")
        return bool(ok)

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
