"""
Live Inventory Scan — localise le tableau PouchItem live (544 bytes/slot)
autour de rupeesAddress, et dump l'inventaire courant pour valider le layout
extrait de botw_editor (itemdata.cs).

PowerShell admin + Cemu in-game :
    python tools/live_inventory.py
"""
import sys, struct, time, zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import numpy as np
from BotWClient.memory_injector import CemuMemoryBridge

ITEM_STRIDE = 544
ITEM_PATTERN = [16, -1, -1, -1, 0, 0, 0, 64]  # 10 ?? ?? ?? 00 00 00 40

# Pattern porté depuis findRupeesAddressInMemory (App.cs ~3737)
RUPEE_PATTERN = [16, -1, -1, -1, 1, 7, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 15, 66, 63]


def crc32(name): return zlib.crc32(name.encode("ascii")) & 0xFFFFFFFF


def find_rupee_address(br):
    pattern = RUPEE_PATTERN
    plen = len(pattern)
    fixed = [(i, b) for i, b in enumerate(pattern) if b != -1]
    idx0, val0 = fixed[0]

    regions = [(b, s) for b, s in br._iter_regions() if s >= plen]
    total = sum(s for _, s in regions)
    print(f"Recherche rupeesAddress sur {len(regions)} regions, {total // (1024*1024)}MB...")

    CHUNK = 16 * 1024 * 1024
    done = 0
    for base, size in regions:
        off = 0
        while off < size:
            n = min(CHUNK, size - off)
            read_n = min(n + plen - 1, size - off)
            chunk = br._read(base + off, read_n)
            if chunk:
                arr = np.frombuffer(chunk, dtype=np.uint8)
                cands = np.where(arr == val0)[0]
                for c in cands:
                    pos = int(c) - idx0
                    if pos < 0 or pos + plen > len(arr):
                        continue
                    if all(arr[pos + i] == b for i, b in fixed):
                        return base + off + pos + plen
            off += n
            done += n
            print(f"\r  {100*done//total}%", end="", flush=True)
    print()
    return None


def matches_item_pattern(buf):
    """buf doit contenir au moins 8 bytes. Verifie le pattern 10 ?? ?? ?? 00 00 00 40."""
    if not buf or len(buf) < 8:
        return False
    return (buf[0] == 16 and buf[4] == 0 and buf[5] == 0 and buf[6] == 0 and buf[7] == 64)


ITEM_PREFIXES = ("Item_", "Weapon_", "Armor_", "Animal_", "Obj_", "Material_")

EARLY_EXIT_SCORE = 5


def score_candidate(br, addr, n_slots=10):
    """Compte combien des n_slots premiers items ont un itemID reconnu."""
    score = 0
    for slot in range(n_slots):
        a = addr + slot * ITEM_STRIDE
        head = br._read(a, 8)
        if not matches_item_pattern(head):
            return score
        item_addr = a + 7
        raw = br._read(item_addr + 1, 64) or b""
        item_id = raw.split(b"\x00")[0].decode("ascii", errors="replace")
        if item_id.startswith(ITEM_PREFIXES) or item_id.endswith("Arrow"):
            score += 1
    return score


def find_inventory_start_in_region(br, region_base, region_size):
    """Scanne toute la region pour le pattern item, valide par stride 544, avec
    scoring et early-exit dès qu'un candidat ressemble vraiment a un inventaire."""
    print(f"\nScan inventaire sur la region: 0x{region_base:012X} .. +{region_size//(1024*1024)}MB")

    CHUNK = 16 * 1024 * 1024
    off = 0
    t0 = time.time()
    n_candidates = 0
    best, best_score = None, -1
    while off < region_size:
        n = min(CHUNK, region_size - off)
        read_n = min(n + ITEM_STRIDE + 8, region_size - off)
        chunk = br._read(region_base + off, read_n)
        if chunk:
            arr = np.frombuffer(chunk, dtype=np.uint8)
            cands = np.where(arr == 16)[0]
            for c in cands:
                pos = int(c)
                if pos + 8 > len(arr):
                    continue
                if not (arr[pos+4] == 0 and arr[pos+5] == 0 and arr[pos+6] == 0 and arr[pos+7] == 64):
                    continue
                if pos + ITEM_STRIDE + 8 > len(arr):
                    continue
                p2 = pos + ITEM_STRIDE
                if not (arr[p2] == 16 and arr[p2+4] == 0 and arr[p2+5] == 0 and arr[p2+6] == 0 and arr[p2+7] == 64):
                    continue
                addr = region_base + off + pos
                n_candidates += 1
                s = score_candidate(br, addr)
                if s > best_score:
                    best, best_score = addr, s
                    print(f"\n  candidat 0x{addr:012X}  score={s}")
                    if s >= EARLY_EXIT_SCORE:
                        print(f"\n  [FOUND] inventoryStartAddress = 0x{best:012X}  score={best_score}")
                        return best
        off += n
        elapsed = time.time() - t0
        print(f"\r  {100*off//region_size}%  {elapsed:.0f}s  candidats={n_candidates}  best_score={best_score}", end="", flush=True)
    print()
    if best is None or best_score <= 0:
        print("\nAucun candidat ne ressemble a un inventaire.")
        return None
    print(f"\n  [FOUND] inventoryStartAddress = 0x{best:012X}  score={best_score}")
    return best


def is_valid_item_id(s: str) -> bool:
    if not s or len(s) < 3:
        return False
    return s.replace("_", "").isalnum() and s[0].isalpha()


def dump_inventory(br, start_addr, max_slots=420):
    items = []
    for slot in range(max_slots):
        addr = start_addr + slot * ITEM_STRIDE
        head = br._read(addr, 8)
        if not matches_item_pattern(head):
            print(f"  slot {slot}: pattern invalide a 0x{addr:012X} — arret")
            break
        item_addr = addr + 7
        raw = br._read(item_addr + 1, 64) or b""
        item_id = raw.split(b"\x00")[0].decode("ascii", errors="replace")
        qtdur_raw = br._read(item_addr - 19, 4)
        qtdur = struct.unpack(">i", qtdur_raw)[0] if qtdur_raw else None
        equip_raw = br._read(item_addr - 15, 1)
        equipped = equip_raw[0] if equip_raw else None
        if is_valid_item_id(item_id):
            items.append((slot, item_addr, item_id, qtdur, equipped))
    return items


def main():
    print("=== Live Inventory Scan ===\n")
    br = CemuMemoryBridge()
    if not br.attach():
        print("ERREUR: admin requis / Cemu introuvable.")
        return
    print(f"pid={br._pid}  gd_base=0x{br._gd_base:012X}\n")

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
    if region_base is None:
        print("Region contenant rupeesAddress introuvable.")
        br.detach()
        return
    print(f"Region: 0x{region_base:012X} .. 0x{region_base+region_size:012X} ({region_size // (1024*1024)}MB)")

    inv_start = find_inventory_start_in_region(br, region_base, region_size)
    if inv_start is None:
        print("\ninventoryStartAddress introuvable dans la region.")
        br.detach()
        return

    print(f"\ninventoryStartAddress = 0x{inv_start:012X}  (diff avec rupees = 0x{inv_start - rupee_addr:X})")

    items = dump_inventory(br, inv_start)
    print(f"\n{len(items)} item(s) valides:\n")
    for slot, item_addr, item_id, qtdur, equipped in items:
        print(f"  slot {slot:3d}  addr=0x{item_addr:012X}  qtdur={qtdur:6}  equipped={equipped}  {item_id}")

    br.detach()


if __name__ == "__main__":
    main()
