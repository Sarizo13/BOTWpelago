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
QUEST_BASE_ID    = 6_082_000   # plage dédiée aux "quêtes/défis"
MEMORY_BASE_ID   = 6_082_500   # plage dédiée aux "souvenirs"

# flags de quête à EXCLURE (dev, goal, sous-étapes, doublons bêtes)
QUEST_EXCLUDE = re.compile(
    r"TestQuest|^Test|GanonQuest|_Relic_|_Intro_|_Playing_|_Ready_|Demo_Finish|^OPDemo|_Step", re.I)


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
    # idempotent : on repart des 139 de base (sanctuaires/tours/bêtes)
    existing = [l for l in loaded if l["category"] in ("shrine", "tower", "beast")]
    existing_flags = {l["flag_name"] for l in existing}
    existing_ids = {l["ap_id"] for l in existing}
    used_names = {l["name"] for l in existing}

    all_flags = [line.strip() for line in
                 FLAG_NAMES.read_text(encoding="ascii", errors="ignore").splitlines() if line.strip()]

    def add_batch(flags, category, base_id, name_fn, region_fn):
        out = []
        apid = base_id
        for f in sorted(set(flags)):
            if f in existing_flags:
                continue
            nm = name_fn(f)
            if not nm or nm in used_names:
                continue
            used_names.add(nm)
            while apid in existing_ids:
                apid += 1
            out.append({"category": category, "flag_name": f, "flag_hash": crc(f),
                        "ap_id": apid, "name": nm, "region": region_fn(f)})
            existing_ids.add(apid)
            apid += 1
        return out

    # lieux découverts (Location_*)
    locs = add_batch(
        [f for f in all_flags if f.startswith("Location_")],
        "location", LOCATION_BASE_ID,
        lambda f: readable(f[len("Location_"):]),
        lambda f: classify_region(f[len("Location_"):]))

    # quêtes / défis (*_Finish / *_Finished, hors dev/goal/sous-étapes/bêtes)
    quests = add_batch(
        [f for f in all_flags if (f.endswith("_Finish") or f.endswith("_Finished"))
         and not QUEST_EXCLUDE.search(f)],
        "quest", QUEST_BASE_ID,
        lambda f: readable(re.sub(r"_Finish(ed)?$", "", f)),
        lambda f: "Hyrule World")

    # souvenirs (IsGet_MemoryPhoto_NNN)
    memories = add_batch(
        [f for f in all_flags if f.startswith("IsGet_MemoryPhoto_")],
        "memory", MEMORY_BASE_ID,
        lambda f: "Souvenir " + f[len("IsGet_MemoryPhoto_"):],
        lambda f: "Hyrule World")

    merged = existing + locs + quests + memories
    for path in LOC_FILES:
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  écrit {path}  ({len(existing)} base + {len(locs)} lieux + {len(quests)} quêtes "
              f"+ {len(memories)} souvenirs = {len(merged)})")

    print("\nAperçu quêtes:")
    for l in quests[:6]:
        print(f"  {l['ap_id']}  {l['flag_name']:32s} {l['name']}")


if __name__ == "__main__":
    main()
