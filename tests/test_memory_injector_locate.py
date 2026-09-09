"""
Tests for the live-inventory localisation robustness in BotWClient/memory_injector.py.

Regression cover for the "1er attach after save load" bug: right after a save is loaded,
BotW reallocates the pouch, leaving a FREED copy still mapped. The AOB rupee flagobj is
NOT reallocated (fixed/live), so the localiser must pick the pouch buffer whose derived
heap_base places that flagobj at a valid guest — i.e. the VIVANT buffer — and never latch
onto the stale copy (which produced "flagobj hors mapping guest" + undelivered items until
a client restart).

memory_injector binds kernel32 at import time → Windows-only. Skipped elsewhere.
"""
import struct
import sys
import time

import pytest

if sys.platform != "win32":  # pragma: no cover - the whole module is Windows-bound
    pytest.skip("memory_injector is Windows-only (kernel32)", allow_module_level=True)

from BotWClient.memory_injector import (  # noqa: E402
    CemuMemoryBridge,
    _FLAG_S32_OFF_HASH,
    _FLAG_S32_OFF_VALUE,
    _GDT_FLAG_S32_VTABLE,
    _GUEST_MAX,
    _RUPEE_FLAG_HASH,
)


def _u32(v: int) -> bytes:
    return struct.pack(">I", v & 0xFFFFFFFF)


# ── _flagobj_guest_ok : the external anchor ────────────────────────────────────

def _bridge_with_flagobj(rupees_addr: int, vtable: int, hashv: int) -> CemuMemoryBridge:
    """A bridge whose _read serves a synthetic Flag<s32> object at rupees_addr - 0x14."""
    b = CemuMemoryBridge()
    flagobj = rupees_addr - _FLAG_S32_OFF_VALUE
    mem = {
        (flagobj, 4): _u32(vtable),
        (flagobj + _FLAG_S32_OFF_HASH, 4): _u32(hashv),
    }
    b._read = lambda addr, size: mem.get((addr, size))  # type: ignore[assignment]
    return b


def test_flagobj_guest_ok_accepts_valid_pair():
    rupees_addr = 0x0000_7F00_0000_0000
    flagobj = rupees_addr - _FLAG_S32_OFF_VALUE
    b = _bridge_with_flagobj(rupees_addr, _GDT_FLAG_S32_VTABLE, _RUPEE_FLAG_HASH)
    heap_base = flagobj - 0x2000              # guest = 0x2000, in range
    assert b._flagobj_guest_ok(rupees_addr, heap_base) == flagobj


def test_flagobj_guest_ok_rejects_stale_base_out_of_range():
    rupees_addr = 0x0000_7F00_0000_0000
    flagobj = rupees_addr - _FLAG_S32_OFF_VALUE
    b = _bridge_with_flagobj(rupees_addr, _GDT_FLAG_S32_VTABLE, _RUPEE_FLAG_HASH)
    # base ABOVE flagobj → negative guest (stale copy shifted the wrong way)
    assert b._flagobj_guest_ok(rupees_addr, flagobj + 0x1000) is None
    # base far BELOW → guest > 4 GiB (copy far away in host space)
    assert b._flagobj_guest_ok(rupees_addr, flagobj - _GUEST_MAX - 1) is None


def test_flagobj_guest_ok_rejects_wrong_object():
    rupees_addr = 0x0000_7F00_0000_0000
    flagobj = rupees_addr - _FLAG_S32_OFF_VALUE
    # right vtable but a different flag's hash → not CurrentRupee → reject
    b = _bridge_with_flagobj(rupees_addr, _GDT_FLAG_S32_VTABLE, 0xDEADBEEF)
    assert b._flagobj_guest_ok(rupees_addr, flagobj - 0x2000) is None
    # right hash but wrong vtable (not a gdt::Flag<s32>) → reject
    b2 = _bridge_with_flagobj(rupees_addr, 0x10000000, _RUPEE_FLAG_HASH)
    assert b2._flagobj_guest_ok(rupees_addr, flagobj - 0x2000) is None


def test_flagobj_guest_ok_none_inputs():
    b = CemuMemoryBridge()
    assert b._flagobj_guest_ok(None, 0x1000) is None
    assert b._flagobj_guest_ok(0x1000, None) is None


# ── _locate_live_inventory : prefers the anchor-validated (VIVANT) buffer ───────

R_STALE, R_LIVE = 0x0000_1000_0000_0000, 0x0000_2000_0000_0000
INV_STALE, INV_LIVE = 0x0000_1000_0010_0000, 0x0000_2000_0010_0000
BASE_STALE, BASE_LIVE = 0x0000_0FFF_0000_0000, 0x0000_1FFF_0000_0000
FLAGOBJ_LIVE = R_LIVE - _FLAG_S32_OFF_VALUE


