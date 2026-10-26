"""
File de livraison (save_file.DeferredSaveInjector) : course réseau / worker.

`queue_item()` tourne sur la boucle réseau (ReceivedItems) pendant que `flush()` →
`_inject_pending()` tourne sur le worker mémoire. Un item reçu PENDANT une livraison
ne doit être perdu ni en mémoire ni sur disque (constat Codex #2, 2026-09-09) : l'index
AP a déjà avancé, le serveur ne le renverrait jamais.
"""
import json

from BotWClient.item_map import get_spec
from BotWClient.providers.save_file import DeferredSaveInjector


class _LiveBridge:
    """Bridge minimal : inventaire live présent, aucune écriture réelle."""
    has_live_inventory = True
    is_attached = True

    def refresh_inventory_if_stale(self):
        pass

    def reassert_qty_targets(self):
        pass

    def clear_qty_targets(self):
        pass


# Deux fillers distincts (ids de data/gate_items.json, section filler_items).
_FIRST, _LATE = 6_080_100, 6_080_120


def test_item_recu_pendant_inject_pending_conserve(tmp_path):
    sav = tmp_path / "game_data.sav"
    sav.write_bytes(b"\0" * 12)
    inj = DeferredSaveInjector(sav, bridge=_LiveBridge())
    inj.queue_item(get_spec(_FIRST))

    def livraison_avec_reception(spec, p=None):
        inj.queue_item(get_spec(_LATE))     # le thread réseau reçoit un item en pleine livraison
        return True

    inj._apply_actions_memory = livraison_avec_reception
    inj._inject_pending()

    on_disk = json.loads((tmp_path / "ap_pending_items.json").read_text(encoding="utf-8"))
    assert [e["ap_item_id"] for e in inj._queue] == [_LATE]
    assert [e["ap_item_id"] for e in on_disk] == [_LATE]
