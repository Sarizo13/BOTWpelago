"""
Rétention et options randomize_* (constat Codex #8, 2026-09-09).

randomize_master_sword / randomize_champion_abilities à OFF : l'item est retiré du pool
côté serveur et s'obtient en vanilla. La rétention ne doit alors JAMAIS remettre son flag
à 0 (sinon Épée / capacités effacées, et goal "full" impossible sans Épée randomisée).
Tant que slot_data est inconnu (avant Connected), ces gates optionnels ne sont pas touchés ;
le Paravoile, toujours dans le pool, l'est.
"""
import struct

import pytest

from BotWClient.providers import save_file
from BotWClient.providers.save_file import DeferredSaveInjector

_PARAGLIDER = 0xFE4D1501
_SWORD = 0x15AD023F            # Get_MasterSword_Finish
_RITO = 0x7DBA0908             # IsGet_Obj_HeroSoul_Rito
_ALL = {"randomize_champion_abilities": True, "randomize_master_sword": True}


@pytest.fixture
def save(tmp_path, monkeypatch):
    monkeypatch.setattr(save_file, "cemu_process_running", lambda: False)
    p = tmp_path / "game_data.sav"
    entries = sorted(save_file._GATE_HASH_TO_AP_ID)
    p.write_bytes(struct.pack(">III", 0, 0xFFFFFFFF, 0) + b"".join(
        struct.pack(">II", h, 1 if h in (_PARAGLIDER, _SWORD, _RITO) else 0) for h in entries))

    def flag(h):
        return struct.unpack_from(">I", p.read_bytes(), 12 + entries.index(h) * 8 + 4)[0]
    return p, flag


def test_options_off_flags_vanilla_conserves(save):
    p, flag = save
    inj = DeferredSaveInjector(p)
    inj.set_slot_options({"randomize_champion_abilities": False, "randomize_master_sword": False})
    inj._enforce_retention()
    assert (flag(_SWORD), flag(_RITO)) == (1, 1)
    assert flag(_PARAGLIDER) == 0                 # toujours dans le pool → gate actif


def test_une_seule_option_off(save):
    p, flag = save
    inj = DeferredSaveInjector(p)
    inj.set_slot_options({"randomize_champion_abilities": True, "randomize_master_sword": False})
    inj._enforce_retention()
    assert (flag(_SWORD), flag(_RITO)) == (1, 0)


def test_options_on_gate_actif(save):
    p, flag = save
    inj = DeferredSaveInjector(p)
    inj.set_slot_options(_ALL)
    inj._enforce_retention()
    assert (flag(_PARAGLIDER), flag(_SWORD), flag(_RITO)) == (0, 0, 0)


def test_options_inconnues_gates_optionnels_intacts(save):
    p, flag = save
    DeferredSaveInjector(p)._enforce_retention()  # avant Connected : slot_data inconnu
    assert (flag(_SWORD), flag(_RITO)) == (1, 1)
    assert flag(_PARAGLIDER) == 0
