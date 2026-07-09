"""
dump_flow — dissèque un .bfevfl du dump : entry points, chaînes d'events, actions/queries + params.

Outil de RECHERCHE V2 (lecture seule sur le dump local — rien n'est copié/commité).
Sert à tracer par ex. le grant paravoile vanilla (Demo027_0) ou la convention d'appel
d'un caller réel de GetDemo::GetManyItemsByName.

Usage :
    python mod/dump_flow.py Event/Demo027_0.sbeventpack EventFlow/Demo027_0.bfevfl
    python mod/dump_flow.py Pack/TitleBG.pack EventFlow/GetDemo.bfevfl --entry GetManyItemsByName
    python mod/dump_flow.py ... --grep PlayerStole2     # n'affiche que les events contenant le motif
Le conteneur est résolu dans update, puis base, puis dlc (config ~/.botwpelago/config.json).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import oead
from evfl import EventFlow
from evfl.event import ActionEvent, SwitchEvent, ForkEvent, JoinEvent, SubFlowEvent


def resolve_container(rel: str) -> Path:
    cfg = json.loads((Path.home() / ".botwpelago" / "config.json").read_text(encoding="utf-8"))
    for key in ("game_update_path", "game_base_path", "game_dlc_path"):
        root = cfg.get(key)
        if root and (Path(root) / rel).is_file():
            return Path(root) / rel
    raise FileNotFoundError(f"{rel} introuvable dans update/base/dlc")


def load_bfevfl(container: Path, inner: str) -> bytes:
    data = container.read_bytes()
    if data[:4] == b"Yaz0":
        data = bytes(oead.yaz0.decompress(data))
    if data[:4] == b"SARC":
        sarc = oead.Sarc(data)
        for f in sarc.get_files():
            if f.name == inner:
                return bytes(f.data)
        raise FileNotFoundError(f"{inner} absent de {container.name} "
                                f"(contenu : {[f.name for f in sarc.get_files()][:20]}…)")
    return data   # fichier .bfevfl nu


def _params(ev) -> str:
    p = getattr(ev, "params", None)
    if not p or not p.data:
        return ""
    return "  " + ", ".join(f"{k}={v.v if hasattr(v, 'v') else v}" for k, v in p.data.items())


def describe(ev) -> str:
    d = ev.data
    if isinstance(d, ActionEvent):
        actor = d.actor.v.identifier.name if d.actor.v else "?"
        action = d.actor_action.v.v if d.actor_action.v else "?"
        return f"Action  {actor}.{action}{_params(d)}"
    if isinstance(d, SwitchEvent):
        actor = d.actor.v.identifier.name if d.actor.v else "?"
        query = d.actor_query.v.v if d.actor_query.v else "?"
        cases = {val: (e.v.name if e.v else "?") for val, e in d.cases.items()}
        return f"Switch  {actor}.{query}{_params(d)}  cases={cases}"
    if isinstance(d, ForkEvent):
        forks = [f.v.name if f.v else "?" for f in d.forks]
        return f"Fork    {forks} join={d.join.v.name if d.join.v else '?'}"
    if isinstance(d, JoinEvent):
        return "Join"
    if isinstance(d, SubFlowEvent):
        return (f"SubFlow {d.res_flowchart_name or '(local)'}::{d.entry_point_name}"
                f"{_params(d)}")
    return f"? {type(d).__name__}"


def walk(start, events_seen: set, indent: str = "  ") -> None:
    ev = start
    while ev is not None:
        tag = " (déjà vu, stop)" if ev.name in events_seen else ""
        print(f"{indent}[{ev.name}] {describe(ev)}{tag}")
        if tag:
            return
        events_seen.add(ev.name)
        d = ev.data
        if isinstance(d, SwitchEvent):
            for val, nxt in d.cases.items():
                if nxt.v:
                    print(f"{indent}  case {val}:")
                    walk(nxt.v, events_seen, indent + "    ")
            return
        if isinstance(d, ForkEvent):
            for f in d.forks:
                if f.v:
                    print(f"{indent}  fork:")
                    walk(f.v, events_seen, indent + "    ")
            ev = d.join.v
            continue
        nxt = getattr(d, "nxt", None)
        ev = nxt.v if nxt and nxt.v else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("container", help="chemin relatif au content/ (ex: Event/Demo027_0.sbeventpack)")
    ap.add_argument("inner", help="fichier dans le SARC (ex: EventFlow/Demo027_0.bfevfl)")
    ap.add_argument("--entry", default=None, help="ne tracer que cet entry point")
    ap.add_argument("--grep", default=None, help="n'afficher que les events dont la description matche")
    args = ap.parse_args()

    path = resolve_container(args.container)
    raw = load_bfevfl(path, args.inner)
    flow = EventFlow()
    flow.read(raw)
    fc = flow.flowchart
    print(f"{args.inner} — {len(fc.events)} events, {len(fc.entry_points)} entry points, "
          f"{len(fc.actors)} actors\n")

    if args.grep:
        for ev in fc.events:
            desc = describe(ev)
            if args.grep in desc or args.grep in ev.name:
                print(f"  [{ev.name}] {desc}")
        return

    for ep in fc.entry_points:
        if args.entry and ep.name != args.entry:
            continue
        print(f"-- entry {ep.name}")
        if ep.main_event.v is None:
            print("   (pas d'event principal)")
            continue
        walk(ep.main_event.v, set())
        print()


if __name__ == "__main__":
    main()
