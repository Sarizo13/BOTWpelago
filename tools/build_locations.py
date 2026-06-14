"""
build_locations — enrichit data/locations.json (et la copie worlds/botw/data/) avec les
checks "lieu découvert" (flags Location_* de flag_names.txt).

Les 139 locations existantes (sanctuaires/tours/bêtes) sont préservées. On ajoute les
Location_* comme category="location", region="Hyrule World" (gated derrière le Paravoile).
ATTENTION flag_names.txt = fins de ligne \r -> on strip (sinon crc32 faux).

Usage : python tools/build_locations.py
"""
from __future__ import annotations

import json
import re
import zlib
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
FLAG_NAMES = PROJECT / "flag_names.txt"
LOC_FILES = [PROJECT / "data" / "locations.json",
             PROJECT / "worlds" / "botw" / "data" / "locations.json"]
LOCATION_BASE_ID = 6_081_400   # plage dédiée aux "lieux" (towers s'arrêtent à 6081315)


def crc(name: str) -> str:
    return f"0x{zlib.crc32(name.encode('ascii')) & 0xFFFFFFFF:08X}"


def readable(s: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)   # camelCase -> espaces
    return s.replace("_", " ").strip()


# Routage région heuristique (conservateur). Ordre = priorité.
# NB: gates de tenues "souples" en BotW -> surtout du flavor de logique. Inconnu -> Hyrule World.
REGION_RULES = [
    ("Gerudo Town",       r"^Gerudo$|GerudoTown"),
    ("Gerudo Highlands",  r"GerudoSummit|GerudoHighland|MountGranajh|Risoka|Sturnida|Gerudo.*Mountain"),
    ("Eldin",             r"Eldin|DeathMountain|Goron|Darb|Medingo|Gorae|Daruk|Cephla|Abandoned.*Mine|Isle ?of ?Rabac|Gut ?Check"),
    ("Hebra",             r"Hebra|Tabantha|Rito|Snowfield|Pikida|Biron|Talonto|Selmie|Flight ?Range|Coldsnap|Sturnida"),
]


def classify_region(loc_suffix: str) -> str:
    for region, pat in REGION_RULES:
        if re.search(pat, loc_suffix, re.I):
            return region
    return "Hyrule World"


def main() -> None:
    loaded = json.loads(LOC_FILES[0].read_text(encoding="utf-8"))
    # idempotent : on repart des locations NON-"location" (139 sanctuaires/tours/bêtes)
    existing = [l for l in loaded if l["category"] != "location"]
    existing_flags = {l["flag_name"] for l in existing}
    existing_ids = {l["ap_id"] for l in existing}

    loc_flags = sorted({
        line.strip() for line in FLAG_NAMES.read_text(encoding="ascii", errors="ignore").splitlines()
        if line.strip().startswith("Location_")
    })

    new = []
    apid = LOCATION_BASE_ID
    for f in loc_flags:
        if f in existing_flags:
            continue
        while apid in existing_ids:
            apid += 1
        suffix = f[len("Location_"):]
        new.append({
            "category": "location",
            "flag_name": f,
            "flag_hash": crc(f),
            "ap_id": apid,
            "name": readable(suffix),
            "region": classify_region(suffix),
        })
        apid += 1

    merged = existing + new
    for path in LOC_FILES:
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  écrit {path}  ({len(existing)} existantes + {len(new)} lieux = {len(merged)})")

    print("\nAperçu nouveaux lieux:")
    for l in new[:6]:
        print(f"  {l['ap_id']}  {l['flag_name']:32s} {l['flag_hash']}  {l['name']}")


if __name__ == "__main__":
    main()
