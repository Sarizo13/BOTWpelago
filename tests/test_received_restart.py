"""
Items déjà reçus après un redémarrage du client (constat Codex #3, 2026-09-09).

`Connected` n'a pas de champ `items` (protocole AP) : l'inventaire complet arrive dans un
`ReceivedItems` index 0, dont le client sautait les entrées déjà traitées (idx < item_index)
sans les marquer reçues → `_received` vide → la rétention remettait à 0 Paravoile, Épée,
capacités. Deux garde-fous :
  A. les items renvoyés sont marqués reçus (jamais remis en file) ;
  B. `_received` est persisté dans ap_client_state.json (clé absente = ensemble vide).
"""
import asyncio
import json
import struct

from BotWClient import BotWClient as client_mod
from BotWClient.providers import save_file
from BotWClient.providers.save_file import DeferredSaveInjector

_PARAGLIDER, _PARAGLIDER_HASH = 6_080_000, 0xFE4D1501
_PAQUET = {"cmd": "ReceivedItems", "index": 0,
           "items": [{"item": _PARAGLIDER, "location": 0, "player": 1, "flags": 1}]}


def _save(tmp_path):
    p = tmp_path / "game_data.sav"
    entries = sorted(save_file._GATE_HASH_TO_AP_ID)
    p.write_bytes(struct.pack(">III", 0, 0xFFFFFFFF, 0) + b"".join(
        struct.pack(">II", h, 1 if h == _PARAGLIDER_HASH else 0) for h in entries))
    return p, entries


def _client(injector):
    c = client_mod.BotWClient.__new__(client_mod.BotWClient)
    c.injector = injector
    c.item_index = injector.load_item_index()     # ce que fait le handler Connected
    return c


def _paraglider_flag(p, entries):
    return struct.unpack_from(">I", p.read_bytes(), 12 + entries.index(_PARAGLIDER_HASH) * 8 + 4)[0]


def test_redemarrage_la_retention_garde_le_paravoile(tmp_path, monkeypatch):
    monkeypatch.setattr(save_file, "cemu_process_running", lambda: False)
    p, entries = _save(tmp_path)
    asyncio.run(_client(DeferredSaveInjector(p))._on_msg(_PAQUET, None))     # session 1

    inj = DeferredSaveInjector(p)                                           # redémarrage
    asyncio.run(_client(inj)._on_msg(_PAQUET, None))
    assert _PARAGLIDER in inj._received
    assert [e["ap_item_id"] for e in inj._queue] == [_PARAGLIDER]           # pas de doublon
    inj._enforce_retention()
    assert _paraglider_flag(p, entries) == 1


def test_received_persiste_et_recharge(tmp_path):
    p, _ = _save(tmp_path)
    asyncio.run(_client(DeferredSaveInjector(p))._on_msg(_PAQUET, None))
    state = json.loads((tmp_path / "ap_client_state.json").read_text(encoding="utf-8"))
    assert state == {"item_index": 1, "received": [_PARAGLIDER]}
    assert DeferredSaveInjector(p)._received == {_PARAGLIDER}               # avant tout réseau


def test_etat_ancien_format_sans_received(tmp_path):
    p, _ = _save(tmp_path)
    (tmp_path / "ap_client_state.json").write_text('{"item_index": 3}', encoding="utf-8")
    inj = DeferredSaveInjector(p)
    assert inj._received == set()
    assert inj.load_item_index() == 3


def test_items_renvoyes_marques_recus_puis_persistes(tmp_path):
    # Ancien fichier d'état (sans "received") : le renvoi du serveur rattrape et persiste.
    p, _ = _save(tmp_path)
    (tmp_path / "ap_client_state.json").write_text('{"item_index": 1}', encoding="utf-8")
    inj = DeferredSaveInjector(p)
    asyncio.run(_client(inj)._on_msg(_PAQUET, None))
    assert inj._received == {_PARAGLIDER}
    assert inj._queue == []                                                 # jamais remis en file
    assert DeferredSaveInjector(p)._received == {_PARAGLIDER}
