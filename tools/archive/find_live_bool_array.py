"""
Bool Array Scanner v6 — teste aussi bitmask (sead::BitFlag).
4 formats : 1-byte, u32-BE, u32-LE, bitmask.

PowerShell admin + Cemu in-game :
    python tools/find_live_bool_array.py
"""
import sys, struct, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
from BotWClient.memory_injector import CemuMemoryBridge, SCAN_CHUNK

try:
    import numpy as _np
except ImportError:
    _np = None

# ── Fingerprint — lit les valeurs depuis game_data au moment du scan ──────────
# Construit dynamiquement pour éviter le décalage temporel.

KNOWN_FLAGS = [
    "IsGet_PlayerStole2", "IsGet_Obj_Magnetglove", "IsGet_Obj_RemoteBomb",
    "IsGet_Obj_StopTimer", "IsGet_Obj_IceMaker", "IsGet_Obj_Camera",
    "IsGet_NormalArrow", "IsGet_Obj_HeroSoul_Rito", "IsGet_Obj_HeroSoul_Goron",
    "IsGet_Obj_HeroSoul_Zora", "IsGet_Obj_HeroSoul_Gerudo", "Get_MasterSword_Finish",
] + [f"Clear_Dungeon{n:03d}" for n in range(120)]

FLAGS_COUNT = 4096

import oead, zlib, re

def crc32(name): return zlib.crc32(name.encode("ascii")) & 0xFFFFFFFF
def to_signed(u): return struct.unpack(">i", struct.pack(">I", u))[0]

def build_fingerprint(save):
    """Build fingerprint from current game_data values + bgdata DataIndex."""
    BOOTUP = Path(r"D:\Emulateur\Jeux Wiiu\Base Games\The Legend of Zelda Breath of the Wild [ALZP01]\content\Pack\Bootup.pack")
    bootup = oead.Sarc(BOOTUP.read_bytes())
    raw_gd = bytes(next(f for f in bootup.get_files() if f.name == "GameData/gamedata.ssarc").data)
    if raw_gd[:4] == b"Yaz0": raw_gd = bytes(oead.yaz0.decompress(raw_gd))
    gd_sarc = oead.Sarc(raw_gd)
    all_flags = []
    for bgf in gd_sarc.get_files():
        if bgf.name != "/bool_data_0.bgdata": continue
        byml = oead.byml.from_binary(bytes(bgf.data))
        yaml = oead.byml.to_text(byml)
        for m in re.finditer(r"DataName:\s*(\S+)", yaml):
            name = m.group(1)
            all_flags.append((crc32(name), name))
    all_flags.sort(key=lambda x: to_signed(x[0]))
    data_index = {name: idx for idx, (h, name) in enumerate(all_flags)}

    fp = []
    for name in KNOWN_FLAGS:
        if name not in data_index: continue
        idx = data_index[name]
        fid = crc32(name)
        val_raw = save.flags.get(fid)
        val = 1 if (val_raw and val_raw != 0) else 0
        fp.append((idx, val))
    fp.sort()
    ones = [i for i, v in fp if v == 1]
    print(f"  Fingerprint: {len(fp)} checks, {len(ones)} ones at DataIndex {ones}")
    return fp, data_index


# ── Verifiers ─────────────────────────────────────────────────────────────────

def make_verifier_1byte(fp):
    def verify(buf):
        for idx, expected in fp:
            if idx >= len(buf) or buf[idx] != expected: return False
        return True
    return verify

def make_verifier_bitmask_lsb(fp):
    """Bitmask LSB-first: bit N = byte N//8, bit N%8 (lsb=0)."""
    def verify(buf):
        for idx, expected in fp:
            b, bit = idx >> 3, idx & 7
            if b >= len(buf): return False
            if ((buf[b] >> bit) & 1) != expected: return False
        return True
    return verify

def make_verifier_bitmask_msb(fp):
    """Bitmask MSB-first: bit N = byte N//8, bit 7-(N%8) (msb=0)."""
    def verify(buf):
        for idx, expected in fp:
            b = idx >> 3
            bit = 7 - (idx & 7)
            if b >= len(buf): return False
            if ((buf[b] >> bit) & 1) != expected: return False
        return True
    return verify

def make_verifier_u32be(fp):
    def verify(buf):
        for idx, expected in fp:
            off = idx * 4
            if off + 4 > len(buf): return False
            if buf[off]!=0 or buf[off+1]!=0 or buf[off+2]!=0: return False
            if buf[off+3] != expected: return False
        return True
    return verify

