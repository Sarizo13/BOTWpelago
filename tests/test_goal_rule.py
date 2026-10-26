"""
Condition de victoire côté génération (constat Codex #11, 2026-09-09).

`rules.goal_reached` doit refléter `is_goal_complete` côté client, mode par mode :
  shrines : aucune exigence d'item ;
  full    : Bow of Light + Master Sword (si randomisée) + 4 Créatures atteignables.
rules.py est chargé seul (sans le framework Archipelago) : seul `worlds.generic.Rules`
est simulé, le prédicat testé n'en dépend pas.
"""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def rules(monkeypatch):
    generic = types.ModuleType("worlds.generic")
    rules_stub = types.ModuleType("worlds.generic.Rules")
    rules_stub.set_rule = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "worlds.generic", generic)
    monkeypatch.setitem(sys.modules, "worlds.generic.Rules", rules_stub)
    spec = importlib.util.spec_from_file_location("botw_rules", ROOT / "worlds/botw/rules.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _State:
    def __init__(self, items=(), reachable=()):
        self.items, self.reachable = set(items), set(reachable)

    def has(self, item, player):
        return item in self.items

    def can_reach_location(self, name, player):
        return name in self.reachable


def test_shrines_n_exige_aucun_item(rules):
    assert rules.goal_reached(_State(), 1, full=False, sword_required=True)


def test_full_exige_arc_epee_et_creatures(rules):
    beasts = rules.BEAST_LOCATIONS
    complet = _State({"Bow of Light", "Master Sword"}, beasts)
    assert rules.goal_reached(complet, 1, full=True, sword_required=True)
    assert not rules.goal_reached(_State({"Master Sword"}, beasts), 1, True, True)
    assert not rules.goal_reached(_State({"Bow of Light"}, beasts), 1, True, True)
    trois_creatures = _State({"Bow of Light", "Master Sword"}, beasts[:3])
    assert not rules.goal_reached(trois_creatures, 1, True, True)


def test_full_sans_epee_randomisee(rules):
    assert rules.goal_reached(_State({"Bow of Light"}, rules.BEAST_LOCATIONS), 1, True, False)


def test_full_n_exige_pas_les_capacites_champions(rules):
    # Le client (mode full) ne lit aucun flag HeroSoul : la génération non plus.
    state = _State({"Bow of Light", "Master Sword"}, rules.BEAST_LOCATIONS)
    assert rules.goal_reached(state, 1, True, True)


def test_noms_des_creatures_existent(rules):
    data = json.loads((ROOT / "worlds/botw/data/locations.json").read_text(encoding="utf-8"))
    locs = data if isinstance(data, list) else data["locations"]
    beasts = {loc["name"] for loc in locs if loc["category"] == "beast"}
    assert set(rules.BEAST_LOCATIONS) == beasts