def _wire_localiser(b: CemuMemoryBridge, rupees_order):
    """Stub the scan primitives so localisation is driven by our synthetic topology.
    Only the (R_LIVE, INV_LIVE, BASE_LIVE) triple validates against the rupee anchor."""
    b._find_rupees_addresses = lambda: list(rupees_order)          # type: ignore
    b._find_inventory_start = lambda ra, prefer_free=False: (       # type: ignore
        {R_STALE: INV_STALE, R_LIVE: INV_LIVE}.get(ra))
    # nodes carry their inv_base so _derive_heap_base can map it back
    b._scan_pouch_nodes = lambda inv_base=None: (                   # type: ignore
        [{"inv": inv_base if inv_base is not None else b._inv_base}])
    b._derive_heap_base = lambda nodes: (                           # type: ignore
        {INV_STALE: BASE_STALE, INV_LIVE: BASE_LIVE}.get(nodes[0]["inv"]))
    b._flagobj_guest_ok = lambda ra, base: (                        # type: ignore
        FLAGOBJ_LIVE if (ra, base) == (R_LIVE, BASE_LIVE) else None)
    b._wallet_valid = lambda: False                                # type: ignore
    b._find_wallet = lambda: False                                 # type: ignore


def test_locate_prefers_live_buffer_even_when_stale_listed_first():
    b = CemuMemoryBridge()
    _wire_localiser(b, rupees_order=[R_STALE, R_LIVE])   # stale copy comes first
    b._locate_live_inventory()
    assert b._inv_base == INV_LIVE
    assert b._rupees_addr == R_LIVE
    assert b._heap_base == BASE_LIVE          # validated base adopted (not the stale one)


def test_locate_falls_back_when_no_pair_validates():
    b = CemuMemoryBridge()
    _wire_localiser(b, rupees_order=[R_STALE])           # only the stale pair exists
    # force the anchor to never validate
    b._flagobj_guest_ok = lambda ra, base: None          # type: ignore
    b._locate_live_inventory()
    assert b._inv_base == INV_STALE                       # historical fallback still delivers
    assert b._rupees_addr == R_STALE
    # Since 2026-07-14 the fallback DERIVES the adopted pouch's base anyway (self-pointer
    # derivation is exact even on a 1-2 node pouch) so wallet/toast can work: _find_wallet
    # rescans the LIVE flagobj by hash when the AOB one is a dead copy.
    assert b._heap_base == BASE_STALE


def test_relocate_resets_stale_heap_base():
    b = CemuMemoryBridge()
    # simulate a prior localisation that latched a stale base + wallet
    b._inv_base = INV_STALE
    b._heap_base = BASE_STALE
    b._wallet_addr = 0xDEAD
    b._wallet_flagobj = 0xBEEF
    _wire_localiser(b, rupees_order=[R_STALE, R_LIVE])
    assert b._relocate_inventory() is True
    assert b._inv_base == INV_LIVE
    assert b._heap_base == BASE_LIVE          # re-derived fresh, stale value discarded
    assert b._wallet_addr is None             # wallet re-derivation forced


# ── _derive_heap_base : self-pointer derivation (near-empty pouch, 2026-07-14) ──
#
# Bug: with only 1-2 nodes (fresh save), adjacency has a single candidate pair and could
# derive a GARBAGE base (guests negative/tiny → "flagobj hors mapping guest" loop, zero
# deliveries). The name FixedSafeString buffer pointer at +0x1C (== node_guest+0x28) gives
# an EXACT base from a single node; implausible candidates (guest outside
# [0x02000000, 4 GiB)) are rejected.

_NODE_G = 0x4000_0000                        # synthetic node guest addr
_HOST_BASE = 0x0000_5000_0000_0000           # synthetic cemu_mem_base
_STRIDE = 544


def _make_node(host: int, guest: int, typ: int = 0, name: str = "Weapon_Sword_001") -> dict:
    raw = bytearray(_STRIDE)
    struct.pack_into(">I", raw, 0x04, 0x5000_0000)            # next (some link)
    struct.pack_into(">I", raw, 0x08, 0x5000_0000)            # prev
    struct.pack_into(">I", raw, 0x0C, typ)                    # type
    struct.pack_into(">I", raw, 0x1C, guest + 0x28)           # name-buffer self-pointer
    nb = name.encode("ascii")
    raw[0x28:0x28 + len(nb)] = nb
    # 3 in-node self-pointers past the name buffer (_node_is_selfref scans [0x20, stride)
    # and needs >= 3 hits)
    struct.pack_into(">I", raw, 0x6C, guest + 0x100)
    struct.pack_into(">I", raw, 0x70, guest + 0x180)
    struct.pack_into(">I", raw, 0x74, guest + 0x200)
    return {"slot": 0, "host": host, "name": name, "type": typ, "sub": 0, "raw": bytes(raw)}


