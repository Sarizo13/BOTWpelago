"""
hash_oracle.py — Trouve la recette de hash (nom de flag -> flag_id) de game_data.sav.

Principe : tu n'as PAS besoin de savoir quel id correspond à quel flag. On prend
l'ensemble des ids qui sont passés 0->1 entre before.sav et after.sav (le cluster
du sanctuaire complété), et l'ensemble de tes noms candidats, et on cherche la
recette de hash telle que hash(un_nom) == un_id_changé. La recette qui aligne 1+
paires est quasi certainement la bonne ; 2+ paires = verrouillé.

Autonome : parse le .sav directement (header 12B + entrées 8B = u32be id, u32be val),
détecte l'alignement, teste les deux endianness du champ id.

Usage :
    python hash_oracle.py before.sav after.sav
    python hash_oracle.py before.sav after.sav --names flags.txt --names data\shrines_flags.txt
"""
from __future__ import annotations

import argparse
import zlib
from pathlib import Path


# ── Parsing ─────────────────────────────────────────────────────────────────

def parse_save(data: bytes) -> tuple[int, float, list[tuple[bytes, int]]]:
    """
    Détecte l'offset des données et renvoie (offset, fraction_val<=1, [(id_bytes, value_be)]).
    L'offset correct est celui où le champ 'valeur' est ~97% dans {0,1}.
    """
    size = len(data)
    best = None
    for off in (16, 12, 20, 8, 4, 0):
        if off >= size:
            continue
        n = (size - off) // 8
        if n <= 0:
            continue
        sample = min(n, 8000)
        le1 = 0
        for i in range(sample):
            v = int.from_bytes(data[off + i * 8 + 4: off + i * 8 + 8], "big")
            if v <= 1:
                le1 += 1
        frac = le1 / sample
        if best is None or frac > best[0]:
            best = (frac, off, n)
    frac, off, n = best
    entries = [
        (data[off + i * 8: off + i * 8 + 4],
         int.from_bytes(data[off + i * 8 + 4: off + i * 8 + 8], "big"))
        for i in range(n)
    ]
    return off, frac, entries


def diff(before: list[tuple[bytes, int]], after: list[tuple[bytes, int]]):
    """Renvoie (changed: [(id_bytes, bval, aval)], became_true: [id_bytes], by_position: bool)."""
    L = min(len(before), len(after))
    aligned = sum(1 for i in range(L) if before[i][0] == after[i][0])
    by_position = L > 0 and aligned / L > 0.99

    changed, became_true = [], []
    if by_position:
        for i in range(L):
            (idb, bv), (_, av) = before[i], after[i]
            if bv != av:
                changed.append((idb, bv, av))
                if bv == 0 and av == 1:
                    became_true.append(idb)
    else:
        bmap = {idb: v for idb, v in before}
        for idb, av in after:
            bv = bmap.get(idb)
            if bv is not None and bv != av:
                changed.append((idb, bv, av))
                if bv == 0 and av == 1:
                    became_true.append(idb)
    return changed, became_true, by_position


# ── Fonctions de hash ────────────────────────────────────────────────────────

def _crc32(b: bytes) -> int:
    return zlib.crc32(b) & 0xFFFFFFFF

def _fnv1a32(b: bytes) -> int:
    h = 0x811C9DC5
    for c in b:
        h = ((h ^ c) * 0x01000193) & 0xFFFFFFFF
    return h

def _djb2(b: bytes) -> int:
    h = 5381
    for c in b:
        h = ((h * 33) + c) & 0xFFFFFFFF
    return h

def _sdbm(b: bytes) -> int:
    h = 0
    for c in b:
        h = (c + (h << 6) + (h << 16) - h) & 0xFFFFFFFF
    return h

HASHES = {"crc32": _crc32, "fnv1a32": _fnv1a32, "djb2": _djb2, "sdbm": _sdbm}


def transforms(name: str):
    """Variantes (label, bytes) d'un nom : casse × encodage × NUL final."""
    out = []
    for case_label, s in (("asis", name), ("lower", name.lower()), ("upper", name.upper())):
        for enc in ("ascii", "utf-16-le", "utf-16-be"):  # ascii == utf-8 pour ces noms
            try:
                b = s.encode(enc)
            except UnicodeEncodeError:
                continue
            out.append((f"{case_label}/{enc}/nonul", b))
            out.append((f"{case_label}/{enc}/nul", b + b"\x00"))
    return out


# ── Noms candidats ───────────────────────────────────────────────────────────

