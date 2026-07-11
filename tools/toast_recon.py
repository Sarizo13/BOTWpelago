"""
toast_recon — recon mémoire GÉNÉRIQUE (lecture seule) : session toast natif 2026-07-11.

  python tools/toast_recon.py handles [substr]            # handles ressources vivants (AOB 4 vtables)
  python tools/toast_recon.py stockitem                   # occurrences "StockItem", classées par string englobante
  python tools/toast_recon.py base                        # dérive + cache heap_base (attach complet, ~10-60 s)
  python tools/toast_recon.py backrefs 0x<host> [lo hi]   # refs guest vers [obj+lo, obj+hi) (défaut -0x40..+0xC0)
  python tools/toast_recon.py scanvals 0x<lo> 0x<hi> [n]  # u32be dont la VALEUR est dans [lo,hi)
  python tools/toast_recon.py dump 0x<host>|g:0x<guest> [before after]
  python tools/toast_recon.py watch 0x<host> <secs> [before after]   # monitor 15 Hz -> JSON

`g:0x...` = adresse GUEST (host = heap_base + guest — le mapping couvre TOUT l'espace
guest, .data/.bss inclus : les singletons DAT_10xxxxxx se lisent directement).
heap_base est caché par PID Cemu dans ~/.botwpelago/toast_recon.json.
"""
from __future__ import annotations

import json
import struct
import sys
import time
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from BotWClient.memory_injector import (  # noqa: E402
    CemuMemoryBridge, _find_pid, _k32, PROCESS_ALL_RW,
)

STATE = Path.home() / ".botwpelago" / "toast_recon.json"
CHUNK = 16 * 1024 * 1024

# Signature handle ressource (session diff 2026-07-12) : 4 vtables guest consécutives.
HANDLE_VT0 = 0x102FD2B4
HANDLE_VT1 = (0x1031FBFC, 0x1031FCB8)
HANDLE_VT2 = 0x10263910
HANDLE_VT3 = 0x10334734
HANDLE_PATH_OFF = 0x38


def log(m=""):
    print(m, flush=True)


def open_bridge() -> CemuMemoryBridge:
    """Attach léger : OpenProcess seulement (pas de scan gamedata/inventaire)."""
    b = CemuMemoryBridge()
    b._pid = _find_pid("cemu.exe")
    if b._pid is None:
        log("ERREUR: cemu.exe introuvable.")
        sys.exit(1)
    b._handle = _k32.OpenProcess(PROCESS_ALL_RW, False, b._pid)
    if not b._handle:
        log("ERREUR: OpenProcess a échoué (shell admin requis).")
        sys.exit(1)
    return b


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=2), encoding="utf-8")


def iter_chunks(b: CemuMemoryBridge, overlap: int):
    """(base, off, n, chunk) sur toutes les régions lisibles, chunks de 16 Mo + overlap."""
    for base, size in b._iter_regions():
        off = 0
        while off < size:
            n = min(CHUNK, size - off)
            chunk = b._read(base + off, min(n + overlap, size - off))
            if chunk:
                yield base, off, n, chunk
            off += n


def read_cstr(b: CemuMemoryBridge, addr: int, maxlen: int = 0x100) -> str:
    raw = b._read(addr, maxlen) or b""
    return raw.split(b"\x00")[0].decode("ascii", "replace")


def hexdump(b: CemuMemoryBridge, addr: int, before: int, after: int) -> str:
    blob = b._read(addr - before, before + after) or b""
    out = []
    for i in range(0, len(blob), 16):
        row = blob[i:i + 16]
        rel = i - before
        hexs = " ".join(f"{x:02X}" for x in row)
        asci = "".join(chr(x) if 32 <= x < 127 else "." for x in row)
        mark = "  <== hit" if rel <= 0 < rel + 16 else ""
        out.append(f"    {rel:+06X}: {hexs:<47}  {asci}{mark}")
    return "\n".join(out)