def test_derive_base_from_single_node_self_pointer():
    node = _make_node(_HOST_BASE + _NODE_G, _NODE_G)
    b = CemuMemoryBridge()
    assert b._derive_heap_base([node]) == _HOST_BASE


def test_derive_base_rejects_garbage_candidates():
    # +0x1C holds a small constant (0x40) instead of a self-pointer → candidate base would
    # put the node at guest 0x18 (< 0x02000000) → rejected → None (old code returned garbage)
    node = _make_node(_HOST_BASE + _NODE_G, _NODE_G)
    raw = bytearray(node["raw"])
    struct.pack_into(">I", raw, 0x1C, 0x40)
    struct.pack_into(">I", raw, 0x6C, 0x64)
    struct.pack_into(">I", raw, 0x70, 0x88)
    struct.pack_into(">I", raw, 0x74, 0x224)
    node["raw"] = bytes(raw)
    b = CemuMemoryBridge()
    assert b._derive_heap_base([node]) is None


# ── real-list anchoring: sentinel walk (insertion on a near-empty pouch) ────────

_SENT_G = 0x5000_0000                        # sentinel (sead::OffsetList.mStartEnd) guest


def _bridge_with_list(node_g: int, sent_g: int, count: int = 1) -> CemuMemoryBridge:
    """One-node circular list: S.next → node+4 ; node.next → S ; S.prev → node+4."""
    b = CemuMemoryBridge()
    mem = {
        (_HOST_BASE + sent_g, 4): _u32(node_g + 0x04),
        (_HOST_BASE + sent_g, 12): _u32(node_g + 0x04) + _u32(node_g + 0x04) + _u32(count),
        (_HOST_BASE + node_g + 0x04, 4): _u32(sent_g),
    }
    b._read = lambda addr, size: mem.get((addr, size))  # type: ignore[assignment]
    return b


def test_find_list_sentinel_one_node():
    node = _make_node(_HOST_BASE + _NODE_G, _NODE_G)
    b = _bridge_with_list(_NODE_G, _SENT_G)
    assert b._find_list_sentinel([node], _HOST_BASE) == _SENT_G


def test_find_insert_link_head_and_tail():
    node = _make_node(_HOST_BASE + _NODE_G, _NODE_G, typ=0)   # a weapon (type 0)
    b = _bridge_with_list(_NODE_G, _SENT_G)
    known = {_NODE_G: node}
    # target type 8 (food) > type 0 → descending list → insert at HEAD (link = sentinel)
    assert b._find_insert_link(_SENT_G, _HOST_BASE, (8, 123), True, known) == _SENT_G
    # target smaller than everything → walk past the node → insert at TAIL (node's link)
    assert b._find_insert_link(_SENT_G, _HOST_BASE, (-1, 0), True, known) == _NODE_G + 0x04


# ── static pouch anchor (anti freed-copy, 2026-07-14 crash) ─────────────────────
#
# Root cause of the 0xc0000005 reload crash: the AOB scan latched a FREED copy of the
# pouch; a splice went into recycled memory (Eightfold Blade never serialized, then the
# game's reuse of that memory mangled the real list — Sheikah Slate lost). The fix
# resolves ONE static data-section slot (guest 0x10xxxxxx) pointing at the validated
# buffer; every pouch access re-reads it, so a freed copy is unaddressable by design.

_STATIC_G = 0x1040_0000                      # 1 MiB-aligned chunk start in the data window
_SLOT_OFF = 0x10                             # slot position inside the chunk (u32-aligned)
_INV_G = 0x4000_1000                         # validated pouch guest addr
_OBJ_OFF = 0x1000                            # pouch buffer offset inside the manager object


def _bridge_with_static(slot_value: int) -> CemuMemoryBridge:
    """Bridge whose data-section scan window serves one chunk containing `slot_value`."""
    b = CemuMemoryBridge()
    b._heap_base = _HOST_BASE
    b._inv_base = _HOST_BASE + _INV_G
    chunk = bytearray(1 << 20)
    struct.pack_into(">I", chunk, _SLOT_OFF, slot_value)
    chunk = bytes(chunk)

    def read(addr, size):
        if size == 1 << 20:
            return chunk if addr == _HOST_BASE + _STATIC_G else None
        if (addr, size) == (_HOST_BASE + _STATIC_G + _SLOT_OFF, 4):
            return _u32(struct.unpack_from(">I", chunk, _SLOT_OFF)[0])
        return None

    b._read = read  # type: ignore[assignment]
    return b


