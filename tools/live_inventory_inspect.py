"""
Live Inventory Inspect — dump les slots "invalides" (0..4, 57+) en hexa pour
voir s'il y a des slots vides exploitables pour injecter un NOUVEL item,
puis (optionnel) teste l'ecriture d'un nouvel item dans le premier slot vide.

PowerShell admin + Cemu in-game :
    python tools/live_inventory_inspect.py
"""
import sys, struct
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge, _ITEM_STRIDE

NEW_ITEM_ID = "Item_Wood"
NEW_QTY = 5


def hexdump(buf: bytes, base: int) -> str:
    lines = []
    for i in range(0, len(buf), 16):
        chunk = buf[i:i+16]
        hexs = " ".join(f"{b:02X}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"  0x{base+i:012X}: {hexs:<48} {asc}")
    return "\n".join(lines)


def main():
    print("=== Live Inventory Inspect ===\n")
    br = CemuMemoryBridge()
    if not br.attach():
        print("ERREUR: admin requis / Cemu introuvable.")
        return

    if not br.has_live_inventory:
        print("Inventaire live non trouve.")
        br.detach()
        return

    print(f"inv_base = 0x{br._inv_base:012X}\n")

    # Dump slots 0..6 et 55..60 en hexa (zone autour de itemAddress = slot_addr+7)
    for slot in list(range(0, 7)) + list(range(55, 61)):
        slot_addr = br._inv_base + slot * _ITEM_STRIDE
        item_addr = slot_addr + 7
        head = br._read(slot_addr, 8)
        valid = CemuMemoryBridge._matches_item_pattern(head)
        raw = br._read(item_addr - 24, 152) or b""
        itemid = raw[24+1:24+1+64].split(b"\x00")[0].decode("ascii", errors="replace")
        print(f"slot {slot:3d}  pattern_valid={valid}  itemID='{itemid}'")
        print(hexdump(raw, item_addr - 24))
        print()

    print("\n--- Test injection nouvel item ---")
    # Cherche un slot avec pattern valide mais itemID vide/invalide dans 0..4
    target_slot = None
    for slot in range(0, 5):
        slot_addr = br._inv_base + slot * _ITEM_STRIDE
        item_addr = slot_addr + 7
        head = br._read(slot_addr, 8)
        if not CemuMemoryBridge._matches_item_pattern(head):
            continue
        raw = br._read(item_addr + 1, 64) or b""
        itemid = raw.split(b"\x00")[0].decode("ascii", errors="replace")
        if itemid == "":
            target_slot = slot
            break

    if target_slot is None:
        print("Aucun slot vide trouve dans 0..4. Pas de test d'injection.")
        br.detach()
        return

    slot_addr = br._inv_base + target_slot * _ITEM_STRIDE
    item_addr = slot_addr + 7
    print(f"\nSlot vide trouve: slot {target_slot}  item_addr=0x{item_addr:012X}")

    # Backup zone large pour pouvoir restaurer
    backup_addr = item_addr - 24
    backup = br._read(backup_addr, 152)
    if backup is None:
        print("Lecture backup echouee, abandon.")
        br.detach()
        return

    # Ecrit le nom de l'item (ascii + null) a itemAddress+1
    name_bytes = NEW_ITEM_ID.encode("ascii") + b"\x00"
    br._write(item_addr + 1, name_bytes)

    # Ecrit la quantite a itemQtDurAddress = itemAddress-19
    br._write(item_addr - 19, struct.pack(">i", NEW_QTY))

    # Equip flag a 0
    br._write(item_addr - 15, b"\x00")

    readback_name = (br._read(item_addr + 1, 64) or b"").split(b"\x00")[0].decode("ascii", errors="replace")
    readback_qty_raw = br._read(item_addr - 19, 4)
    readback_qty = struct.unpack(">i", readback_qty_raw)[0] if readback_qty_raw else None
    print(f"Ecrit '{NEW_ITEM_ID}' qty={NEW_QTY}")
    print(f"Relu: itemID='{readback_name}' qty={readback_qty}")
    print(f"\n>>> Va dans l'inventaire EN JEU (Materiaux), ferme/rouvre, regarde si '{NEW_ITEM_ID}' (Bois) apparait <<<")

    try:
        input("\nENTREE pour restaurer le slot d'origine... ")
    except Exception:
        pass

    br._write(backup_addr, backup)
    restored = br._read(backup_addr, 152)
    print("Restaure:", "OK" if restored == backup else "MISMATCH")

    br.detach()


if __name__ == "__main__":
    main()
