"""
Live Inject Test — confirme que l'inventaire live (trouve par live_inventory.py)
est bien LIVE: ecrit +10 sur un materiau et demande de verifier en jeu instantanement.

PowerShell admin + Cemu in-game :
    python tools/live_inject_test.py
"""
import sys, struct
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge
from live_inventory import find_rupee_address, find_inventory_start_in_region, dump_inventory, ITEM_STRIDE

TARGET_ITEM = "Item_Ore_B"
DELTA = 10


def main():
    print("=== Live Inject Test ===\n")
    br = CemuMemoryBridge()
    if not br.attach():
        print("ERREUR: admin requis / Cemu introuvable.")
        return
    print(f"pid={br._pid}\n")

    rupee_addr = find_rupee_address(br)
    if rupee_addr is None:
        print("rupeesAddress introuvable.")
        br.detach()
        return
    print(f"rupeesAddress = 0x{rupee_addr:012X}")

    region_base, region_size = None, None
    for base, size in br._iter_regions():
        if base <= rupee_addr < base + size:
            region_base, region_size = base, size
            break

    inv_start = find_inventory_start_in_region(br, region_base, region_size)
    if inv_start is None:
        print("inventoryStartAddress introuvable.")
        br.detach()
        return
    print(f"\ninventoryStartAddress = 0x{inv_start:012X}")

    items = dump_inventory(br, inv_start)
    target = next((it for it in items if it[2] == TARGET_ITEM), None)
    if target is None:
        print(f"\n{TARGET_ITEM} introuvable dans l'inventaire actuel.")
        br.detach()
        return

    slot, item_addr, item_id, qtdur, equipped = target
    qtdur_addr = item_addr - 19
    print(f"\n{item_id} (slot {slot}): qtdur actuel = {qtdur}  @ 0x{qtdur_addr:012X}")

    new_val = qtdur + DELTA
    ok = br._write(qtdur_addr, struct.pack(">i", new_val))
    readback_raw = br._read(qtdur_addr, 4)
    readback = struct.unpack(">i", readback_raw)[0] if readback_raw else None
    print(f"Ecrit {new_val} (write_ok={ok}), relu = {readback}")
    print(f"\n>>> Va dans l'inventaire EN JEU (Materiaux) et regarde si '{item_id}' affiche {new_val} <<<")
    print(">>> PAS BESOIN de fermer/rouvrir l'inventaire si c'est vraiment live <<<")

    try:
        input("\nENTREE pour restaurer la valeur d'origine... ")
    except Exception:
        pass

    br._write(qtdur_addr, struct.pack(">i", qtdur))
    readback_raw = br._read(qtdur_addr, 4)
    readback = struct.unpack(">i", readback_raw)[0] if readback_raw else None
    print(f"Restaure a {qtdur}, relu = {readback}")

    br.detach()


if __name__ == "__main__":
    main()
