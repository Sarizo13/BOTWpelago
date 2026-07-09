"""
scan_actions — énumère toutes les (actor, action) et (actor, query) distinctes utilisées
par les .bfevfl du dump, avec leur nombre d'occurrences.

Outil de RECHERCHE V2 (lecture seule). Sert à trouver les primitives vanilla disponibles
(ex : fade d'écran, test « joueur au sol », affichage d'un message) sans deviner les noms.

Usage :
    python mod/scan_actions.py                     # tout, trié par fréquence
    python mod/scan_actions.py --grep Fade Ground  # filtre (substring, insensible casse)
    python mod/scan_actions.py --actor EventSystemActor
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import oead
from evfl import EventFlow

_CONTAINER_EXTS = {".pack", ".sbeventpack", ".beventpack", ".sarc"}


def _iter_bfevfl(data: bytes, path: str):
    if data[:4] == b"Yaz0":
        data = bytes(oead.yaz0.decompress(data))
    if data[:4] == b"SARC":
        try:
            sarc = oead.Sarc(data)
        except Exception:
            return
        for f in sarc.get_files():
            yield from _iter_bfevfl(bytes(f.data), f"{path}/{f.name}")
    elif path.endswith(".bfevfl"):
        yield path, data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grep", nargs="+", default=None)
    ap.add_argument("--actor", default=None)
    args = ap.parse_args()

    cfg = json.loads((Path.home() / ".botwpelago" / "config.json").read_text(encoding="utf-8"))
    roots = [Path(cfg[k]) for k in ("game_update_path", "game_base_path", "game_dlc_path")
             if cfg.get(k) and Path(cfg[k]).is_dir()]

    actions: Counter = Counter()
    queries: Counter = Counter()
    seen: set[str] = set()
    n_flows = 0
    for root in roots:
        for p in sorted(root.rglob("*")):
            if not (p.is_file() and p.suffix.lower() in _CONTAINER_EXTS | {".bfevfl"}):
                continue
            rel = p.relative_to(root).as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            try:
                raw = p.read_bytes()
            except OSError:
                continue
            for vpath, flow_bytes in _iter_bfevfl(raw, rel):
                try:
                    flow = EventFlow()
                    flow.read(flow_bytes)
                except Exception:
                    continue
                n_flows += 1
                for actor in flow.flowchart.actors:
                    name = actor.identifier.name
                    for a in actor.actions:
                        actions[(name, a.v)] += 1
                    for q in actor.queries:
                        queries[(name, q.v)] += 1

    def show(counter: Counter, label: str) -> None:
        print(f"\n== {label} ==")
        for (actor, name), n in counter.most_common():
            if args.actor and actor != args.actor:
                continue
            if args.grep and not any(g.lower() in name.lower() for g in args.grep):
                continue
            print(f"  {n:5d}  {actor}.{name}")

    print(f"{n_flows} flows analysés")
    show(actions, "ACTIONS")
    show(queries, "QUERIES")


if __name__ == "__main__":
    main()
