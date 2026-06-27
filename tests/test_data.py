"""
Data-integrity tests for the BotW Archipelago world.

These run WITHOUT the Archipelago framework: they validate the committed JSON
(worlds/botw/data/*.json) and the flag-hash recipe — the project's core invariant:

    flag_id = zlib.crc32(flag_name.encode("ascii")) & 0xFFFFFFFF   (stored big-endian)
"""
import json
import zlib
from collections import Counter
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[1] / "worlds" / "botw" / "data"


def crc32(name: str) -> int:
    return zlib.crc32(name.encode("ascii")) & 0xFFFFFFFF


@pytest.fixture(scope="module")
def locations():
    return json.loads((DATA / "locations.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gate_items():
    return json.loads((DATA / "gate_items.json").read_text(encoding="utf-8"))


# ── locations.json ──────────────────────────────────────────────────────────

def test_location_total(locations):
    # Stable game facts; the total only ever grows (places/quests/memories…).
    assert len(locations) >= 640


def test_fixed_category_counts(locations):
    counts = Counter(e["category"] for e in locations)
    assert counts["shrine"] == 120
    assert counts["tower"] == 15
    assert counts["beast"] == 4


def test_location_ap_ids_unique(locations):
    ids = [e["ap_id"] for e in locations]
    assert len(ids) == len(set(ids))


def test_location_flag_hash_matches_crc32(locations):
    """flag_hash must equal crc32(flag_name) for every single location."""
    bad = [e["flag_name"] for e in locations
           if int(e["flag_hash"], 16) != crc32(e["flag_name"])]
    assert bad == [], f"{len(bad)} flag_hash mismatch(es): {bad[:5]}"


# ── gate_items.json ─────────────────────────────────────────────────────────

def test_gate_item_ids_unique(gate_items):
    ids = [i["ap_item_id"] for i in gate_items["items"]]
    ids += [i["ap_item_id"] for i in gate_items.get("filler_items", [])]
    assert len(ids) == len(set(ids))


def test_gate_flag_hash_matches_crc32(gate_items):
    bad = [i["flag_name"] for i in gate_items["items"]
           if i.get("flag_hash") and int(i["flag_hash"], 16) != crc32(i["flag_name"])]
    assert bad == [], f"gate flag_hash mismatch(es): {bad}"


def test_runes_are_starting_items(gate_items):
    """Runes must be role=starting (precollected) — never placed in the pool."""
    runes = {"Magnesis Rune", "Stasis Rune", "Cryonis Rune",
             "Remote Bomb Rune", "Camera Rune"}
    by_name = {i["name"]: i for i in gate_items["items"]}
    for r in runes:
        assert r in by_name, f"missing rune: {r}"
        assert by_name[r]["role"] == "starting", f"{r} should be role=starting"


def test_item_and_location_id_ranges_disjoint(locations, gate_items):
    loc_ids = {e["ap_id"] for e in locations}
    item_ids = {i["ap_item_id"] for i in gate_items["items"]}
    item_ids |= {i["ap_item_id"] for i in gate_items.get("filler_items", [])}
    assert loc_ids.isdisjoint(item_ids)


# ── shrine_chests.json (the world's actual location source) ──────────────────

VALID_REGIONS = {
    "Great Plateau", "Hyrule World", "Eldin", "Hebra",
    "Gerudo Highlands", "Gerudo Town",
}


@pytest.fixture(scope="module")
def shrine_chests():
    return json.loads((DATA / "shrine_chests.json").read_text(encoding="utf-8"))


def test_shrine_chest_total(shrine_chests):
    assert len(shrine_chests) == 205


def test_shrine_chest_dlc_split(shrine_chests):
    base = [c for c in shrine_chests if not c["dlc"]]
    dlc = [c for c in shrine_chests if c["dlc"]]
    assert len(base) == 186 and len(dlc) == 19


def test_shrine_chest_ap_ids_unique(shrine_chests):
    ids = [c["ap_id"] for c in shrine_chests]
    assert len(ids) == len(set(ids))


def test_shrine_chest_names_unique(shrine_chests):
    names = [c["name"] for c in shrine_chests]
    assert len(names) == len(set(names))


def test_shrine_chest_regions_valid(shrine_chests):
    bad = [c["name"] for c in shrine_chests if c["region"] not in VALID_REGIONS]
    assert bad == [], f"invalid region(s): {bad[:5]}"


def test_shrine_chest_hash_id_is_int(shrine_chests):
    assert all(isinstance(c["hash_id"], int) for c in shrine_chests)


def test_shrine_chest_sphere_one(shrine_chests):
    """Great Plateau must hold enough chests for the Paraglider (sphere 1)."""
    plateau = [c for c in shrine_chests if c["region"] == "Great Plateau"]
    assert len(plateau) >= 4


def test_shrine_chest_ids_disjoint_from_items(shrine_chests, gate_items):
    loc_ids = {c["ap_id"] for c in shrine_chests}
    item_ids = {i["ap_item_id"] for i in gate_items["items"]}
    item_ids |= {i["ap_item_id"] for i in gate_items.get("filler_items", [])}
    assert loc_ids.isdisjoint(item_ids)


def test_shrine_chest_flag_hash_matches_crc32(shrine_chests):
    """flag_hash must equal crc32(flag_name) — the client's chest-open poll key."""
    bad = [c["flag_name"] for c in shrine_chests
           if int(c["flag_hash"], 16) != crc32(c["flag_name"])]
    assert bad == [], f"{len(bad)} chest flag_hash mismatch(es): {bad[:5]}"


def test_shrine_chest_flag_naming(shrine_chests):
    """Every chest flag is a CDungeon treasure-box flag suffixed with its HashId."""
    for c in shrine_chests:
        assert c["flag_name"].startswith("CDungeon_TBox_Dungeon_")
        assert c["flag_name"].endswith(str(c["hash_id"]))


def test_shrine_chest_flag_hashes_unique(shrine_chests):
    hashes = [c["flag_hash"] for c in shrine_chests]
    assert len(hashes) == len(set(hashes))
