"""
watch_counter — valide le hook par-frame (pack BOTWpelago_HookTest).

Scanne la mémoire de Cemu pour le magic 0x42425045 (codecave @ guest 0x01800000),
puis lit le compteur (+4) 2× à ~1.5s. Δ ~30-60 => le hook s'exécute CHAQUE FRAME.
(Le mapping bas du guest n'a pas la même base que le tas -> on scanne au lieu de calculer.)

Prérequis : pack activé + BotW lancé. Admin requis. Usage : python tools/watch_counter.py
"""
from __future__ import annotations

import os
import struct
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import BotWClient.memory_injector as mi  # noqa: E402

MAGIC_BE = struct.pack(">I", 0x42425045)


def main() -> None:
    pid = mi._find_pid("cemu.exe")
    if not pid:
        print("Cemu introuvable."); return
    br = mi.CemuMemoryBridge()
    br._pid = pid
    h = mi._k32.OpenProcess(mi.PROCESS_ALL_RW, False, pid)
    if not h:
        print("OpenProcess échec (admin requis)."); return
    br._handle = h

    print("Scan du magic 0x42425045 (BBPE) …")
    hits = []
    for base, size in br._iter_regions():
        off = 0
        CH = 32 * 1024 * 1024
        while off < size:
            n = min(CH, size - off)
            chunk = br._read(base + off, n)
            if chunk:
                arr = np.frombuffer(chunk, dtype=np.uint8)
                for c in np.where(arr == 0x42)[0]:
                    c = int(c)
                    if chunk[c:c+4] == MAGIC_BE:
                        hits.append(base + off + c)
            off += n - 3 if n > 3 else n
    if not hits:
        print("Magic introuvable. (pack actif ? log: 'Applying patch group BOTWpelago_HookTest') ")
        mi._k32.CloseHandle(h); return
    print(f"{len(hits)} occurrence(s). Lecture du compteur (+4) sur ~1.5s :")
    first = {}
    for hh in hits:
        r = br._read(hh + 4, 4)
        first[hh] = struct.unpack(">I", r)[0] if r else -1
    time.sleep(1.5)
    for hh in hits:
        r = br._read(hh + 4, 4)
        v2 = struct.unpack(">I", r)[0] if r else -1
        d = (v2 - first[hh]) & 0xFFFFFFFF if first[hh] >= 0 and v2 >= 0 else -1
        tag = "  <<< PER-FRAME (HOOK VALIDE!)" if 15 <= d <= 400 else ""
        print(f"  magic@host 0x{hh:012X}  counter {first[hh]} -> {v2}  (delta={d}){tag}")
    mi._k32.CloseHandle(h)


if __name__ == "__main__":
    main()
