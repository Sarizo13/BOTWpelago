"""
scan_map — liste les actors « déclencheurs » (Area, EventTag, WarpTag, …) des map units
MainField du dump, avec leurs paramètres et positions.

Outil de RECHERCHE V2 (lecture seule sur le dump local). Sert à comprendre comment le
vanilla câble ses zones à effet (ex : la forêt perdue = brouillard + renvoi du joueur)
pour ré-implémenter le pattern « zone gate » (message + warp) du mod BOTWpelago.

Usage :
    python mod/scan_map.py E-3 F-3                     # actors triggers de ces carrés
    python mod/scan_map.py E-3 --types Area,WarpTag    # filtre de types
    python mod/scan_map.py --all --types WarpTag       # tout MainField (plus lent)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import oead

DEFAULT_TYPES = {"Area", "EventTag", "WarpTag", "BasicSignalTag", "ActorObserverTag",
                 "DungeonMoveTag", "DungeonResetPosTag"}


def _roots() -> list[Path]:
    cfg = json.loads((Path.home() / ".botwpelago" / "config.json").read_text(encoding="utf-8"))
    return [Path(cfg[k]) for k in ("game_update_path", "game_base_path", "game_dlc_path")
            if cfg.get(k) and Path(cfg[k]).is_dir()]


_TITLEBG: oead.Sarc | None = None


def _titlebg(roots: list[Path]) -> oead.Sarc | None:
    """TitleBG.pack (update) — contient les <carré>_Static.smubin du MainField."""
    global _TITLEBG
    if _TITLEBG is None:
        for r in roots:
            p = r / "Pack" / "TitleBG.pack"
            if p.is_file():
                _TITLEBG = oead.Sarc(p.read_bytes())
                break
    return _TITLEBG


def _read_mubin(roots: list[Path], rel: str) -> bytes | None:
    """Résout un fichier map comme le jeu : fichier libre (update > base > dlc), sinon TitleBG.pack."""
    for r in roots:
        p = r / rel
        if p.is_file():
            return p.read_bytes()
    tbg = _titlebg(roots)
    if tbg is not None:
        for f in tbg.get_files():
            if f.name == rel.replace("\\", "/"):
                return bytes(f.data)
    return None


def _parse_byml(data: bytes):
    if data[:4] == b"Yaz0":
        data = bytes(oead.yaz0.decompress(data))
    return oead.byml.from_binary(data)


def _fmt(v) -> str:
    if isinstance(v, (oead.F32, oead.S32, oead.U32)):
        return str(v.v if hasattr(v, "v") else v)
    return str(v)


def scan_square(roots: list[Path], square: str, types: set[str]) -> None:
    for kind in ("Static", "Dynamic"):
        raw = _read_mubin(roots, f"Map/MainField/{square}/{square}_{kind}.smubin")
        if raw is None:
            continue
        try:
            data = _parse_byml(raw)
        except Exception as exc:
            print(f"  ! {square}_{kind}: {exc}")
            continue
        objs = data["Objs"] if "Objs" in data else []
        for obj in objs:
            name = str(obj["UnitConfigName"]) if "UnitConfigName" in obj else ""
            if name not in types:
                continue
            pos = [round(float(x), 1) for x in obj["Translate"]] if "Translate" in obj else []
            scale = None
            if "Scale" in obj:
                try:
                    scale = [round(float(x), 1) for x in obj["Scale"]]
                except TypeError:
                    scale = round(float(obj["Scale"]), 1)
            pstr = ""
            if "!Parameters" in obj:
                pstr = "  " + ", ".join(f"{k}={_fmt(v)}" for k, v in obj["!Parameters"].items())
            lstr = f"  ->{len(obj['LinksToObj'])} liens" if "LinksToObj" in obj else ""
            print(f"  [{square} {kind}] {name} @ {pos} scale={scale}{lstr}{pstr}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("squares", nargs="*", help="carrés MainField (ex: E-3 F-3)")
    ap.add_argument("--all", action="store_true", help="tous les carrés A-1..J-8")
    ap.add_argument("--types", default=None, help="types d'actors, séparés par des virgules")
    args = ap.parse_args()

    types = set(args.types.split(",")) if args.types else DEFAULT_TYPES
    squares = args.squares
    if args.all:
        squares = [f"{c}-{r}" for c in "ABCDEFGHIJ" for r in range(1, 9)]
    if not squares:
        ap.error("donne des carrés (ex: E-3) ou --all")

    roots = _roots()     # résolution par fichier : update > base > dlc
    print(f"dump : {len(roots)} racines  |  types : {sorted(types)}")
    for sq in squares:
        scan_square(roots, sq, types)


if __name__ == "__main__":
    main()