def build_candidates(extra_files: list[Path]) -> list[str]:
    names: set[str] = set()

    # Sanctuaires : patterns documentés, Dungeon001..120
    for n in range(1, 121):
        d = f"{n:03d}"
        names.update({
            f"Location_MainField_Dungeon{d}_Enable",
            f"MainField_Dungeon{d}_Clear",
            f"FldObj_Dungeon{d}_Entrance_Enable",
            f"Dungeon{d}_Clear",
            f"CompleteDungeon_{d}",
        })

    # Bêtes divines + items / capacités cités par la communauté
    names.update({
        "FldObj_BeastBird_IsGet", "FldObj_BeastFire_IsGet",
        "FldObj_BeastWater_IsGet", "FldObj_BeastLightning_IsGet",
        "IsGet_Obj_Magnetglove", "IsGet_Obj_RemoteBomb", "IsGet_Obj_RemoteBombLv2",
        "IsGet_Obj_StopTimer", "IsGet_Obj_StopTimerLv2", "IsGet_Obj_IceMaker",
        "IsGet_Obj_Camera", "IsGet_Obj_SheikSensor", "IsGet_Obj_SheikSensorLv2",
        "Open_MasterSword_FullPower",
        "Equiped_Pouch_Paraglider",
        "HasRune_Magnet", "HasRune_Stasis", "HasRune_Ice", "HasRune_Bomb", "HasRune_Camera",
    })
    for i in range(1, 16):
        names.add(f"MapTower_{i:02d}")

    # Fichiers fournis par l'utilisateur (un nom par ligne)
    for f in extra_files:
        if f.exists():
            for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and line != "---":
                    names.add(line)

    return sorted(names)


# ── Recherche ────────────────────────────────────────────────────────────────

def search(target_big: set[int], target_little: set[int], names: list[str]):
    results = []
    for hname, hfn in HASHES.items():
        per_recipe: dict[str, dict[int, str]] = {}
        for name in names:
            for tlabel, b in transforms(name):
                per_recipe.setdefault(tlabel, {})[hfn(b)] = name
        for tlabel, hmap in per_recipe.items():
            matches = []
            for hv, name in hmap.items():
                if hv in target_big:
                    matches.append((name, f"{hv:08X}", "id=BE"))
                if hv in target_little:
                    matches.append((name, f"{hv:08X}", "id=LE"))
            if matches:
                results.append((f"{hname} | {tlabel}", matches))
    results.sort(key=lambda r: len(r[1]), reverse=True)
    return results


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Oracle de hash flag_name -> flag_id (BotW save).")
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--names", action="append", default=[], type=Path,
                    help="fichier de noms candidats (répétable)")
    args = ap.parse_args()

    off_b, frac_b, eb = parse_save(Path(args.before).read_bytes())
    off_a, frac_a, ea = parse_save(Path(args.after).read_bytes())
    print(f"[*] before: offset={off_b}  val<=1={frac_b:.3f}  entries={len(eb)}")
    print(f"[*] after : offset={off_a}  val<=1={frac_a:.3f}  entries={len(ea)}")

    changed, became_true, by_pos = diff(eb, ea)
    print(f"[*] alignement {'positionnel' if by_pos else 'par id'} ; "
          f"{len(changed)} ids changés, {len(became_true)} passés 0->1\n")

    if not changed:
        print("[!] Aucun changement. Capture suspecte (mauvais slot ? rien complété ?).")
        return

    print("--- ids passés 0->1 (le cluster du sanctuaire) ---")
    for idb in became_true:
        print(f"    BE=0x{int.from_bytes(idb,'big'):08X}  LE=0x{int.from_bytes(idb,'little'):08X}")
    print()

    target_set = became_true if became_true else [c[0] for c in changed]
    big = {int.from_bytes(idb, "big") for idb in target_set}
    little = {int.from_bytes(idb, "little") for idb in target_set}

    names = build_candidates(args.names)
    print(f"[*] {len(names)} noms candidats testés\n")

    results = search(big, little, names)
    if not results:
        print("[!] Aucune recette ne matche. Pistes : ajoute des noms via --names, "
              "fais une 2e paire sur un autre sanctuaire, ou le hash porte sur autre "
              "chose que le nom brut.")
        return

    print("=== RECETTES TROUVÉES (triées par nb de correspondances) ===")
    for recipe, matches in results[:10]:
        print(f"\n[{len(matches)} match] {recipe}")
        for name, idhex, endian in matches:
            print(f"    {idhex}  ({endian})  <-  {name}")

    print("\n[*] La recette en tête (surtout si 2+ matches) est ton algo de hash. "
          "Applique-la à toute ta liste de noms pour générer la table id->nom.")


if __name__ == "__main__":
    main()
