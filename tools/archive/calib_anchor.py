"""
Calibration via ancre verifiee dans le code compile :
FUN_02cbb0d4 calcule r7 = 0x101d00ec via `lis r7,0x101d` / `addi r7,r7,0xec`.
tmp/rodata.bin offset 0x1d00ec == "Access_AllTerminalFire" (vaddr = 0x10000000 + offset).

Pour chaque occurrence de cette chaine en memoire Cemu, on calcule
cemu_mem_base = host - 0x101d00ec, puis on verifie cette base en lisant
les adresses predites pour 4 autres chaines connues.

Usage (PowerShell admin, Cemu en jeu) :
    python tools/calib_anchor.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge

ANCHOR = b"Access_AllTerminalFire"
ANCHOR_VADDR = 0x101D00EC

CHECKS = [
    (b"IsGet_Obj_Magnetglove", 0x101CCF30),
    (b"PutRupee_Gold", 0x101C9126),
    (b"DungeonClearCounter", 0x101C8724),
    (b"HorseCustom_ShopSaddleName", 0x101D2734),
]


def find_all(bridge, needle, max_hits=20):
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

    hits = find_all(bridge, ANCHOR)
    print(f"Anchor '{ANCHOR.decode()}' hits: {len(hits)}")
    for h in hits:
        print(f"  0x{h:012X}")

    for h in hits:
        base = h - ANCHOR_VADDR
        print(f"\n--- Candidate cemu_mem_base = 0x{base:012X} (from hit 0x{h:012X}) ---")
        for needle, vaddr in CHECKS:
            addr = base + vaddr
            data = bridge._read(addr, len(needle) + 8)
            print(f"  {needle.decode():28s} @ 0x{addr:012X} -> {data!r}")


if __name__ == "__main__":
    main()
