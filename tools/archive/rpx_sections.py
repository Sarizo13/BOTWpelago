"""
RPX Sections — liste toutes les sections d'un RPX/RPL (nom, type, flags, addr,
offset, taille decompressee), pour comprendre le layout memoire reel (chaque
section .rodata* a sa propre adresse virtuelle de chargement).

Usage:
    python tools/rpx_sections.py <chemin U-King.rpx>
"""
import struct
import sys
import zlib
from pathlib import Path

SHF_RPL_ZLIB = 0x08000000


def main():
    rpx_path = Path(sys.argv[1])
    data = rpx_path.read_bytes()
    e_shoff, = struct.unpack_from(">I", data, 32)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(">HHH", data, 46)

    def read_section(i):
        off = e_shoff + i * e_shentsize
        name, stype, flags, addr, offset, size, link, info, align, entsize = \
            struct.unpack_from(">10I", data, off)
        return dict(idx=i, name=name, type=stype, flags=flags, addr=addr,
                     offset=offset, size=size, align=align)

    secs = [read_section(i) for i in range(e_shnum)]

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
            decsize = dsize
        else:
            decsize = s["size"]
        print(f"[{s['idx']:2d}] {name:24s} type={s['type']:#x} flags={s['flags']:#010x} "
              f"addr=0x{s['addr']:08X} align=0x{s['align']:X} decsize=0x{decsize:X} "
              f"end=0x{s['addr']+decsize:08X}")


if __name__ == "__main__":
    main()
