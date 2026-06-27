"""
inspect_save_porch — dump les entrées PorchItem (nom + quantité) d'une save disque.

Sert à voir ce qui est RÉELLEMENT persisté (fantômes, doublons, mauvais comptes).

Usage : python tools/inspect_save_porch.py <chemin game_data.sav>
        (sans arg : prend la plus récente du profil 80000002)
"""
from __future__ import annotations

import glob
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from BotWClient.save_parser import flag_id as crc32_id  # noqa: E402

PORCH = crc32_id("PorchItem")
PVAL = crc32_id("PorchItem_Value1")
SLOTS = 420
NAME_ENTRIES = 16


def first_run(data: bytes, fid: int) -> int:
    n = (len(data) - 12) // 8
    needle = struct.pack(">I", fid)
    lo, hi, res = 0, n - 1, -1
    while lo <= hi:
        mid = (lo + hi) // 2
        off = 12 + mid * 8
        cmp = data[off:off + 4]
        if cmp == needle:
            res = mid; hi = mid - 1
        elif cmp < needle:
            lo = mid + 1
        else:
            hi = mid - 1
    return res


def read_name(data, fp, slot):
    raw = bytearray()
    for i in range(NAME_ENTRIES):
        off = 12 + (fp + slot * NAME_ENTRIES + i) * 8 + 4
        raw += data[off:off + 4]
    return raw.split(b"\x00")[0].decode("ascii", errors="replace")


def main() -> None:
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        cands = glob.glob("/d/Emulateur/Cemu/cemu_1.18.1/mlc01/usr/save/00050000/"
                          "101c9500/user/80000002/*/game_data.sav")
        path = max(cands, key=os.path.getmtime) if cands else None
    if not path or not os.path.exists(path):
        print("save introuvable"); return
    data = open(path, "rb").read()
    print(f"save: {path}\n")
    fp = first_run(data, PORCH)
    fv = first_run(data, PVAL)
    if fp < 0 or fv < 0:
        print("PorchItem introuvable"); return
    print(" slot  qty   name")
    total = 0
    for slot in range(SLOTS):
        name = read_name(data, fp, slot)
        voff = 12 + (fv + slot) * 8 + 4
        val = struct.unpack_from(">i", data, voff)[0]
        if name or val:
            mark = "  <<<" if ("DungeonClearSeal" in name or "Ore_I" in name or not name) else ""
            print(f" {slot:>4}  {val:>4}  {name!r}{mark}")
            total += 1
    print(f"\n{total} entrées non vides")


if __name__ == "__main__":
    main()