def guest_consts(b: CemuMemoryBridge, addr: int, before: int, after: int) -> list[str]:
    """Constantes guest 0x10xxxxxx (vtables v208, stables) autour d'une adresse."""
    blob = b._read(addr - before, before + after) or b""
    found = []
    for off in range(0, len(blob) - 3, 4):
        w = struct.unpack_from(">I", blob, off)[0]
        if 0x10000000 <= w < 0x10400000:
            found.append(f"{off - before:+#x}:0x{w:08X}")
    return found


# ── handles ──────────────────────────────────────────────────────────────────

def cmd_handles(substr: str | None) -> None:
    b = open_bridge()
    sig0 = struct.pack(">I", HANDLE_VT0)
    t0 = time.monotonic()
    found: list[tuple[int, str]] = []
    for base, off, n, chunk in iter_chunks(b, 16 + HANDLE_PATH_OFF + 0x100):
        s = 0
        while True:
            i = chunk.find(sig0, s)
            if i < 0 or i >= n:
                break
            s = i + 1
            if i + 16 > len(chunk):
                continue
            w1, w2, w3 = struct.unpack_from(">III", chunk, i + 4)
            if w1 not in HANDLE_VT1 or w2 != HANDLE_VT2 or w3 != HANDLE_VT3:
                continue
            addr = base + off + i
            path = read_cstr(b, addr + HANDLE_PATH_OFF, 0x100)
            if not path or not all(32 <= ord(c) < 127 for c in path):
                path = "<no-path?>"
            found.append((addr, path))
    dt = time.monotonic() - t0
    if substr:
        shown = [(a, p) for a, p in found if substr.lower() in p.lower()]
    else:
        shown = found
    log(f"{len(found)} handle(s) vivants en {dt:.1f}s ; affichés: {len(shown)}"
        + (f" (filtre {substr!r})" if substr else ""))
    for a, p in shown:
        log(f"  0x{a:012X}  {p}")
    st = _load_state()
    st["handles"] = [{"host": f"0x{a:X}", "path": p} for a, p in found]
    st["handles_pid"] = b._pid
    _save_state(st)


# ── stockitem strings ────────────────────────────────────────────────────────

def _enclosing_string(b: CemuMemoryBridge, hit: int, needle_len: int) -> tuple[int, str]:
    """Étend le hit à la C-string ASCII englobante (chars imprimables)."""
    before = b._read(hit - 0x80, 0x80) or b""
    start = hit
    for i in range(len(before) - 1, -1, -1):
        c = before[i]
        if 32 <= c < 127:
            start = hit - (len(before) - i)
        else:
            break
    full = read_cstr(b, start, 0x120)
    return start, full


def cmd_stockitem() -> None:
    b = open_bridge()
    needle = b"StockItem"
    t0 = time.monotonic()
    hits: list[int] = []
    for base, off, n, chunk in iter_chunks(b, len(needle) + 8):
        s = 0
        while True:
            i = chunk.find(needle, s)
            if i < 0 or i >= n:
                break
            hits.append(base + off + i)
            s = i + 1
    dt = time.monotonic() - t0
    log(f"{len(hits)} occurrence(s) de 'StockItem' en {dt:.1f}s")

    groups: dict[str, list[int]] = {}
    starts: dict[int, int] = {}
    for h in hits:
        start, full = _enclosing_string(b, h, len(needle))
        groups.setdefault(full, []).append(h)
        starts[h] = start
    log(f"\n=== {len(groups)} strings englobantes distinctes ===")
    for full, where in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        log(f"  [{len(where):4d}x] {full!r}")
        # celles qui ne sont NI un path UI/ NI un .bat/.bas : contexte objet -> candidates
    interesting = {full: where for full, where in groups.items()
                   if "UI/StockItem" not in full and ".bat" not in full
                   and ".bas" not in full and ".bitemico" not in full}
    log(f"\n=== hors-path ({len(interesting)} strings) : hexdumps (max 6 par string) ===")
    for full, where in interesting.items():
        log(f"\n--- {full!r} ({len(where)} hits) ---")
        for h in where[:6]:
            log(f"  hit @0x{h:012X} (string start 0x{starts[h]:012X})")
            log(hexdump(b, h, 0x60, 0x60))
            g = guest_consts(b, h, 0x60, 0x60)
            if g:
                log(f"    vtables/consts guest: {' '.join(g)}")
    st = _load_state()
    st["stockitem"] = {full: [f"0x{a:X}" for a in where] for full, where in groups.items()}
    _save_state(st)


