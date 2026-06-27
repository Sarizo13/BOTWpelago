"""
find_codecave — localise le codecave via la chaine ASCII 'BOTWPELAGO_FRAME' et lit le
compteur (apres la chaine alignee). Valide le hook par-frame.
"""
from __future__ import annotations

import os
import struct
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import BotWClient.memory_injector as mi  # noqa: E402

NEEDLE = b"BOTWPELAGO_FRAME"


def scan(br, needle):
    hits = []
    for base, size in br._iter_regions():
        off = 0
        while off < size:
            n = min(32 * 1024 * 1024, size - off)
            chunk = br._read(base + off, n)
            if chunk:
                arr = np.frombuffer(chunk, dtype=np.uint8)
                for c in np.where(arr == needle[0])[0]:
                    c = int(c)
                    if chunk[c:c+len(needle)] == needle:
                        hits.append(base + off + c)
            off += max(n - len(needle) + 1, 1)
    return hits


def main() -> None:
    pid = mi._find_pid("cemu.exe")
    br = mi.CemuMemoryBridge(); br._pid = pid
    h = mi._k32.OpenProcess(mi.PROCESS_ALL_RW, False, pid)
    if not h:
        print("admin requis"); return
    br._handle = h
    print("scan de la chaine 'BOTWPELAGO_FRAME' ...")
    hits = scan(br, NEEDLE)
    print(f"{len(hits)} hit(s) : {[hex(x) for x in hits[:5]]}")
    if not hits:
        print("=> codecave non trouve en memoire (region non scannee). On passera par"
              " l'activation du logging OSReport de Cemu.")
        mi._k32.CloseHandle(h); return
    # _counter est apres _msg (chaine 'BOTWPELAGO_FRAME %d\n' = 20o -> aligne 0x18) + .align 4
    for hh in hits:
        # cherche le compteur : on lit 0x20 octets apres le debut de la chaine, on teste
        raw = br._read(hh, 0x40) or b""
        print(f"\n@0x{hh:012X} dump :")
        for o in range(0, len(raw), 16):
            print("  " + " ".join(f"{x:02X}" for x in raw[o:o+16]))
    # lecture du compteur a +0x18 (apres la chaine alignee), 2x
    hh = hits[0]
    def rdc(fmt):
        r = br._read(hh + 0x18, 4); return struct.unpack(fmt, r)[0] if r else -1
    for fmt in (">I", "<I"):
        a = rdc(fmt); time.sleep(1.0); b = rdc(fmt)
        print(f"compteur(+0x18,{fmt}) {a} -> {b}  delta={(b-a)&0xFFFFFFFF}")
    mi._k32.CloseHandle(h)


if __name__ == "__main__":
    main()
