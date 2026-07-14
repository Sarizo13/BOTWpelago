"""
Baseline des checks (SaveFileProvider._apply_baseline) — fix du 2026-07-13.

Bug d'origine : `--reset` supprimait ap_baseline.json → le 1er poll RE-SNAPSHOTAIT l'état
courant de la save → les checks faits pendant un trou de couverture (crash Cemu, client
down) étaient MANGÉS et jamais envoyés (constaté : 4 sanctuaires du Plateau + tour).

Nouveau contrat :
  1. la baseline est INDEXÉE PAR SEED : réutilisée tant que la seed ne change pas ;
     --reset ne la supprime plus (reset_ap_state) ;
  2. au snapshot d'une room EN COURS (le serveur connaît déjà des checks), seuls les
     checks connus du serveur sont baselinés — un flag vrai mais « missing » côté
     serveur est ÉMIS au poll suivant ;
  3. room vierge : comportement historique (tout l'existant baseliné) + warning ;
  4. fichier legacy (liste nue) → re-snapshot avec la seed courante.
"""
import json

from BotWClient.providers.save_file import (
    SaveFileProvider,
    _LOC_HASH_TO_AP_ID,
    reset_ap_state,
)


class _FakeSave:
    """ParsedSave minimal : sert get_bool depuis un set de hashes 'vrais'."""
    def __init__(self, true_hashes):
        self._t = set(true_hashes)

    def get_bool(self, h):
        return h in self._t

    def get_s32(self, h):
        return 0


# trois locations réelles de la table (stables : shrines)
_H = sorted(_LOC_HASH_TO_AP_ID)[:3]
_AP = [_LOC_HASH_TO_AP_ID[h] for h in _H]


def _provider(tmp_path, true_hashes, seed=None, checked=()):
    p = SaveFileProvider(tmp_path)          # tmp dir : _reload() ne trouve rien → garde _save
    p._save = _FakeSave(true_hashes)
    p.set_server_context(seed, set(checked))
    return p


def test_room_vierge_snapshot_all(tmp_path):
    p = _provider(tmp_path, _H[:2], seed="seed-A")
    assert p.poll() == []                                    # tout baseliné (room vierge)
    data = json.loads((tmp_path / "ap_baseline.json").read_text(encoding="utf-8"))
    assert data["seed"] == "seed-A"
    assert sorted(data["ids"]) == sorted(_AP[:2])


def test_room_en_cours_emet_les_checks_hors_couverture(tmp_path):
    # flags vrais : {0, 1} ; le serveur ne connaît que {0} → 1 doit être ÉMIS, pas mangé
    p = _provider(tmp_path, _H[:2], seed="seed-A", checked=[_AP[0]])
    emitted = p.poll()
    assert emitted == [_AP[1]]
    data = json.loads((tmp_path / "ap_baseline.json").read_text(encoding="utf-8"))
    assert data["ids"] == [_AP[0]]                           # seule la part connue est baselinée


def test_baseline_reutilisee_meme_seed(tmp_path):
    # 1er run : snapshot {0}
    p1 = _provider(tmp_path, _H[:1], seed="seed-A")
    p1.poll()
    # 2e run (relance client), la save a AVANCÉ ({0,1}) : baseline de seed-A réutilisée
    # → le nouveau check 1 est émis, PAS re-baseliné
    p2 = _provider(tmp_path, _H[:2], seed="seed-A")
    assert p2.poll() == [_AP[1]]


def test_baseline_resnapshot_si_seed_change(tmp_path):
    p1 = _provider(tmp_path, _H[:1], seed="seed-A")
    p1.poll()
    # nouvelle seed, room vierge : re-snapshot (l'existant est re-baseliné pour CETTE seed)
    p2 = _provider(tmp_path, _H[:2], seed="seed-B")
    assert p2.poll() == []
    data = json.loads((tmp_path / "ap_baseline.json").read_text(encoding="utf-8"))
    assert data["seed"] == "seed-B"


