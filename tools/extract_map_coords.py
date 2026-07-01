"""
Extrait les positions carte des lieux BotW depuis le dump du jeu (LocationMarker/Pointer +
Location.smubin dans Bootup.pack) et les convertit en pixels pour la carte PopTracker
(Hyrule 3000x2500). Sortie : poptracker/map_coords.json  {ap_id: [px, py]}  (LOCAL, gitignored).

  python tools/extract_map_coords.py [--dump "D:/Emulateur/Jeux Wiiu"]

Transfo (source zeldamods/objmap : MAP_SIZE=[24000,20000], bornes |x|<=6000 |z|<=5000 ;
carte 3000x2500 = carte complète / 8) :  px = (x+6000)*0.25 ,  py = (z+5000)*0.25
(+X = est, +Z = sud). Les coords sont des faits dérivés du jeu → on garde le fichier LOCAL.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT  = ROOT / "poptracker" / "map_coords.json"
DEFAULT_DUMP = r"D:/Emulateur/Jeux Wiiu"
MAP_W, MAP_H = 3000, 2500
SCALE = 0.25            # 3000/12000 = 2500/10000
OFF_X, OFF_Z = 6000, 5000


def _find_bootup(dump: Path) -> Path:
    for p in dump.rglob("Bootup.pack"):
        if "Base Games" in str(p):     # priorité base game (données de carte)
            return p
    hits = list(dump.rglob("Bootup.pack"))
    if not hits:
        raise SystemExit(f"Bootup.pack introuvable sous {dump}")
    return hits[0]


def _to_px(x, z):
    return [round((float(x) + OFF_X) * SCALE, 1), round((float(z) + OFF_Z) * SCALE, 1)]


def build(dump_dir: str) -> None:
    import oead
    boot = _find_bootup(Path(dump_dir))
    sarc = oead.Sarc(boot.read_bytes())

    def to_py(o):
        if isinstance(o, oead.byml.Hash):  return {k: to_py(o[k]) for k in o.keys()}
        if isinstance(o, oead.byml.Array): return [to_py(x) for x in o]
        return getattr(o, "value", o)

    def load(n):
        raw = bytes(sarc.get_file(n).data)
        if raw[:4] == b"Yaz0":
            raw = oead.yaz0.decompress(raw)
        return to_py(oead.byml.from_binary(raw))

    st = load("Map/MainField/Static.smubin")
    markers = list(st["LocationMarker"]) + list(st["LocationPointer"])
    loc_list = load("Map/MainField/Location.smubin")
    markers += [m for m in loc_list if isinstance(m, dict)]

    by_flag, by_msg = {}, {}
    for m in markers:
        t = m.get("Translate") or {}
        if t.get("X") is None or t.get("Z") is None:
            continue
        xz = (t["X"], t["Z"])
        if m.get("SaveFlag"):  by_flag.setdefault(m["SaveFlag"], xz)
        if m.get("MessageID"): by_msg.setdefault(m["MessageID"], xz)

    # dungeon_id -> (x,z) du sanctuaire (sert aussi aux coffres, co-localisés)
    shrine_xz = {}

    def resolve(loc):
        cat, fn = loc["category"], loc.get("flag_name", "")
        if cat == "shrine":
            did = fn.replace("Clear_Dungeon", "")
            xz = by_msg.get(f"Dungeon{did}")
            if xz:
                shrine_xz[did] = xz
            return xz
        if cat == "shrine_chest":
            did = f"{loc.get('dungeon_id', -1):03d}"
            return by_msg.get(f"Dungeon{did}") or shrine_xz.get(did)
        if cat == "tower":
            return by_flag.get(fn) or by_flag.get(fn.replace("MapTower_", "Location_MapTower"))
        if cat == "beast":
            return by_flag.get(fn.replace("Clear_", "Location_"))
        if cat == "location":
            return by_flag.get(fn) or by_msg.get(fn.replace("Location_", ""))
        return None  # quêtes (pas de position unique), mémoires (source à part)

    locs = json.loads((ROOT / "data" / "locations.json").read_text(encoding="utf-8"))
    locs = list(locs.values()) if isinstance(locs, dict) else locs
    chests = json.loads((ROOT / "data" / "shrine_chests.json").read_text(encoding="utf-8"))

    # 1re passe sanctuaires (remplit shrine_xz) puis le reste
    coords, cov, miss = {}, {}, {}
    for loc in sorted(locs + chests, key=lambda l: 0 if l["category"] == "shrine" else 1):
        xz = resolve(loc)
        cat = loc["category"]
        if xz and xz[0] is not None:
            coords[str(loc["ap_id"])] = _to_px(xz[0], xz[1])
            cov[cat] = cov.get(cat, 0) + 1
        else:
            miss[cat] = miss.get(cat, 0) + 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(coords, indent=0), encoding="utf-8")
    print(f"[coords] {len(coords)} marqueurs -> {OUT}")
    print(f"  couverts: {cov}")
    print(f"  sans position (arbre seulement): {miss}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default=DEFAULT_DUMP)
    build(ap.parse_args().dump)


if __name__ == "__main__":
    main()
