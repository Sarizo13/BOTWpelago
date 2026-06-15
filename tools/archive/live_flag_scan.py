"""
Live Flag Scan — recherche cible des hash CRC32 de flags GameData connus
(gate_items.json) dans la memoire live de Cemu, pour determiner si la table
GameDataMgr lue par l'EventFlow est trouvable/ecrivable en live (sans reload),
par opposition au buffer gd_base (copie de save, non-live, deja localise).

Pour chaque hash connu, on cherche les occurrences en u32 big-endian ET
little-endian dans tout le tas, on affiche le contexte (16 octets avant/apres)
et on tente d'interpreter une "valeur" adjacente (format save: u32be id, u32be
valeur consecutifs).

Les hits dans la plage [gd_base, gd_base + ~1.1MB) sont annotes "(gd_base copy)"
— ce sont la copie de save deja connue, PAS la cible.

PowerShell admin + Cemu in-game :
    python tools/live_flag_scan.py
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge

# (nom, flag_name, hash_be_hex)
KNOWN_FLAGS = [
    ("Paraglider",          "IsGet_PlayerStole2",      0xFE4D1501),
    ("Magnesis Rune",       "IsGet_Obj_Magnetglove",   0x795E7BBC),
    ("Stasis Rune",         "IsGet_Obj_StopTimer",     0x7504085D),
    ("Cryonis Rune",        "IsGet_Obj_IceMaker",      0x5992B256),
    ("Remote Bomb Rune",    "IsGet_Obj_RemoteBomb",    0x191BCCF9),
    ("Camera Rune",         "IsGet_Obj_Camera",        0xF7DD3E03),
    ("Master Sword",        "Get_MasterSword_Finish",  0x15AD023F),
    ("Revali's Gale",       "IsGet_Obj_HeroSoul_Rito", 0x7DBA0908),
    ("Daruk's Protection",  "IsGet_Obj_HeroSoul_Goron",0xFF48AA75),
    ("Mipha's Grace",       "IsGet_Obj_HeroSoul_Zora", 0x0D61D7D4),
    ("Urbosa's Fury",       "IsGet_Obj_HeroSoul_Gerudo",0x8E7188D0),
    ("DungeonClearCounter", "DungeonClearCounter",     0xE605CE62),
]

# Marge generosa pour la copie save en memoire (12 + ~140k entrees * 8 octets)
_GD_BASE_SPAN = 12 + 140_000 * 8

_SCAN_CHUNK = 16 * 1024 * 1024


def hexdump(buf: bytes, base: int) -> str:
    lines = []
    for i in range(0, len(buf), 16):
        chunk = buf[i:i + 16]
        hexs = " ".join(f"{b:02X}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"    0x{base + i:012X}: {hexs:<48} {asc}")
    return "\n".join(lines)


def main():
    print("=== Live Flag Scan ===\n")
    br = CemuMemoryBridge()
    if not br.attach():
        print("ERREUR: admin requis / Cemu introuvable.")
        return

    gd_base = br._gd_base
    print(f"gd_base = 0x{gd_base:012X}  (copie save connue, exclue/annotee)\n")
    if br.has_live_inventory:
        print(f"inv_base = 0x{br._inv_base:012X}\n")

    try:
        import numpy as np
    except ImportError:
        print("ERREUR: numpy requis.")
        br.detach()
        return

    needles = []
    for name, flag_name, h in KNOWN_FLAGS:
        needles.append((name, flag_name, h, struct.pack(">I", h), struct.pack("<I", h)))

    # On limite le scan aux regions contenant gd_base et inv_base (sinon: heures).
    targets = [gd_base]
    if br.has_live_inventory:
        targets.append(br._inv_base)

    regions: list[tuple[int, int]] = []
    for addr in targets:
        for base, size in br._iter_regions():
            if base <= addr < base + size and (base, size) not in regions:
                regions.append((base, size))
                break

    for base, size in regions:
        print(f"-- Region 0x{base:012X} .. 0x{base + size:012X}  ({size / (1024 * 1024):.1f} MiB) --\n")

    total_hits = 0
    for base, size in regions:
        if size < 4:
            continue
        off = 0
        while off < size:
            n = min(_SCAN_CHUNK, size - off)
            read_n = min(n + 3, size - off)
            chunk = br._read(base + off, read_n)
            if not chunk:
                off += n
                continue
            buf = np.frombuffer(chunk, dtype=np.uint8)
            for name, flag_name, h, be_bytes, le_bytes in needles:
                for endian, needle in (("BE", be_bytes), ("LE", le_bytes)):
                    n0 = needle[0]
                    positions = np.where(buf[:len(chunk) - 3] == n0)[0]
                    for p in positions:
                        if bytes(chunk[p:p + 4]) != needle:
                            continue
                        addr = base + off + int(p)
                        total_hits += 1
                        in_gd = gd_base <= addr < gd_base + _GD_BASE_SPAN
                        tag = " (gd_base copy)" if in_gd else "  <-- HORS gd_base !"
                        print(f"[{name}] {flag_name}  hash={h:#010x}  {endian}"
                              f"  @ 0x{addr:012X}{tag}")
                        ctx = br._read(max(0, addr - 16), 36) or b""
                        print(hexdump(ctx, max(0, addr - 16)))
                        # interpretation "valeur adjacente" style save (id u32be, val u32be)
                        val_be = br._read(addr + 4, 4)
                        if val_be:
                            v = struct.unpack(">I", val_be)[0]
                            print(f"      -> next u32be (valeur potentielle) = {v}")
                        print()
            off += n

    print(f"\nTotal hits: {total_hits}")
    br.detach()


if __name__ == "__main__":
    main()
