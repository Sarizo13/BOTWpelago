"""
native_give_test — déclenche le codecave addItem (test pomme hardcodée).

Scanne le marqueur 'BOTWPELAGOMBX1', écrit trigger=1 (marqueur+0x10) sur chaque copie,
puis attend qu'une copie repasse à 0 (= la vivante : le codecave a appelé addItem).
Observe en jeu : une pomme (Item_Fruit_A) doit apparaître dans les matériaux.

Admin requis + BotW lancé avec le pack BOTWpelago_GiveItem actif.
Usage : python tools/native_give_test.py
"""
from __future__ import annotations

import os
import struct
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import BotWClient.memory_injector as mi  # noqa: E402

MARKER = b"BOTWPELAGOMBX1"
TRIGGER_OFF = 0x10


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
    print("scan du marqueur 'BOTWPELAGOMBX1' ...")
    hits = scan(br, MARKER)
    print(f"{len(hits)} copie(s) : {[hex(x) for x in hits[:6]]}")
    if not hits:
        print("codecave introuvable (pack actif ? log: 'Applying patch group BOTWpelago_GiveItem')")
        mi._k32.CloseHandle(h); return
    # écrit trigger=1 sur chaque copie (la vivante sera lue par le codecave)
    for hh in hits:
        br._write(hh + TRIGGER_OFF, struct.pack(">I", 1))
    print("trigger=1 écrit. Attente de la consommation (codecave -> addItem) ...")
    deadline = time.monotonic() + 3.0
    consumed = None
    while time.monotonic() < deadline:
        for hh in hits:
            r = br._read(hh + TRIGGER_OFF, 4)
            if r and struct.unpack(">I", r)[0] == 0:
                consumed = hh
                break
        if consumed:
            break
        time.sleep(0.05)
    if consumed:
        print(f"=> TRIGGER CONSOMMÉ @0x{consumed:012X} : le codecave a appelé addItem !")
        print("   Vérifie en jeu : une POMME doit apparaître (onglet matériaux).")
    else:
        print("=> trigger pas consommé (le hook ne lit pas cette copie, ou addItem a planté).")
    mi._k32.CloseHandle(h)


if __name__ == "__main__":
    main()
