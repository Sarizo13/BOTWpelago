"""
Live Scan — localise rupeesAddress (AOB pattern porté depuis Cemu BotW Editor),
vérifie l'hypothèse "persist = live - 4704656", puis scanne le bool array
autour de ces deux ancres (fenêtre étroite, rapide).

PowerShell admin + Cemu in-game :
    python tools/live_scan.py
"""
import sys, struct, time, zlib, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import oead
import numpy as np
from BotWClient.memory_injector import CemuMemoryBridge
from BotWClient.save_parser import parse as parse_save
from BotWClient.providers.save_file import _current_save_in_slot

BOOTUP = Path(r"D:\Emulateur\Jeux Wiiu\Base Games\The Legend of Zelda Breath of the Wild [ALZP01]\content\Pack\Bootup.pack")
SLOT   = Path(r"D:\Emulateur\Cemu\cemu_1.18.1\mlc01\usr\save\00050000\101c9500\user\80000002")

PERSIST_OFFSET = 4704656

# Pattern porté depuis findRupeesAddressInMemory (App.cs ~3737)
# -1 = wildcard. rupeesAddress = match_pos + len(pattern)
RUPEE_PATTERN = [16, -1, -1, -1, 1, 7, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 15, 66, 63]

KNOWN_FLAGS = (
    ["IsGet_PlayerStole2", "IsGet_Obj_Magnetglove", "IsGet_Obj_RemoteBomb",
     "IsGet_Obj_StopTimer", "IsGet_Obj_IceMaker", "IsGet_Obj_Camera",
     "IsGet_NormalArrow", "IsGet_Obj_HeroSoul_Rito", "IsGet_Obj_HeroSoul_Goron",
     "IsGet_Obj_HeroSoul_Zora", "IsGet_Obj_HeroSoul_Gerudo", "Get_MasterSword_Finish"]
    + [f"Clear_Dungeon{n:03d}" for n in range(120)]
)


def crc32(name): return zlib.crc32(name.encode("ascii")) & 0xFFFFFFFF
def to_signed(u): return struct.unpack(">i", struct.pack(">I", u))[0]


def load_data_index():
    bootup = oead.Sarc(BOOTUP.read_bytes())
    raw = bytes(next(f for f in bootup.get_files() if f.name == "GameData/gamedata.ssarc").data)
    if raw[:4] == b"Yaz0": raw = bytes(oead.yaz0.decompress(raw))
    gd_sarc = oead.Sarc(raw)
    flags = []
    for bgf in gd_sarc.get_files():
        if bgf.name != "/bool_data_0.bgdata": continue
        byml = oead.byml.from_binary(bytes(bgf.data))
        yaml = oead.byml.to_text(byml)
        for m in re.finditer(r"DataName:\s*(\S+)", yaml):
            name = m.group(1)
            flags.append((crc32(name), name))
    flags.sort(key=lambda x: to_signed(x[0]))
    return {name: idx for idx, (h, name) in enumerate(flags)}


def build_fp(save, data_index):
    fp = []
    for name in KNOWN_FLAGS:
        if name not in data_index: continue
        idx = data_index[name]
        val = 1 if save.flags.get(crc32(name)) else 0
        fp.append((idx, val))
    fp.sort()
    return fp


def verify_1byte(buf, fp):
    for idx, v in fp:
        if idx >= len(buf) or buf[idx] != v: return False
    return True

def verify_bitmask(buf, fp, msb=False):
    for idx, v in fp:
        b, bit = idx >> 3, (7 - (idx & 7)) if msb else (idx & 7)
        if b >= len(buf): return False
        if ((buf[b] >> bit) & 1) != v: return False
    return True


def find_rupee_addresses(br):
    """Scanne toutes les regions pour le pattern AOB rupees. Retourne liste de rupeesAddress (live)."""
    pattern = RUPEE_PATTERN
    plen = len(pattern)
    fixed = [(i, b) for i, b in enumerate(pattern) if b != -1]
    idx0, val0 = fixed[0]

    results = []
    regions = [(b, s) for b, s in br._iter_regions() if s >= plen]
    total = sum(s for _, s in regions)
    print(f"Scan AOB rupees sur {len(regions)} regions, {total // (1024*1024)}MB total...")

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
                        match_addr = base + off + pos
                        results.append(match_addr + plen)
            off += n
            done += n
            print(f"\r  {100*done//total}%  found={len(results)}", end="", flush=True)
    print()
    return results