def test_find_pouch_static_resolves_backref():
    b = _bridge_with_static(_INV_G - _OBJ_OFF)   # slot points at the manager object
    b._find_pouch_static()
    assert b._pouch_static_host == _HOST_BASE + _STATIC_G + _SLOT_OFF
    assert b._pouch_buf_off == _OBJ_OFF
    assert b._pouch_static_val == _INV_G - _OBJ_OFF


def test_find_pouch_static_ignores_out_of_range_values():
    b = _bridge_with_static(_INV_G + 0x10)       # points PAST the buffer → not a backref
    b._find_pouch_static()
    assert b._pouch_static_host is None          # feature stays off → historical behavior


def test_refresh_follows_reallocation_through_static():
    b = _bridge_with_static(_INV_G - _OBJ_OFF)
    b._find_pouch_static()
    new_obj = 0x4800_0000                        # game reallocated the manager/pouch
    mem = {(b._pouch_static_host, 4): _u32(new_obj)}
    b._read = lambda addr, size: mem.get((addr, size))  # type: ignore[assignment]
    node = _make_node(_HOST_BASE + new_obj + _OBJ_OFF, new_obj + _OBJ_OFF)
    b._scan_pouch_nodes = lambda inv_base=None: [node]  # type: ignore[assignment]
    assert b._refresh_inv_from_static() is True
    assert b._inv_base == _HOST_BASE + new_obj + _OBJ_OFF   # re-targeted to the LIVE buffer


def test_refresh_defers_writes_during_load():
    b = _bridge_with_static(_INV_G - _OBJ_OFF)
    b._find_pouch_static()
    # mid-load: the static slot reads 0 (torn state) → all pouch access must report NOT ready
    b._read = lambda addr, size: _u32(0) if size == 4 else None  # type: ignore[assignment]
    assert b._refresh_inv_from_static() is False
    assert list(b._iter_inventory_slots()) == []   # iteration refuses recycled memory


def test_refresh_without_anchor_keeps_historical_behavior():
    b = CemuMemoryBridge()
    b._inv_base = _HOST_BASE + _INV_G            # located, but no anchor resolved
    assert b._refresh_inv_from_static() is True
    b._inv_base = None
    assert b._refresh_inv_from_static() is False


# ── tab capacity cap (release-all freeze, 2026-07-14) ──────────────────────────
#
# The game only has *PorchStockNum slots per equipment tab (8/5/4 vanilla). Creating nodes
# beyond that put the tab in an illegal state → scrambled inventory then a FREEZE during
# the 703-item release-all. At cap, live_create_item must refuse AND raise the overflow
# signal so the caller converts filler gear to rupees instead of retrying forever.

def _bridge_with_full_weapon_tab(cap_flag_value):
    b = CemuMemoryBridge()
    b._inv_base = _HOST_BASE + _INV_G
    b._heap_base = _HOST_BASE
    nodes = [_make_node(_HOST_BASE + _NODE_G + i * 0x1000, _NODE_G + i * 0x1000, typ=0)
             for i in range(8)]                       # 8 armes actives (cap vanilla atteint)
    b._scan_pouch_nodes = lambda inv_base=None: nodes           # type: ignore
    b._derive_heap_base = lambda ns: _HOST_BASE                 # type: ignore
    b.live_find_item = lambda name: None                        # type: ignore
    b.read_flag = lambda name: cap_flag_value                   # type: ignore
    return b


def test_live_create_full_weapon_tab_signals_overflow():
    b = _bridge_with_full_weapon_tab(cap_flag_value=8)
    assert b.live_create_item("Weapon_Sword_001", 0, 0, 10) is False
    assert b._last_create_overflow is True           # l'appelant convertit en rubis


def test_live_create_cap_falls_back_to_vanilla_default():
    # flag absent/aberrant (None) → cap vanilla 8 → toujours plein avec 8 armes
    b = _bridge_with_full_weapon_tab(cap_flag_value=None)
    assert b.live_create_item("Weapon_Sword_001", 0, 0, 10) is False
    assert b._last_create_overflow is True


# ── list integrity (pickup-crash guard, 2026-07-14 night) ──────────────────────
#
# The game crashed while INSERTING a natural pickup into a list our splices had
# perturbed (7th/8th runs; a chest's Barbarian Helm even vanished). Before any create
# batch the client now walks the REAL ring (sentinel → sentinel), checking next/prev
# reciprocity and mCount; a broken ring suspends creates until the next reload.

