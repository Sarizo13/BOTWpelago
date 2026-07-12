"""Intégrité des items gate/progression (verrouille l'audit du 2026-07-09).

Invariants garantis sans données du jeu (gitignorées) :
  - chaque flag_hash == crc32(flag_name) ;
  - le mapping champion (ap_item_id → flag de race) est COHÉRENT avec les objets-clés
    companion livrés en poche par le client (une inversion Mipha/Daruk serait silencieuse) ;
  - les 4 sets d'armure livrent 3 pièces + 3 flags IsGet appariés au même actor ;
  - les deux copies de gate_items.json (data/ et worlds/botw/data/) sont identiques.
"""
import json
import zlib
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def gate():
    return json.loads((PROJECT / "data" / "gate_items.json").read_text(encoding="utf-8"))


def test_copies_identical(gate):
    other = json.loads(
        (PROJECT / "worlds" / "botw" / "data" / "gate_items.json").read_text(encoding="utf-8"))
    assert json.dumps(gate["items"], sort_keys=True) == json.dumps(other["items"], sort_keys=True)


def test_flag_hashes_match_names(gate):
    for it in gate["items"]:
        if it.get("flag_name") and it.get("flag_hash"):
            real = zlib.crc32(it["flag_name"].encode("ascii")) & 0xFFFFFFFF
            assert int(it["flag_hash"], 16) == real, it["name"]


def test_champion_companion_pouch_consistency(gate):
    """L'objet-clé Obj_HeroSoul_<race> livré en poche doit correspondre à la race du
    flag IsGet_Obj_HeroSoul_<race> du même ap_item_id."""
    from BotWClient.providers.save_file import _COMPANION_POUCH

    champions = {it["ap_item_id"]: it["flag_name"] for it in gate["items"]
                 if str(it.get("flag_name", "")).startswith("IsGet_Obj_HeroSoul_")}
    assert len(champions) == 4
    for ap_id, flag in champions.items():
        race = flag.removeprefix("IsGet_Obj_HeroSoul_")
        pouch_items = _COMPANION_POUCH.get(ap_id, [])
        assert pouch_items == [f"Obj_HeroSoul_{race}"], f"{ap_id}: {flag} vs {pouch_items}"


def test_master_sword_companion(gate):
    from BotWClient.providers.save_file import _COMPANION_POUCH

    ms = next(it for it in gate["items"] if it["name"] == "Master Sword")
    assert _COMPANION_POUCH.get(ms["ap_item_id"]) == ["Weapon_Sword_070"]


def test_armor_sets_complete(gate):
    for it in gate["items"]:
        if it.get("role") != "ap_progression_logical":
            continue
        inject = it.get("inject") or []
        porch = [a for a in inject if a["type"] == "add_porch"]
        flags = [a for a in inject if a["type"] == "set_flag"]
        if it["name"] == "Bow of Light":
            # Gate Ganon : 1 arc + le flag MAILBOX du mur (TestQuest inerte) — surtout
            # PAS IsGet_Weapon_Bow_071, qui est la preuve du goal 'full' (posé par
            # Zelda pendant Dark Beast, jamais par le client).
            assert [a["item"] for a in porch] == ["Weapon_Bow_071"], it["name"]
            assert [f["flag"] for f in flags] == ["TestQuest_Takano_01_Finish"], it["name"]
            goal_full = gate["goal"]["modes"]["full"]
            assert "IsGet_Weapon_Bow_071" in goal_full
            assert all(f["flag"] not in goal_full for f in flags), it["name"]
            continue
        assert len(porch) == 3 and len(flags) == 3, it["name"]
        actors = {a["item"] for a in porch}
        # un seul set Armor_XXX, avec les 3 pièces
        bases = {a.rsplit("_", 1)[0] for a in actors}
        assert len(bases) == 1, it["name"]
        parts = {a.rsplit("_", 1)[1] for a in actors}
        assert parts == {"Head", "Upper", "Lower"}, it["name"]
        # chaque flag correspond exactement à un actor livré
        assert {f["flag"] for f in flags} == {f"IsGet_{a}" for a in actors}, it["name"]


def test_logical_items_wired_to_companion_delivery(gate):
    """Fix 2026-07-12 : les items logiques (tenues + Arc) sont livrés via le MÉCANISME
    COMPANION du provider (pièces pouch + flags IsGet_/gate), PAS via _inject_pending (où
    un spec mixte porch+flag était mal routé vers la voie flag-only → rien livré). On
    verrouille que chaque pièce et chaque flag du champ `inject` est bien câblé."""
    from BotWClient.providers.save_file import _COMPANION_FLAGS, _COMPANION_POUCH

    logical = [it for it in gate["items"] if it.get("role") == "ap_progression_logical"]
    assert logical, "aucun item logique — la fixture a changé ?"
    for it in logical:
        ap = it["ap_item_id"]
        want_pouch = [e["item"] for e in it["inject"] if e["type"] == "add_porch"]
        want_flags = [e["flag"] for e in it["inject"] if e["type"] == "set_flag"]
        for item in want_pouch:
            assert item in _COMPANION_POUCH.get(ap, []), f"{it['name']}: pièce {item} non câblée"
        for flag in want_flags:
            assert flag in _COMPANION_FLAGS.get(ap, []), f"{it['name']}: flag {flag} non câblé"


def test_logical_flags_are_client_written(gate):
    """Les flags posés par le client (IsGet_Armor_*, mailbox de gate) ne doivent JAMAIS être
    détectés comme des checks joueur (sinon faux check envoyé au serveur)."""
    from BotWClient.providers.save_file import _CLIENT_WRITTEN_FLAGS
    from BotWClient.save_parser import flag_id

    for it in gate["items"]:
        if it.get("role") != "ap_progression_logical":
            continue
        for e in it["inject"]:
            if e["type"] == "set_flag":
                assert flag_id(e["flag"]) in _CLIENT_WRITTEN_FLAGS, e["flag"]


def test_logical_items_have_no_injectable_actions():
    """item_map n'expose AUCUNE action pour les items logiques → queue_item ne fait que
    tracer la réception (pas de spec mixte mal routé). Régression du bug de livraison."""
    from BotWClient.item_map import get_spec

    for ap in (6_080_014, 6_080_015, 6_080_016, 6_080_017, 6_080_018):
        assert get_spec(ap).actions == [], ap
