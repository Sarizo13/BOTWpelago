"""
Scan ciblé ±128MB autour de gd_base — beaucoup plus rapide (~2 min).
Lit la fingerprint depuis la save courante.

PowerShell admin + Cemu in-game :
    python tools/targeted_scan.py
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

def crc32(name): return zlib.crc32(name.encode("ascii")) & 0xFFFFFFFF
def to_signed(u): return struct.unpack(">i", struct.pack(">I", u))[0]

KNOWN_FLAGS = (
    ["IsGet_PlayerStole2", "IsGet_Obj_Magnetglove", "IsGet_Obj_RemoteBomb",
     "IsGet_Obj_StopTimer", "IsGet_Obj_IceMaker", "IsGet_Obj_Camera",
     "IsGet_NormalArrow", "IsGet_Obj_HeroSoul_Rito", "IsGet_Obj_HeroSoul_Goron",
     "IsGet_Obj_HeroSoul_Zora", "IsGet_Obj_HeroSoul_Gerudo", "Get_MasterSword_Finish"]
    + [f"Clear_Dungeon{n:03d}" for n in range(120)]
)


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
        idx  = data_index[name]
        fid  = crc32(name)
        val  = 1 if save.flags.get(fid) else 0
        fp.append((idx, val))
    fp.sort()
    return fp


def verify_1byte(buf, fp):
    for idx, v in fp:
        if idx >= len(buf) or buf[idx] != v: return False
    return True

def verify_bitmask_lsb(buf, fp):
    for idx, v in fp:
        b, bit = idx >> 3, idx & 7
        if b >= len(buf): return False
        if ((buf[b] >> bit) & 1) != v: return False
    return True

def verify_bitmask_msb(buf, fp):
    for idx, v in fp:
        b, bit = idx >> 3, 7 - (idx & 7)
        if b >= len(buf): return False
        if ((buf[b] >> bit) & 1) != v: return False
    return True


def scan_range(br, start, size, fp):
    """Scan start..start+size for 1-byte and bitmask formats."""
    CHUNK  = 8 * 1024 * 1024  # 8MB
    FLAGS_COUNT = 4096
    arr_1b  = FLAGS_COUNT + 100
    arr_bm  = FLAGS_COUNT // 8 + 16   # 512 bytes

    # Anchors: first "1" in fingerprint
    anchor_1b = next(idx for idx, v in fp if v == 1)
    anchor_bm = anchor_1b >> 3   # byte in bitmask

    cands = {"1-byte": [], "bitmask-LSB": [], "bitmask-MSB": []}
    off = 0
    t0 = time.time()
    while off < size:
        n = min(CHUNK, size - off)
        chunk = br._read(start + off, n)
        if chunk is None:
            off += n; continue

        arr_np = np.frombuffer(chunk, dtype=np.uint8)

        # ── 1-byte format ────────────────────────────────────────────────────
        pos1 = np.where(arr_np == 1)[0]
        pos1 = pos1[pos1 >= anchor_1b]
        for pos in pos1:
            cb = start + off + int(pos) - anchor_1b
            buf = br._read(cb, arr_1b)
            if buf and verify_1byte(buf, fp):
                cands["1-byte"].append(cb)
                print(f"  [1-byte MATCH] 0x{cb:012X}")

        # ── bitmask-LSB ───────────────────────────────────────────────────────
        mask = 1 << (anchor_1b & 7)
        pos_bm = np.where((arr_np & mask) != 0)[0]
        pos_bm = pos_bm[pos_bm >= anchor_bm]
        for pos in pos_bm:
            cb = start + off + int(pos) - anchor_bm
            buf = br._read(cb, arr_bm)
            if buf and verify_bitmask_lsb(buf, fp):
                cands["bitmask-LSB"].append(cb)
                print(f"  [bitmask-LSB MATCH] 0x{cb:012X}")
            if buf and verify_bitmask_msb(buf, fp):
                cands["bitmask-MSB"].append(cb)
                print(f"  [bitmask-MSB MATCH] 0x{cb:012X}")

        off += n
        elapsed = time.time() - t0
        pct = 100 * off / size
        print(f"\r  {pct:.0f}%  {elapsed:.0f}s  cands={sum(len(v) for v in cands.values())}", end="", flush=True)

    print()
    return cands


def main():
    print("=== Targeted Bool Array Scan ===\n")
    br = CemuMemoryBridge()
    if not br.attach():
        print("ERREUR: admin requis.")
        return
    print(f"pid={br._pid}  gd_base=0x{br._gd_base:012X}")

    # Fresh fingerprint
    save = parse_save(_current_save_in_slot(SLOT).read_bytes())
    data_index = load_data_index()
    fp = build_fp(save, data_index)
    ones = [data_index[n] for n in KNOWN_FLAGS if n in data_index and save.flags.get(crc32(n))]
    print(f"Fingerprint: {len(fp)} checks, ones at DataIndex {sorted(ones)}\n")

    # Scan ±128MB around gd_base
    WINDOW = 128 * 1024 * 1024
    start = max(0, br._gd_base - WINDOW)
    size  = WINDOW * 2
    print(f"Scanning 0x{start:012X} .. +{size//(1024*1024)}MB\n")

    cands = scan_range(br, start, size, fp)

    print("\n=== Résultats ===")
    para_idx = data_index.get("IsGet_PlayerStole2", 2025)
    any_found = False
    for fmt, addrs in cands.items():
        if addrs:
            any_found = True
            arr_base = addrs[0]
            print(f"{fmt}: 0x{arr_base:012X}")
            if fmt == "1-byte":
                off = para_idx
                br._write(arr_base + off, b"\x01")
                val = br._read(arr_base + off, 1)
                print(f"  Paraglider @ +{off}: ecrit 1, relu={val[0] if val else '?'}")
                print("  >>> Regarde en jeu si le Paraglider apparait <<<")
                try: input("  ENTREE pour restaurer... ")
                except: pass
                br._write(arr_base + off, b"\x00")
                print(f"  Restaure. bool_array_base=0x{arr_base:012X}")

    if not any_found:
        print("Rien dans ±128MB. Le bool array n'est pas pres de gd_base.")
        print("-> Prochaine etape : scan diff (prend un snapshot, action en jeu, compare)")
        print("   Lance: python tools/diff_scan.py")

    br.detach()


if __name__ == "__main__":
    main()
