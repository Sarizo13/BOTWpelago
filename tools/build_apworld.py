"""
Package worlds/botw into a distributable botw.apworld (zip with a top-level
botw/ folder), then optionally copy it into an Archipelago install's
custom_worlds/.

Usage:
  python tools/build_apworld.py                 # -> dist/botw.apworld
  python tools/build_apworld.py --install        # also copy to C:/ProgramData/Archipelago/custom_worlds
  python tools/build_apworld.py --install "D:/path/to/Archipelago"
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "worlds" / "botw"
DIST = ROOT / "dist"
DEFAULT_INSTALL = Path(r"C:/ProgramData/Archipelago")

# Files shipped in the apworld. Only what the world loads at runtime.
PY_FILES = ["__init__.py", "items.py", "locations.py", "options.py", "regions.py", "rules.py"]
EXTRA = ["archipelago.json"]
DATA = ["gate_items.json", "shrine_chests.json"]


def build() -> Path:
    DIST.mkdir(exist_ok=True)
    out = DIST / "botw.apworld"
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in PY_FILES + EXTRA:
            p = SRC / name
            if not p.exists():
                raise SystemExit(f"manquant: {p}")
            z.write(p, f"botw/{name}")
        for name in DATA:
            p = SRC / "data" / name
            if not p.exists():
                raise SystemExit(f"manquant: {p}")
            z.write(p, f"botw/data/{name}")
    print(f"[build] {out}  ({out.stat().st_size} octets)")
    with zipfile.ZipFile(out) as z:
        for n in z.namelist():
            print("   ", n)
    return out


def install(apworld: Path, target: Path) -> None:
    cw = target / "custom_worlds"
    if not cw.exists():
        raise SystemExit(f"custom_worlds introuvable: {cw}")
    dest = cw / "botw.apworld"
    shutil.copy2(apworld, dest)
    print(f"[install] copie -> {dest}")


if __name__ == "__main__":
    ap = build()
    if "--install" in sys.argv:
        i = sys.argv.index("--install")
        target = Path(sys.argv[i + 1]) if len(sys.argv) > i + 1 and not sys.argv[i + 1].startswith("-") else DEFAULT_INSTALL
        install(ap, target)
