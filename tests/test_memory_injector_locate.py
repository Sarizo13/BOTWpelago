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
    assert b._heap_base is None                           # NOT set from an unvalidated base


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
