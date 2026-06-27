"""
find_const — scanne tout le .text v208 (capstone PPC BE) et liste chaque endroit où un
registre reçoit une constante 32 bits donnée (paire lis + addi/ori). Sert à trouver les
sites qui manipulent une adresse précise (vtable PouchItem 0x1021B5D4, etc.).

Usage : python tools/find_const.py 0x1021B5D4
"""
from __future__ import annotations

import os
import sys

from capstone import Cs, CS_ARCH_PPC, CS_MODE_BIG_ENDIAN, CS_MODE_32

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT_BASE = 0x02000000
_text = open(os.path.join(ROOT, "tmp/rpx_v208/02_text.bin"), "rb").read()


def main() -> None:
    target = int(sys.argv[1], 0)
    md = Cs(CS_ARCH_PPC, CS_MODE_BIG_ENDIAN | CS_MODE_32)
    md.detail = False
    md.skipdata = True            # continue au-delà des mots non décodables (îlots de données)
    hi: dict[str, int] = {}
    hits = []
    for insn in md.disasm(_text, TEXT_BASE):
        mn, ops = insn.mnemonic, insn.op_str
        if mn == "lis":
            try:
                rd, imm = ops.split(", ")
                hi[rd] = (int(imm, 0) & 0xFFFF) << 16
            except Exception:
                pass
        elif mn in ("addi", "ori", "addic") and ops.count(",") == 2:
            p = [x.strip() for x in ops.split(",")]
            if p[1] in hi:
                base = hi[p[1]]
                try:
                    imm = int(p[2], 0)
                except ValueError:
                    continue
                val = (base | (imm & 0xFFFF)) if mn == "ori" else (base + imm) & 0xFFFFFFFF
                if val == target:
                    hits.append(insn.address)
                hi[p[0]] = val
    print(f"{len(hits)} site(s) formant 0x{target:08X} :")
    for a in hits:
        print(f"  0x{a:08X}")


if __name__ == "__main__":
    main()
