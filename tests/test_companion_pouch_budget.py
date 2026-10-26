"""
Création des objets companion (constat Codex #7, 2026-09-09).

_deliver_companion_pouch créait en live tous les objets companion manquants (jusqu'à 19 :
paravoile, Épée, 4 capacités, 4 tenues × 3, Arc de Lumière) en UN cycle, sans regarder
_LIVE_CREATE_ENABLED, pool_exhausted ni le budget MAX_DELIVER_PER_FLUSH — exactement la
rafale que le budget doit empêcher (pool épuisé → reconstruction de la poche qui plante).
Désormais : commutateur + pool respectés, budget PARTAGÉ avec _inject_pending du même flush.
"""
from pathlib import Path

import pytest

from BotWClient.providers import save_file
from BotWClient.providers.save_file import MAX_DELIVER_PER_FLUSH, DeferredSaveInjector


class _Bridge:
    is_attached = True
    has_live_inventory = True
    _last_create_overflow = False

    def __init__(self, pool_exhausted=False):
        self.pool_exhausted = pool_exhausted
        self.inventory = set()
        self.created = []

    def live_find_item(self, name):
        return 1 if name in self.inventory else None

    def live_create_item(self, name, typ, sub, val):
        self.created.append(name)
        self.inventory.add(name)
        return True

    def toast_enqueue(self, *a):
        pass


@pytest.fixture
def setup(tmp_path: Path):
    b = _Bridge()
    inj = DeferredSaveInjector(tmp_path, bridge=b)
    inj._received = set(save_file._COMPANION_POUCH)      # tous les gates reçus, poche vide
    return b, inj


def test_commutateur_coupe_les_creations(setup, monkeypatch):
    b, inj = setup
    monkeypatch.setattr(save_file, "_LIVE_CREATE_ENABLED", False)
    inj._deliver_companion_pouch()
    assert b.created == []


def test_pool_epuise_aucune_creation(setup):
    b, inj = setup
    b.pool_exhausted = True
    inj._deliver_companion_pouch()
    assert b.created == []


def test_budget_par_cycle(setup):
    b, inj = setup
    inj._deliver_companion_pouch()
    assert len(b.created) == MAX_DELIVER_PER_FLUSH


def test_budget_partage_avec_inject_pending(setup):
    b, inj = setup
    inj._heavy_this_flush = 4                            # 4 livraisons lourdes déjà faites
    inj._deliver_companion_pouch()
    assert len(b.created) == MAX_DELIVER_PER_FLUSH - 4


def test_inject_pending_remet_le_compteur_a_zero(setup):
    _, inj = setup
    inj._heavy_this_flush = 6
    inj._inject_pending()                                # file vide : rien livré ce cycle
    assert inj._heavy_this_flush == 0


def test_tout_finit_livre_sur_plusieurs_cycles_sans_doublon(setup):
    b, inj = setup
    total = sum(len(v) for v in save_file._COMPANION_POUCH.values())
    for _ in range(10):
        inj._heavy_this_flush = 0
        inj._deliver_companion_pouch()
    assert len(b.created) == total
    assert len(set(b.created)) == total
