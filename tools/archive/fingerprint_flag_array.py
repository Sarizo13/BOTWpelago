"""
Fingerprint Flag Array (lean) — localise le tableau de valeurs LIVE des flags bool.

Format octet uniquement (le plus probable pour des bool). Empreinte : 4 runes possédées (=1)
+ 6 capacités non possédées (=0), à leurs index A connus (table d'index 16o de live_flag_scan).
Cherche une base B telle que B[A]==valeur pour tous. Flush + progression par région.

Lecture seule. PowerShell admin + Cemu en jeu :
    python tools/fingerprint_flag_array.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass
import numpy as np
from BotWClient.memory_injector import CemuMemoryBridge

ONES  = [0x4E80, 0x4BCC, 0x3A75, 0x1077]                  # runes possédées
ZEROS = [0x9F26, 0x0E4B, 0x512A, 0xA3B6, 0x08DC, 0xA328]  # Camera/MasterSword/Revali/Daruk/Mipha/Paraglider
MAXA  = max(ONES + ZEROS)
PAD   = MAXA + 16
CHUNK = 64 * 1024 * 1024


def main():
    b = CemuMemoryBridge()
    if not b.attach():
        print("ERREUR attach (admin + Cemu en jeu requis).", flush=True)
        return
    print(f"gd_base={b._gd_base:#x}  maxA={MAXA:#x}  (format octet)\n", flush=True)
    results = []
    for base, size in b._iter_regions():
        if size < PAD:
            continue
        print(f"-- region 0x{base:012X} ({size//(1024*1024)} MiB) --", flush=True)
        off = 0
        while off < size:
            rd = min(CHUNK, size - off)
            chunk = b._read(base + off, rd)
            if chunk and len(chunk) > PAD:
                arr = np.frombuffer(chunk, dtype=np.uint8)
                eq1 = (arr == 1)
                eq0 = (arr == 0)
                L = len(arr) - PAD
                valid = eq1[ONES[0]:ONES[0] + L].copy()
                for o in ONES[1:]:
                    valid &= eq1[o:o + L]
                for o in ZEROS:
                    valid &= eq0[o:o + L]
                for p in np.where(valid)[0]:
                    results.append(base + off + int(p))
                    print(f"  >>> CANDIDAT base=0x{base+off+int(p):012X}", flush=True)
            if rd < CHUNK:
                break
            off += rd - PAD
    print(f"\n=== {len(results)} candidat(s) ===", flush=True)
    if not results:
        print("  Aucun en format octet. Le tableau live a peut-être un autre format/stride,", flush=True)
        print("  ou le jeu relit gd_base aux événements (pas de cache indexé simple).", flush=True)


if __name__ == "__main__":
    main()
