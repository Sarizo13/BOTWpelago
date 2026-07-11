"""
toast_watch — observe EN LIVE la structure pilote du toast de ramassage.

Idee : on connait deja le "slot pickup" (sead::FixedSafeString vt 0x1024BDA8 = nom
d'actor du DERNIER objet ramasse, a adresse FIXE dans la session). On le localise UNE
fois (scan restreint au gros tas -> rapide), puis on MONITORE cette region a ~15 Hz
pendant que tu ramasses une dizaine d'objets. Chaque changement (nom + mots de 4 octets
autour) est logue -> on voit quel champ = nom, quel champ = compteur/timer/etat d'anim.

A lancer TOI-MEME dans un terminal ADMIN (Cemu tourne en admin -> ReadProcessMemory
exige admin), Cemu + BotW lances, une save chargee, DEBOUT pres d'objets a ramasser :

    python tools/toast_watch.py

Etapes (le script te guide) :
  1. localisation auto -> "MEMOIRE TROUVEE @ ..." (quelques secondes)
  2. Entree -> demarre le scan
  3. ramasse ~10 objets varies (secoue un arbre, ramasse tout)
  4. Entree -> termine ; le log complet est ecrit dans
     ~/.botwpelago/toast_watch_out.json  (Claude le lira)
"""
from __future__ import annotations

import json
import re
import struct
import sys
import threading
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from BotWClient.memory_injector import (  # noqa: E402
    CemuMemoryBridge, _find_pid, _k32, PROCESS_ALL_RW,
)

OUT = Path.home() / ".botwpelago" / "toast_watch_out.json"
# Signature du slot pickup : vtable sead::FixedSafeString 0x1024BDA8 + taille buffer 64,
# immediatement suivie du nom d'actor (cf. session diff 2026-07-12).
SIG = bytes.fromhex("1024BDA8" + "00000040")
NAME_LEN = 0x40
WIN_BEFORE, WIN_AFTER = 0x40, 0x80          # fenetre monitoree autour du nom
ACTOR_RE = re.compile(rb"^(Item_|Weapon_|Armor_|Obj_|Animal_|Material_|Get_|Bomb|Fire|Ice|"
                      rb"Electric|Normal|Ancient|Remote)[A-Za-z0-9_]*")
POLL_HZ = 15
BIG_REGION = 256 * 1024 * 1024              # ne scanner que le(s) gros tas (~3.6 Go)
CHUNK = 16 * 1024 * 1024


def log(m=""):
    print(m, flush=True)


def open_bridge() -> CemuMemoryBridge:
    b = CemuMemoryBridge()
    b._pid = _find_pid("cemu.exe")
    if b._pid is None:
        log("ERREUR: cemu.exe introuvable.")
        sys.exit(1)
    b._handle = _k32.OpenProcess(PROCESS_ALL_RW, False, b._pid)
    if not b._handle:
        log("ERREUR: OpenProcess a echoue -> lance ce terminal EN ADMIN (Cemu est admin).")
        sys.exit(1)
    return b


def locate(b: CemuMemoryBridge) -> list[int]:
    """Scan des GROS tas pour la signature du slot pickup suivie d'un nom d'actor valide."""
    hits: list[int] = []
    for base, size in b._iter_regions():
        if size < BIG_REGION:
            continue
        off = 0
        while off < size:
            n = min(CHUNK, size - off)
            chunk = b._read(base + off, min(n + len(SIG) + NAME_LEN, size - off))
            if chunk:
                s = 0
                while True:
                    i = chunk.find(SIG, s)
                    if i < 0 or i >= n:
                        break
                    name_addr = base + off + i + len(SIG)
                    tail = chunk[i + len(SIG): i + len(SIG) + NAME_LEN]
                    name = tail.split(b"\x00")[0]
                    if ACTOR_RE.match(name):
                        hits.append(name_addr)
                    s = i + 1
            off += n
    return sorted(set(hits))


def read_name(b: CemuMemoryBridge, addr: int) -> str:
    raw = b._read(addr, NAME_LEN) or b""
    return raw.split(b"\x00")[0].decode("ascii", "replace")


def snap(b: CemuMemoryBridge, addr: int) -> bytes:
    return b._read(addr - WIN_BEFORE, WIN_BEFORE + WIN_AFTER) or b""


def changed_words(old: bytes, new: bytes) -> list[dict]:
    out = []
    for off in range(0, min(len(old), len(new)) - 3, 4):
        a = struct.unpack_from(">I", old, off)[0]
        c = struct.unpack_from(">I", new, off)[0]
        if a != c:
            out.append({"off": off - WIN_BEFORE, "old": f"0x{a:08X}", "new": f"0x{c:08X}"})
    return out


def main() -> None:
    b = open_bridge()
    log("Localisation du slot pickup (scan du gros tas)...")
    t0 = time.monotonic()
    cands = locate(b)
    log(f"MEMOIRE TROUVEE : {len(cands)} candidat(s) en {time.monotonic()-t0:.1f}s")
    for a in cands:
        log(f"   0x{a:012X}  nom actuel = {read_name(b, a)!r}")
    if not cands:
        log("Aucun candidat — ramasse d'abord UN objet (le slot n'existe qu'apres un 1er "
            "ramassage), puis relance.")
        return

    try:
        input("\n>>> Va pres des objets, puis Entree pour DEMARRER le scan... ")
    except EOFError:
        log("(pas de stdin interactif — lance ce script dans TON terminal)")
        return

    stop = threading.Event()
    events: list[dict] = []
    baselines = {a: snap(b, a) for a in cands}
    names0 = {a: read_name(b, a) for a in cands}

    def monitor():
        last = dict(baselines)
        period = 1.0 / POLL_HZ
        while not stop.is_set():
            for a in cands:
                cur = snap(b, a)
                if cur and cur != last[a]:
                    events.append({
                        "t": round(time.monotonic() - t0, 3),
                        "addr": f"0x{a:012X}",
                        "name": read_name(b, a),
                        "changed": changed_words(last[a], cur),
                    })
                    last[a] = cur
            time.sleep(period)

    th = threading.Thread(target=monitor, daemon=True)
    th.start()
    log("Scan EN COURS — ramasse ~10 objets varies. Entree pour terminer.")
    try:
        input()
    except EOFError:
        time.sleep(30)
    stop.set()
    th.join(timeout=2)

    # resume : offsets qui ont bouge (hors le nom lui-meme) + sequence de noms
    off_counter: dict[int, int] = {}
    for e in events:
        for w in e["changed"]:
            if not (0 <= w["off"] < NAME_LEN):        # ignore les octets du nom
                off_counter[w["off"]] = off_counter.get(w["off"], 0) + 1
    name_seq = [e["name"] for e in events if e["name"] not in ("", None)]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "candidates": [f"0x{a:012X}" for a in cands],
        "names_baseline": {f"0x{a:012X}": names0[a] for a in cands},
        "n_events": len(events),
        "changed_offsets": dict(sorted(off_counter.items())),
        "name_sequence": name_seq,
        "events": events[:400],
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    log(f"\nTERMINE : {len(events)} changement(s) captures.")
    log(f"  noms vus : {name_seq[:15]}{' ...' if len(name_seq) > 15 else ''}")
    log(f"  offsets (hors nom) qui ont bouge : "
        f"{[f'{o:+#x}' for o in sorted(off_counter)]}")
    log(f"  log complet -> {OUT}")
    log("  Dis a Claude que c'est fini, il lira le fichier.")


if __name__ == "__main__":
    main()
