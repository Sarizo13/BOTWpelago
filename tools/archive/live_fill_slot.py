"""
TEST approche A (insertion live d'un nouvel item) — version MINIMALE et SURE.

Le slot 4 du tableau PouchItem est un noeud VALIDE et DEJA CHAINE dans la liste active,
mais vide (nom='', type=0xFFFFFFFF, valeur=0). On le remplit avec l'identite d'un item
(par defaut une pomme Item_Fruit_A : type=7, subtype=8, valeur=1) SANS toucher aux
pointeurs de liste. Aucun splice, aucune copie, aucun re-basing -> risque minimal.

Si l'item apparait en jeu (ouvrir/fermer l'inventaire pour redraw), l'approche A est
validee et on pourra faire l'insertion complete (depuis le pool libre) en production.

Usage (PowerShell admin, Cemu en jeu) :
    python tools/live_fill_slot.py                 # DRY-RUN (n'ecrit rien)
    python tools/live_fill_slot.py --commit        # ecrit (backup auto du slot avant)
    python tools/live_fill_slot.py --restore        # restaure le backup
    options : --slot N  --name Item_Xxx  --type T  --subtype S  --value V
"""
import sys
import struct
import argparse
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge, _ITEM_STRIDE

OFF_NAME = 0x08
OFF_TYPE = 0x20C
OFF_SUB  = 0x210
OFF_VAL  = 0x214
BACKUP = Path(__file__).parents[1] / "tmp" / "slot_backup.bin"


def name_at(bridge, h):
    raw = bridge._read(h + OFF_NAME, 64) or b""
    return raw.split(b"\x00")[0].decode("ascii", errors="backslashreplace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, default=4)
    ap.add_argument("--name", default="Item_Fruit_A")
    ap.add_argument("--type", type=int, default=7)
    ap.add_argument("--subtype", type=int, default=8)
    ap.add_argument("--value", type=int, default=1)
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    bridge = CemuMemoryBridge()
    if not bridge.attach() or not bridge.has_live_inventory:
        print("ERREUR attach / inventaire live introuvable.")
        return
    inv = bridge._inv_base
    node = inv + args.slot * _ITEM_STRIDE
    print(f"inv_base=0x{inv:012X}  slot {args.slot} node=0x{node:012X}")

    if args.restore:
        if not BACKUP.exists():
            print("Pas de backup a restaurer.")
            return
        data = BACKUP.read_bytes()
        ok = bridge._write(node, data)
        print(f"Restauration {'OK' if ok else 'ECHEC'} ({len(data)} octets).")
        return

    # etat actuel
    cur_name = name_at(bridge, node)
    cur = bridge._read(node + 0x200, 0x20) or b""
    ints = [struct.unpack_from(">I", cur, i)[0] for i in range(0, len(cur), 4)]
    print(f"  actuel: name={cur_name!r} type=0x{ints[3]:08X} sub=0x{ints[4]:08X} val=0x{ints[5]:08X}")

    if cur_name and not args.restore:
        print(f"  ATTENTION: slot {args.slot} n'est PAS vide (name={cur_name!r}). "
              f"Choisis un slot vide avec --slot, ou abandonne.")
        if args.commit:
            print("  Commit annule par securite.")
            return

    # writes prevus
    name_bytes = args.name.encode("ascii")[:63] + b"\x00"
    print("\n  ECRITURES PREVUES:")
    print(f"    +0x{OFF_NAME:03X} name  = {args.name!r}  ({len(name_bytes)} octets)")
    print(f"    +0x{OFF_TYPE:03X} type  = {args.type}")
    print(f"    +0x{OFF_SUB:03X} sub   = {args.subtype}")
    print(f"    +0x{OFF_VAL:03X} value = {args.value}")

    if not args.commit:
        print("\n  (DRY-RUN — rien ecrit. Relance avec --commit pour appliquer.)")
        return

    # backup du noeud entier avant ecriture
    full = bridge._read(node, _ITEM_STRIDE)
    if full:
        BACKUP.parent.mkdir(exist_ok=True)
        BACKUP.write_bytes(full)
        print(f"\n  Backup du slot -> {BACKUP} ({len(full)} octets)")

    oks = []
    oks.append(bridge._write(node + OFF_NAME, name_bytes))
    oks.append(bridge._write(node + OFF_TYPE, struct.pack(">i", args.type)))
    oks.append(bridge._write(node + OFF_SUB,  struct.pack(">i", args.subtype)))
    oks.append(bridge._write(node + OFF_VAL,  struct.pack(">i", args.value)))
    print(f"  Ecritures: {oks}")
    print("  -> Ouvre/ferme l'inventaire en jeu pour forcer le redraw.")
    print("  -> Pour annuler: python tools/live_fill_slot.py --restore")


if __name__ == "__main__":
    main()
