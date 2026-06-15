"""
Verifie le contenu actuel des adresses mailbox Accio (0x10024060 / 0x10024038)
avec la base de calibration verifiee (v208) : cemu_mem_base = 0x247E4440000.

Lecture seule - aucune ecriture.

Usage (PowerShell admin, Cemu en jeu) :
    python tools/check_accio_mailbox.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge

CEMU_MEM_BASE = 0x247E4440000
ACCIO_NAME_VADDR = 0x10024060
ACCIO_QTY_VADDR = 0x10024038


def main():
    bridge = CemuMemoryBridge()
    if not bridge.attach():
        print("ERREUR: admin requis / Cemu introuvable / game_data introuvable.")
        return

    print(f"gd_base = 0x{bridge._gd_base:012X}")

    name_addr = CEMU_MEM_BASE + ACCIO_NAME_VADDR
    qty_addr = CEMU_MEM_BASE + ACCIO_QTY_VADDR

    name_data = bridge._read(name_addr, 64)
    qty_data = bridge._read(qty_addr, 8)

    print(f"\nName mailbox @ 0x{name_addr:012X} (vaddr 0x{ACCIO_NAME_VADDR:08X}):")
    print(f"  raw: {name_data!r}")
    print(f"\nQty mailbox  @ 0x{qty_addr:012X} (vaddr 0x{ACCIO_QTY_VADDR:08X}):")
    print(f"  raw: {qty_data!r}")

    # Sanity re-verification of the calibration with one more known string
    sanity_vaddr = 0x101F1F88  # DungeonClearCounter
    sanity_addr = CEMU_MEM_BASE + sanity_vaddr
    sanity_data = bridge._read(sanity_addr, 19)
    print(f"\nSanity check (DungeonClearCounter) @ 0x{sanity_addr:012X}:")
    print(f"  raw: {sanity_data!r}")


if __name__ == "__main__":
    main()
