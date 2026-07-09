"""
Patch « hard enforcement » du paravoile.

Vanilla : dans la scène du Roi sur le toit du Temple du Temps (quête FindDungeon,
Event/FindDungeon.sbeventpack → EventFlow/FindDungeon.bfevfl), l'event `Event65` fait
`SubFlow GetDemo::GetItemByName(CheckTargetActorName=PlayerStole2)` — c'est LE grant
vanilla du paravoile (item + popup + flag IsGet_PlayerStole2). Tracé par mod/dump_flow.py.

Patch : on EXCISE ce SubFlow de la chaîne (tous les prédécesseurs sont rebranchés sur son
successeur). Le reste de la scène est intact : dialogues du Roi, Demo_AdvanceQuest
(FindDungeon), FlagON GanonQuest_Activated / Find_Impa_Activated, AutoSave. Résultat :
la quête avance normalement mais le paravoile n'est JAMAIS donné par le jeu — il arrive
uniquement par Archipelago (le client écrit IsGet_PlayerStole2 + l'item pouch).

L'event orphelin reste dans le fichier (inoffensif, jamais référencé) — diff minimal.
"""
from __future__ import annotations

from evfl import EventFlow
from evfl.event import ForkEvent, SubFlowEvent, SwitchEvent

from . import FlowPatch, PatchError


def _param_str(params, key: str) -> str:
    if not params or not params.data:
        return ""
    v = params.data.get(key)
    return str(getattr(v, "v", v) if v is not None else "")


def _find_grant(fc):
    for ev in fc.events:
        d = ev.data
        if (isinstance(d, SubFlowEvent) and d.entry_point_name == "GetItemByName"
                and _param_str(d.params, "CheckTargetActorName") == "PlayerStole2"):
            return ev
    return None


def _excise(fc, target) -> int:
    """Rebranche toute référence vers `target` sur son successeur. Retourne le nb de liens."""
    successor = target.data.nxt.v
    if successor is None:
        raise PatchError("le grant n'a pas de successeur — excision ambiguë, on ne patche pas")
    n = 0
    for ev in fc.events:
        if ev is target:
            continue
        d = ev.data
        nxt = getattr(d, "nxt", None)
        if nxt is not None and nxt.v is target:
            nxt.v = successor
            n += 1
        if isinstance(d, SwitchEvent):
            for case in d.cases.values():
                if case.v is target:
                    case.v = successor
                    n += 1
        if isinstance(d, ForkEvent):
            for f in d.forks:
                if f.v is target:
                    f.v = successor
                    n += 1
    for ep in fc.entry_points:
        if ep.main_event.v is target:
            ep.main_event.v = successor
            n += 1
    return n


def transform(flow: EventFlow) -> None:
    fc = flow.flowchart
    grant = _find_grant(fc)
    if grant is None:
        raise PatchError("SubFlow GetItemByName(PlayerStole2) introuvable dans FindDungeon "
                         "(fichier déjà patché, ou version de jeu inattendue)")
    n = _excise(fc, grant)
    if n == 0:
        raise PatchError("grant trouvé mais aucun lien entrant — structure inattendue")


def verify(flow: EventFlow) -> None:
    """Sur le flow patché re-parsé : le grant ne doit plus être ATTEIGNABLE depuis aucun
    entry point (l'event orphelin peut rester dans le tableau)."""
    fc = flow.flowchart
    grant = _find_grant(fc)
    if grant is None:
        return                     # complètement retiré : ok aussi
    reachable: set[int] = set()

    def walk(ev):
        while ev is not None and id(ev) not in reachable:
            reachable.add(id(ev))
            d = ev.data
            if isinstance(d, SwitchEvent):
                for case in d.cases.values():
                    walk(case.v)
                return
            if isinstance(d, ForkEvent):
                for f in d.forks:
                    walk(f.v)
                ev = d.join.v
                continue
            nxt = getattr(d, "nxt", None)
            ev = nxt.v if nxt else None

    for ep in fc.entry_points:
        walk(ep.main_event.v)
    if id(grant) in reachable:
        raise PatchError("VÉRIF ÉCHOUÉE : le grant paravoile est encore atteignable")


PATCH = FlowPatch(
    name="paraglider-enforcement",
    container="Event/FindDungeon.sbeventpack",
    inner="EventFlow/FindDungeon.bfevfl",
    transform=transform,
    verify=verify,
    description="Retire le grant paravoile vanilla de la scène du Roi (quête FindDungeon) ; "
                "le paravoile n'arrive plus que via Archipelago.",
)
