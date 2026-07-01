"""
Génère un pack PopTracker pour BotW avec AUTOTRACKING Archipelago.

Sortie : poptracker/botw-ap-tracker/  (JSON + Lua + icônes placeholder — tout est NOTRE contenu,
donc committable ; la carte/les images du jeu viendront en Phase 2 et resteront hors git).

  python tools/build_poptracker.py                 # -> poptracker/botw-ap-tracker/
  python tools/build_poptracker.py --install       # + copie vers D:/poptracker/packs/

Phase 1 : pas de carte. Arbre de lieux (régions → catégories → 851 checks) auto-coché par AP,
+ grille d'items-clés (paravoile, épée, champions, tenues) + compteur d'orbes. La carte cliquable
(Phase 2) nécessite une image de Hyrule + les coords (sourcées depuis zeldamods/objmap).
"""
from __future__ import annotations

import argparse
import json
import struct
import shutil
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT  = ROOT / "poptracker" / "botw-ap-tracker"

CATEGORY_LABEL = {
    "shrine":       "Shrines",
    "shrine_chest": "Shrine Chests",
    "tower":        "Towers",
    "beast":        "Divine Beasts",
    "memory":       "Memories",
    "quest":        "Quests",
    "location":     "Places",
}
# Ordre d'affichage des catégories dans chaque région
CAT_ORDER = ["shrine", "beast", "tower", "memory", "quest", "location", "shrine_chest"]

# Items-clés du tracker.
#   ap      = id AP (None = pas un item AP → pas d'ITEM_MAPPING ; toggle manuel / compteur goal)
#   type    = toggle | consumable   ; rgb = couleur du placeholder si pas d'icône fournie
#   special = "shrine_counter" (+1 sur chaque check sanctuaire) | "shrine_goal" (= slot_data)
#   Les tenues utilisent l'icône du CASQUE (le rando garde la tenue complète pour le gate).
KEY_ITEMS = [
    {"ap": 6_080_000, "disp": "Paraglider",        "code": "paraglider",   "type": "toggle",     "rgb": (0xF2, 0xC0, 0x4C)},
    {"ap": 6_080_006, "disp": "Master Sword",      "code": "master_sword", "type": "toggle",     "rgb": (0x5C, 0x8A, 0xF0)},
    {"ap": None,      "disp": "Bow of Light",      "code": "bow_of_light", "type": "toggle",     "rgb": (0xBF, 0xE8, 0xFF)},
    {"ap": 6_080_010, "disp": "Revali's Gale",     "code": "revali",       "type": "toggle",     "rgb": (0x2E, 0xC4, 0x66)},
    {"ap": 6_080_011, "disp": "Mipha's Grace",     "code": "mipha",        "type": "toggle",     "rgb": (0x3A, 0xB6, 0xD6)},
    {"ap": 6_080_012, "disp": "Daruk's Protection","code": "daruk",        "type": "toggle",     "rgb": (0xD6, 0x5A, 0x3A)},
    {"ap": 6_080_013, "disp": "Urbosa's Fury",     "code": "urbosa",       "type": "toggle",     "rgb": (0xE0, 0xC8, 0x3A)},
    {"ap": 6_080_014, "disp": "Flamebreaker (casque)", "code": "flamebreaker", "type": "toggle", "rgb": (0xC4, 0x45, 0x2E)},
    {"ap": 6_080_015, "disp": "Snowquill (casque)",    "code": "snowquill",    "type": "toggle", "rgb": (0xBE, 0xD8, 0xE8)},
    {"ap": 6_080_016, "disp": "Vai (casque)",          "code": "vai",          "type": "toggle", "rgb": (0xC8, 0x7A, 0xC8)},
    {"ap": 6_080_017, "disp": "Zora (casque)",         "code": "zora",         "type": "toggle", "rgb": (0x3A, 0x9A, 0xD6)},
    {"ap": 6_080_100, "disp": "Spirit Orbs",       "code": "spirit_orbs",  "type": "consumable", "rgb": (0xE8, 0xC8, 0x50), "max": 200},
    {"ap": None, "disp": "Shrines Cleared",  "code": "shrines_cleared",  "type": "consumable", "rgb": (0x7A, 0xC8, 0xE8), "max": 120, "special": "shrine_counter", "icon_src": "shrine"},
    {"ap": None, "disp": "Shrines Required", "code": "shrines_required", "type": "consumable", "rgb": (0xF0, 0xC0, 0x40), "max": 120, "special": "shrine_goal", "icon_src": "shrine"},
]