def _ring_bridge(count_val=1, break_prev=False) -> CemuMemoryBridge:
    """One-node circular list with full next/prev reciprocity served from a dict."""
    b = CemuMemoryBridge()
    prev_of_node = _SENT_G if not break_prev else 0x0DEAD000
    mem = {
        (_HOST_BASE + _SENT_G, 4): _u32(_NODE_G + 0x04),          # S.next → node link
        (_HOST_BASE + _SENT_G, 12): _u32(_NODE_G + 0x04) + _u32(_NODE_G + 0x04) + _u32(count_val),
        (_HOST_BASE + _SENT_G + 4, 4): _u32(_NODE_G + 0x04),      # S.prev (tail) → node link
        (_HOST_BASE + _SENT_G + 8, 4): _u32(count_val),           # mCount
        (_HOST_BASE + _NODE_G + 0x04, 4): _u32(_SENT_G),          # node.next → S
        (_HOST_BASE + _NODE_G + 0x08, 4): _u32(prev_of_node),     # node.prev → S (ou cassé)
    }
    b._read = lambda addr, size: mem.get((addr, size))  # type: ignore[assignment]
    return b


def test_list_integrity_accepts_consistent_ring():
    node = _make_node(_HOST_BASE + _NODE_G, _NODE_G)
    b = _ring_bridge(count_val=1)
    assert b._list_integrity_ok([node], _HOST_BASE) is True


def test_list_integrity_rejects_broken_prev():
    node = _make_node(_HOST_BASE + _NODE_G, _NODE_G)
    b = _ring_bridge(count_val=1, break_prev=True)
    assert b._list_integrity_ok([node], _HOST_BASE) is False


def test_list_integrity_rejects_mcount_mismatch():
    node = _make_node(_HOST_BASE + _NODE_G, _NODE_G)
    b = _ring_bridge(count_val=3)                     # 1 nœud réel mais mCount=3
    assert b._list_integrity_ok([node], _HOST_BASE) is False


# ── sentinelle : identification POSITIVE (cause racine des corruptions, 2026-09-09) ──
#
# `_find_list_sentinel` prenait pour sentinelle « le premier lien hors de l'ensemble
# scanné », validé par trois tests de plausibilité. Lire 12 o au LINK d'un nœud ACTIF U
# donne (U.next, U.prev, U.type) — et les trois tests passent sur une liste SAINE :
# `tail == cur` est vrai par construction et `U.type ∈ [0,9]` satisfait `0 <= cnt < 2000`.
# Un nœud actif absent du scan (motif non reconnu, lecture ratée) était donc adopté comme
# sentinelle, après quoi mCount écrivait dans U+0x0C (son TYPE) et le free-count dans
# U+0x1C (le self-pointer de son nom). C'est le mécanisme des runs 9-11, resté intact
# dans le code censé l'avoir supprimé.

_A_G = _INV_G - 0x20                             # nœud 0 du tableau (scanné)
_U_G = _INV_G - 0x20 + _STRIDE                   # nœud 1 : ACTIF mais ABSENT du scan


def _bridge_ring_with_unscanned_node(u_type: int = 7, count: int = 2) -> CemuMemoryBridge:
    """Anneau S → A → U → S où seul A est dans `selfref`. U est un nœud actif normal
    placé DANS le tableau de nœuds (420 × 544 o) ancré par `_inv_base`."""
    b = CemuMemoryBridge()
    b._inv_base = _HOST_BASE + _INV_G
    mem = {
        (_HOST_BASE + _SENT_G, 4):  _u32(_A_G + 0x04),                     # S.next → A
        (_HOST_BASE + _SENT_G, 12): _u32(_A_G + 0x04) + _u32(_U_G + 0x04) + _u32(count),
        (_HOST_BASE + _SENT_G + 4, 4): _u32(_U_G + 0x04),                  # S.prev → U (queue)
        (_HOST_BASE + _SENT_G + 8, 4): _u32(count),                        # mCount
        (_HOST_BASE + _A_G + 0x04, 4): _u32(_U_G + 0x04),                  # A.next → U
        (_HOST_BASE + _A_G + 0x08, 4): _u32(_SENT_G),                      # A.prev → S
        (_HOST_BASE + _U_G + 0x04, 4): _u32(_SENT_G),                      # U.next → S
        (_HOST_BASE + _U_G + 0x08, 4): _u32(_A_G + 0x04),                  # U.prev → A
        # la lecture de 12 o au LINK de U — celle qui piégeait l'ancien validateur
        (_HOST_BASE + _U_G + 0x04, 12): _u32(_SENT_G) + _u32(_A_G + 0x04) + _u32(u_type),
    }
    b._read = lambda addr, size: mem.get((addr, size))  # type: ignore[assignment]
    return b