def test_fichier_legacy_resnapshote(tmp_path):
    # ancien format = liste nue (pré-seed) → re-snapshot avec la room en cours
    (tmp_path / "ap_baseline.json").write_text(json.dumps(_AP[:2]), encoding="utf-8")
    p = _provider(tmp_path, _H[:2], seed="seed-A", checked=[_AP[0]])
    assert p.poll() == [_AP[1]]                              # le check non-serveur est émis


def test_dungeon_counter_counts_clear_flags(tmp_path):
    """DungeonClearCounter peut rester à 0 sur une save réelle (constat 2026-07-14) →
    le compteur = MAX(compteur, nb de Clear_Dungeon* à 1), sinon goal/tracker morts."""
    from BotWClient.providers.save_file import _SHRINE_FLAG_IDS
    p = _provider(tmp_path, _SHRINE_FLAG_IDS[:2], seed=None)   # 2 sanctuaires clear, s32=0
    assert p.get_dungeon_counter() == 2


def test_locations_preclears_hors_table_client(tmp_path):
    """Les 7 locations pré-vraies (InitValue=1 posé par le rando à toute nouvelle partie)
    sont HORS POOL (2026-07-14 : un Paraglider placé sur « Map Tower07 » arrivait gratuit
    à la connexion) → le client ne doit plus les émettre du tout."""
    from BotWClient.providers.save_file import _RANDO_INIT_LOCATION_IDS
    assert len(_RANDO_INIT_LOCATION_IDS) == 7
    assert not (_RANDO_INIT_LOCATION_IDS & set(_LOC_HASH_TO_AP_ID.values()))


def test_preclears_miroir_worlds_client():
    """La liste d'exclusion du POOL (worlds/botw/locations.py, import AP impossible ici →
    lecture source) doit rester le MIROIR exact de celle du client."""
    import re
    from pathlib import Path
    from BotWClient.providers.save_file import _RANDO_INIT_LOCATION_IDS
    src = (Path(__file__).resolve().parents[1] / "worlds" / "botw" / "locations.py") \
        .read_text(encoding="utf-8")
    m = re.search(r"RANDO_INIT_LOCATION_IDS[^=]*= frozenset\(\{(.*?)\}\)", src, re.S)
    assert m, "RANDO_INIT_LOCATION_IDS introuvable dans worlds/botw/locations.py"
    ids = {int(x.replace("_", "")) for x in re.findall(r"6_[\d_]+", m.group(1))}
    assert ids == _RANDO_INIT_LOCATION_IDS


def test_dungeon_counter_exclut_les_preclears_du_rando(tmp_path):
    """Les 4 sanctuaires pré-clearés (InitValue=1) ne comptent ni pour le goal ni pour le
    tracker — sinon un goal « 5 sanctuaires » démarrerait à 4/5 sur toute save neuve."""
    from BotWClient.providers.save_file import _RANDO_INIT_SHRINE_FLAG_IDS, _SHRINE_FLAG_IDS
    assert len(_RANDO_INIT_SHRINE_FLAG_IDS) == 4
    real = [h for h in _SHRINE_FLAG_IDS if h not in _RANDO_INIT_SHRINE_FLAG_IDS][:1]
    p = _provider(tmp_path, list(_RANDO_INIT_SHRINE_FLAG_IDS) + real, seed=None)
    assert p.get_dungeon_counter() == 1                      # 4 pré-clearés ignorés, 1 réel


def test_reset_ap_state_preserve_baseline(tmp_path):
    (tmp_path / "ap_baseline.json").write_text(
        json.dumps({"seed": "s", "ids": []}), encoding="utf-8")
    (tmp_path / "ap_pending_items.json").write_text("[]", encoding="utf-8")
    (tmp_path / "ap_client_state.json").write_text("{}", encoding="utf-8")
    n = reset_ap_state(tmp_path)
    assert n == 2                                            # pending + state supprimés
    assert (tmp_path / "ap_baseline.json").exists()          # baseline CONSERVÉE
