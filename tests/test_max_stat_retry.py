"""
Reprise après échec partiel de _deliver_max_stat (constat Codex #5, 2026-09-09).

La livraison relisait le max courant et RE-planifiait à chaque essai : après un échec
partiel (StaminaMax écrit mais StaminaCurrentMax raté, ou stat montée mais rubis d'overflow
indisponibles), l'essai suivant re-créditait la fiole ou doublait les rubis. Le plan est
désormais mémorisé par stat (cible + étapes faites) ; si la quantité coalescée grandit entre
deux essais, seul le reliquat est replanifié.
"""
from pathlib import Path

from BotWClient.providers.base import InjectionSpec
from BotWClient.providers.save_file import DeferredSaveInjector


class _Bridge:
    """Flags relus après écriture ; échecs injectables (n prochains appels)."""
    has_live_inventory = True

    def __init__(self, flags, fail_flag=None, fail_rupees=0):
        self.flags = dict(flags)
        self.fail_flag, self.fail_count = fail_flag, 1 if fail_flag else 0
        self.fail_rupees = fail_rupees
        self.rupees = 0

    def read_flag(self, name):
        v = self.flags.get(name)
        return None if v is None else int(v) & 0xFFFFFFFF

    def read_flag_f32(self, name):
        return self.flags.get(name)

    def _write(self, name, value):
        if name == self.fail_flag and self.fail_count:
            self.fail_count -= 1
            return False
        self.flags[name] = value
        return True

    def write_flag(self, name, value):
        return self._write(name, value)

    def write_flag_f32(self, name, value):
        return self._write(name, value)

    def live_add_rupees(self, amount):
        if self.fail_rupees:
            self.fail_rupees -= 1
            return None
        self.rupees += amount
        return self.rupees

    def toast_enqueue(self, actor, qty=1):
        pass

    def toast_enqueue_text(self, text):
        pass


def _stamina(amount):
    return InjectionSpec(
        ap_item_id=6_080_129, ap_item_name="Stamina Vessel",
        actions=[InjectionSpec.AddMaxStat(stat="stamina", amount=amount, overflow_rupees=500)])


def _deliver(inj, spec):
    return inj._deliver_max_stat(spec.actions[0], spec, memory=True)


def test_flag_partiel_pas_de_fiole_en_trop(tmp_path: Path):
    b = _Bridge({"StaminaMax": 1000.0, "StaminaCurrentMax": 1000.0},
                fail_flag="StaminaCurrentMax")
    inj = DeferredSaveInjector(tmp_path, bridge=b)
    assert _deliver(inj, _stamina(1)) is False          # 2e flag raté → reporté
    assert _deliver(inj, _stamina(1)) is True           # reprise
    assert (b.flags["StaminaMax"], b.flags["StaminaCurrentMax"]) == (1200.0, 1200.0)


def test_rubis_indisponibles_pas_de_rubis_en_double(tmp_path: Path):
    # 2 fioles coalescées à 2800 (plafond 3000) : 1 appliquée + 1 overflow = 500 rubis
    b = _Bridge({"StaminaMax": 2800.0, "StaminaCurrentMax": 2800.0}, fail_rupees=1)
    inj = DeferredSaveInjector(tmp_path, bridge=b)
    assert _deliver(inj, _stamina(2)) is False          # portefeuille pas encore localisé
    assert _deliver(inj, _stamina(2)) is True
    assert b.flags["StaminaMax"] == 3000.0
    assert b.rupees == 500


def test_quantite_coalescee_qui_grandit_reliquat_seul(tmp_path: Path):
    b = _Bridge({"StaminaMax": 1000.0, "StaminaCurrentMax": 1000.0},
                fail_flag="StaminaCurrentMax")
    inj = DeferredSaveInjector(tmp_path, bridge=b)
    assert _deliver(inj, _stamina(1)) is False
    assert _deliver(inj, _stamina(3)) is True           # 2 fioles de plus arrivées entre-temps
    assert (b.flags["StaminaMax"], b.flags["StaminaCurrentMax"]) == (1600.0, 1600.0)


def test_livraison_suivante_repart_de_zero(tmp_path: Path):
    b = _Bridge({"StaminaMax": 1000.0, "StaminaCurrentMax": 1000.0})
    inj = DeferredSaveInjector(tmp_path, bridge=b)
    assert _deliver(inj, _stamina(1)) is True
    assert _deliver(inj, _stamina(1)) is True           # 2e fiole distincte : appliquée
    assert b.flags["StaminaMax"] == 1400.0