def test_sentinel_walks_through_unscanned_active_node():
    """Le nœud actif non scanné est TRAVERSÉ, pas confondu avec la sentinelle."""
    a = _make_node(_HOST_BASE + _A_G, _A_G)
    b = _bridge_ring_with_unscanned_node()
    assert b._find_list_sentinel([a], _HOST_BASE) == _SENT_G


def test_sentinel_never_returns_a_node_link():
    """Régression directe : U+0x04 satisfait les 3 anciens tests et doit être REFUSÉ.
    L'accepter faisait écrire mCount dans U+0x0C (type) et le free-count dans U+0x1C."""
    a = _make_node(_HOST_BASE + _A_G, _A_G)
    for u_type in (0, 7, 9):                       # types usuels : tous < 2000
        b = _bridge_ring_with_unscanned_node(u_type=u_type)
        assert b._find_list_sentinel([a], _HOST_BASE) != _U_G + 0x04


def test_looks_like_node_uses_array_range_then_vtable():
    b = CemuMemoryBridge()
    b._inv_base = _HOST_BASE + _INV_G
    assert b._looks_like_node(_U_G, _HOST_BASE) is True          # dans le tableau
    b._read = lambda addr, size: _u32(b._POUCH_VTABLE)           # type: ignore[assignment]
    assert b._looks_like_node(0x0700_0000, _HOST_BASE) is True   # hors tableau, vtable PouchItem
    b._read = lambda addr, size: _u32(0x1234_5678)               # type: ignore[assignment]
    assert b._looks_like_node(0x0700_0000, _HOST_BASE) is False  # ni l'un ni l'autre


def test_integrity_ok_on_ring_with_unscanned_node():
    """La marche d'intégrité compte les nœuds NON scannés (2 ici) — plus de faux positif
    de « liste incohérente » sur une poche fragmentée."""
    a = _make_node(_HOST_BASE + _A_G, _A_G)
    b = _bridge_ring_with_unscanned_node(count=2)
    assert b._list_integrity_ok([a], _HOST_BASE) is True


# ── rollback : un splice avorté rend le nœud à la free-list ───────────────────
#
# Avant, un échec d'écriture APRÈS le retrait de la free-list laissait F dans AUCUNE des
# deux listes (nœud perdu, free-count faux), et un nœud à demi écrit que le scan suivant
# pouvait reprendre.

def test_free_relink_restores_node_and_neighbours():
    F_G, P_G, N_G = 0x4100_0000, 0x4100_1000, 0x4100_2000
    f_link = F_G + 0x04
    writes: dict[int, bytes] = {}
    b = CemuMemoryBridge()
    b._free_sent_g = _SENT_G
    b._read = lambda addr, size: _u32(3)                      # type: ignore[assignment]
    b._write = lambda addr, data: (writes.__setitem__(addr, data), True)[1]  # type: ignore

    b._free_relink(F_G, P_G, N_G, _HOST_BASE)

    assert writes[_HOST_BASE + F_G + 0x04] == _u32(N_G)       # F.next restauré
    assert writes[_HOST_BASE + F_G + 0x08] == _u32(P_G)       # F.prev restauré
    assert writes[_HOST_BASE + F_G + 0x0C] == _u32(0xFFFFFFFF)  # F re-marqué LIBRE
    assert writes[_HOST_BASE + F_G + 0x28] == b"\x00" * 64    # nom effacé
    assert writes[_HOST_BASE + P_G] == _u32(f_link)           # voisins re-chaînés sur F
    assert writes[_HOST_BASE + N_G + 4] == _u32(f_link)
    assert writes[_HOST_BASE + _SENT_G + 0x18] == struct.pack(">i", 4)  # free-count rendu


# ── free-list : ne JAMAIS la prendre pour la liste active (relecteur, 2026-09-09) ──
#
# La free-list est le SECOND sead::OffsetList du même objet (S+0x10) : même forme, hors du
# tableau de nœuds, sans vtable PouchItem — l'identification positive ne l'en distingue pas.
# Si le nœud de départ a été libéré entre le scan et la marche (le joueur consomme l'item),
# on part dans la chaîne libre et on aboutit à S+0x10 ; `mCount += 1` irait alors écrire
# dans le COMPTEUR DE LA FREE-LIST pendant qu'on splice dans la liste active.

_FREE_SENT_G = _SENT_G + 0x10


