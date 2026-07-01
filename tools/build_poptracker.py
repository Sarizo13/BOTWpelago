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

# Items-clés suivis (ap_item_id, nom affiché, code tracker, type, couleur icône RGB)
KEY_ITEMS = [
    (6_080_000, "Paraglider",         "paraglider",   "toggle",     (0xF2, 0xC0, 0x4C)),
    (6_080_006, "Master Sword",       "master_sword", "toggle",     (0x5C, 0x8A, 0xF0)),
    (6_080_010, "Revali's Gale",      "revali",       "toggle",     (0x2E, 0xC4, 0x66)),
    (6_080_011, "Mipha's Grace",      "mipha",        "toggle",     (0x3A, 0xB6, 0xD6)),
    (6_080_012, "Daruk's Protection", "daruk",        "toggle",     (0xD6, 0x5A, 0x3A)),
    (6_080_013, "Urbosa's Fury",      "urbosa",       "toggle",     (0xE0, 0xC8, 0x3A)),
    (6_080_014, "Flamebreaker Armor", "flamebreaker", "toggle",     (0xC4, 0x45, 0x2E)),
    (6_080_015, "Snowquill Set",      "snowquill",    "toggle",     (0xBE, 0xD8, 0xE8)),
    (6_080_016, "Vai Outfit",         "vai",          "toggle",     (0xC8, 0x7A, 0xC8)),
    (6_080_100, "Spirit Orbs",        "spirit_orbs",  "consumable", (0xE8, 0xC8, 0x50)),
]


def _load(name: str):
    d = json.loads((DATA / name).read_text(encoding="utf-8"))
    return list(d.values()) if isinstance(d, dict) else d


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

    # ── Arbre de lieux : région → catégorie → sections (un check = une section) ──
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
        tree.setdefault(region, {}).setdefault(label, []).append(name)
        loc_mapping[int(loc["ap_id"])] = path

    locations_json = []
    for region in sorted(tree):
        children = []
        cats = tree[region]
        for label in sorted(cats, key=lambda l: next(
                (i for i, c in enumerate(CAT_ORDER) if CATEGORY_LABEL.get(c) == l), 99)):
            children.append({"name": label,
                             "sections": [{"name": n} for n in cats[label]]})
        locations_json.append({"name": region, "children": children})
    (OUT / "locations" / "locations.json").write_text(
        json.dumps(locations_json, indent=1, ensure_ascii=False), encoding="utf-8")

    # ── Items-clés + icônes placeholder ──
    items_json, item_mapping = [], {}
    for ap_id, disp, code, typ, rgb in KEY_ITEMS:
        img = f"images/items/{code}.png"
        _png_square(OUT / img, rgb)
        entry = {"name": disp, "type": typ, "img": img, "codes": code}
        if typ == "consumable":
            entry["max_quantity"] = 900
            entry["increment"] = 1
        items_json.append(entry)
        item_mapping[ap_id] = [[code, typ]]
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

    # ── Layouts (grille d'items pour l'overlay de stream + fenêtre principale) ──
    grid = {
        "type": "array", "orientation": "vertical", "margin": "4,4", "content": [
            {"type": "itemgrid", "item_margin": "3,3", "item_size": "40,40",
             "rows": [
                 ["paraglider", "master_sword"],
                 ["revali", "mipha", "daruk", "urbosa"],
                 ["flamebreaker", "snowquill", "vai"],
                 ["spirit_orbs"],
             ]},
        ],
    }
    (OUT / "layouts" / "tracker.json").write_text(
        json.dumps({"tracker_default": grid, "tracker_broadcast": grid}, indent=1), encoding="utf-8")

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
    print(f"  lieux : {len(loc_mapping)}  |  items-clés : {len(item_mapping)}  |  régions : {len(tree)}")


_INIT_LUA = """\
-- Point d'entrée PopTracker (exécuté au chargement du pack)
ENABLE_DEBUG_LOG = true
Tracker:AddItems("items/items.json")
Tracker:AddLocations("locations/locations.json")
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
