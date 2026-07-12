"""
toast_queue_watch — capture EN LIVE la file de requêtes du HUD (le canal du toast de
ramassage), le nom d'actor du contexte, et mLastAddedItems, pendant que le joueur ramasse.

Architecture (RE session 2026-07-11, docs/status.md §6c) :
  - HUD MainScreen = registre écran id 0x25 : `screen = *(regArray + 0x25*4)`,
    `regArray = *(*(0x1047E650) + 0x18)`.
  - request manager = `reqMgr = *(HUD + 0x1B84)` ; file de requêtes d'ouverture d'écran
    à `reqMgr + 0x150` (tête) / `+0x154` / `+0x158` (freelist) / `+0x160` (capacité),
    nœuds de 0x54 octets (contiennent un id de type + un sead::FixedSafeString).
    L'événement pickup enfile le type 0xB ici (FUN_030731ec → FUN_02ed1f7c).
  - nom d'actor du toast = SafeString `*(0x1047B054) + 0x2C` (buffer inline).

Protocole (terminal ADMIN, Cemu+BotW lancés, save chargée, `python tools/toast_recon.py base`
déjà fait) :
    python tools/toast_queue_watch.py 40      # surveille 40 s
  -> pendant ces 40 s, RAMASSE 3-4 objets variés (un déjà en stock = moins de bruit).
  Le script logue chaque changement de la file + du nom d'actor -> ~/.botwpelago/toast_queue.json
  Dis à Claude quand c'est fini.
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

REG_PTR = 0x1047E650
CTX_PTR = 0x1047B054
HUD_ID = 0x25
REQMGR_OFF = 0x1B84
QUEUE_LO, QUEUE_HI = 0x140, 0x174     # fenêtre file dans reqMgr
OUT = Path.home() / ".botwpelago" / "toast_queue.json"
POLL_HZ = 30


def main() -> None:
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
    st = _load_state()
    if "heap_base" not in st:
        print("Lance d'abord : python tools/toast_recon.py base")
        return
    heap = int(st["heap_base"], 16)
    b = open_bridge()

    def rd32(guest):
        raw = b._read(heap + guest, 4)
        return struct.unpack(">I", raw)[0] if raw else 0

    reg = rd32(REG_PTR)
    arr = rd32(reg + 0x18)
    hud = rd32(arr + HUD_ID * 4)
    reqmgr = rd32(hud + REQMGR_OFF)
    print(f"HUD screen g:0x{hud:08X}  reqMgr g:0x{reqmgr:08X}")
    if not reqmgr:
        print("reqMgr nul — HUD pas encore initialisé ? charge une save en jeu.")
        return

    def snap_queue():
        return b._read(heap + reqmgr + QUEUE_LO, QUEUE_HI - QUEUE_LO) or b""

    def snap_name():
        raw = b._read(heap + CTX_PTR, 4)
        if not raw:
            return ""
        ctx = struct.unpack(">I", raw)[0]
        buf = b._read(heap + ctx + 0x2C, 0x40) or b""
        return buf.split(b"\x00")[0].decode("ascii", "replace")

    print(f"Surveillance {secs:.0f}s — RAMASSE des objets maintenant...")
    events = []
    t0 = time.monotonic()
    last_q = snap_queue()
    last_n = snap_name()
    period = 1.0 / POLL_HZ
    while time.monotonic() - t0 < secs:
        q = snap_queue()
        n = snap_name()
        if q != last_q or n != last_n:
            words = [f"{struct.unpack_from('>I', q, k)[0]:08X}"
                     for k in range(0, len(q) - 3, 4)]
            events.append({"t": round(time.monotonic() - t0, 3), "name": n,
                           "queue": words})
            last_q, last_n = q, n
        time.sleep(period)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "hud": f"0x{hud:08X}", "reqmgr": f"0x{reqmgr:08X}",
        "queue_off": [f"0x{QUEUE_LO:X}", f"0x{QUEUE_HI:X}"],
        "n_events": len(events), "events": events[:400],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(events)} changement(s) -> {OUT}")
    for e in events[:20]:
        print(f"  t={e['t']:7.3f}  name={e['name']!r}  queue={' '.join(e['queue'])}")


if __name__ == "__main__":
    main()
