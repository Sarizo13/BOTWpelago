"""
find_inc — cherche dans une plage .text le motif "compteur += 1" à un offset donné :
  lwz  rA, OFF(rB)
  addi/addic rA, rA, 1
  stw  rA, OFF(rB)
Sert à repérer createPorchItem (this->0x08 ++), inverse de freePorchItem.

Usage : python tools/find_inc.py 0x02ea0000 0x02ec8000 [offset=8]
"""
from __future__ import annotations

import os
import sys

from capstone import Cs, CS_ARCH_PPC, CS_MODE_BIG_ENDIAN, CS_MODE_32

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT_BASE = 0x02000000
_text = open(os.path.join(ROOT, "tmp/rpx_v208/02_text.bin"), "rb").read()


def main() -> None:
    start = int(sys.argv[1], 0)
    end = int(sys.argv[2], 0)
    off = int(sys.argv[3], 0) if len(sys.argv) > 3 else 8
    code = _text[start - TEXT_BASE:end - TEXT_BASE]
    md = Cs(CS_ARCH_PPC, CS_MODE_BIG_ENDIAN | CS_MODE_32)
    md.skipdata = True
    insns = list(md.disasm(code, start))
    disp = f"0x{off:x}(" if off else "("  # capstone format ex: '0x8(r25)'
    hits = []
    for i in range(len(insns) - 2):
        a, b, c = insns[i], insns[i + 1], insns[i + 2]
        if a.mnemonic != "lwz" or b.mnemonic not in ("addi", "addic", "addic.") \
           or c.mnemonic != "stw":
            continue
        # a: 'rA, 0x8(rB)' ; b: 'rA, rA, 1' ; c: 'rA, 0x8(rB)'
        try:
            ra_a, mem_a = [x.strip() for x in a.op_str.split(",", 1)]
            bp = [x.strip() for x in b.op_str.split(",")]
            ra_c, mem_c = [x.strip() for x in c.op_str.split(",", 1)]
        except ValueError:
            continue
        if disp not in mem_a or disp not in mem_c:
            continue
        if not (ra_a == bp[0] == bp[1] == ra_c):
            continue
        if bp[2].strip() not in ("1", "0x1"):
            continue
        hits.append(a.address)
    print(f"{len(hits)} incrément(s) de +{off:#x} dans [0x{start:08X},0x{end:08X}) :")
    for h in hits:
        print(f"  0x{h:08X}")


if __name__ == "__main__":
    main()
