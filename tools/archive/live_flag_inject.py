"""
live_flag_inject — localise le tableau de valeurs LIVE des flags bool puis (optionnel)
écrit un flag pour tester l'activation d'une capacité sans reload.

Tout est re-dérivé dans la session courante (adresses spécifiques à la session) :
  1. lit gd_base + la TABLE D'INDEX (16o: [hash][A][gd_base_offset][0]) située après gd_base
     -> récupère des centaines de couples (index A, valeur) validés contre gd_base.
  2. scanne le tas avec un SCORE (matches B[A]==valeur) -> la base du tableau live = score max.
  3. dry-run : affiche la base, le score, et l'octet courant à base+A(flag cible).
  --write : écrit 1 à base + A(flag cible).

Lecture seule par défaut. PowerShell admin + Cemu en jeu :
    python tools/live_flag_inject.py                          # confirme la base (dry-run)
    python tools/live_flag_inject.py --write                  # + écrit le Paraglider
    python tools/live_flag_inject.py --flag IsGet_Obj_HeroSoul_Rito --write
"""
import sys, struct, argparse, zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass
import numpy as np
from BotWClient.memory_injector import CemuMemoryBridge

CHUNK = 64 * 1024 * 1024


def u32be(buf, off):
    return struct.unpack_from(">I", buf, off)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flag", default="IsGet_PlayerStole2", help="flag cible (def: Paraglider)")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    b = CemuMemoryBridge()
    if not b.attach():
        print("ERREUR attach (admin + Cemu en jeu).", flush=True)
        return
    gd = b._gd_base
    print(f"gd_base=0x{gd:012X}", flush=True)

    gdbuf = b._read(gd, 0x140000) or b""
    # --- parse la table d'index dans [gd+0x120000 .. gd+0x320000] ---
    win_base = gd + 0x120000
    win = b._read(win_base, 0x200000) or b""
    target_hash = zlib.crc32(args.flag.encode("ascii")) & 0xFFFFFFFF
    fp = {}          # A -> value (0/1)
    byhash = {}      # hash -> (A, value)
    target_A = None
    n_entries = 0
    for pos in range(0, len(win) - 16, 4):
        h = u32be(win, pos); A = u32be(win, pos + 4); gdoff = u32be(win, pos + 8); z = u32be(win, pos + 12)
        if z != 0 or A >= 0x20000 or gdoff + 8 > len(gdbuf):
            continue
        if gdbuf[gdoff:gdoff + 4] != struct.pack(">I", h):
            continue
        n_entries += 1
        val = u32be(gdbuf, gdoff + 4)
        if val in (0, 1):
            fp[A] = val
            byhash[h] = (A, val)
        if h == target_hash:
            target_A = A
    print(f"table d'index: {n_entries} entrées validées, {len(fp)} flags bool (0/1)", flush=True)
    if target_A is None:
        print(f"  ! flag cible {args.flag} introuvable dans la table d'index.", flush=True)
        return
    print(f"  flag cible {args.flag}: index A=0x{target_A:X}", flush=True)

    # Filtrer aux flags BOOL uniquement (IsGet_/Clear_ depuis flag_names.txt) : les flags
    # s32 (compteurs) vivent dans un autre tableau et cassent le AND byte.
    bool_hashes = set()
    fn = Path(__file__).parents[1] / "flag_names.txt"
    if fn.exists():
        for line in fn.read_text(encoding="ascii", errors="ignore").splitlines():
            nm = line.strip()
            if nm.startswith(("IsGet_", "Clear_")):
                bool_hashes.add(zlib.crc32(nm.encode()) & 0xFFFFFFFF)
        bool_A = {byhash[h][0] for h in bool_hashes if h in byhash}
        print(f"flags bool (IsGet_/Clear_) connus: {len(bool_hashes)}, présents dans la table: {len(bool_A)}", flush=True)
    else:
        bool_A = None
        print("  ! flag_names.txt absent — pas de filtre bool (risque de mélange s32).", flush=True)

    # flags=1 BOOL monotones (gotten reste gotten) -> 1 en live aussi.
    ones = sorted(a for a, v in fp.items() if v == 1 and (bool_A is None or a in bool_A))[:50]
    # flags=0 FIABLES : items AP-gated que le joueur ne peut PAS avoir -> 0 garanti en live.
    RELIABLE_ZERO = ["IsGet_PlayerStole2", "Get_MasterSword_Finish", "IsGet_Obj_HeroSoul_Rito",
                     "IsGet_Obj_HeroSoul_Goron", "IsGet_Obj_HeroSoul_Zora", "IsGet_Obj_HeroSoul_Gerudo",
                     "IsGet_Obj_Camera"]
    zeros = []
    for nm in RELIABLE_ZERO:
        e = byhash.get(zlib.crc32(nm.encode()) & 0xFFFFFFFF)
        if e and e[1] == 0:
            zeros.append(e[0])
    if len(ones) < 6 or len(zeros) < 3:
        print(f"  ! empreinte insuffisante (ones={len(ones)}, zeros={len(zeros)}).", flush=True)
        return
    maxA = max(ones + zeros)
    print(f"empreinte BIT-PACKED: {len(ones)} flags=1 ET {len(zeros)} flags=0, maxA=0x{maxA:X} — scan…", flush=True)

    def bit_at(arr, a, L):
        return (arr[a >> 3: (a >> 3) + L] >> (a & 7)) & 1

    PAD = (maxA >> 3) + 16
    candidates = []
    for base, size in b._iter_regions():
        if size < PAD:
            continue
        off = 0
        while off < size:
            rd = min(CHUNK, size - off)
            chunk = b._read(base + off, rd)
            if chunk and len(chunk) > PAD:
                arr = np.frombuffer(chunk, dtype=np.uint8)
                L = len(arr) - PAD
                valid = bit_at(arr, ones[0], L) == 1
                for a in ones[1:]:
                    valid &= (bit_at(arr, a, L) == 1)
                for a in zeros:
                    valid &= (bit_at(arr, a, L) == 0)
                for p in np.where(valid)[0]:
                    candidates.append(base + off + int(p))
            if rd < CHUNK:
                break
            off += rd - PAD
    print(f"\n>>> {len(candidates)} base(s) BIT-PACKED matchant {len(ones)} '1' + {len(zeros)} '0'", flush=True)
    for c in candidates[:10]:
        print(f"    base=0x{c:012X}", flush=True)
    if not candidates:
        print("  Aucune base — un flag=1 diffère peut-être entre gd_base et live.", flush=True)
        return
    ambiguous = len(candidates) > 16    # cluster serré attendu
    best_addr = candidates[0]

    byte_addr = best_addr + (target_A >> 3)
    bit = target_A & 7
    cur = b._read(byte_addr, 1)
    curbit = (cur[0] >> bit) & 1 if cur else "?"
    print(f"  bit A({args.flag}) à 0x{byte_addr:012X} bit{bit} = {curbit}", flush=True)

    if args.write:
        if ambiguous:
            print(f"  ÉCRITURE ANNULÉE ({len(candidates)} candidats — base ambiguë).", flush=True)
            return
        if cur:
            newbyte = bytes([cur[0] | (1 << bit)])
            ok = b._write(byte_addr, newbyte)
            print(f"  ÉCRITURE bit {bit} à 0x{byte_addr:012X} : {ok}", flush=True)
            print("  -> En jeu : ouvre/ferme le menu (ou change de zone) et teste la capacité.", flush=True)


if __name__ == "__main__":
    main()