def _load(name: str):
    d = json.loads((DATA / name).read_text(encoding="utf-8"))
    return list(d.values()) if isinstance(d, dict) else d


def _copy_as_png(src: Path, dest: Path) -> None:
    """Copie une icône en la RÉ-ENCODANT en vrai PNG. Les sites d'icônes servent souvent du
    WebP (ou JPEG) renommé .png, que le loader de PopTracker ne sait PAS afficher → on convertit.
    Fallback : copie brute si Pillow est absent."""
    try:
        from PIL import Image
        Image.open(src).convert("RGBA").save(dest, "PNG")
    except Exception:
        shutil.copy(src, dest)


def _png_square(path: Path, rgb, size: int = 40) -> None:
    """Écrit un PNG carré uni (icône placeholder) — sans dépendance externe."""
    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # RGB 8-bit
    row = b"\x00" + bytes(rgb) * size
    idat = zlib.compress(row * size, 9)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def build() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "scripts" / "autotracking").mkdir(parents=True)
    (OUT / "locations").mkdir()
    (OUT / "items").mkdir()
    (OUT / "layouts").mkdir()
    (OUT / "images" / "items").mkdir(parents=True)

    locs = _load("locations.json") + _load("shrine_chests.json")

    # ── Coords carte extraites du dump (tools/extract_map_coords.py) — LOCAL, optionnel ──
    coords: dict[str, list] = {}
    cfile = ROOT / "poptracker" / "map_coords.json"
    if cfile.exists():
        coords = json.loads(cfile.read_text(encoding="utf-8"))

    # ── Arbre : région → catégorie → CHECK (location épinglée sur la carte) → 1 section ──
    tree: dict[str, dict[str, list]] = {}
    loc_mapping: dict[int, str] = {}
    seen_paths: set[str] = set()
    for loc in locs:
        region = loc.get("region") or "Hyrule World"
        cat = loc["category"]
        label = CATEGORY_LABEL.get(cat, cat.title())
        name = loc["name"]
        path = f"@{region}/{label}/{name}"
        if path in seen_paths:                      # collision de nom → suffixe l'ap_id
            path = f"{path} ({loc['ap_id']})"
            name = f"{name} ({loc['ap_id']})"
        seen_paths.add(path)
        tree.setdefault(region, {}).setdefault(label, []).append((name, int(loc["ap_id"])))
        loc_mapping[int(loc["ap_id"])] = path

    def _check_node(name: str, ap_id: int) -> dict:
        # chaque check = une location (1 section) → référencée par son @path ; le pin carte
        # (map_locations) se colore selon sa complétion. onLocation décrémente son ChestCount.
        node = {"name": name, "sections": [{"name": name}]}   # section NOMMÉE → pin rendu
        xy = coords.get(str(ap_id))
        if xy:
            node["map_locations"] = [{"map": "hyrule", "x": int(xy[0]), "y": int(xy[1])}]
        return node

    locations_json = []
    for region in sorted(tree):
        children = []
        cats = tree[region]
        for label in sorted(cats, key=lambda l: next(
                (i for i, c in enumerate(CAT_ORDER) if CATEGORY_LABEL.get(c) == l), 99)):
            children.append({"name": label,
                             "children": [_check_node(n, i) for n, i in cats[label]]})
        locations_json.append({"name": region, "children": children})
    (OUT / "locations" / "locations.json").write_text(
        json.dumps(locations_json, indent=1, ensure_ascii=False), encoding="utf-8")
    n_pins = sum(1 for i in loc_mapping if str(i) in coords)

    # ── Carte (Phase 2) : maps.json + image hyrule.png ──
    # L'image de carte (art du jeu) se place à poptracker/hyrule.png (SOURCE, hors pack, gitignored) ;
    # on la copie dans le pack. La garder hors de OUT évite qu'un rmtree de régénération l'efface.
    (OUT / "maps").mkdir(exist_ok=True)
    (OUT / "maps" / "maps.json").write_text(json.dumps([{
        "name": "hyrule", "img": "maps/hyrule.png",
        "location_size": 10, "location_border_thickness": 2,
    }], indent=1), encoding="utf-8")
    src_map = ROOT / "poptracker" / "hyrule.png"
    if src_map.exists():
        shutil.copy(src_map, OUT / "maps" / "hyrule.png")
    else:
        print("  (place la carte à poptracker/hyrule.png -> elle sera copiée dans le pack)")

    # ── Items-clés : icône depuis poptracker/icons/<code>.png (SOURCE, hors pack) sinon placeholder ──
    src_icons = ROOT / "poptracker" / "icons"
    items_json, item_mapping = [], {}
    for it in KEY_ITEMS:
        code, typ = it["code"], it["type"]
        img = f"images/items/{code}.png"
        src = src_icons / f"{it.get('icon_src', code)}.png"   # icon_src : réutilise une autre icône (ex: shrine)
        if src.exists():
            _copy_as_png(src, OUT / img)      # ré-encode (WebP/JPEG renommé .png → vrai PNG)
        else:
            _png_square(OUT / img, it["rgb"])
        entry = {"name": it["disp"], "type": typ, "img": img, "codes": code}
        if typ == "consumable":
            entry["max_quantity"] = it.get("max", 200)
            entry["increment"] = 1
        items_json.append(entry)
        if it["ap"] is not None:                       # None = manuel (Arc) / compteur goal
            item_mapping[it["ap"]] = [[code, typ]]
    (OUT / "items" / "items.json").write_text(
        json.dumps(items_json, indent=1, ensure_ascii=False), encoding="utf-8")

    # ── Lua : mappings AP ──
    def lua_loc():
        lines = ["-- AUTO-GÉNÉRÉ par tools/build_poptracker.py — ne pas éditer à la main",
                 "LOCATION_MAPPING = {"]
        for ap_id in sorted(loc_mapping):
            p = loc_mapping[ap_id].replace('"', '\\"')
            lines.append(f'  [{ap_id}] = {{"{p}"}},')
        lines.append("}")
        return "\n".join(lines) + "\n"

    def lua_item():
        lines = ["-- AUTO-GÉNÉRÉ par tools/build_poptracker.py",
                 "ITEM_MAPPING = {"]
        for ap_id in sorted(item_mapping):
            pairs = ", ".join('{"%s", "%s"}' % (c, t) for c, t in item_mapping[ap_id])
            lines.append(f"  [{ap_id}] = {{{pairs}}},")
        lines.append("}")
        return "\n".join(lines) + "\n"

    (OUT / "scripts" / "autotracking" / "location_mapping.lua").write_text(lua_loc(), encoding="utf-8")
    (OUT / "scripts" / "autotracking" / "item_mapping.lua").write_text(lua_item(), encoding="utf-8")
    (OUT / "scripts" / "autotracking" / "archipelago.lua").write_text(_ARCHIPELAGO_LUA, encoding="utf-8")
    (OUT / "scripts" / "init.lua").write_text(_INIT_LUA, encoding="utf-8")

    # ── Layouts : grille d'items (overlay stream) + carte de Hyrule ──
    grid = {
        "type": "array", "orientation": "vertical", "margin": "4,4", "content": [
            {"type": "itemgrid", "item_margin": "3,3", "item_size": "40,40",
             "rows": [
                 ["paraglider", "master_sword", "bow_of_light"],
                 ["revali", "mipha", "daruk", "urbosa"],
                 ["flamebreaker", "snowquill", "vai", "zora"],
                 ["spirit_orbs", "shrines_cleared", "shrines_required"],
             ]},
        ],
    }
    map_view = {"type": "map", "maps": ["hyrule"]}
    default = {"type": "array", "orientation": "horizontal", "margin": "0,0",
               "content": [grid, map_view]}
    (OUT / "layouts" / "tracker.json").write_text(
        json.dumps({"tracker_default": default,
                    "tracker_broadcast": grid,
                    "tracker_maps": map_view}, indent=1), encoding="utf-8")

    # ── Manifest ──
    manifest = {
        "name": "BotW Archipelago Tracker",
        "game_name": "The Legend of Zelda: Breath of the Wild",
        "package_version": "0.1.0",
        "package_uid": "botw-ap",
        "platform": "wiiu",
        "author": "BOTWpelago",
        "variants": {"standard": {"display_name": "Tracker", "flags": ["ap"]}},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=4), encoding="utf-8")

    print(f"[poptracker] pack généré -> {OUT}")
    print(f"  lieux : {len(loc_mapping)}  |  pins carte : {n_pins}  |  "
          f"items-clés : {len(item_mapping)}  |  régions : {len(tree)}")
    if not coords:
        print("  (pas de map_coords.json — lance tools/extract_map_coords.py pour les pins carte)")


