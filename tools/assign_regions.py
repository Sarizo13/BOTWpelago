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


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Enveloppe convexe (Andrew monotone chain), sens trigo."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _grow(poly: list[tuple[float, float]], margin: float) -> list[tuple[float, float]]:
    """Élargit un polygone convexe en poussant chaque sommet de `margin` unités depuis le
    centroïde. Rend le test point-dans-polygone inclusif pour les points coïncidant avec un
    sommet (les lieux de sanctuaire sont AUX coords des sanctuaires = sommets de l'enveloppe)."""
    if not poly:
        return poly
    cx = sum(p[0] for p in poly) / len(poly)
    cz = sum(p[1] for p in poly) / len(poly)
    out = []
    for x, z in poly:
        dx, dz = x - cx, z - cz
        d = (dx * dx + dz * dz) ** 0.5 or 1.0
        out.append((x + dx / d * margin, z + dz / d * margin))
    return out


def _plateau_polygon(ref_locs: list[dict], margin: float = 120.0) -> list[tuple[float, float]]:
    """Zone Grand Plateau = enveloppe convexe des checks DÉJÀ tagués 'Great Plateau'
    (4 sanctuaires + tour), élargie d'une marge conservatrice. Le Plateau n'est pas muré
    (pas de zone_walls) mais forme une zone géographique nette et ISOLÉE : tout ce qui est
    DESSUS est atteignable SANS la paravoile (comme les sanctuaires ; la paravoile ne garde
    que la SORTIE du plateau). Sans ça, les LIEUX du plateau (Location_* co-localisés aux
    sanctuaires + Temple du Temps) retombaient en 'Hyrule World' → affichés inaccessibles
    dans le tracker et gatés à tort dans la logique AP. Marge 120 u : l'Hyrule central le
    plus proche (Dah Kaso) est à ~390 u → aucun risque de sur-inclusion."""
    pts = []
    for loc in ref_locs:
        if (loc.get("region") or "") == "Great Plateau":
            w = _world(loc["ap_id"])
            if w:
                pts.append(w)
    return _grow(_convex_hull(pts), margin) if len(pts) >= 3 else []


def _zone_polygons(ref_locs: list[dict] | None = None) -> dict[str, list[tuple[float, float]]]:
    """Ferme les murs en polygones de zone avec les bords de carte (~±5100). Ajoute la zone
    Grand Plateau (dérivée des checks du plateau, cf. _plateau_polygon) si `ref_locs` fourni."""
    w = WALLS["regions"]
    eldin = [tuple(p) for p in w["Eldin"]["walls"][0]["points"]]
    eldin += [(eldin[-1][0], -4200.0), (eldin[0][0], -4200.0)]          # bord nord
    rito = [tuple(p) for p in w["Rito"]["walls"][0]["points"]]          # déjà fermé
    zora = [tuple(p) for p in w["Zora"]["walls"][0]["points"]]
    zora += [(5200.0, zora[-1][1]), (5200.0, zora[0][1])]               # bord est
    gerudo = [tuple(p) for wall in w["Gerudo"]["walls"] for p in wall["points"]]
    gerudo += [(gerudo[-1][0], 4200.0), (-5200.0, 4200.0), (-5200.0, gerudo[0][1])]
    polys: dict[str, list[tuple[float, float]]] = {}
    # Plateau EN PREMIER : petite zone isolée, prioritaire sur les grandes zones murées.
    if ref_locs is not None:
        plateau = _plateau_polygon(ref_locs)
        if plateau:
            polys["Great Plateau"] = plateau
    polys.update({"Eldin": eldin, "Hebra": rito, "Zora": zora, "Gerudo": gerudo})
    return polys


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

    # Zone Grand Plateau dérivée des checks du plateau de la copie de référence (data/).
    ref_locs = json.loads(DATA_FILES[0].read_text(encoding="utf-8"))
    polys = _zone_polygons(ref_locs)
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
