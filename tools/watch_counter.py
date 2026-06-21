"""
watch_counter — valide le hook par-frame du pack BOTWpelago_HookTest.

Scanne la mémoire de Cemu pour le magic 0x42425045 ("BBPE") placé par le codecave,
puis lit le compteur juste après (+4) deux fois à ~1s d'intervalle. Si le delta est
~30-60 (framerate), le hook s'exécute bien CHAQUE FRAME -> point de hook validé.

Prérequis : pack activé dans Cemu + BotW lancé. Usage : python tools/watch_counter.py
"""
from __future__ import annotations

import os
import struct
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from BotWClient.memory_injector import CemuMemoryBridge  # noqa: E402

MAGIC = 0x42425045


def find_magic(br: CemuMemoryBridge) -> list[int]:
    needle = struct.pack(">I", MAGIC)
    hits: list[int] = []
    for base, size in br._iter_regions():
        off = 0
        CH = 16 * 1024 * 1024
        while off < size:
            n = min(CH, size - off)
            chunk = br._read(base + off, n)
            if chunk:
                arr = np.frombuffer(chunk, dtype=np.uint8)
                cand = np.where(arr == needle[0])[0]
                for c in cand:
                    c = int(c)
                    if c + 4 <= len(chunk) and chunk[c:c+4] == needle:
                        hits.append(base + off + c)
            off += n
    return hits


def main() -> None:
    br = CemuMemoryBridge()
    # attach minimal : on a juste besoin du handle process (pas de l'inventaire)
    br._pid = __import__("BotWClient.memory_injector", fromlist=["_find_pid"])._find_pid("cemu.exe")
    if not br._pid:
        print("Cemu introuvable."); return
    import ctypes
    from BotWClient.memory_injector import _k32, PROCESS_ALL_RW
    h = _k32.OpenProcess(PROCESS_ALL_RW, False, br._pid)
    if not h:
        print("OpenProcess échec (admin requis)."); return
    br._handle = h
    print("Scan du magic 0x42425045 …")
    hits = find_magic(br)
    if not hits:
        print("Magic introuvable — pack pas activé ? (active le graphic pack + relance BotW)")
        return
    print(f"{len(hits)} occurrence(s). Lecture du compteur (+4) sur ~1.5s :")
    first = {h: struct.unpack(">I", br._read(h + 4, 4) or b"\0\0\0\0")[0] for h in hits}
    time.sleep(1.5)
    for h in hits:
        v2 = struct.unpack(">I", br._read(h + 4, 4) or b"\0\0\0\0")[0]
        d = v2 - first[h]
        tag = "  <<< PER-FRAME (hook OK!)" if 20 <= d <= 200 else ""
        print(f"  magic@0x{h:012X}  counter {first[h]} -> {v2}  (Δ={d}){tag}")
    _k32.CloseHandle(h)


if __name__ == "__main__":
    main()
