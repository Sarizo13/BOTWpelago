"""
Cap cœurs / endurance + overflow rubis (save_file._deliver_max_stat / _plan_max_stat).

Un Réceptacle de Cœur / une Fiole d'Endurance monte le MAX persistant jusqu'au plafond DUR
du jeu ; toute unité au-delà (joueur déjà au max) devient un don de rubis. Ces tests
verrouillent la LOGIQUE (planificateur pur + livraison) sans jeu : les constantes de flags
(cf. _MAX_STAT) restent À CONFIRMER IN-GAME, mais le repli SÛR (flag absent → rubis, jamais
d'écriture hasardeuse) est garanti ici.
"""
import struct

import pytest

from BotWClient.providers.base import InjectionSpec
from BotWClient.providers.save_file import (
    DeferredSaveInjector,
    _MAX_STAT,
    _plan_max_stat,
)


# ── planificateur pur ──────────────────────────────────────────────────────────

def test_plan_below_cap_all_applied():
    # loin du plafond : les 2 unités s'appliquent, aucun overflow
    assert _plan_max_stat(12, 4, 120, 2) == (20, 2, 0)


def test_plan_partial_overflow():
    # 112 → 116 → 120 (2 appliquées), les 3 restantes débordent
    assert _plan_max_stat(112, 4, 120, 5) == (120, 2, 3)


def test_plan_full_overflow_at_cap():
    assert _plan_max_stat(120, 4, 120, 3) == (120, 0, 3)


def test_plan_stamina_float():
    v, applied, overflow = _plan_max_stat(2800.0, 200.0, 3000.0, 3)
    assert applied == 1 and overflow == 2 and v == pytest.approx(3000.0)


def test_plan_zero_amount():
    assert _plan_max_stat(12, 4, 120, 0) == (12, 0, 0)


# ── livraison (voie mémoire) via faux bridge ────────────────────────────────────

class _MockBridge:
    """CemuMemoryBridge minimal : sert des flags synthétiques et enregistre les écritures."""
    def __init__(self, flags):
        self._flags = dict(flags)         # nom -> valeur (u32 pour s32, float pour f32)
        self.writes = {}                  # nom -> valeur écrite
        self.rupees = 0
        self.has_live_inventory = True

    def read_flag(self, name):
        v = self._flags.get(name)
        return None if v is None else (v & 0xFFFFFFFF)

    def read_flag_f32(self, name):
        return self._flags.get(name)

    def write_flag(self, name, value):
        self.writes[name] = value
        return True

    def write_flag_f32(self, name, value):
        self.writes[name] = value
        return True

    def live_add_rupees(self, amount):
        self.rupees += amount
        return self.rupees


def _injector(tmp_path, bridge):
    inj = DeferredSaveInjector(tmp_path, bridge=bridge)
    return inj


def _spec(stat, amount=1, overflow=500):
    return InjectionSpec(
        ap_item_id=6_080_128 if stat == "heart" else 6_080_129,
        ap_item_name="Heart Container" if stat == "heart" else "Stamina Vessel",
        actions=[InjectionSpec.AddMaxStat(stat=stat, amount=amount, overflow_rupees=overflow)],
    )


def test_deliver_heart_below_cap_writes_stat_no_rupees(tmp_path):
    b = _MockBridge({"Item_LifeMaxUp": 12})          # 3 cœurs
    inj = _injector(tmp_path, b)
    spec = _spec("heart", amount=2)
    assert inj._deliver_max_stat(spec.actions[0], spec, memory=True) is True
    assert b.writes["Item_LifeMaxUp"] == 20          # +2 cœurs (8 ¼-cœurs)
    assert b.rupees == 0


def test_deliver_heart_overflow_gives_rupees(tmp_path):
    b = _MockBridge({"Item_LifeMaxUp": 112})         # 28 cœurs (près du max 30)
    inj = _injector(tmp_path, b)
    spec = _spec("heart", amount=5, overflow=500)
    assert inj._deliver_max_stat(spec.actions[0], spec, memory=True) is True
    assert b.writes["Item_LifeMaxUp"] == 120         # clampé au plafond
    assert b.rupees == 3 * 500                        # 3 réceptacles au-delà → rubis


def test_deliver_heart_flag_absent_all_rupees_no_write(tmp_path):
    """Flag introuvable (cas RÉEL de cette version : Item_LifeMaxUp absent du dump) →
    repli SÛR : tout en rubis, AUCUNE écriture de flag hasardeuse."""
    b = _MockBridge({})                              # pas de flag cœurs
    inj = _injector(tmp_path, b)
    spec = _spec("heart", amount=2, overflow=500)
    assert inj._deliver_max_stat(spec.actions[0], spec, memory=True) is True
    assert "Item_LifeMaxUp" not in b.writes          # jamais écrit
    assert b.rupees == 2 * 500


def test_deliver_stamina_f32_below_cap(tmp_path):
    b = _MockBridge({"StaminaMax": 1000.0})          # 1 roue
    inj = _injector(tmp_path, b)
    spec = _spec("stamina", amount=2)
    assert inj._deliver_max_stat(spec.actions[0], spec, memory=True) is True
    assert b.writes["StaminaMax"] == pytest.approx(1400.0)
    assert b.rupees == 0


def test_deliver_stamina_at_cap_all_rupees(tmp_path):
    b = _MockBridge({"StaminaMax": 3000.0})          # 3 roues (max)
    inj = _injector(tmp_path, b)
    spec = _spec("stamina", amount=1, overflow=500)
    assert inj._deliver_max_stat(spec.actions[0], spec, memory=True) is True
    assert "StaminaMax" not in b.writes
    assert b.rupees == 500


def test_deliver_heart_implausible_value_falls_back_to_rupees(tmp_path):
    """Valeur hors plage plausible (lecture douteuse) → repli rubis, pas d'écriture."""
    b = _MockBridge({"Item_LifeMaxUp": 999999})      # hors [lo, hi]
    inj = _injector(tmp_path, b)
    spec = _spec("heart", amount=1, overflow=500)
    assert inj._deliver_max_stat(spec.actions[0], spec, memory=True) is True
    assert "Item_LifeMaxUp" not in b.writes
    assert b.rupees == 500


def test_max_stat_config_present():
    assert set(_MAX_STAT) == {"heart", "stamina"}
    assert _MAX_STAT["stamina"]["kind"] == "f32"
    assert _MAX_STAT["heart"]["kind"] == "s32"
