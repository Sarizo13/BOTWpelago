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
