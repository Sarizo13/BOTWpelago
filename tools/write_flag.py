"""
write_flag — lit/écrit un flag GameData EN LIVE (Cemu attaché) via le bridge du client.

Usage :
    python tools/write_flag.py <FlagName>            # lecture
    python tools/write_flag.py <FlagName> <valeur>   # écriture (puis relecture)

Sert notamment à l'EXPÉRIENCE POPUP (mod/patches/zone_gate.py §POPUP_TEST) :
    python tools/write_flag.py TestQuest_kwz001_Extermination 1
→ debout au relais du Pied-de-Mont : si la couche map poll les flags, le popup natif
  « pomme obtenue » part immédiatement et le flag est réarmé (FlagOFF) par l'event.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from BotWClient.memory_injector import CemuMemoryBridge  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    flag = sys.argv[1]
    b = CemuMemoryBridge()
    if not b.attach():
        print("ERREUR: Cemu/BotW non attaché.")
        return
    cur = b.read_flag(flag)
    print(f"{flag} = {cur}")
    if len(sys.argv) >= 3:
        val = int(sys.argv[2])
        ok = b.write_flag(flag, val)
        print(f"write {val}: {'OK' if ok else 'ÉCHEC'} ; relecture = {b.read_flag(flag)}")


if __name__ == "__main__":
    main()
