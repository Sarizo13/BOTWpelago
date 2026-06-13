"""
RPX Extract — decompresse les sections zlib d'un binaire RPX/RPL (Cafe OS, Wii U)
et exporte .text/.rodata bruts pour recherche de chaines/hashes.

Format RPX: ELF32 BE (e_type=0xFE01). Les sections avec le flag SHF_RPL_ZLIB
(0x08000000) ont en debut de donnees un entete u32be = taille decompressee,
suivi d'un flux zlib classique.

Usage:
    python tools/rpx_extract.py <chemin U-King.rpx> <dossier sortie>
"""
import struct
import sys
import zlib
from pathlib import Path

SHF_RPL_ZLIB = 0x08000000


def main():
    if len(sys.argv) != 3:
        print("Usage: python tools/rpx_extract.py <U-King.rpx> <outdir>")
        return
    rpx_path, outdir = Path(sys.argv[1]), Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)

    data = rpx_path.read_bytes()
    e_shoff, = struct.unpack_from(">I", data, 32)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(">HHH", data, 46)

    def read_section(i):
        off = e_shoff + i * e_shentsize
        name, stype, flags, addr, offset, size, link, info, align, entsize = \
            struct.unpack_from(">10I", data, off)
        return dict(idx=i, name=name, type=stype, flags=flags, addr=addr,
                     offset=offset, size=size)

    secs = [read_section(i) for i in range(e_shnum)]

    # shstrtab (section e_shstrndx) is itself zlib-compressed
    shstr = secs[e_shstrndx]
    raw = data[shstr["offset"]:shstr["offset"] + shstr["size"]]
    if shstr["flags"] & SHF_RPL_ZLIB:
        dsize = struct.unpack(">I", raw[:4])[0]
        shstr_data = zlib.decompress(raw[4:])
        assert len(shstr_data) == dsize
    else:
        shstr_data = raw

    def secname(s):
        end = shstr_data.index(b"\x00", s["name"])
        return shstr_data[s["name"]:end].decode()

    for s in secs:
        if s["size"] == 0 or s["type"] == 0:
            continue
        name = secname(s)
        raw = data[s["offset"]:s["offset"] + s["size"]]
        if s["flags"] & SHF_RPL_ZLIB:
            dsize = struct.unpack(">I", raw[:4])[0]
            out = zlib.decompress(raw[4:])
            assert len(out) == dsize
        else:
            out = raw
        safe = name.strip(".").replace(".", "_") or f"sec{s['idx']}"
        fname = outdir / f"{s['idx']:02d}_{safe}.bin"
        fname.write_bytes(out)
        print(f"[{s['idx']:2d}] {name:20s} addr=0x{s['addr']:08X} "
              f"size=0x{len(out):X} -> {fname}")


if __name__ == "__main__":
    main()
