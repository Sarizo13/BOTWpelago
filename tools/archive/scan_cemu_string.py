"""
Scan Cemu Strings — cherche une chaine ASCII donnee n'importe ou dans la memoire de
Cemu (sans hypothese d'adresse), et affiche toutes les adresses hote trouvees.

Usage (PowerShell admin, Cemu en jeu) :
    python tools/scan_cemu_string.py "HorseCustom_ShopSaddleName"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge


def find_all(bridge: CemuMemoryBridge, needle: bytes, max_hits: int = 20):
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
    needles = sys.argv[1:] if len(sys.argv) > 1 else ["HorseCustom_ShopSaddleName"]

    bridge = CemuMemoryBridge()
    if not bridge.attach():
        print("ERREUR: admin requis / Cemu introuvable / game_data introuvable.")
        return

    print(f"gd_base = 0x{bridge._gd_base:012X}\n")

    for s in needles:
        needle = s.encode("ascii")
        print(f"=== {needle!r} ===")
        hits = find_all(bridge, needle)
        if not hits:
            print("  Aucune occurrence trouvee.")
        else:
            for h in hits:
                print(f"  0x{h:012X}")
            print(f"  {len(hits)} occurrence(s)")
        print()

    bridge.detach()


if __name__ == "__main__":
    main()
