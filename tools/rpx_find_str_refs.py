"""
find_str_refs — offline : localise des strings dans .rodata du RPX v208 et trouve
(a) les sites .text qui les matérialisent en lis/addi (ou lis/ori),
(b) les pointeurs 32-bit directs vers elles dans .rodata / .data.

  python find_str_refs.py                 # jeu StockItem par défaut
  python find_str_refs.py "1_OpenWait" ...

Sections v208 : .text vaddr 0x02000000 (02_text.bin), .rodata vaddr 0x10000000
(03_rodata.bin). 04_data.bin : base inconnue ici -> hits rapportés en offset fichier.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TEXT_BASE = 0x02000000
RODATA_BASE = 0x10000000

DEFAULT = [
    "UI/StockItem/%s",
    "UI/StockItem/%s.bitemico",
    "StockItemIconExcanger.bat",
    "StockItemIconConvert.bat",
    "StockItem",
    "1_OpenWait",
]

_text = (ROOT / "tmp/rpx_v208/02_text.bin").read_bytes()
_rodata = (ROOT / "tmp/rpx_v208/03_rodata.bin").read_bytes()
_data = (ROOT / "tmp/rpx_v208/04_data.bin").read_bytes()

words = np.frombuffer(_text[: len(_text) - (len(_text) % 4)], dtype=">u4")
op = (words >> 26).astype(np.uint16)
f21_25 = ((words >> 21) & 31).astype(np.uint8)   # rD (addi/addis) ou rS (ori)
f16_20 = ((words >> 16) & 31).astype(np.uint8)   # rA
uimm = (words & 0xFFFF).astype(np.uint32)

lis_mask = (op == 15) & (f16_20 == 0)            # addis rD, 0, SIMM
WINDOW = 96                                       # distance max lis -> addi/ori (instr)


def find_string_vaddrs(s: bytes) -> list[int]:
    """Occurrences de s comme DEBUT de C-string dans .rodata (byte précédent = 0)."""
    out = []
    start = 0
    while True:
        i = _rodata.find(s, start)
        if i < 0:
            break
        start = i + 1
        if i > 0 and _rodata[i - 1] != 0:
            continue
        # fin de string exacte (le needle peut être un préfixe d'une autre string)
        out.append(RODATA_BASE + i)
    return out


def text_sites(target: int) -> list[tuple[int, str]]:
    """Sites .text matérialisant `target` : (vaddr de l'addi/ori, 'lis@vaddr+forme')."""
    hits = []
    ha = ((target + 0x8000) >> 16) & 0xFFFF
    hi = (target >> 16) & 0xFFFF
    lo = target & 0xFFFF

    # lis positions par forme
    lis_ha = np.where(lis_mask & (uimm == ha))[0]
    lis_hi = np.where(lis_mask & (uimm == hi))[0] if hi != ha else np.array([], dtype=int)

    # addi rD, rA, simm : simm brut == lo (le ha compense le signe)
    addi_idx = np.where((op == 14) & (uimm == lo))[0]
    # ori rA, rS, uimm (rS = f21_25)
    ori_idx = np.where((op == 24) & (uimm == lo))[0] if lo else np.array([], dtype=int)

    lis_ha_set = {int(i): int(f21_25[i]) for i in lis_ha}
    lis_hi_set = {int(i): int(f21_25[i]) for i in lis_hi}

    for ai in addi_idx:
        ra = int(f16_20[ai])
        for j in range(max(0, ai - WINDOW), ai):
            if j in lis_ha_set and lis_ha_set[j] == ra:
                hits.append((TEXT_BASE + int(ai) * 4,
                             f"lis@0x{TEXT_BASE + j*4:08X}(ha)+addi"))
                break
    for oi in ori_idx:
        rs = int(f21_25[oi])
        for j in range(max(0, oi - WINDOW), oi):
            if j in lis_hi_set and lis_hi_set[j] == rs:
                hits.append((TEXT_BASE + int(oi) * 4,
                             f"lis@0x{TEXT_BASE + j*4:08X}(hi)+ori"))
                break
    return hits


def ptr_hits(target: int) -> tuple[list[int], list[int]]:
    """Pointeurs 32-bit BE directs : (vaddrs .rodata, offsets fichier .data)."""
    needle = struct.pack(">I", target)
    ro, da = [], []
    start = 0
    while True:
        i = _rodata.find(needle, start)
        if i < 0:
            break
        start = i + 1
        if i % 4 == 0:
            ro.append(RODATA_BASE + i)
    start = 0
    while True:
        i = _data.find(needle, start)
        if i < 0:
            break
        start = i + 1
        if i % 4 == 0:
            da.append(i)
    return ro, da


def main() -> None:
    targets = sys.argv[1:] or DEFAULT
    for t in targets:
        tb = t.encode("ascii")
        vaddrs = find_string_vaddrs(tb)
        print(f"\n=== {t!r} : {len(vaddrs)} occurrence(s) .rodata ===")
        for va in vaddrs:
            end = _rodata.find(b"\x00", va - RODATA_BASE)
            full = _rodata[va - RODATA_BASE:end].decode("ascii", "replace")
            print(f"  .rodata @0x{va:08X}  (string complète: {full!r})")
            sites = text_sites(va)
            for site, how in sites:
                print(f"    .text ref @0x{site:08X}  [{how}]")
            if not sites:
                print("    (aucun site lis/addi .text)")
            ro, da = ptr_hits(va)
            for p in ro:
                print(f"    ptr direct .rodata @0x{p:08X}")
            for off in da:
                print(f"    ptr direct .data  fileoff 0x{off:X}")


if __name__ == "__main__":
    main()
