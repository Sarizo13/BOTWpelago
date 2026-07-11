"""Trouve les sites .text référençant une fenêtre d'adresses (vtable) via lis/addi."""
import sys
from pathlib import Path

import numpy as np

TEXT_BASE = 0x02000000
text = (Path(__file__).resolve().parents[1] / "tmp/rpx_v208/02_text.bin").read_bytes()
words = np.frombuffer(text[: len(text) - (len(text) % 4)], dtype=">u4")
op = words >> 26
f_rd = (words >> 21) & 31
f_ra = (words >> 16) & 31
uimm = words & 0xFFFF

lo_min = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x10245300
lo_max = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x102455B0
ha = ((lo_min + 0x8000) >> 16) & 0xFFFF   # suppose même ha sur la fenêtre

lis_mask = (op == 15) & (f_ra == 0)
lis_idx = np.where(lis_mask & (uimm == ha))[0]
lis_map = {int(i): int(f_rd[i]) for i in lis_idx}
addi_idx = np.where((op == 14) & (uimm >= (lo_min & 0xFFFF)) & (uimm <= (lo_max & 0xFFFF)))[0]

hits: dict[int, list[int]] = {}
for ai in addi_idx:
    r = int(f_ra[ai])
    for j in range(max(0, int(ai) - 96), int(ai)):
        if j in lis_map and lis_map[j] == r:
            target = (ha << 16) - 0x10000 * (1 if (lo_min & 0xFFFF) >= 0x8000 else 0) \
                     + int(uimm[ai])
            target = (ha << 16) + int(uimm[ai]) if int(uimm[ai]) < 0x8000 else \
                     ((ha << 16) - 0x10000) + int(uimm[ai])
            hits.setdefault(target, []).append(TEXT_BASE + int(ai) * 4)
            break

for t in sorted(hits):
    sites = " ".join(f"0x{s:08X}" for s in hits[t])
    print(f"ref 0x{t:08X} <- {sites}")
