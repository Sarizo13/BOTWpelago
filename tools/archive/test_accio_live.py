"""
Test Accio Live — calibre la traduction adresse-WiiU -> adresse-hote Cemu, puis
ecrit dans le "mailbox" du cheat communautaire "Accio" (m-byte918/BotW-Cheat-Codes)
pour tester si Cemu utilise un mapping memoire plat (host = base + adresse_WiiU).

Etape 1 (calibration) : on cherche dans la memoire de Cemu la chaine ASCII
"HorseCustom_ShopSaddleName", connue pour etre dans .rodata de U-King.rpx a
l'offset 0x1d2734 (= adresse WiiU 0x10000000 + 0x1d2734 = 0x101d2734).
Si trouvee a l'adresse hote H, alors:
    cemu_mem_base = H - 0x101d2734
    accio_name_addr = cemu_mem_base + 0x10024060   (ASCII item/actor name)
    accio_qty_addr  = cemu_mem_base + 0x10024038   (quantite)

Etape 2 (optionnelle, --write) : ecrit "PutRupee_Gold" + qty dans ces adresses.
Necessite que le "Master Code" Accio soit actif dans Cemu (cheats.txt) pour que
le spawn se produise reellement.

Usage (PowerShell admin, Cemu en jeu) :
    python tools/test_accio_live.py                # calibration seule
    python tools/test_accio_live.py --write        # + ecrit PutRupee_Gold x1
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge

SIG = b"HorseCustom_ShopSaddleName"
SIG_OFFSET = 0x1D2734
SIG_WIIU_ADDR = 0x10000000 + SIG_OFFSET

ACCIO_NAME_ADDR = 0x10024060
ACCIO_QTY_ADDR = 0x10024038


def find_signature(bridge: CemuMemoryBridge, sig: bytes) -> int | None:
    chunk_size = 32 * 1024 * 1024
    overlap = len(sig) - 1
    for base, size in bridge._iter_regions():
        if size < len(sig):
            continue
        off = 0
        while off < size:
            n = min(chunk_size, size - off)
            read_n = min(n + overlap, size - off)
            chunk = bridge._read(base + off, read_n)
            if chunk:
                idx = chunk.find(sig)
                if idx >= 0:
                    return base + off + idx
            off += n
    return None


def main():
    write_mode = "--write" in sys.argv

    print("=== Test Accio Live ===\n")
    print(f"Signature: {SIG!r}")
    print(f"Adresse WiiU attendue de la signature: 0x{SIG_WIIU_ADDR:08X}\n")

    bridge = CemuMemoryBridge()
    if not bridge.attach():
        print("ERREUR: admin requis / Cemu introuvable.")
        return

    print("Recherche de la signature dans la memoire de Cemu...")
    host_addr = find_signature(bridge, SIG)
    if host_addr is None:
        print("INTROUVABLE -> calibration impossible.")
        bridge.detach()
        return

    print(f"Trouvee a l'adresse hote: 0x{host_addr:012X}")
    cemu_mem_base = host_addr - SIG_WIIU_ADDR
    print(f"cemu_mem_base = 0x{cemu_mem_base:012X}\n")

    name_addr = cemu_mem_base + ACCIO_NAME_ADDR
    qty_addr = cemu_mem_base + ACCIO_QTY_ADDR
    print(f"Accio name addr (host) = 0x{name_addr:012X}  (WiiU 0x{ACCIO_NAME_ADDR:08X})")
    print(f"Accio qty  addr (host) = 0x{qty_addr:012X}  (WiiU 0x{ACCIO_QTY_ADDR:08X})")

    # Sanity: ces deux adresses doivent etre lisibles
    cur_name = bridge._read(name_addr, 32)
    cur_qty = bridge._read(qty_addr, 4)
    print(f"\nContenu actuel name (32 bytes): {cur_name!r}")
    print(f"Contenu actuel qty  (4 bytes):  {cur_qty!r}")

    if write_mode:
        print("\n--write: ecriture de 'PutRupee_Gold' + qty=1...")
        name_bytes = b"PutRupee_Gold\x00"
        padded = name_bytes + b"\x00" * (32 - len(name_bytes))
        ok1 = bridge._write(name_addr, padded)
        ok2 = bridge._write(qty_addr, struct.pack(">I", 1))
        print(f"write name -> {ok1}, write qty -> {ok2}")
        print("\n--> Observe le jeu MAINTENANT (le Master Code Accio doit etre actif).")
    else:
        print("\nCalibration terminee. Relance avec --write pour tester le spawn")
        print("(necessite le Master Code Accio actif dans Cemu).")

    bridge.detach()


if __name__ == "__main__":
    main()
