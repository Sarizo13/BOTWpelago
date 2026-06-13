"""Verifie cemu_mem_base en lisant plusieurs adresses .rodata predites et en
comparant leur contenu aux chaines attendues."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge

CEMU_MEM_BASE = 0x0247E446B7A8

CHECKS = [
    (0x101ccf30, b"IsGet_Obj_Magnetglove"),
    (0x101c9126, b"PutRupee_Gold"),
    (0x101c8724, b"DungeonClearCounter"),
]


def main():
    bridge = CemuMemoryBridge()
    if not bridge.attach():
        print("ERREUR: admin requis / Cemu introuvable.")
        return

    for wiiu_addr, expected in CHECKS:
        host = CEMU_MEM_BASE + wiiu_addr
        data = bridge._read(host, len(expected) + 4)
        print(f"WiiU 0x{wiiu_addr:08X} -> host 0x{host:012X}: {data!r} (expected starts {expected!r})")

    bridge.detach()


if __name__ == "__main__":
    main()