# ── heap base ────────────────────────────────────────────────────────────────

def ensure_base(force: bool = False) -> tuple[CemuMemoryBridge, int]:
    """heap_base (guest = host - base). Caché par PID Cemu (fixe pour la vie du process)."""
    pid = _find_pid("cemu.exe")
    st = _load_state()
    if not force and st.get("base_pid") == pid and st.get("heap_base"):
        b = open_bridge()
        return b, int(st["heap_base"], 16)
    log("Attach complet (scan gamedata+inventaire) pour dériver heap_base...")
    b = CemuMemoryBridge()
    if not b.attach():
        log("ERREUR: attach complet impossible (save chargée ?).")
        sys.exit(1)
    nodes = b._scan_pouch_nodes()
    base = b._derive_heap_base(nodes) if nodes else None
    if base is None:
        log("ERREUR: heap_base non dérivable (inventaire vide/introuvable).")
        sys.exit(1)
    st["base_pid"] = pid
    st["heap_base"] = f"0x{base:X}"
    _save_state(st)
    log(f"heap_base = 0x{base:X} (caché pour pid {pid})")
    return b, base


def cmd_base() -> None:
    _, base = ensure_base(force=True)
    log(f"OK heap_base 0x{base:X}")


# ── backrefs ─────────────────────────────────────────────────────────────────

def cmd_backrefs(host: int, lo_off: int, hi_off: int) -> None:
    b, base = ensure_base()
    guest = host - base
    if not (0 < guest <= 0xFFFFFFFF):
        log(f"ERREUR: guest 0x{guest:X} hors plage (heap_base périmé ? relance 'base').")
        sys.exit(1)
    lo, hi = guest + lo_off, guest + hi_off
    log(f"objet host 0x{host:012X} -> guest 0x{guest:08X} ; scan refs vers "
        f"[0x{lo:08X}, 0x{hi:08X}) ...")
    t0 = time.monotonic()
    refs: list[tuple[int, int]] = []
    for rbase, off, n, chunk in iter_chunks(b, 4):
        n4 = n - (n % 4)
        if n4 <= 0:
            continue
        arr = np.frombuffer(chunk[:n4], dtype=">u4")
        idx = np.where((arr >= lo) & (arr < hi))[0]
        for i in idx:
            refs.append((rbase + off + int(i) * 4, int(arr[i])))
    dt = time.monotonic() - t0
    log(f"{len(refs)} référence(s) en {dt:.0f}s")
    in_self = [(a, v) for a, v in refs if host + lo_off <= a < host + hi_off]
    ext = [(a, v) for a, v in refs if not (host + lo_off <= a < host + hi_off)]
    log(f"  dont {len(in_self)} DANS l'objet lui-même (self), {len(ext)} externes\n")
    for a, v in ext[:40]:
        log(f"  ref @0x{a:012X} -> guest 0x{v:08X} (obj{v - guest:+#x})")
        log(hexdump(b, a, 0x40, 0x40))
        g = guest_consts(b, a, 0x40, 0x40)
        if g:
            log(f"    vtables/consts guest: {' '.join(g)}")
        log("")
    if len(ext) > 40:
        log(f"  (+{len(ext) - 40} non affichées)")
    st = _load_state()
    st["backrefs"] = {"target_host": f"0x{host:X}", "target_guest": f"0x{guest:X}",
                      "refs": [{"addr": f"0x{a:X}", "val": f"0x{v:X}"} for a, v in refs]}
    _save_state(st)


