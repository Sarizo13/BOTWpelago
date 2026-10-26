"""
Garde anti-écriture de game_data.sav (constat Codex #1, 2026-09-09).

Les appelants testent `cemu_process_running()` UNE fois puis enchaînent les écritures : Cemu
lancé entre-temps → écriture du fichier pendant qu'il tourne (contention → crash). La garde
est donc revérifiée au dernier moment, dans `_write_atomic`, juste avant le remplacement :
Cemu présent → save intacte, aucun fichier temporaire laissé, l'appelant renvoie False
(l'item reste en file, la rétention retentera au poll suivant).
"""
import struct

from BotWClient.providers import save_file
from BotWClient.providers.save_file import _write_flag_to_save

_FLAG = 0x795E7BBC   # IsGet_Obj_Magnetglove


def _save(tmp_path, value):
    p = tmp_path / "game_data.sav"
    p.write_bytes(b"\0" * 12 + struct.pack(">II", _FLAG, value))
    return p


def test_cemu_lance_avant_ecriture_save_intacte(tmp_path, monkeypatch):
    p = _save(tmp_path, 0)
    before = p.read_bytes()
    monkeypatch.setattr(save_file, "cemu_process_running", lambda: True)
    assert _write_flag_to_save(p, _FLAG, 1) is False
    assert p.read_bytes() == before
    assert list(tmp_path.iterdir()) == [p]          # pas de .botwtmp résiduel


def test_cemu_absent_ecriture_faite(tmp_path, monkeypatch):
    p = _save(tmp_path, 0)
    monkeypatch.setattr(save_file, "cemu_process_running", lambda: False)
    assert _write_flag_to_save(p, _FLAG, 1) is True
    assert struct.unpack_from(">I", p.read_bytes(), 16)[0] == 1
