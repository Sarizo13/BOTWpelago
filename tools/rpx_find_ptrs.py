"""Cherche des pointeurs u32be dans .rodata (base 0x10000000) et .data (base 0x10462BC0)."""
import struct
import sys
from pathlib import Path

RO_BASE = 0x10000000
DATA_BASE = 0x10462BC0            # vaddr .data v208 (parse ELF, session 2026-07-11)
_ROOT = Path(__file__).resolve().parents[1]
ro = (_ROOT / "tmp/rpx_v208/03_rodata.bin").read_bytes()
da = (_ROOT / "tmp/rpx_v208/04_data.bin").read_bytes()

for arg in sys.argv[1:]:
    t = int(arg, 0)
    needle = struct.pack(">I", t)
    print(f"=== 0x{t:08X} ===")
    for blob, base, name in ((ro, RO_BASE, ".rodata"), (da, DATA_BASE, ".data")):
        start = 0
        while True:
            i = blob.find(needle, start)
            if i < 0:
                break
            start = i + 1
            ctx = blob[max(0, i - 16):i + 20]
            words = " ".join(f"{struct.unpack_from('>I', ctx, k)[0]:08X}"
                             for k in range(0, len(ctx) - 3, 4))
            print(f"  {name} @0x{base + i:08X}  ctx: {words}")
