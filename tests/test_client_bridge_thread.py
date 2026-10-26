"""
Accès au bridge depuis la boucle réseau (constat Codex #12, 2026-09-09).

Le worker mémoire (thread unique « botw-mem ») sérialise flush/poll sur le bridge, et le
flush gèle TOUTE écriture tant que `delivery_ready` est faux (crash 0xc0000005 du 14/07 :
écritures pendant un load). Le retrait des rubis-placeholder écrivait, lui, depuis la boucle
réseau sans cette garde, en concurrence avec le worker ; la lecture des orbes du tracker
parcourait la poche pendant les splices. Les deux passent désormais par le worker, et le
retrait attend `delivery_ready`. (DeathLink volontairement hors périmètre.)
"""
import asyncio
import concurrent.futures
import threading

from BotWClient import BotWClient as client_mod
from BotWClient.providers.save_file import SaveFileProvider


class _Bridge:
    is_attached = True
    has_live_inventory = True

    def __init__(self, ready):
        self.delivery_ready = ready
        self.rupee_calls = []          # (amount, thread)
        self.qty_threads = []

    def live_add_rupees(self, amount):
        self.rupee_calls.append((amount, threading.current_thread().name))
        return 100 + amount

    def live_get_item_qty(self, item_id):
        self.qty_threads.append(threading.current_thread().name)
        return 7


class _Injector:
    def __init__(self, bridge):
        self._bridge = bridge


class _WS:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


def _client(bridge, debt=0):
    c = client_mod.BotWClient.__new__(client_mod.BotWClient)
    c.injector = _Injector(bridge)
    c._pending_rupee_strip = debt
    c._exec = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="botw-mem")
    return c


def test_retrait_rubis_gele_si_jeu_pas_pret():
    bridge = _Bridge(ready=False)
    c = _client(bridge, debt=3)
    asyncio.run(c._settle_rupee_strip())
    assert bridge.rupee_calls == []                 # aucune écriture pendant un load
    assert c._pending_rupee_strip == 3              # dette conservée, rejouée plus tard


def test_retrait_rubis_sur_le_worker_si_pret():
    bridge = _Bridge(ready=True)
    c = _client(bridge, debt=3)
    asyncio.run(c._settle_rupee_strip())
    [(amount, thread)] = bridge.rupee_calls
    assert amount == -3 * client_mod.PLACEHOLDER_RUPEE_VALUE
    assert thread.startswith("botw-mem")
    assert c._pending_rupee_strip == 0


def test_orbes_du_tracker_lues_sur_le_worker(tmp_path, monkeypatch):
    bridge = _Bridge(ready=True)
    c = _client(bridge)
    provider = SaveFileProvider(tmp_path)
    monkeypatch.setattr(provider, "get_spirit_orbs", lambda: 0)
    monkeypatch.setattr(provider, "get_dungeon_counter", lambda: 0)
    c.provider, c._slot_num, c._team, c._pushed_state, c.slot_data = provider, 1, 0, {}, {}
    ws = _WS()
    asyncio.run(c._push_game_state(ws))
    assert len(bridge.qty_threads) == 1 and bridge.qty_threads[0].startswith("botw-mem")
    assert c._pushed_state["SpiritOrbs"] == 7
