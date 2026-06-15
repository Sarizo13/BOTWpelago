"""
Diff Bool Array Scanner v2 — vérification 100% stricte.
Snap1 → action → snap2 → diff → vérifie TOUS les 132 checks pour éliminer les faux positifs.

python tools/diff_scan.py   (PowerShell admin, Cemu in-game)
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
FLAGS_COUNT = 4096

def crc32(name): return zlib.crc32(name.encode("ascii")) & 0xFFFFFFFF
def to_signed(u): return struct.unpack(">i", struct.pack(">I", u))[0]


def load_data():
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
            flags.append((crc32(m.group(1)), m.group(1)))
    flags.sort(key=lambda x: to_signed(x[0]))
    return {name: idx for idx, (h, name) in enumerate(flags)}


KNOWN_FLAGS = (
    ["IsGet_PlayerStole2","IsGet_Obj_Magnetglove","IsGet_Obj_RemoteBomb",
     "IsGet_Obj_StopTimer","IsGet_Obj_IceMaker","IsGet_Obj_Camera",
     "IsGet_NormalArrow","IsGet_Obj_HeroSoul_Rito","IsGet_Obj_HeroSoul_Goron",
     "IsGet_Obj_HeroSoul_Zora","IsGet_Obj_HeroSoul_Gerudo","Get_MasterSword_Finish"]
    + [f"Clear_Dungeon{n:03d}" for n in range(120)]
)


def make_fp(save, data_index):
    fp = []
    for name in KNOWN_FLAGS:
        if name not in data_index: continue
        val = 1 if save.flags.get(crc32(name)) else 0
        fp.append((data_index[name], val))
    fp.sort()
    return fp


def verify_1byte(buf, fp):
    for idx, v in fp:
        if idx >= len(buf) or buf[idx] != v: return False
    return True

def verify_bitmask(buf, fp, msb=False):
    for idx, v in fp:
        b, bit = idx >> 3, (7 - idx & 7) if msb else (idx & 7)
        if b >= len(buf) or ((buf[b] >> bit) & 1) != v: return False
    return True


def take_snapshot(br, regions):
    data = {}
    total = sum(s for _, s in regions)
    done = 0
    for base, size in regions:
        buf = bytearray()
        off = 0
        while off < size:
            n = min(4 * 1024 * 1024, size - off)
            chunk = br._read(base + off, n) or bytes(n)
            buf += chunk
            off += n
            done += n
        data[base] = bytes(buf)
        print(f"\r  {100*done//total}% ({done//(1024*1024)}MB)", end="", flush=True)
    print()
    return data


def main():
    print("=== Diff Bool Array Scanner v2 ===\n")
    br = CemuMemoryBridge()
    if not br.attach():
        print("ERREUR: admin requis.")
        return
    print(f"pid={br._pid}  gd_base=0x{br._gd_base:012X}")

    data_index = load_data()
    save = parse_save(_current_save_in_slot(SLOT).read_bytes())
    fp = make_fp(save, data_index)

    ones  = [idx for idx, v in fp if v == 1]
    zeros = [idx for idx, v in fp if v == 0]
    print(f"Fingerprint: {len(fp)} checks  |  {len(ones)} ones: {ones}  |  {len(zeros)} zeros")

    regions = [(b, s) for b, s in br._iter_regions() if s >= 4096]
    total_mb = sum(s for _, s in regions) // (1024 * 1024)
    print(f"\n{len(regions)} regions, {total_mb}MB total")

    print("\nSnapshot 1 — NE BOUGE PAS...")
    snap1 = take_snapshot(br, regions)

    print("\n>>> ACTION: allume un feu de camp et choisis 'Jusqu au matin'")
    print(">>>         (ou ramasse 1 item, ou attends que le jour/nuit change)")
    print(">>> Puis appuie ENTREE ici <<<")
    try: input()
    except: pass

    print("\nSnapshot 2...")
    snap2 = take_snapshot(br, regions)

    # Collect all changed addresses in BOTH directions
    print("\nDiff...")
    changed_to_1 = []  # 0→1: these occupy "ones" positions
    changed_to_0 = []  # 1→0: these occupy "ones" positions (night→day etc.)
    for base in snap1:
        if base not in snap2: continue
        b1 = np.frombuffer(snap1[base], dtype=np.uint8)
        b2 = np.frombuffer(snap2[base], dtype=np.uint8)
        for p in np.where((b1 == 0) & (b2 == 1))[0]: changed_to_1.append(base + int(p))
        for p in np.where((b1 == 1) & (b2 == 0))[0]: changed_to_0.append(base + int(p))

    print(f"Bytes 0->1: {len(changed_to_1)}  |  Bytes 1->0: {len(changed_to_0)}")
    # Use 1→0 changes as anchors for "ones" positions (flag turned off = it WAS a 1)
    changed = changed_to_1 + changed_to_0
    if not changed:
        print("Aucun changement. Refais une action plus marquante.")
        br.detach()
        return

    print(f"\nTest de {len(changed)} adresses × {len(ones)} DataIndex × 3 formats...")
    print("(Verification stricte: 100% des checks doivent correspondre)\n")

    found = []
    checked = set()

    for addr in changed:
        for one_idx in ones:
            # 1-byte format
            base_1b = addr - one_idx
            if base_1b >= 0 and ("1b", base_1b) not in checked:
                checked.add(("1b", base_1b))
                buf = br._read(base_1b, FLAGS_COUNT + 32)
                if buf and verify_1byte(buf, fp):
                    found.append(("1-byte", base_1b))
                    print(f"  [FOUND] 1-byte  base=0x{base_1b:012X}")

            # bitmask-LSB format: byte = one_idx // 8, bit = one_idx & 7
            base_bm = addr - (one_idx >> 3)
            if base_bm >= 0 and ("bm", base_bm) not in checked:
                checked.add(("bm", base_bm))
                buf = br._read(base_bm, FLAGS_COUNT // 8 + 32)
                if buf and verify_bitmask(buf, fp, msb=False):
                    found.append(("bitmask-LSB", base_bm))
                    print(f"  [FOUND] bitmask-LSB  base=0x{base_bm:012X}")
                if buf and verify_bitmask(buf, fp, msb=True):
                    found.append(("bitmask-MSB", base_bm))
                    print(f"  [FOUND] bitmask-MSB  base=0x{base_bm:012X}")

    print(f"\n{len(found)} result(s) apres verification stricte")

    if not found:
        print("Aucun. Le flag change n'est pas dans bool_data_0, ou la fingerprint est encore decalee.")
        print("Essaie avec 'completer un shrine' comme action.")
        br.detach()
        return

    fmt, arr_base = found[0]
    para_idx = data_index.get("IsGet_PlayerStole2", 2025)
    para_off = para_idx if fmt == "1-byte" else (para_idx >> 3)

    print(f"\nbool_array_base = 0x{arr_base:012X}  format = {fmt}")
    print(f"Paraglider DataIndex = {para_idx}  offset = {para_off}")
    print("\nTest injection Paraglider...")
    br._write(arr_base + para_off, b"\x01")
    val = br._read(arr_base + para_off, 1)
    print(f"Ecrit 0x01, relu={val[0] if val else '?'}")
    print(">>> Regarde EN JEU si le Paraglider apparait dans l'inventaire <<<")
    try: input("ENTREE pour restaurer... ")
    except: pass
    br._write(arr_base + para_off, b"\x00")
    print(f"Restaure. ADRESSE CONFIRMEE: bool_array_base = 0x{arr_base:012X}")
    br.detach()


if __name__ == "__main__":
    main()
