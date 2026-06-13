"""
TEST decisif : l'icone d'un item suit-elle le champ nom (+0x08) ?

Trouve un item EXISTANT par son nom actuel (adressage stable, pas d'index de slot),
le renomme vers un autre item, et lit le resultat. On regarde ensuite en jeu si l'icone
a change. Aucun nouveau noeud, aucun splice -> isole la question de l'icone.

Usage (PowerShell admin, Cemu en jeu) :
    python tools/live_rename_item.py --from Item_Roast_03 --to Item_Fruit_A          # DRY-RUN
    python tools/live_rename_item.py --from Item_Roast_03 --to Item_Fruit_A --commit
    python tools/live_rename_item.py --restore
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

CEMU_MEM_BASE = 0x247E4440000
STRIDE = _ITEM_STRIDE
OFF_NAME = 0x08
BACKUP = Path(__file__).parents[1] / "tmp" / "rename_backup.bin"
BACKUP_ADDR = Path(__file__).parents[1] / "tmp" / "rename_backup_addr.txt"


def find_node_by_name(bridge, inv, target):
    for slot in range(80):
        a = inv + slot * STRIDE
        node = bridge._read(a, STRIDE)
        if not node:
            break
        if not (node[0] == 0x10 and node[4] == 0 and node[5] == 0 and node[6] == 0 and node[7] == 0x40):
            break
        name = node[8:8+40].split(b"\x00")[0].decode("ascii", "backslashreplace")
        if name == target:
            return a, node
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", default="Item_Roast_03")
    ap.add_argument("--to", dest="dst", default="Item_Fruit_A")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    bridge = CemuMemoryBridge()
    if not bridge.attach() or not bridge.has_live_inventory:
        print("ERREUR attach / inventaire live introuvable.")
        return
    inv = bridge._inv_base

    if args.restore:
        if not BACKUP.exists() or not BACKUP_ADDR.exists():
            print("Pas de backup a restaurer.")
            return
        addr = int(BACKUP_ADDR.read_text().strip(), 16)
        data = BACKUP.read_bytes()
        ok = bridge._write(addr, data)
        print(f"Restauration @0x{addr:012X} {'OK' if ok else 'ECHEC'} ({len(data)} octets).")
        return

    a, node = find_node_by_name(bridge, inv, args.src)
    if a is None:
        print(f"Item source {args.src!r} introuvable en inventaire.")
        return
    a_g = a - CEMU_MEM_BASE
    print(f"Item {args.src!r} trouve @ host=0x{a:012X} guest=0x{a_g:08X}")
    print(f"  renommage prevu: {args.src!r} -> {args.dst!r}")

    if not args.commit:
        print("\n  (DRY-RUN — rien ecrit. Ajoute --commit pour appliquer.)")
        return

    # backup
    full = bridge._read(a, STRIDE)
    BACKUP.parent.mkdir(exist_ok=True)
    BACKUP.write_bytes(full)
    BACKUP_ADDR.write_text(f"0x{a:012X}")
    print(f"  Backup -> {BACKUP} (@0x{a:012X})")

    name_bytes = args.dst.encode("ascii")[:63]
    name_bytes = name_bytes + b"\x00" * (64 - len(name_bytes))   # remplit tout le buffer 64o
    ok = bridge._write(a + OFF_NAME, name_bytes)
    print(f"  Ecriture nom: {ok}")
    print("  -> Ouvre/ferme l'inventaire (onglet Ingredients) et regarde l'icone de cet item.")
    print("  -> Annuler: python tools/live_rename_item.py --restore")


if __name__ == "__main__":
    main()