def test_sentinel_refuses_when_start_node_was_freed():
    """Nœud de départ rendu à la free-list → None (splice reporté), jamais S+0x10."""
    a = _make_node(_HOST_BASE + _A_G, _A_G)
    mem = {
        (_HOST_BASE + _A_G + 0x0C, 4): _u32(0xFFFFFFFF),        # A est LIBRE désormais
        (_HOST_BASE + _A_G + 0x04, 4): _u32(_FREE_SENT_G),      # …et chaîné à la free-list
        (_HOST_BASE + _FREE_SENT_G, 12): _u32(_A_G + 0x04) + _u32(_A_G + 0x04) + _u32(9),
    }
    b = CemuMemoryBridge()
    b._inv_base = _HOST_BASE + _INV_G
    b._read = lambda addr, size: mem.get((addr, size))  # type: ignore[assignment]
    assert b._find_list_sentinel([a], _HOST_BASE) is None


def test_sentinel_refuses_when_walk_enters_a_free_node():
    """Un nœud LIBRE rencontré en route → None (on est entré dans la chaîne libre)."""
    a = _make_node(_HOST_BASE + _A_G, _A_G)
    mem = {
        (_HOST_BASE + _A_G + 0x0C, 4): _u32(0),                 # A actif
        (_HOST_BASE + _A_G + 0x04, 4): _u32(_U_G + 0x04),       # A → U
        (_HOST_BASE + _U_G + 0x0C, 4): _u32(0xFFFFFFFF),        # U est LIBRE
        (_HOST_BASE + _U_G + 0x04, 4): _u32(_FREE_SENT_G),
        (_HOST_BASE + _FREE_SENT_G, 12): _u32(_U_G + 0x04) + _u32(_U_G + 0x04) + _u32(9),
    }
    b = CemuMemoryBridge()
    b._inv_base = _HOST_BASE + _INV_G
    b._read = lambda addr, size: mem.get((addr, size))  # type: ignore[assignment]
    assert b._find_list_sentinel([a], _HOST_BASE) is None


def test_free_relink_does_not_credit_a_decrement_that_never_happened():
    """`_free_sent_g` non armé (décrément jamais effectué) → aucun crédit du free-count.
    Sinon le jeu croirait disposer d'un nœud libre de plus qu'en réalité."""
    writes: dict = {}
    b = CemuMemoryBridge()
    b._free_sent_g = None
    b._read = lambda addr, size: _u32(3)                      # type: ignore[assignment]
    b._write = lambda addr, data: (writes.__setitem__(addr, data), True)[1]  # type: ignore
    b._free_relink(0x4100_0000, 0x4100_1000, 0x4100_2000, _HOST_BASE)
    assert _HOST_BASE + _SENT_G + 0x18 not in writes


# ── live_create_item : l'invariant « False ⇒ mémoire du jeu INTACTE » ────────────
#
# L'appelant (providers/save_file.py) REJOUE la spec quand live_create_item renvoie False.
# Si un abandon pouvait laisser une mutation derrière lui, la reprise créait un 2e exemplaire
# sur une liste déjà modifiée. Tout ce qui peut échouer doit donc échouer AVANT la 1re
# écriture — c'est ce que ces tests verrouillent.

_SPLICE_A_G = _INV_G - 0x20                       # ancre : arme active, slot 0
_SPLICE_F_G = _INV_G - 0x20 + _STRIDE             # nœud LIBRE cible, slot 1


