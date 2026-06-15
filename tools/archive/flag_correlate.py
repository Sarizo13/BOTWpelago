"""
flag_correlate — à partir du snapshot AVANT (flagdiff_before.bin) + mémoire actuelle
(paravoile obtenu), trouve les changements isolés près de gd_base, puis CORRÈLE :
pour chaque candidat, hypothèse "c'est le flag paravoile (A_para)", en déduit la base+format
(octet ou bit) du tableau de flags live, et vérifie contre l'empreinte (runes=1, gated=0).
Le candidat qui valide = le flag live + donne base+format pour écrire n'importe quel flag.

PowerShell admin + Cemu en jeu (même session, pas de reload depuis --before) :
    python tools/flag_correlate.py
"""
import sys, struct, zlib, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass
import numpy as np
from BotWClient.memory_injector import CemuMemoryBridge

W = 96 * 1024 * 1024
RDCHUNK = 32 * 1024 * 1024
SNAP = Path(__file__).parents[1] / "tmp" / "flagdiff_before.bin"
META = Path(__file__).parents[1] / "tmp" / "flagdiff_meta.txt"
PARA = "IsGet_PlayerStole2"
RELIABLE_ZERO = ["Get_MasterSword_Finish", "IsGet_Obj_HeroSoul_Rito", "IsGet_Obj_HeroSoul_Goron",
                 "IsGet_Obj_HeroSoul_Zora", "IsGet_Obj_HeroSoul_Gerudo", "IsGet_Obj_Camera"]


def u32be(buf, off):
    return struct.unpack_from(">I", buf, off)[0]


def read_window(b, start, size):
    parts, off = [], 0
    while off < size:
        n = min(RDCHUNK, size - off)
        d = b._read(start + off, n) or b""
        parts.append(d + b"\x00" * (n - len(d)))
        off += n
    return b"".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", dest="setflag", default=None,
                    help="nom d'un flag à mettre à 1 dans le tableau live (test)")
    args = ap.parse_args()

    b = CemuMemoryBridge()
    if not b.attach():
        print("ERREUR attach.")
        return
    gd = b._gd_base
    if not SNAP.exists():
        print("Pas de snapshot AVANT (flagdiff_before.bin).")
        return
    old_gd = int(META.read_text().split()[0], 16)
    if old_gd != gd:
        print(f"!! reload détecté ({old_gd:#x}->{gd:#x}).")
        return
    start = gd - W

    # 1) index table -> A,value par flag
    gdbuf = b._read(gd, 0x140000) or b""
    win = b._read(gd + 0x120000, 0x200000) or b""
    byhash = {}
    for pos in range(0, len(win) - 16, 4):
        h = u32be(win, pos); A = u32be(win, pos + 4); gdoff = u32be(win, pos + 8); z = u32be(win, pos + 12)
        if z != 0 or A >= 0x20000 or gdoff + 8 > len(gdbuf):
            continue
        if gdbuf[gdoff:gdoff + 4] == struct.pack(">I", h):
            v = u32be(gdbuf, gdoff + 4)
            if v in (0, 1):
                byhash[h] = (A, v)
    A_para = byhash.get(zlib.crc32(PARA.encode()) & 0xFFFFFFFF, (None,))[0]
    if A_para is None:
        print("Paraglider absent de la table d'index.")
        return
    print(f"gd_base=0x{gd:012X}  A_paraglider=0x{A_para:X}  flags table={len(byhash)}")

    # empreinte de vérif : flags A<0x4000 (fenêtre courte), runes=1 + gated=0
    verif = [(A, v) for (A, v) in byhash.values() if A < 0x4000]
    zerosA = []
    for nm in RELIABLE_ZERO:
        e = byhash.get(zlib.crc32(nm.encode()) & 0xFFFFFFFF)
        if e:
            zerosA.append(e[0])
    print(f"empreinte de vérif: {len(verif)} flags (A<0x4000) + {len(zerosA)} gated=0")

    # 2) diff -> candidats isolés bit 0->1 près de gd_base
    before = np.frombuffer(SNAP.read_bytes(), dtype=np.uint8)
    after = np.frombuffer(read_window(b, start, 2 * W), dtype=np.uint8)
    n = min(len(before), len(after)); before, after = before[:n], after[:n]
    didx = np.where(before != after)[0]
    gaps = np.diff(didx)
    cands = []
    for k in range(len(didx)):
        pg = gaps[k - 1] if k > 0 else 1 << 30
        ng = gaps[k] if k < len(gaps) else 1 << 30
        if pg <= 64 or ng <= 64:
            continue
        i = int(didx[k]); o, nw = int(before[i]), int(after[i])
        if nw & o == o and bin(nw & ~o).count("1") == 1 and abs(start + i - gd) <= 24 * 1024 * 1024:
            cands.append((start + i, (nw & ~o).bit_length() - 1))
    print(f"{len(cands)} candidats isolés.\n")

    # 3) corrélation : chaque candidat = paraglider ? teste octet ET bit
    WSZ = 0x4001
    best = None
    for addr, bit in cands:
        # --- format OCTET : base = addr - A_para ; flag F à base+A_F ---
        base = addr - A_para
        buf = b._read(base, WSZ)
        if buf:
            arr = np.frombuffer(buf, np.uint8)
            sc = sum(1 for (A, v) in verif if (arr[A] == 1) == (v == 1))
            z = sum(1 for A in zerosA if A < 0x4000 and arr[A] == 0)
            if best is None or sc > best[1]:
                best = (addr, sc, len(verif), "octet", base, bit)
        # --- format BIT : byte addr = base_bit + A_para//8, bit = A_para&7 ---
        if bit == (A_para & 7):
            base_bit = addr - (A_para >> 3)
            buf = b._read(base_bit, (0x4000 >> 3) + 1)
            if buf:
                arr = np.frombuffer(buf, np.uint8)
                sc = sum(1 for (A, v) in verif if (((arr[A >> 3] >> (A & 7)) & 1) == 1) == (v == 1))
                if best is None or sc > best[1]:
                    best = (addr, sc, len(verif), "bit", base_bit, bit)

    if best:
        addr, sc, tot, fmt, base, bit = best
        print(f">>> MEILLEUR: candidat 0x{addr:012X} (bit{bit}) format={fmt} "
              f"base=0x{base:012X} score={sc}/{tot}")
        if sc >= tot * 0.95:
            print("  => EMPREINTE VALIDÉE : tableau de flags live localisé !")
            print(f"  Paraglider live @ format {fmt}, base 0x{base:012X}, A=0x{A_para:X}")
            if args.setflag and fmt == "octet":
                e = byhash.get(zlib.crc32(args.setflag.encode()) & 0xFFFFFFFF)
                if not e:
                    print(f"  ! flag {args.setflag} absent de la table.")
                else:
                    a = base + e[0]
                    cur = b._read(a, 1)
                    ok = b._write(a, b"\x01")
                    print(f"  ÉCRITURE {args.setflag} @0x{a:012X} (A=0x{e[0]:X}) : "
                          f"avant={cur[0] if cur else '?'} -> écrit=1 ({ok})")
                    print("  -> En jeu (SANS reload) : ouvre le menu capacités (L), change de zone, teste.")
        else:
            print("  (score insuffisant — aucun candidat ne valide l'empreinte ; format/modèle à revoir)")


if __name__ == "__main__":
    main()
