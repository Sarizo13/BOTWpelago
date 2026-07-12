"""
toast_queue_watch v2 — inspecte + capture EN LIVE la file de requêtes du HUD (canal du
toast de ramassage), fondé sur la décomp EXACTE de l'enqueue (FUN_02ed1f7c) et du
pushBack sead (FUN_0308e7e8) — session 2026-07-12.

Structure reqMgr (= *(HUD+0x1B84), HUD = écran registre id 0x25) :
  +0x110  critical section (le jeu locke autour de l'enqueue)
  +0x14C  sentinel.next = HEAD (liste circulaire ; self-référent = vide)
  +0x150  sentinel.prev = TAIL
  +0x154  count (s32)
  +0x158  freelist head (pop : node = *0x158 ; *0x158 = *node — 1er mot du nœud libre)
  +0x160  capacité (3)

Nœud (0x54 octets de données + ListNode 8 octets) :
  +0x00  u32 type (0xB = toast ramassage) | en freelist : ptr next-libre
  +0x04  mStringTop -> node+0x10 (guest)
  +0x08  vtable 0x1021D0FC (FixedSafeString<64> finale)
  +0x0C  bufsize 0x40
  +0x10  char[64] nom (NUL-terminé)
  +0x50  u8 flag = 0
  +0x54  link.next   +0x58  link.prev   (links pointent les +0x54 des voisins / le sentinel)

Les nœuds RECYCLÉS en freelist gardent leur contenu résiduel (string du dernier toast)
→ le dump post-mortem suffit à figer le layout même sans attraper la transition.

Usage (terminal ADMIN, Cemu+BotW lancés, `python tools/toast_recon.py base` déjà fait) :
    python tools/toast_queue_watch.py            # inspect one-shot (repos OU après ramassage)
    python tools/toast_queue_watch.py 40         # watch 40 s (busy-loop ~kHz) + post-mortem
  -> pendant le watch, RAMASSE 2-3 objets. Résultat -> ~/.botwpelago/toast_queue.json
"""
from __future__ import annotations

import json
import struct
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from toast_recon import open_bridge, _load_state  # noqa: E402

REG_PTR = 0x1047E650      # registre des écrans
CTX_PTR = 0x1047B054      # contexte toast (nom d'actor @ctx+0x2C)
UIROOT_PTR = 0x1046BDD8   # uiroot (bit dirty @+0x4075C)
DEFSTR_PTR = 0x10549FEC   # SafeString par défaut passée par FUN_030731ec (bss, à lire live)
HUD_ID = 0x25
REQMGR_OFF = 0x1B84
DIRTY_OFF = 0x4075C
NODE_VT = 0x1021D0FC

SENT_NEXT, SENT_PREV, COUNT, FREELIST, CAP = 0x14C, 0x150, 0x154, 0x158, 0x160
WIN_LO, WIN_HI = 0x140, 0x178
NODE_SIZE = 0x5C          # 0x54 données + link {next,prev}

OUT = Path.home() / ".botwpelago" / "toast_queue.json"


def _hexdump(blob: bytes, base_label: int = 0) -> list[str]:
    rows = []
    for i in range(0, len(blob), 16):
        row = blob[i:i + 16]
        hexs = " ".join(f"{x:02X}" for x in row)
        asci = "".join(chr(x) if 32 <= x < 127 else "." for x in row)
        rows.append(f"+{base_label + i:04X}: {hexs:<47}  {asci}")
    return rows


