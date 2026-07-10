"""
hunt_wallet — trouve le VRAI portefeuille de rubis (pas le miroir réécrit par le jeu).

Méthode = change-detection (comme la chasse au HP) : on scanne toutes les adresses u32
qui valent le compteur de rubis AFFICHÉ, le joueur fait varier ses rubis, on RE-scanne et
on INTERSECTE. En 2–3 passes il reste une poignée de candidats. On VÉRIFIE ensuite en
écrivant une valeur test : la bonne adresse fait changer l'affichage ET PERSISTE (le miroir,
lui, est réécrit → revient à l'ancienne valeur).

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
