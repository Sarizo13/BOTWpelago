"""
hunt_wallet -- trouve le VRAI portefeuille de rubis (pas le miroir réécrit par le jeu).

Méthode = change-detection (comme la chasse au HP) : on scanne toutes les adresses u32
qui valent le compteur de rubis AFFICHÉ, le joueur fait varier ses rubis, on RE-scanne et
on INTERSECTE. En 2–3 passes il reste une poignée de candidats. On VÉRIFIE ensuite en
écrivant une valeur test : la bonne adresse fait changer l'affichage ET PERSISTE (le miroir,
lui, est réécrit -> revient à l'ancienne valeur).

Session live (Cemu + BotW + save chargée), à CHAQUE étape donne la valeur AFFICHÉE à l'écran :
    python tools/hunt_wallet.py snap 120        # 1re capture (120 rubis à l'écran)
    #   -> dépense/gagne des rubis en jeu (marchand, vendre un item…)
    python tools/hunt_wallet.py narrow 87        # intersecte avec les adresses = 87
    #   -> refais varier, re-narrow autant que nécessaire (jusqu'à ~1–20 candidats)
    python tools/hunt_wallet.py verify 87 500    # écrit 500 dans chaque candidat, liste-les
    #   -> en jeu : ouvre le menu ; le candidat qui affiche 500 ET LE GARDE = le portefeuille
    python tools/hunt_wallet.py write <addr> 999 # confirme un candidat précis
Les candidats sont stockés dans ~/.botwpelago/wallet_hunt.json entre les passes.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from BotWClient.memory_injector import CemuMemoryBridge  # noqa: E402

STATE = Path.home() / ".botwpelago" / "wallet_hunt.json"
CHUNK = 16 * 1024 * 1024


def _bridge() -> CemuMemoryBridge:
    b = CemuMemoryBridge()
    if not b.attach():
        print("ERREUR: Cemu/BotW non attaché.")
        sys.exit(1)
    return b


def _scan_value(b: CemuMemoryBridge, value: int, restrict: list[int] | None = None) -> list[int]:
    needle = struct.pack(">i", value)
    hits: list[int] = []
    if restrict is not None:
        for addr in restrict:
            r = b._read(addr, 4)
            if r == needle:
                hits.append(addr)
        return hits
    for base, size in b._iter_regions():
        addr, end = base, base + size
        while addr < end:
            n = min(CHUNK, end - addr)
            chunk = b._read(addr, n)
            if chunk:
                start = 0
                while True:
                    i = chunk.find(needle, start)
                    if i < 0:
                        break
                    if (i & 3) == 0:                # aligné sur 4 (les compteurs le sont)
                        hits.append(addr + i)
                    start = i + 1
            addr += n
    return hits


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    b = _bridge()

    if cmd == "snap":
        value = int(sys.argv[2])
        hits = _scan_value(b, value)
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(hits), encoding="utf-8")
        print(f"snap {value} : {len(hits)} adresses. Fais varier les rubis puis 'narrow'.")

    elif cmd == "narrow":
        value = int(sys.argv[2])
        prev = json.loads(STATE.read_text(encoding="utf-8"))
        hits = _scan_value(b, value, restrict=prev)
        STATE.write_text(json.dumps(hits), encoding="utf-8")
        print(f"narrow {value} : {len(hits)} candidat(s) restant(s).")
        if len(hits) <= 25:
            for a in hits:
                print(f"  0x{a:012X}")

    elif cmd == "verify":
        old, test = int(sys.argv[2]), int(sys.argv[3])
        cands = json.loads(STATE.read_text(encoding="utf-8"))
        print(f"écriture de {test} dans {len(cands)} candidat(s) (ancien={old}) :")
        for a in cands:
            cur = b._read(a, 4)
            curv = struct.unpack(">i", cur)[0] if cur else None
            b._write(a, struct.pack(">i", test))
            print(f"  0x{a:012X}  était {curv} -> {test}")
        print("En jeu : ouvre le menu. Le candidat qui affiche "
              f"{test} ET LE GARDE = le portefeuille. Confirme avec 'write <addr> <val>'.")

    elif cmd == "probe":
        # écrit une valeur DISTINCTE dans chaque candidat, attend, relit : le VRAI
        # portefeuille garde sa valeur ; un miroir est réécrit par le jeu (revient).
        import time
        cands = json.loads(STATE.read_text(encoding="utf-8"))
        marks = [70001 + i * 1111 for i in range(len(cands))]
        for a, m in zip(cands, marks):
            b._write(a, struct.pack(">i", m))
        print(f"écrit {marks} ; attente 2 s…")
        time.sleep(2.0)
        survivors = []
        for a, m in zip(cands, marks):
            r = b._read(a, 4)
            v = struct.unpack(">i", r)[0] if r else None
            kept = (v == m)
            if kept:
                survivors.append(a)
            print(f"  0x{a:012X}  écrit {m} -> relu {v}  {'GARDÉ' if kept else 'réécrit (miroir)'}")
        if len(survivors) == 1:
            print(f"\n>>> PORTEFEUILLE = 0x{survivors[0]:012X}  (unique survivant)")
        else:
            print(f"\n{len(survivors)} survivant(s) -- regarde AUSSI l'écran : celui dont la "
                  "valeur s'affiche est celui que l'UI lit. Refais 'probe' si besoin.")

    elif cmd == "context":
        # dump 0x40 avant / 0x20 après une adresse : cherche une structure PouchItem
        # (le vrai portefeuille pourrait être le value +0x14 d'un nœud "Money") pour
        # trouver un localisateur STABLE au lieu de scanner une valeur volatile.
        addr = int(sys.argv[2], 0)
        blob = b.read_flag  # noqa (garde l'attache)
        before = b._read(addr - 0x40, 0x64) or b""
        print(f"contexte de 0x{addr:012X} (-0x40 .. +0x24) :")
        for i in range(0, len(before), 16):
            row = before[i:i + 16]
            rel = i - 0x40
            hexs = " ".join(f"{x:02X}" for x in row)
            asci = "".join(chr(x) if 32 <= x < 127 else "." for x in row)
            mark = "  <== addr" if rel <= 0 < rel + 16 else ""
            print(f"  {rel:+04X}: {hexs}  {asci}{mark}")
        # cherche un nom ASCII lisible (type Item_/Obj_/Money) dans une fenêtre plus large
        wide = b._read(addr - 0x200, 0x240) or b""
        import re as _re
        for m in _re.finditer(rb"[A-Za-z_][A-Za-z0-9_]{3,31}", wide):
            s = m.group().decode()
            if any(k in s for k in ("Money", "Rupee", "Item_", "Obj_", "PorchMoney")):
                print(f"  nom proche @ off -0x{0x200 - m.start():X} : {s!r}")

    elif cmd == "write":
        addr, val = int(sys.argv[2], 0), int(sys.argv[3])
        cur = b._read(addr, 4)
        b._write(addr, struct.pack(">i", val))
        print(f"0x{addr:012X}: {struct.unpack('>i', cur)[0] if cur else '?'} -> {val}")

    else:
        print(f"commande inconnue: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
