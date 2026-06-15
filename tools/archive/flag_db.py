"""
flag_db.py — Résolveur de flags BotW game_data.sav.

Recette de hash CONFIRMÉE empiriquement (Oman Au -> IsGet_Obj_Magnetglove) :
    flag_id = crc32(name.encode("ascii")) & 0xFFFFFFFF   # CRC32 IEEE (zlib), pas de NUL
    id stocké big-endian, offset données = 12.

Usage :
    # Flags nommés actuellement à True dans un save :
    python flag_db.py --save after.sav --names flags.txt

    # Quels flags ont changé entre deux saves (résolus quand le nom est connu) :
    python flag_db.py --diff before.sav after.sav --names flags.txt
"""
from __future__ import annotations

import argparse
import zlib
from pathlib import Path


# ── Recette ──────────────────────────────────────────────────────────────────

def flag_id(name: str) -> int:
    """nom de flag -> id 32 bits (CRC32 IEEE de l'ASCII, sans NUL)."""
    return zlib.crc32(name.encode("ascii")) & 0xFFFFFFFF


# Constante de validation : ne jamais régresser sur la recette.
_KNOWN = {"IsGet_Obj_Magnetglove": 0x795E7BBC}
for _n, _v in _KNOWN.items():
    assert flag_id(_n) == _v, f"recette de hash cassée pour {_n}"


# ── Parsing du save ──────────────────────────────────────────────────────────

def parse_save(data: bytes) -> dict[int, int]:
    """Renvoie {id_big_endian: value}. Détecte l'offset (val<=1 maximal)."""
    size = len(data)
    best = None
    for off in (12, 16, 20, 8, 4, 0):
        if off >= size:
            continue
        n = (size - off) // 8
        if n <= 0:
            continue
        sample = min(n, 8000)
        le1 = sum(
            1 for i in range(sample)
            if int.from_bytes(data[off + i * 8 + 4: off + i * 8 + 8], "big") <= 1
        )
        frac = le1 / sample
        if best is None or frac > best[0]:
            best = (frac, off, n)
    _, off, n = best
    return {
        int.from_bytes(data[off + i * 8: off + i * 8 + 4], "big"):
        int.from_bytes(data[off + i * 8 + 4: off + i * 8 + 8], "big")
        for i in range(n)
    }


# ── Table de noms ────────────────────────────────────────────────────────────

# Graine de noms confirmés / très probables (le pattern IsGet_Obj_* est validé
# par Magnetglove). À étoffer via savedataformat.ssarc pour la table complète.
_SEED = {
    "IsGet_Obj_Magnetglove", "IsGet_Obj_RemoteBomb", "IsGet_Obj_RemoteBombLv2",
    "IsGet_Obj_StopTimer", "IsGet_Obj_StopTimerLv2", "IsGet_Obj_IceMaker",
    "IsGet_Obj_Camera", "IsGet_Obj_SheikSensor", "IsGet_Obj_SheikSensorLv2",
}


def load_names(files: list[Path]) -> list[str]:
    names = set(_SEED)
    for f in files:
        if f.exists():
            for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and line != "---":
                    names.add(line)
    return sorted(names)


class FlagTable:
    def __init__(self, names: list[str]):
        self.id_to_name: dict[int, str] = {}
        self.collisions: list[tuple[int, str, str]] = []
        for name in names:
            i = flag_id(name)
            if i in self.id_to_name and self.id_to_name[i] != name:
                self.collisions.append((i, self.id_to_name[i], name))
            else:
                self.id_to_name[i] = name

    def name(self, flag_id_value: int) -> str | None:
        return self.id_to_name.get(flag_id_value)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Résolveur de flags BotW.")
    ap.add_argument("--save", type=Path, help="affiche les flags nommés à True")
    ap.add_argument("--diff", nargs=2, type=Path, metavar=("BEFORE", "AFTER"),
                    help="affiche les flags changés (résolus si nom connu)")
    ap.add_argument("--names", action="append", default=[], type=Path)
    args = ap.parse_args()

    table = FlagTable(load_names(args.names))
    print(f"[*] {len(table.id_to_name)} noms chargés"
          + (f" ({len(table.collisions)} collisions)" if table.collisions else ""))

    if args.save:
        flags = parse_save(args.save.read_bytes())
        named_true = sorted(
            (table.name(i), i) for i, v in flags.items()
            if v == 1 and table.name(i)
        )
        print(f"\n[*] {len(named_true)} flags nommés à True :")
        for name, i in named_true:
            print(f"    0x{i:08X}  {name}")

    if args.diff:
        before = parse_save(args.diff[0].read_bytes())
        after = parse_save(args.diff[1].read_bytes())
        changed = sorted(
            (i, before.get(i), av) for i, av in after.items()
            if before.get(i) != av
        )
        resolved = [(i, b, a) for i, b, a in changed if table.name(i)]
        unknown = [(i, b, a) for i, b, a in changed if not table.name(i)]
        print(f"\n[*] {len(changed)} flags changés — {len(resolved)} résolus, "
              f"{len(unknown)} noms inconnus")
        print("\n--- résolus ---")
        for i, b, a in resolved:
            print(f"    0x{i:08X}  {b}->{a}  {table.name(i)}")
        print("\n--- noms encore inconnus (étoffer la liste --names) ---")
        for i, b, a in unknown:
            print(f"    0x{i:08X}  {b}->{a}")


if __name__ == "__main__":
    main()