def make_verifier_u32le(fp):
    def verify(buf):
        for idx, expected in fp:
            off = idx * 4
            if off + 4 > len(buf): return False
            if buf[off] != expected: return False
            if buf[off+1]!=0 or buf[off+2]!=0 or buf[off+3]!=0: return False
        return True
    return verify


# ── Scanner ───────────────────────────────────────────────────────────────────

def scan_format(br, fmt_name, fp, anchor_byte_off, verify_fn, array_size):
    """anchor_byte_off = byte position of the first 'one' in this format."""
    print(f"\n[{fmt_name}] anchor_byte={anchor_byte_off}  array={array_size}B  checks={len(fp)}")
    t0 = time.time()
    candidates = []
    ones_vals = [0x01]  # byte value to search for at anchor

    for base, rsz in br._iter_regions():
        if rsz < array_size + anchor_byte_off: continue
        off = 0
        while off < rsz:
            n = min(SCAN_CHUNK, rsz - off)
            chunk = br._read(base + off, n)
            if chunk is None:
                off += n; continue
            if _np is not None:
                arr = _np.frombuffer(chunk, dtype=_np.uint8)
                positions = _np.where(arr == 1)[0]
                positions = positions[positions >= anchor_byte_off]
            else:
                positions = [i for i in range(anchor_byte_off, len(chunk)) if chunk[i] == 1]
            for pos in positions:
                cb = base + off + int(pos) - anchor_byte_off
                buf = br._read(cb, array_size)
                if buf and verify_fn(buf):
                    candidates.append(cb)
                    print(f"  [MATCH] 0x{cb:012X}  ({time.time()-t0:.1f}s)")
            off += n
    print(f"  Done {time.time()-t0:.1f}s — {len(candidates)} match(es)")
    return candidates


def scan_bitmask(br, fmt_name, fp, verify_fn):
    """For bitmask: scan for bytes where specific bits are set."""
    ARRAY_SIZE = FLAGS_COUNT // 8 + 16  # 512 bytes + buffer
    # Find the first 'one' in the fingerprint and its byte/bit position
    first_one_idx, _ = next((idx, v) for idx, v in fp if v == 1)
    anchor_byte = first_one_idx >> 3  # byte position
    print(f"\n[{fmt_name}] anchor_byte={anchor_byte}  array={ARRAY_SIZE}B  checks={len(fp)}")
    t0 = time.time()
    candidates = []

    # For LSB bitmask: look for byte[anchor_byte] where the right bits are set
    # anchor bit in the byte
    anchor_bit_lsb = first_one_idx & 7
    anchor_bit_msb = 7 - (first_one_idx & 7)

    for base, rsz in br._iter_regions():
        if rsz < ARRAY_SIZE + anchor_byte: continue
        off = 0
        while off < rsz:
            n = min(SCAN_CHUNK, rsz - off)
            chunk = br._read(base + off, n)
            if chunk is None:
                off += n; continue
            if _np is not None:
                arr = _np.frombuffer(chunk, dtype=_np.uint8)
                # For LSB: bit anchor_bit_lsb set
                mask_lsb = 1 << anchor_bit_lsb
                positions = _np.where((arr & mask_lsb) != 0)[0]
                positions = positions[positions >= anchor_byte]
            else:
                mask_lsb = 1 << anchor_bit_lsb
                positions = [i for i in range(anchor_byte, len(chunk)) if chunk[i] & mask_lsb]
            for pos in positions:
                cb = base + off + int(pos) - anchor_byte
                buf = br._read(cb, ARRAY_SIZE)
                if buf and verify_fn(buf):
                    candidates.append(cb)
                    print(f"  [MATCH] 0x{cb:012X}  ({time.time()-t0:.1f}s)")
            off += n
    print(f"  Done {time.time()-t0:.1f}s — {len(candidates)} match(es)")
    return candidates


