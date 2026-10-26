"""
Persistance de l'état client (constat Codex #4, 2026-09-09).

- `ap_pending_items.json` / `ap_client_state.json` écrits de façon ATOMIQUE : un échec en
  cours d'écriture laisse l'ancien fichier intact (jamais un JSON tronqué).
- Fichier corrompu au chargement : mis de côté en `.corrupt` + warning, jamais avalé en
  silence (sinon la file suivante l'écrase et la perte devient invisible).
- ReceivedItems : l'item est mis en file AVANT que l'index AP avance — un arrêt entre les
  deux donne au pire un doublon renvoyé par le serveur, jamais une perte.
"""
import asyncio
import json
import logging

import pytest

from BotWClient import BotWClient as client_mod
from BotWClient.item_map import get_spec
from BotWClient.providers import save_file
from BotWClient.providers.save_file import DeferredSaveInjector

_FILLER = 6_080_120


def _injector(tmp_path):
    sav = tmp_path / "game_data.sav"
    sav.write_bytes(b"\0" * 12)
    return DeferredSaveInjector(sav)


def test_file_corrompue_mise_de_cote_avec_warning(tmp_path, caplog):
    queue = tmp_path / "ap_pending_items.json"
    queue.write_text('[{"ap_item_id": 6080120, "ap_it', encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        inj = _injector(tmp_path)
    assert inj._queue == []
    assert (tmp_path / "ap_pending_items.json.corrupt").read_text(encoding="utf-8").startswith("[{")
    assert "ap_pending_items.json" in caplog.text


def test_etat_corrompu_mis_de_cote_avec_warning(tmp_path, caplog):
    inj = _injector(tmp_path)
    (tmp_path / "ap_client_state.json").write_text('{"item_ind', encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert inj.load_item_index() == 0
    assert (tmp_path / "ap_client_state.json.corrupt").exists()
    assert "ap_client_state.json" in caplog.text


@pytest.mark.parametrize("persist", ["queue", "index"])
def test_echec_d_ecriture_laisse_l_ancien_fichier_intact(tmp_path, monkeypatch, persist):
    inj = _injector(tmp_path)
    inj.queue_item(get_spec(_FILLER))
    inj.persist_item_index(7)
    target = tmp_path / ("ap_pending_items.json" if persist == "queue" else "ap_client_state.json")
    before = target.read_text(encoding="utf-8")

    def crash(*_a, **_k):
        raise OSError("arrêt simulé avant le remplacement")

    monkeypatch.setattr(save_file.os, "replace", crash)
    with pytest.raises(OSError):
        if persist == "queue":
            inj.queue_item(get_spec(_FILLER))
        else:
            inj.persist_item_index(8)
    assert target.read_text(encoding="utf-8") == before
    json.loads(before)


class _RecordingInjector:
    def __init__(self):
        self.calls = []

    def persist_item_index(self, index):
        self.calls.append("index")

    def queue_item(self, spec):
        self.calls.append("queue")


def test_received_items_met_en_file_avant_d_avancer_l_index():
    client = client_mod.BotWClient.__new__(client_mod.BotWClient)
    client.item_index = 0
    client.injector = _RecordingInjector()
    msg = {"cmd": "ReceivedItems", "index": 0,
           "items": [{"item": _FILLER, "location": 0, "player": 1, "flags": 0}]}
    asyncio.run(client._on_msg(msg, None))
    assert client.injector.calls == ["queue", "index"]