def cmd_scanvals(lo: int, hi: int, max_dump: int) -> None:
    """Tous les u32be alignés dont la VALEUR est dans [lo, hi) — ex: instances par vtable."""
    b = open_bridge()
    t0 = time.monotonic()
    hits: list[tuple[int, int]] = []
    for rbase, off, n, chunk in iter_chunks(b, 4):
        n4 = n - (n % 4)
        if n4 <= 0:
            continue
        arr = np.frombuffer(chunk[:n4], dtype=">u4")
        idx = np.where((arr >= lo) & (arr < hi))[0]
        for i in idx:
            hits.append((rbase + off + int(i) * 4, int(arr[i])))
    print(f"{len(hits)} hit(s) en {time.monotonic()-t0:.0f}s pour valeurs [0x{lo:08X},0x{hi:08X})")
    for a, v in hits[:max_dump]:
        print(f"\n  @0x{a:012X} = 0x{v:08X}")
        print(hexdump(b, a, 0x20, 0x40))
    if len(hits) > max_dump:
        print(f"  (+{len(hits) - max_dump} non affichés)")
    st = _load_state()
    st["scanvals"] = [{"addr": f"0x{a:X}", "val": f"0x{v:X}"} for a, v in hits]
    _save_state(st)


# ── dump / watch ─────────────────────────────────────────────────────────────

def _parse_addr(s: str) -> tuple[int, bool]:
    if s.startswith("g:"):
        return int(s[2:], 0), True
    return int(s, 0), False


def cmd_dump(spec: str, before: int, after: int) -> None:
    addr, is_guest = _parse_addr(spec)
    if is_guest:
        b, base = ensure_base()
        addr = base + addr
        log(f"guest -> host 0x{addr:012X}")
    else:
        b = open_bridge()
    log(hexdump(b, addr, before, after))
    g = guest_consts(b, addr, before, after)
    if g:
        log(f"    vtables/consts guest: {' '.join(g)}")


def cmd_watch(spec: str, secs: float, before: int, after: int) -> None:
    addr, is_guest = _parse_addr(spec)
    if is_guest:
        b, base = ensure_base()
        addr = base + addr
    else:
        b = open_bridge()
    out = STATE.parent / f"toast_watch_{addr:X}.json"
    period = 1.0 / 15
    t0 = time.monotonic()
    last = b._read(addr - before, before + after) or b""
    events = []
    log(f"watch 0x{addr:012X} [-{before:#x}..+{after:#x}] pendant {secs:.0f}s ...")
    while time.monotonic() - t0 < secs:
        cur = b._read(addr - before, before + after) or b""
        if cur and cur != last:
            ch = []
            for off in range(0, min(len(last), len(cur)) - 3, 4):
                a0 = struct.unpack_from(">I", last, off)[0]
                c0 = struct.unpack_from(">I", cur, off)[0]
                if a0 != c0:
                    ch.append({"off": f"{off - before:+#x}",
                               "old": f"0x{a0:08X}", "new": f"0x{c0:08X}"})
            events.append({"t": round(time.monotonic() - t0, 3), "changed": ch})
            last = cur
        time.sleep(period)
    out.write_text(json.dumps(events, indent=1), encoding="utf-8")
    log(f"{len(events)} changement(s) -> {out}")
    for e in events[:30]:
        log(f"  t={e['t']:8.3f}  " + "  ".join(
            f"{c['off']}:{c['old']}->{c['new']}" for c in e["changed"][:8]))


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "handles":
        cmd_handles(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "stockitem":
        cmd_stockitem()
    elif cmd == "base":
        cmd_base()
    elif cmd == "backrefs":
        host = int(sys.argv[2], 0)
        lo = int(sys.argv[3], 0) if len(sys.argv) > 3 else -0x40
        hi = int(sys.argv[4], 0) if len(sys.argv) > 4 else 0xC0
        cmd_backrefs(host, lo, hi)
    elif cmd == "scanvals":
        lo = int(sys.argv[2], 0)
        hi = int(sys.argv[3], 0)
        md = int(sys.argv[4], 0) if len(sys.argv) > 4 else 24
        cmd_scanvals(lo, hi, md)
    elif cmd == "dump":
        before = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x100
        after = int(sys.argv[4], 0) if len(sys.argv) > 4 else 0x100
        cmd_dump(sys.argv[2], before, after)
    elif cmd == "watch":
        secs = float(sys.argv[3]) if len(sys.argv) > 3 else 60.0
        before = int(sys.argv[4], 0) if len(sys.argv) > 4 else 0x40
        after = int(sys.argv[5], 0) if len(sys.argv) > 5 else 0x100
        cmd_watch(sys.argv[2], secs, before, after)
    else:
        print(f"commande inconnue: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
