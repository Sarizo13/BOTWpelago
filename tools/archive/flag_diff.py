"""
flag_diff — diff mémoire avant/après l'obtention NATURELLE d'une capacité en jeu, pour
localiser le cache de flags LIVE (l'octet/bit qui passe 0->1 quand le jeu donne le paravoile).

Fenêtre = [gd_base - 96MB, gd_base + 96MB] (les structures GameDataMgr sont autour de gd_base).
Étapes (même session Cemu, PAS de reload entre les deux) :
    python tools/flag_diff.py --before      # AVANT de parler au Roi / recevoir le paravoile
    (en jeu : récupère le paravoile)
    python tools/flag_diff.py --after       # juste après -> affiche les changements

Lecture seule.
"""
import sys, struct, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import numpy as np
from BotWClient.memory_injector import CemuMemoryBridge

W = 96 * 1024 * 1024
RDCHUNK = 32 * 1024 * 1024
SNAP = Path(__file__).parents[1] / "tmp" / "flagdiff_before.bin"
META = Path(__file__).parents[1] / "tmp" / "flagdiff_meta.txt"


def read_window(b, start):
    parts = []
    off = 0
    total = 2 * W
    while off < total:
        n = min(RDCHUNK, total - off)
        d = b._read(start + off, n)
        if not d or len(d) != n:
            d = (d or b"") + b"\x00" * (n - len(d or b""))
        parts.append(d)
        off += n
    return b"".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", action="store_true")
    ap.add_argument("--after", action="store_true")
    args = ap.parse_args()

    b = CemuMemoryBridge()
    if not b.attach():
        print("ERREUR attach (admin + Cemu en jeu).")
        return
    gd = b._gd_base
    start = gd - W
    print(f"gd_base=0x{gd:012X}  fenêtre=[0x{start:012X} .. 0x{start+2*W:012X}] ({2*W//(1024*1024)} MiB)")

    if args.before:
        data = read_window(b, start)
        SNAP.parent.mkdir(exist_ok=True)
        SNAP.write_bytes(data)
        META.write_text(f"{gd:#x}\n{start:#x}\n")
        print(f"Snapshot AVANT sauvegardé ({len(data)//(1024*1024)} MiB).")
        print("-> En jeu : récupère le paravoile, PUIS lance:  python tools/flag_diff.py --after")
        return

    if args.after:
        if not SNAP.exists():
            print("Pas de snapshot AVANT. Lance d'abord --before.")
            return
        meta = META.read_text().split()
        old_gd = int(meta[0], 16)
        if old_gd != gd:
            print(f"!! gd_base a changé ({old_gd:#x} -> {gd:#x}) : reload détecté, snapshots incomparables.")
            return
        before = np.frombuffer(SNAP.read_bytes(), dtype=np.uint8)
        after = np.frombuffer(read_window(b, start), dtype=np.uint8)
        n = min(len(before), len(after))
        before, after = before[:n], after[:n]
        diff_idx = np.where(before != after)[0]
        print(f"\n{len(diff_idx)} octets changés.")
        gaps = np.diff(diff_idx)
        ISO = 64          # isolé = aucun autre changement à ±64 octets
        NEAR = 24 * 1024 * 1024   # proche de gd_base (±24 MB)
        isolated = []
        for k in range(len(diff_idx)):
            prev_gap = gaps[k - 1] if k > 0 else 1 << 30
            next_gap = gaps[k] if k < len(gaps) else 1 << 30
            if prev_gap <= ISO or next_gap <= ISO:
                continue
            i = int(diff_idx[k])
            o, nw = int(before[i]), int(after[i])
            if not (nw & o == o and bin(nw & ~o).count("1") == 1):   # 1 bit ajouté 0->1
                continue
            addr = start + i
            if abs(addr - gd) > NEAR:
                continue
            isolated.append((addr, o, nw, (nw & ~o).bit_length() - 1))
        print(f"=== {len(isolated)} changements ISOLÉS 'bit 0->1' proches de gd_base (±24MB) ===")
        for addr, o, nw, bit in isolated:
            rel = addr - gd
            sign = "+" if rel >= 0 else "-"
            print(f"  0x{addr:012X} (gd{sign}0x{abs(rel):X})  {o:#04x}->{nw:#04x}  bit{bit}")


if __name__ == "__main__":
    main()
