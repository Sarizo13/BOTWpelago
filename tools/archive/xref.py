"""
xref — trouve les instructions de branchement (bl/b absolu ou relatif) du .text v208
qui ciblent une adresse donnée. Sert à remonter les appelants (ex: callers de
createPorchItem / du constructeur de nœud PouchItem).

Usage : python tools/xref.py 0x02ead6cc
"""
from __future__ import annotations

import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT_BASE = 0x02000000
_text = open(os.path.join(ROOT, "tmp/rpx_v208/02_text.bin"), "rb").read()


def sign26(v: int) -> int:
    v &= 0x03FFFFFF
    return v - (1 << 26) if v & (1 << 25) else v


def main() -> None:
    target = int(sys.argv[1], 0)
    hits = []
    n = len(_text) // 4
    for i in range(n):
        word = struct.unpack_from(">I", _text, i * 4)[0]
        op = word >> 26
        if op != 18:                      # 18 = b/bl/ba/bla
            continue
        aa = (word >> 1) & 1
        lk = word & 1
        li = word & 0x03FFFFFC
        addr = TEXT_BASE + i * 4
        tgt = li if aa else addr + sign26(li)
        if tgt == target:
            hits.append((addr, "bl" if lk else "b "))
    print(f"{len(hits)} référence(s) vers 0x{target:08X} :")
    for addr, kind in hits:
        print(f"  0x{addr:08X}  {kind}")


if __name__ == "__main__":
    main()
