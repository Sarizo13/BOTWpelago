"""
État client lié à la partie (constat Codex #9, 2026-09-09).

ap_client_state.json / ap_pending_items.json vivent dans le dossier du slot Cemu : réutiliser
le profil pour une NOUVELLE seed (ou un autre slot AP) sans --reset sautait les premières
réceptions, livrait l'ancienne file et — via `received` — donnait le Paravoile gratuitement.
L'état porte donc seed + slot : partie différente → état remis à zéro, ancienne file mise de
côté (.old) ; ancien format sans seed → adopté (impossible de savoir d'où il vient).
"""
import asyncio
import json
import struct

from BotWClient import BotWClient as client_mod
from BotWClient.providers import save_file
from BotWClient.providers.save_file import DeferredSaveInjector

_PARAGLIDER, _PARAGLIDER_HASH, _ARROWS = 6_080_000, 0xFE4D1501, 6_080_120


def _save(tmp_path):
    p = tmp_path / "game_data.sav"
    entries = sorted(save_file._GATE_HASH_TO_AP_ID)
    p.write_bytes(struct.pack(">III", 0, 0xFFFFFFFF, 0)
                  + b"".join(struct.pack(">II", h, 0) for h in entries))
    return p, entries


def _connect(injector, seed, slot="Shorizo", *packets):
    """Connected (handler réel) puis les ReceivedItems donnés."""
    c = client_mod.BotWClient.__new__(client_mod.BotWClient)
    c.injector, c.item_index, c.provider, c.rando = injector, 0, None, None
    c._seed_name, c.slot, c.death_link = seed, slot, False
    c._slot_game, c._slot_name = {}, {}
    asyncio.run(c._on_msg({"cmd": "Connected", "slot": 1, "team": 0, "slot_data": {},
                           "checked_locations": [], "missing_locations": []}, None))
    for pkt in packets:
        asyncio.run(c._on_msg(pkt, None))
    return c


def _items(*ids):
    return {"cmd": "ReceivedItems", "index": 0,
            "items": [{"item": i, "location": 0, "player": 1, "flags": 0} for i in ids]}


def test_nouvelle_seed_etat_remis_a_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(save_file, "cemu_process_running", lambda: False)
    p, entries = _save(tmp_path)
    _connect(DeferredSaveInjector(p), "seedA", "Shorizo", _items(_PARAGLIDER))

    inj = DeferredSaveInjector(p)
    _connect(inj, "seedB", "Shorizo", _items(_ARROWS))
    assert [e["ap_item_id"] for e in inj._queue] == [_ARROWS]       # 1re réception livrée
    assert inj._received == {_ARROWS}
    old = json.loads((tmp_path / "ap_pending_items.json.old").read_text(encoding="utf-8"))
    assert [e["ap_item_id"] for e in old] == [_PARAGLIDER]          # ancienne file conservée
    inj._enforce_retention()
    flag = struct.unpack_from(">I", p.read_bytes(), 12 + entries.index(_PARAGLIDER_HASH) * 8 + 4)
    assert flag[0] == 0                                             # pas de Paravoile gratuit


def test_autre_slot_meme_seed_etat_remis_a_zero(tmp_path):
    p, _ = _save(tmp_path)
    _connect(DeferredSaveInjector(p), "seedA", "p1", _items(_PARAGLIDER))
    inj = DeferredSaveInjector(p)
    c = _connect(inj, "seedA", "p2")
    assert c.item_index == 0
    assert inj._received == set()


def test_meme_seed_meme_slot_etat_conserve(tmp_path):
    p, _ = _save(tmp_path)
    _connect(DeferredSaveInjector(p), "seedA", "Shorizo", _items(_PARAGLIDER))
    inj = DeferredSaveInjector(p)
    c = _connect(inj, "seedA", "Shorizo", _items(_PARAGLIDER))
    assert c.item_index == 1
    assert inj._received == {_PARAGLIDER}
    assert [e["ap_item_id"] for e in inj._queue] == [_PARAGLIDER]   # pas de doublon
    assert not (tmp_path / "ap_pending_items.json.old").exists()


def test_ancien_format_adopte_et_complete(tmp_path):
    p, _ = _save(tmp_path)
    (tmp_path / "ap_client_state.json").write_text(
        json.dumps({"item_index": 1, "received": [_PARAGLIDER]}), encoding="utf-8")
    inj = DeferredSaveInjector(p)
    c = _connect(inj, "seedA", "Shorizo")
    assert c.item_index == 1
    assert inj._received == {_PARAGLIDER}
    state = json.loads((tmp_path / "ap_client_state.json").read_text(encoding="utf-8"))
    assert (state["seed"], state["slot"]) == ("seedA", "Shorizo")