_INIT_LUA = """\
-- Point d'entrée PopTracker (exécuté au chargement du pack)
ENABLE_DEBUG_LOG = true
Tracker:AddItems("items/items.json")
Tracker:AddLocations("locations/locations.json")
Tracker:AddMaps("maps/maps.json")
Tracker:AddLayouts("layouts/tracker.json")
ScriptHost:LoadScript("scripts/autotracking/archipelago.lua")
"""

# Hooks AP (calqués sur le pack Celeste) : onClear (reset + slot_data), onItem, onLocation.
_ARCHIPELAGO_LUA = """\
ScriptHost:LoadScript("scripts/autotracking/item_mapping.lua")
ScriptHost:LoadScript("scripts/autotracking/location_mapping.lua")

CUR_INDEX = -1

function onClear(slot_data)
    CUR_INDEX = -1
    for _, path in pairs(LOCATION_MAPPING) do
        local obj = Tracker:FindObjectForCode(path[1])
        if obj then
            if path[1]:sub(1, 1) == "@" then
                obj.AvailableChestCount = obj.ChestCount
            else
                obj.Active = false
            end
        end
    end
    for _, v in pairs(ITEM_MAPPING) do
        local obj = Tracker:FindObjectForCode(v[1][1])
        if obj then
            if v[1][2] == "toggle" then obj.Active = false
            elseif v[1][2] == "consumable" then obj.AcquiredCount = 0 end
        end
    end
    -- Goal : compteur de sanctuaires (X cochés / N requis via slot_data)
    local sc = Tracker:FindObjectForCode("shrines_cleared")
    if sc then sc.AcquiredCount = 0 end
    local req = slot_data and slot_data["required_shrine_count"]
    local sr = Tracker:FindObjectForCode("shrines_required")
    if sr and req then sr.AcquiredCount = tonumber(req) end
end

function onItem(index, item_id, item_name, player_number)
    if index <= CUR_INDEX then return end
    CUR_INDEX = index
    local v = ITEM_MAPPING[item_id]
    if not v then return end
    for _, it in pairs(v) do
        local obj = Tracker:FindObjectForCode(it[1])
        if obj then
            if it[2] == "toggle" then obj.Active = true
            elseif it[2] == "consumable" then obj.AcquiredCount = obj.AcquiredCount + obj.Increment end
        end
    end
end

function onLocation(location_id, location_name)
    local a = LOCATION_MAPPING[location_id]
    if not a or not a[1] then return end
    local obj = Tracker:FindObjectForCode(a[1])
    if obj then
        if a[1]:sub(1, 1) == "@" then
            obj.AvailableChestCount = obj.AvailableChestCount - 1
        else
            obj.Active = true
        end
    end
    -- Goal : +1 au compteur quand un sanctuaire est coché (ids 6081000-6081119)
    if location_id >= 6081000 and location_id <= 6081119 then
        local s = Tracker:FindObjectForCode("shrines_cleared")
        if s then s.AcquiredCount = s.AcquiredCount + 1 end
    end
end

Archipelago:AddClearHandler("clear", onClear)
Archipelago:AddItemHandler("item", onItem)
Archipelago:AddLocationHandler("location", onLocation)
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", nargs="?", const="D:/poptracker/packs", default=None,
                    help="copie le pack dans le dossier packs de PopTracker")
    args = ap.parse_args()
    build()
    if args.install:
        dst = Path(args.install) / OUT.name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(OUT, dst)
        print(f"[install] copié -> {dst}")


if __name__ == "__main__":
    main()