def scan_region(br, start, size, fp, label):
    """Scan complet d'une region [start, start+size) pour bool array (1-byte / bitmask)."""
    FLAGS_COUNT = 4096
    arr_1b = FLAGS_COUNT + 100
    arr_bm = FLAGS_COUNT // 8 + 16

    anchor_1b = next(idx for idx, v in fp if v == 1)
    anchor_bm = anchor_1b >> 3

    print(f"\nScan {label}: 0x{start:012X} .. +{size//(1024*1024)}MB")

    CHUNK = 16 * 1024 * 1024
    found = []
    off = 0
    t0 = time.time()
    while off < size:
        n = min(CHUNK, size - off)
        chunk = br._read(start + off, n)
        if chunk is None:
            off += n
            continue
        arr_np = np.frombuffer(chunk, dtype=np.uint8)

        pos1 = np.where(arr_np == 1)[0]
        pos1 = pos1[pos1 >= anchor_1b]
        for pos in pos1:
            cb = start + off + int(pos) - anchor_1b
            buf = br._read(cb, arr_1b)
            if buf and verify_1byte(buf, fp):
                found.append(("1-byte", cb))
                print(f"  [1-byte MATCH] 0x{cb:012X}")

        mask = 1 << (anchor_1b & 7)
        pos_bm = np.where((arr_np & mask) != 0)[0]
        pos_bm = pos_bm[pos_bm >= anchor_bm]
        for pos in pos_bm:
            cb = start + off + int(pos) - anchor_bm
            buf = br._read(cb, arr_bm)
            if buf and verify_bitmask(buf, fp, msb=False):
                found.append(("bitmask-LSB", cb))
                print(f"  [bitmask-LSB MATCH] 0x{cb:012X}")
            if buf and verify_bitmask(buf, fp, msb=True):
                found.append(("bitmask-MSB", cb))
                print(f"  [bitmask-MSB MATCH] 0x{cb:012X}")

        off += n
        elapsed = time.time() - t0
        print(f"\r  {100*off//size}%  {elapsed:.0f}s  found={len(found)}", end="", flush=True)
    print()
    return found


def main():
    print("=== Live Scan (rupees AOB + persist offset + bool array) ===\n")
    br = CemuMemoryBridge()
    if not br.attach():
        print("ERREUR: admin requis / Cemu introuvable.")
        return
    print(f"pid={br._pid}  gd_base=0x{br._gd_base:012X}\n")

    save = parse_save(_current_save_in_slot(SLOT).read_bytes())
    rupee_now = save.flags.get(crc32("CurrentRupee"))
    print(f"CurrentRupee (save) = {rupee_now}")

    addrs = find_rupee_addresses(br)
    if not addrs:
        print("\nAucune adresse rupees trouvee. Le pattern ne correspond pas (build/version differente ?).")
        br.detach()
        return

    print(f"\n{len(addrs)} candidat(s) rupeesAddress:")
    for live_addr in addrs:
        persist_addr = live_addr - PERSIST_OFFSET
        v_live = br._read(live_addr, 4)
        v_persist = br._read(persist_addr, 4) if persist_addr > 0 else None
        i_live = struct.unpack(">i", v_live)[0] if v_live else None
        i_persist = struct.unpack(">i", v_persist)[0] if v_persist else None
        print(f"  live=0x{live_addr:012X} val={i_live}   persist=0x{persist_addr:012X} val={i_persist}")

    # Choisit le premier candidat dont la valeur live correspond a la save
    chosen = None
    for live_addr in addrs:
        v_live = br._read(live_addr, 4)
        if v_live and struct.unpack(">i", v_live)[0] == rupee_now:
            chosen = live_addr
            break
    if chosen is None:
        chosen = addrs[0]
        print("\n[!] Aucun candidat ne correspond exactement a CurrentRupee — on prend le premier.")
    else:
        print(f"\n[OK] live=0x{chosen:012X} correspond a CurrentRupee={rupee_now}")

    persist_addr = chosen - PERSIST_OFFSET

    data_index = load_data_index()
    fp = build_fp(save, data_index)
    ones = [idx for idx, v in fp if v == 1]
    print(f"\nFingerprint: {len(fp)} checks, {len(ones)} ones: {ones}")

    # Trouve la region contenant rupeesAddress (le gros heap, ~1-4GB selon
    # FindRegionBySize de l'outil) et scanne cette region entiere.
    region_base, region_size = None, None
    for base, size in br._iter_regions():
        if base <= chosen < base + size:
            region_base, region_size = base, size
            break

    if region_base is None:
        print("\n[!] Region contenant rupeesAddress introuvable (?)")
        br.detach()
        return

    print(f"\nRegion contenant rupeesAddress: 0x{region_base:012X} .. 0x{region_base+region_size:012X} "
          f"({region_size // (1024*1024)}MB)")

    found_region = scan_region(br, region_base, region_size, fp, "region heap (rupees)")

    all_found = found_region
    if not all_found:
        print("\nRien trouve autour des ancres. Essaie une fenetre plus large ou un autre flag fingerprint.")
        br.detach()
        return

    fmt, arr_base = all_found[0]
    para_idx = data_index.get("IsGet_PlayerStole2", 2025)
    para_off = para_idx if fmt == "1-byte" else (para_idx >> 3)

    print(f"\n=== bool_array_base = 0x{arr_base:012X}  format={fmt} ===")
    print(f"Paraglider DataIndex={para_idx}  offset={para_off}")
    print("\nTest injection Paraglider LIVE (pas besoin de reload)...")
    br._write(arr_base + para_off, b"\x01")
    val = br._read(arr_base + para_off, 1)
    print(f"Ecrit 0x01, relu={val[0] if val else '?'}")
    print(">>> Regarde EN JEU (ouvre l'inventaire) si le Paraglider apparait <<<")
    try: input("ENTREE pour restaurer... ")
    except: pass
    br._write(arr_base + para_off, b"\x00")
    print(f"Restaure. bool_array_base=0x{arr_base:012X} (format={fmt})")

    br.detach()


if __name__ == "__main__":
    main()
