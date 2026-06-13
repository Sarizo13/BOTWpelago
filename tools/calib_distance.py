"""
Calibration par distance relative : on cherche TOUTES les occurrences de 2 chaines
connues et on cherche une paire dont la distance correspond exactement a la distance
dans tmp/rodata.bin (preuve que ces 2 copies appartiennent au meme blob .rodata).

Usage (PowerShell admin, Cemu en jeu) :
    python tools/calib_distance.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge

A = b"Access_AllTerminalFire"
B = b"IsGet_Obj_Magnetglove"

data = open("tmp/rodata.bin", "rb").read()
OFF_A = data.find(A)
OFF_B = data.find(B)
EXPECTED_DIST = OFF_B - OFF_A
print(f"rodata.bin: A@0x{OFF_A:X} B@0x{OFF_B:X} dist(B-A)=0x{EXPECTED_DIST:X} ({EXPECTED_DIST})")


def find_all(bridge, needle, max_hits=200):
    hits = []
    chunk_size = 32 * 1024 * 1024
    overlap = len(needle) - 1
    for base, size in bridge._iter_regions():
        if size < len(needle):
            continue
        off = 0
        while off < size:
            n = min(chunk_size, size - off)
            read_n = min(n + overlap, size - off)
            chunk = bridge._read(base + off, read_n)
            if chunk:
                start = 0
                while True:
                    idx = chunk.find(needle, start)
                    if idx < 0:
                        break
                    hits.append(base + off + idx)
                    if len(hits) >= max_hits:
                        return hits
                    start = idx + 1
            off += n
    return hits


def main():
    bridge = CemuMemoryBridge()
    if not bridge.attach():
        print("ERREUR: admin requis / Cemu introuvable / game_data introuvable.")
        return

    print(f"gd_base = 0x{bridge._gd_base:012X}\n")

    hits_a = find_all(bridge, A)
    hits_b = find_all(bridge, B)
    print(f"A hits: {len(hits_a)}")
    for h in hits_a:
        print(f"  0x{h:012X}")
    print(f"B hits: {len(hits_b)}")
    for h in hits_b:
        print(f"  0x{h:012X}")

    print("\nMatching pairs (dist == expected):")
    found = False
    for ha in hits_a:
        for hb in hits_b:
            if hb - ha == EXPECTED_DIST:
                print(f"  A=0x{ha:012X} B=0x{hb:012X} -> cemu_mem_base = 0x{ha - 0x101D00EC:012X}")
                found = True
    if not found:
        print("  (none)")


if __name__ == "__main__":
    main()