def main():
    from BotWClient.save_parser import parse as parse_save
    from BotWClient.providers.save_file import _current_save_in_slot

    print("=== Bool Array Scanner v6 ===\n")
    br = CemuMemoryBridge()
    if not br.attach():
        print("ERREUR: lance en admin.")
        return
    print(f"pid={br._pid}  gd_base=0x{br._gd_base:012X}")

    # Build fingerprint from CURRENT save
    slot = Path(r"D:\Emulateur\Cemu\cemu_1.18.1\mlc01\usr\save\00050000\101c9500\user\80000002")
    save = parse_save(_current_save_in_slot(slot).read_bytes())
    print("\nBuilding fingerprint from current save...")
    fp, data_index = build_fingerprint(save)

    # Get DataIndex for IsGet_PlayerStole2 (Paraglider) for injection test
    para_idx = data_index.get("IsGet_PlayerStole2", 2025)

    # Find anchor (first '1' in fingerprint)
    anchor_idx = next(idx for idx, val in fp if val == 1)
    print(f"  Anchor DataIndex: {anchor_idx}")

    # 1-byte format
    c1 = scan_format(br, "1-byte", fp,
                     anchor_byte_off=anchor_idx,
                     verify_fn=make_verifier_1byte(fp),
                     array_size=FLAGS_COUNT + 100)

    # Bitmask LSB format
    cb_lsb = scan_bitmask(br, "bitmask-LSB", fp, make_verifier_bitmask_lsb(fp))

    # Bitmask MSB format
    cb_msb = scan_bitmask(br, "bitmask-MSB", fp, make_verifier_bitmask_msb(fp))

    # u32-BE format
    cbe = scan_format(br, "u32-BE", fp,
                      anchor_byte_off=anchor_idx * 4 + 3,
                      verify_fn=make_verifier_u32be(fp),
                      array_size=FLAGS_COUNT * 4 + 100)

    print("\n=== Résultats ===")
    found = False
    for cands, fmt, para_off in [
        (c1,     "1-byte",       para_idx),
        (cb_lsb, "bitmask-LSB",  None),
        (cb_msb, "bitmask-MSB",  None),
        (cbe,    "u32-BE",       para_idx * 4 + 3),
    ]:
        if cands:
            found = True
            print(f"{fmt}: {len(cands)} match(es) -> 0x{cands[0]:012X}")
            if para_off is not None:
                arr_base = cands[0]
                print(f"  Test Paraglider (DataIndex {para_idx}, byte offset {para_off})")
                br._write(arr_base + para_off, b"\x01")
                val = br._read(arr_base + para_off, 1)
                print(f"  Ecrit 0x01 -> relu {val[0] if val else '?'}")
                print("  >>> Regarde si le Paraglider apparait EN JEU <<<")
                try: input("  ENTREE pour restaurer... ")
                except: pass
                br._write(arr_base + para_off, b"\x00")
                print(f"  Restaure. bool_array_base=0x{arr_base:012X}")

    if not found:
        print("Toujours rien. Passage au scan diff (requis).")
        print("\n=== Scan diff ===")
        print("1. NE BOUGE PAS — capture snapshot 1...")
        _diff_scan(br, fp, data_index)

    br.detach()


def _diff_scan(br, fp, data_index):
    """Capture two memory snapshots, diff to find bool array."""
    # Scan a targeted 256MB range around gd_base
    gd_base = br._gd_base
    RANGE_START = max(0, gd_base - 128 * 1024 * 1024)
    RANGE_SIZE  = 256 * 1024 * 1024
    CHUNK_SIZE  = 1 * 1024 * 1024  # 1MB chunks

    print(f"  Range: 0x{RANGE_START:012X} + {RANGE_SIZE // (1024*1024)}MB")
    print("  Capture snapshot 1...")

    snap1 = {}
    for off in range(0, RANGE_SIZE, CHUNK_SIZE):
        addr = RANGE_START + off
        data = br._read(addr, CHUNK_SIZE)
        if data:
            snap1[addr] = data

    print(f"  Captured {len(snap1)} chunks.")
    print("\n  ACTION: complete un shrine et attend l'autosave, puis appuie ENTREE...")
    try: input()
    except: pass

    print("  Capture snapshot 2...")
    diffs = []
    for off in range(0, RANGE_SIZE, CHUNK_SIZE):
        addr = RANGE_START + off
        data2 = br._read(addr, CHUNK_SIZE)
        data1 = snap1.get(addr)
        if data1 and data2 and len(data1) == len(data2):
            for i in range(len(data1)):
                if data1[i] == 0 and data2[i] == 1:
                    diffs.append(addr + i)

    print(f"  Bytes 0->1: {len(diffs)}")
    if diffs:
        print("  First 20:", [f"0x{a:012X}" for a in diffs[:20]])
        print(f"  Hint: le bool array base = diff_addr - DataIndex_of_changed_flag")


if __name__ == "__main__":
    main()
