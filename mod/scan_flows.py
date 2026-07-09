"""
scan_flows — localise des motifs (noms d'actions/flags/acteurs) dans TOUS les .bfevfl du dump.

Outil de RECHERCHE V2 (lecture seule sur le dump local du joueur — rien du jeu n'est copié
ni commité). Sert à trouver :
  - où le jeu accorde le paravoile vanilla (motif `PlayerStole2`) → cible enforcement,
  - quels flows appellent `GetManyItemsByName` / `Demo_IncreasePorchItem` (primitive
    « donner item + popup », cf. docs/status.md §EventFlow trace),
  - les flows candidats au déclencheur « mailbox » (events récurrents).

Usage :
    python mod/scan_flows.py                          # motifs par défaut, chemins du config
    python mod/scan_flows.py --patterns PlayerStole2 Ganon
    python mod/scan_flows.py --json out.json          # rapport machine
Les chemins base/update/dlc viennent de ~/.botwpelago/config.json (surchageables --roots).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import oead

DEFAULT_PATTERNS = [
    "PlayerStole2",            # paravoile (IsGet_PlayerStole2 + acteur)
    "GetManyItemsByName",      # entry point GetDemo « donner N items + popup »
    "Demo_IncreasePorchItem",  # action pouch-increment
]

# Extensions de conteneurs à ouvrir récursivement (SARC, éventuellement Yaz0-compressés)
_CONTAINER_EXTS = {".pack", ".sbeventpack", ".beventpack", ".sarc", ".ssarc", ".bactorpack", ".sbactorpack"}


def _decompress(data: bytes) -> bytes:
    if data[:4] == b"Yaz0":
        return bytes(oead.yaz0.decompress(data))
    return data


def _iter_bfevfl(data: bytes, path: str):
    """Descend récursivement dans les SARC et yield (chemin_virtuel, bytes) des .bfevfl."""
    data = _decompress(data)
    if data[:4] == b"SARC":
        try:
            sarc = oead.Sarc(data)
        except Exception:
            return
        for f in sarc.get_files():
            yield from _iter_bfevfl(bytes(f.data), f"{path}/{f.name}")
    elif path.endswith(".bfevfl"):
        yield path, data


def scan_file(disk_path: Path, patterns: list[bytes], rel: str) -> list[dict]:
    hits = []
    try:
        raw = disk_path.read_bytes()
    except OSError as exc:
        print(f"  ! {rel}: {exc}", file=sys.stderr)
        return hits
    for vpath, flow in _iter_bfevfl(raw, rel):
        found = [p.decode() for p in patterns if p in flow]
        if found:
            hits.append({"file": vpath, "patterns": found, "size": len(flow)})
    return hits


def main() -> None:
    ap = argparse.ArgumentParser(description="Scanne les .bfevfl du dump pour des motifs")
    ap.add_argument("--patterns", nargs="+", default=DEFAULT_PATTERNS)
    ap.add_argument("--roots", nargs="+", default=None,
                    help="dossiers content/ à scanner (défaut : update+base+dlc du config)")
    ap.add_argument("--json", default=None, help="écrit aussi le rapport en JSON")
    args = ap.parse_args()

    roots: list[Path] = []
    if args.roots:
        roots = [Path(r) for r in args.roots]
    else:
        cfg_path = Path.home() / ".botwpelago" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        # update d'abord (fichiers les plus récents = ceux que le jeu charge), puis base, puis dlc
        for key in ("game_update_path", "game_base_path", "game_dlc_path"):
            v = cfg.get(key)
            if v and Path(v).is_dir():
                roots.append(Path(v))

    patterns = [p.encode("ascii") for p in args.patterns]
    print(f"Motifs : {args.patterns}")

    all_hits: dict[str, list[dict]] = {}
    seen_names: set[str] = set()          # update masque base : premier vu gagne
    for root in roots:
        candidates = [p for p in root.rglob("*")
                      if p.is_file() and p.suffix.lower() in _CONTAINER_EXTS | {".bfevfl"}]
        print(f"\n[{root}] {len(candidates)} conteneurs/flows")
        n_hit = 0
        for p in sorted(candidates):
            rel = p.relative_to(root).as_posix()
            if rel in seen_names:
                continue
            seen_names.add(rel)
            hits = scan_file(p, patterns, rel)
            if hits:
                n_hit += len(hits)
                all_hits.setdefault(str(root), []).extend(hits)
                for h in hits:
                    print(f"  {h['file']}  <- {', '.join(h['patterns'])}")
        print(f"  ({n_hit} flow(s) avec motif)")

    if args.json:
        Path(args.json).write_text(json.dumps(all_hits, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
        print(f"\nRapport JSON -> {args.json}")


if __name__ == "__main__":
    main()
