"""
Voie FICHIER et équipement (constat Codex #6, 2026-09-09).

  a. Une arme reçue hors ligne était « bumpée » sur l'arme du même nom déjà en save :
     sa valeur (= DURABILITÉ) montait (30 → 50) et l'item était compté livré — pas de
     2e exemplaire. L'équipement ne passe plus jamais par un bump fichier : il reste en
     file et part en live (création d'un vrai nœud), comme en mémoire.
  b. La rétention fichier créait TOUS les objets companion en save avec la valeur 1
     (Épée de Légende à 1 de durabilité au lieu de 40, jusqu'à 19 slots neufs). Seuls les
     objets-clés (type 9 : paravoile, capacités) créent encore un slot fichier ; épée,
     arc et tenues sont livrés en live par _deliver_companion_pouch.
"""
import struct
from pathlib import Path

import pytest

from BotWClient.providers import save_file
from BotWClient.providers.base import InjectionSpec
from BotWClient.providers.save_file import DeferredSaveInjector, _read_porch_value


def _save(tmp_path: Path, slots=()) -> Path:
    """Save synthétique : runs PorchItem (noms) + PorchItem_Value1, triés par flag_id."""
    names, vals = [], []
    for i in range(save_file._PORCH_SLOTS):
        name, val = slots[i] if i < len(slots) else ("", 0)
        raw = (name.encode("ascii") + b"\0" * 64)[:64]
        names += [struct.unpack(">I", raw[j * 4:j * 4 + 4])[0] for j in range(16)]
        vals.append(val)
    runs = sorted([(save_file._PORCH_ITEM_ID, names), (save_file._PORCH_VALUE1_ID, vals)])
    body = b"".join(struct.pack(">II", fid, w) for fid, words in runs for w in words)
    p = tmp_path / "game_data.sav"
    p.write_bytes(struct.pack(">III", 0, 0xFFFFFFFF, 0) + body)
    return p


def _pouch_spec(item, amount):
    return InjectionSpec(ap_item_id=6_080_999, ap_item_name=item,
                         actions=[InjectionSpec.AddPouchItem(item_name=item, amount=amount)])


def test_arme_hors_ligne_pas_de_bump_de_durabilite(tmp_path):
    p = _save(tmp_path, [("Weapon_Lsword_001", 30)])
    inj = DeferredSaveInjector(p)
    assert inj._apply_actions_savefile(p, _pouch_spec("Weapon_Lsword_001", 20)) is False
    assert _read_porch_value(p.read_bytes(), "Weapon_Lsword_001") == 30   # intacte, reportée


def test_empilable_hors_ligne_toujours_bumpe(tmp_path):
    p = _save(tmp_path, [("Item_Fruit_A", 3)])
    inj = DeferredSaveInjector(p)
    assert inj._apply_actions_savefile(p, _pouch_spec("Item_Fruit_A", 5)) is True
    assert _read_porch_value(p.read_bytes(), "Item_Fruit_A") == 8


@pytest.fixture
def retention(tmp_path, monkeypatch):
    monkeypatch.setattr(save_file, "cemu_process_running", lambda: False)
    p = _save(tmp_path)
    inj = DeferredSaveInjector(p)
    inj._received = set(save_file._COMPANION_POUCH)
    inj.set_slot_options({"randomize_champion_abilities": True, "randomize_master_sword": True})
    inj._enforce_retention()
    return p.read_bytes()


def test_retention_fichier_cree_les_objets_cles(retention):
    for key_item in ("PlayerStole2", "Obj_HeroSoul_Rito", "Obj_HeroSoul_Gerudo"):
        assert _read_porch_value(retention, key_item) == 1


def test_retention_fichier_ne_cree_pas_l_equipement(retention):
    for gear in ("Weapon_Sword_070", "Weapon_Bow_071", "Armor_011_Head", "Armor_006_Lower"):
        assert _read_porch_value(retention, gear) is None              # livré en live