class Q:
    def __init__(self):
        st = _load_state()
        if "heap_base" not in st:
            print("Lance d'abord : python tools/toast_recon.py base")
            sys.exit(1)
        self.heap = int(st["heap_base"], 16)
        self.b = open_bridge()
        reg = self.rd32(REG_PTR)
        arr = self.rd32(reg + 0x18) if reg else 0
        self.hud = self.rd32(arr + HUD_ID * 4) if arr else 0
        self.reqmgr = self.rd32(self.hud + REQMGR_OFF) if self.hud else 0
        print(f"HUD g:0x{self.hud:08X}  reqMgr g:0x{self.reqmgr:08X}")
        if not self.reqmgr:
            print("reqMgr nul — HUD pas initialisé ? (save chargée en jeu ?)")
            sys.exit(1)

    def rd(self, guest: int, n: int) -> bytes:
        return self.b._read(self.heap + guest, n) or b""

    def rd32(self, guest: int) -> int:
        raw = self.rd(guest, 4)
        return struct.unpack(">I", raw)[0] if len(raw) == 4 else 0

    def cstr(self, guest: int, maxlen: int = 0x40) -> str:
        raw = self.rd(guest, maxlen)
        return raw.split(b"\x00")[0].decode("ascii", "replace")

    def plausible(self, g: int) -> bool:
        return 0x02000000 <= g < 0x80000000 and g % 4 == 0

    # ── décodage ─────────────────────────────────────────────────────────────

    def decode_node(self, node_g: int) -> dict:
        blob = self.rd(node_g, NODE_SIZE)
        d = {"node": f"0x{node_g:08X}"}
        if len(blob) < NODE_SIZE:
            d["error"] = "lecture courte"
            return d
        w = struct.unpack(">23I", blob[:0x5C])
        d.update({
            "type_or_freenext": f"0x{w[0]:08X}",
            "top": f"0x{w[1]:08X}", "top_ok": w[1] == node_g + 0x10,
            "vtable": f"0x{w[2]:08X}", "vt_ok": w[2] == NODE_VT,
            "bufsize": f"0x{w[3]:08X}",
            "str": blob[0x10:0x50].split(b"\x00")[0].decode("ascii", "replace"),
            "byte50": blob[0x50],
            "link_next": f"0x{w[0x54 // 4]:08X}", "link_prev": f"0x{w[0x58 // 4]:08X}",
            "hex": _hexdump(blob),
        })
        return d

    def walk_active(self) -> list[dict]:
        sent = self.reqmgr + SENT_NEXT
        out, link, hops = [], self.rd32(sent), 0
        while link and link != sent and hops < 8:
            out.append(self.decode_node(link - 0x54))
            link = self.rd32(link)          # link.next @+0
            hops += 1
        return out

    def walk_freelist(self) -> list[dict]:
        out, node, seen = [], self.rd32(self.reqmgr + FREELIST), set()
        while node and self.plausible(node) and node not in seen and len(out) < 8:
            seen.add(node)
            out.append(self.decode_node(node))
            node = self.rd32(node)          # next-libre = 1er mot
        return out

    def snapshot(self) -> dict:
        sent = self.reqmgr + SENT_NEXT
        head, tail = self.rd32(sent), self.rd32(self.reqmgr + SENT_PREV)
        ctx = self.rd32(CTX_PTR)
        uiroot = self.rd32(UIROOT_PTR)
        deftop = self.rd32(DEFSTR_PTR)
        snap = {
            "reqmgr": f"0x{self.reqmgr:08X}",
            "head": f"0x{head:08X}", "tail": f"0x{tail:08X}",
            "empty": head == sent and tail == sent,
            "count": self.rd32(self.reqmgr + COUNT),
            "freelist": f"0x{self.rd32(self.reqmgr + FREELIST):08X}",
            "cap": self.rd32(self.reqmgr + CAP),
            "window_hex": _hexdump(self.rd(self.reqmgr + WIN_LO, WIN_HI - WIN_LO), WIN_LO),
            "active_nodes": self.walk_active(),
            "freelist_nodes": self.walk_freelist(),
            "ctx": f"0x{ctx:08X}",
            "ctx_top": f"0x{self.rd32(ctx + 0x20):08X}" if ctx else None,
            "ctx_actor": self.cstr(ctx + 0x2C) if ctx else None,
            "uiroot": f"0x{uiroot:08X}",
            "dirty_word": f"0x{self.rd32(uiroot + DIRTY_OFF):08X}" if uiroot else None,
            "defstr_top": f"0x{deftop:08X}",
            "defstr": self.cstr(deftop) if self.plausible(deftop) else "",
        }
        return snap


def print_snap(tag: str, s: dict) -> None:
    print(f"\n=== {tag} ===")
    print(f"  file: head={s['head']} tail={s['tail']} vide={s['empty']} "
          f"count={s['count']} freelist={s['freelist']} cap={s['cap']}")
    print(f"  ctx actor={s['ctx_actor']!r} (top={s['ctx_top']})  "
          f"defstr={s['defstr']!r}  dirty={s['dirty_word']}")
    for i, n in enumerate(s["active_nodes"]):
        print(f"  ACTIF[{i}] @{n['node']} type={n.get('type_or_freenext')} "
              f"str={n.get('str')!r} vt_ok={n.get('vt_ok')} top_ok={n.get('top_ok')}")
    for i, n in enumerate(s["freelist_nodes"]):
        print(f"  LIBRE[{i}] @{n['node']} freenext={n.get('type_or_freenext')} "
              f"str_residuelle={n.get('str')!r} vt_ok={n.get('vt_ok')}")


def main() -> None:
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
    q = Q()
    initial = q.snapshot()
    print_snap("ÉTAT INITIAL", initial)
    result = {"reqmgr": f"0x{q.reqmgr:08X}", "hud": f"0x{q.hud:08X}",
              "initial": initial, "events": [], "final": None}

    if secs > 0:
        print(f"\nSurveillance {secs:.0f}s (busy-loop) — RAMASSE des objets maintenant...")
        win_g, win_n = q.reqmgr + WIN_LO, WIN_HI - WIN_LO
        ctx = q.rd32(CTX_PTR)
        sent = q.reqmgr + SENT_NEXT
        last_w = q.rd(win_g, win_n)
        last_c = q.rd(ctx + 0x2C, 0x40) if ctx else b""
        events, iters = [], 0
        t0 = time.monotonic()
        while time.monotonic() - t0 < secs:
            iters += 1
            w = q.rd(win_g, win_n)
            c = q.rd(ctx + 0x2C, 0x40) if ctx else b""
            if w != last_w or c != last_c:
                ev = {"t": round(time.monotonic() - t0, 4),
                      "actor": c.split(b"\x00")[0].decode("ascii", "replace"),
                      "win": [f"{struct.unpack_from('>I', w, k)[0]:08X}"
                              for k in range(0, len(w) - 3, 4)]}
                head = struct.unpack_from(">I", w, SENT_NEXT - WIN_LO)[0]
                if head and head != sent:
                    ev["head_node"] = q.decode_node(head - 0x54)
                events.append(ev)
                last_w, last_c = w, c
                if len(events) >= 400:
                    break
        rate = iters / max(time.monotonic() - t0, 1e-9)
        print(f"{len(events)} changement(s), polling effectif {rate:,.0f} Hz")
        result["events"] = events
        result["poll_hz"] = round(rate)

    final = q.snapshot()
    print_snap("POST-MORTEM", final)
    result["final"] = final
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
