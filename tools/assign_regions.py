"""
assign_regions — aligne le champ `region` des locations sur les MURS physiques du mod V2.

Les murs (mod/data/zone_walls.json, polylignes monde) sont fermés avec les bords de la
carte pour former des polygones de zone ; chaque location géolocalisée (via
poptracker/map_coords.json) est testée par point-dans-polygone :
  Eldin  (arc + bord nord)      → region "Eldin"          (gate Flamebreaker)
  Rito   (boucle fermée)        → region "Hebra"          (gate Snowquill — même item)
  Zora   (arc + bords est)      → region "Zora"           (gate armure Zora)  [NOUVELLE]
  Gerudo (chaîne + bords SO)    → region "Gerudo"         (gate tenue Gerudo) [NOUVELLE]
"Great Plateau" et "Gerudo Town" existants sont préservés (le Plateau n'est pas muré ;
la ville est DANS la zone Gerudo mais garde sa région dédiée, même gate).
Les locations SANS coordonnées sont listées pour revue manuelle (aucun changement).

Usage :
    python tools/assign_regions.py            # rapport seul (dry-run)
    python tools/assign_regions.py --write    # applique aux 4 fichiers de données
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
WALLS = json.loads((PROJECT / "mod" / "data" / "zone_walls.json").read_text(encoding="utf-8"))
COORDS = json.loads((PROJECT / "poptracker" / "map_coords.json").read_text(encoding="utf-8"))

DATA_FILES = [
    PROJECT / "data" / "locations.json",
    PROJECT / "data" / "shrine_chests.json",
    PROJECT / "worlds" / "botw" / "data" / "locations.json",
    PROJECT / "worlds" / "botw" / "data" / "shrine_chests.json",
]

KEEP_REGIONS = {"Great Plateau", "Gerudo Town"}   # jamais réassignées

# Locations SANS coordonnées (quêtes surtout) : assignation par mots-clés du nom.
# Sur-assigner vers une zone est SANS RISQUE (logique plus restrictive que le monde) ;
# le danger n'existe que dans l'autre sens. Premier match gagne.
NAME_OVERRIDES = [
    ("Goron", "Eldin"), ("Fire Relic", "Eldin"), ("Death Mountain", "Eldin"),
    ("Zora", "Zora"), ("Water Relic", "Zora"),
    ("Rito", "Hebra"), ("Wind Relic", "Hebra"),
    ("Gerudo", "Gerudo"), ("Electric Relic", "Gerudo"), ("Oasis", "Gerudo"),
    ("Desert", "Gerudo"), ("Sand Warm", "Gerudo"),
]


def _zone_polygons() -> dict[str, list[tuple[float, float]]]:
    """Ferme les murs en polygones de zone avec les bords de carte (~±5100)."""
    w = WALLS["regions"]
    eldin = [tuple(p) for p in w["Eldin"]["walls"][0]["points"]]
    eldin += [(eldin[-1][0], -4200.0), (eldin[0][0], -4200.0)]          # bord nord
    rito = [tuple(p) for p in w["Rito"]["walls"][0]["points"]]          # déjà fermé
    zora = [tuple(p) for p in w["Zora"]["walls"][0]["points"]]
    zora += [(5200.0, zora[-1][1]), (5200.0, zora[0][1])]               # bord est
    gerudo = [tuple(p) for wall in w["Gerudo"]["walls"] for p in wall["points"]]
    gerudo += [(gerudo[-1][0], 4200.0), (-5200.0, 4200.0), (-5200.0, gerudo[0][1])]
    return {"Eldin": eldin, "Hebra": rito, "Zora": zora, "Gerudo": gerudo}


def _inside(x: float, z: float, poly: list[tuple[float, float]]) -> bool:
    n = len(poly)
    hit = False
    j = n - 1
    for i in range(n):
        xi, zi = poly[i]
        xj, zj = poly[j]
        if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / (zj - zi) + xi:
            hit = not hit
        j = i
    return hit


def _world(ap_id) -> tuple[float, float] | None:
    xy = COORDS.get(str(ap_id))
    if not xy:
        return None
    return (xy[0] / 0.25 - 6000.0, xy[1] / 0.25 - 5000.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="applique les changements")
    args = ap.parse_args()

    polys = _zone_polygons()
    changes: dict[int, tuple[str, str, str]] = {}     # ap_id -> (name, old, new)
    no_coords: list[str] = []
    census: dict[str, int] = {}

    # calcul sur la copie de référence (data/) ; application sur les 4 fichiers
    for path in DATA_FILES[:2]:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.values() if isinstance(data, dict) else data
        for loc in items:
            old = loc.get("region") or "Hyrule World"
            if old in KEEP_REGIONS:
                census[old] = census.get(old, 0) + 1
                continue
            w = _world(loc["ap_id"])
            if w is None:
                new = next((r for kw, r in NAME_OVERRIDES if kw in loc["name"]), None)
                if new and new != old:
                    changes[loc["ap_id"]] = (loc["name"], old, f"{new} (mot-clé)")
                    census[new] = census.get(new, 0) + 1
                else:
                    no_coords.append(f"{loc['name']} [{loc.get('category')}] (region={old})")
                    census[old] = census.get(old, 0) + 1
                continue
            new = "Hyrule World"
            for region, poly in polys.items():
                if _inside(w[0], w[1], poly):
                    new = region
                    break
            census[new] = census.get(new, 0) + 1
            if new != old:
                changes[loc["ap_id"]] = (loc["name"], old, new)

    print(f"Répartition finale : { {k: census[k] for k in sorted(census)} }")
    print(f"\n{len(changes)} changement(s) de région :")
    for ap_id, (name, old, new) in sorted(changes.items()):
        print(f"  {name:42s} {old:16s} -> {new}")
    print(f"\n{len(no_coords)} location(s) SANS coordonnées (inchangées, à revoir) :")
    for line in no_coords:
        print(f"  {line}")

    if not args.write:
        print("\n(dry-run — relance avec --write pour appliquer)")
        return

    for path in DATA_FILES:
        if not path.is_file():
            print(f"  ! absent : {path}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.values() if isinstance(data, dict) else data
        n = 0
        for loc in items:
            ch = changes.get(loc["ap_id"])
            if ch:
                loc["region"] = ch[2].replace(" (mot-clé)", "")
                n += 1
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  écrit {path} ({n} régions mises à jour)")


if __name__ == "__main__":
    main()