def _splice_bridge(recip_ok: bool = True, fail_write_at: int = -1):
    """Bridge minimal qui pilote le VRAI chemin de splice de live_create_item.

    Insertion en QUEUE : l'ancre est A, son successeur est la sentinelle. `fail_write_at`
    = index (0-based) de l'écriture qui échoue, -1 = toutes réussissent.
    """
    b = CemuMemoryBridge()
    b._inv_base = _HOST_BASE + _INV_G
    b._heap_base = _HOST_BASE
    a = _make_node(_HOST_BASE + _SPLICE_A_G, _SPLICE_A_G, typ=0, name="Weapon_Sword_ZZZ")
    f = _make_node(_HOST_BASE + _SPLICE_F_G, _SPLICE_F_G, typ=0)
    f = {**f, "name": "", "type": 0xFFFFFFFF}
    nodes = [a, f]
    anchor_link = _SPLICE_A_G + 0x04
    f_link = _SPLICE_F_G + 0x04

    mem = {
        (_HOST_BASE + _SPLICE_F_G + 0x0C, 4): _u32(0xFFFFFFFF),      # F libre (2 lectures)
        (_HOST_BASE + anchor_link, 4): _u32(_SENT_G),                # A.next → sentinelle
        (_HOST_BASE + _SENT_G, 8): b"\x00" * 8,
        (_HOST_BASE + _SENT_G + 4, 4): _u32(anchor_link if recip_ok else 0x0BAD_0000),
        (_HOST_BASE + _SPLICE_A_G, 4): _u32(b._POUCH_VTABLE),        # ancre vivante
        (_HOST_BASE + _SPLICE_A_G + 0x0C, 4): _u32(0),
        (_HOST_BASE + _SPLICE_F_G + 0x04, 4): _u32(_FREE_SENT_G),    # F.next (free-list)
        (_HOST_BASE + _SPLICE_F_G + 0x08, 4): _u32(_FREE_SENT_G),    # F.prev
        (_HOST_BASE + _FREE_SENT_G + 4, 4): _u32(f_link),            # r1
        (_HOST_BASE + _FREE_SENT_G, 4): _u32(f_link),                # r2
        (_HOST_BASE + _SENT_G + 0x18, 4): struct.pack(">i", 5),      # free-count
        (_HOST_BASE + _SENT_G + 0x08, 4): struct.pack(">i", 1),      # mCount
    }
    writes: dict = {}
    order: list = []

    def _read(addr, size):
        return mem.get((addr, size))

    def _write(addr, data):
        if fail_write_at >= 0 and len(order) == fail_write_at:
            order.append(addr)
            return False
        order.append(addr)
        writes[addr] = data
        return True

    b._read = _read                                             # type: ignore[assignment]
    b._write = _write                                           # type: ignore[assignment]
    b._refresh_inv_from_static = lambda: True                   # type: ignore
    b._scan_pouch_nodes = lambda inv_base=None: nodes           # type: ignore
    b._derive_heap_base = lambda ns: _HOST_BASE                 # type: ignore
    b.live_find_item = lambda name: None                        # type: ignore
    b.read_flag = lambda name: 8                                # type: ignore
    b._find_list_sentinel = lambda sr, base: _SENT_G            # type: ignore
    b._list_integrity_ok = lambda sr, base: True                # type: ignore
    b._last_pouch_sig = ("Weapon_Sword_ZZZ", "")
    b._sig_changed_at = 0.0                                     # poche calme depuis longtemps
    b._last_integrity_check = time.monotonic()                  # saute le contrôle périodique
    return b, writes, order, anchor_link, f_link


def test_create_aborts_without_touching_memory_when_anchor_not_reciprocal():
    """Ancre non réciproque (liste modifiée sous nos pieds) → False ET ZÉRO écriture."""
    b, writes, order, _, _ = _splice_bridge(recip_ok=False)
    assert b.live_create_item("Weapon_Sword_502", 0, 0, 10) is False
    assert writes == {}, f"la mémoire du jeu a été modifiée malgré l'abandon : {writes}"
    assert order == []


def test_create_publishes_in_the_documented_order():
    """Contenu de F, puis lien ARRIÈRE du successeur, puis PUBLICATION du lien avant."""
    b, writes, order, anchor_link, f_link = _splice_bridge()
    assert b.live_create_item("Weapon_Sword_502", 0, 0, 10) is True
    # 0-1 : retrait de la free-list · 2 : free-count · 3-5 : contenu, arrière, publication
    splice = order[3:6]
    assert splice == [_HOST_BASE + _SPLICE_F_G,          # contenu de F
                      _HOST_BASE + _SENT_G + 4,          # prev du successeur (queue)
                      _HOST_BASE + anchor_link]          # publication EN DERNIER
    assert writes[_HOST_BASE + anchor_link] == _u32(f_link)


def test_create_rolls_back_and_never_publishes_when_node_write_fails():
    """Échec d'écriture du CONTENU → F rendu à la free-list, AUCUNE publication.

    Avant, `ok &= self._write(...)` n'était pas court-circuité : un nœud dont l'écriture
    avait échoué était publié quand même dans la liste du jeu.
    """
    b, writes, order, anchor_link, f_link = _splice_bridge(fail_write_at=3)
    assert b.live_create_item("Weapon_Sword_502", 0, 0, 10) is False
    assert _HOST_BASE + anchor_link not in writes, "nœud publié malgré l'échec d'écriture"
    # rollback : F re-marqué libre et re-chaîné
    assert writes[_HOST_BASE + _SPLICE_F_G + 0x0C] == _u32(0xFFFFFFFF)
    assert writes[_HOST_BASE + _SPLICE_F_G + 0x04] == _u32(_FREE_SENT_G)
    assert writes[_HOST_BASE + _FREE_SENT_G + 4] == _u32(f_link)
