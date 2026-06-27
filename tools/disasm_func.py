"""
disasm_func — désassemble une fonction du RPX v208 (PowerPC big-endian) via capstone,
avec résolution des constantes : chaînes .rodata (0x10xxxxxx), vtables PouchItem connues,
cibles d'appels (bl), et annotations d'offsets mémoire (stw/lwz) utiles au RE PouchItem.

Bases (v208) :
  .text   vaddr 0x02000000  -> tmp/rpx_v208/02_text.bin
  .rodata vaddr 0x10000000  -> tmp/rpx_v208/03_rodata.bin
  .data   vaddr 0x10000000+ -> tmp/rpx_v208/04_data.bin (souvent juste après rodata)

Usage :
  python tools/disasm_func.py 0x02eae294            # désassemble jusqu'au blr
  python tools/disasm_func.py 0x02eae294 200        # 200 instructions max
"""
from __future__ import annotations

import os
import sys

from capstone import Cs, CS_ARCH_PPC, CS_MODE_BIG_ENDIAN, CS_MODE_32

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT_BASE = 0x02000000
RODATA_BASE = 0x10000000

KNOWN = {
    0x1021B5D4: "vtable PouchItem",
    0x1021B524: "vtable FixedSafeString<64>",
}

_text = open(os.path.join(ROOT, "tmp/rpx_v208/02_text.bin"), "rb").read()
_rodata = open(os.path.join(ROOT, "tmp/rpx_v208/03_rodata.bin"), "rb").read()


def rodata_str(addr: int) -> str | None:
    off = addr - RODATA_BASE
    if 0 <= off < len(_rodata):
        end = _rodata.find(b"\x00", off)
        s = _rodata[off:end if end >= 0 else off + 48]
        try:
            t = s.decode("ascii")
            if t.isprintable() and len(t) >= 2:
                return t
        except Exception:
            pass
    return None


def annotate_const(val: int) -> str | None:
    if val in KNOWN:
        return KNOWN[val]
    s = rodata_str(val)
    if s is not None:
        return f'.rodata "{s}"'
    if 0x10000000 <= val < 0x10800000:
        return ".rodata/.data?"
    if 0x02000000 <= val < 0x04000000:
        return "-> .text"
    return None


def main() -> None:
    vaddr = int(sys.argv[1], 0)
    maxn = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    off = vaddr - TEXT_BASE
    if not (0 <= off < len(_text)):
        print("vaddr hors .text"); return
    code = _text[off:off + maxn * 4]
    md = Cs(CS_ARCH_PPC, CS_MODE_BIG_ENDIAN | CS_MODE_32)
    md.detail = False

    # suivi des lis rX pour reconstituer les constantes 32 bits (lis + addi/ori)
    hi: dict[str, int] = {}
    n = 0
    for insn in md.disasm(code, vaddr):
        n += 1
        note = ""
        mn, ops = insn.mnemonic, insn.op_str
        if mn == "lis":
            try:
                rd, imm = ops.split(", ")
                hi[rd] = (int(imm, 0) & 0xFFFF) << 16
            except Exception:
                pass
        elif mn in ("addi", "ori", "addic", "subi") and "," in ops:
            parts = [p.strip() for p in ops.split(",")]
            if len(parts) == 3 and parts[1] in hi:
                base = hi[parts[1]]
                imm = int(parts[2], 0)
                val = (base + imm) & 0xFFFFFFFF if mn != "ori" else (base | (imm & 0xFFFF))
                a = annotate_const(val)
                note = f"   ; {parts[0]} = 0x{val:08X}" + (f"  {a}" if a else "")
                hi[parts[0]] = val if mn == "ori" else val  # propage la constante complète
        elif mn in ("bl", "b", "bla", "ba"):
            try:
                t = int(ops, 0)
                note = f"   ; -> 0x{t:08X}"
            except Exception:
                pass
        elif mn in ("stw", "stb", "sth", "lwz", "lbz", "lhz", "stwu") and "(" in ops:
            # ex: 'r0, 0x204(r3)' -> annoter l'offset hexa pour repérer +0x0C/0x14/0x04...
            try:
                disp = ops.split(",")[1].split("(")[0].strip()
                d = int(disp, 0)
                if d:
                    note = f"   ; off 0x{d:X}"
            except Exception:
                pass
        print(f"  0x{insn.address:08X}:  {mn:<8} {ops}{note}")
        if mn in ("blr", "bctr"):
            break
    if n == 0:
        print("(rien désassemblé)")


if __name__ == "__main__":
    main()
