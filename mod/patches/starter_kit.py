"""
Patch « kit de départ » — débloque TOUS les onglets de la sacoche dès le réveil.

Problème : un item AP livré dans un onglet JAMAIS débloqué corrompt la poche (crash plat du
2026-07-14) ; le client REPORTE désormais ces créations (garde « onglet verrouillé »), mais
sans kit les livraisons attendent les premiers ramassages du joueur.

Point d'accroche (RÉVISÉ v3, 2026-07-14 soir) : les accroches Demo003_0 (socle) ont échoué —
`CommonFirst` ne joue jamais sur partie moddée, et `Common` a tourné dans un contexte où la
poche ne recevait pas (flag de garde posé, 0 item livré). La bonne accroche = la fin de la
CINÉMATIQUE DU RÉVEIL patchée par le rando (`Demo700_0`, entry `Demo700_0`) : le rando y donne
la tablette (SUBFLOW GetDemo::GetItemByName) puis enchaîne ses flags de quêtes
(FindDungeon_Activated → Open_Door → FIN). On APPEND en queue de cette chaîne :

    … Open_Door ─> Demo_WaitFrame(30) ─> kit (8 × Demo_IncreasePorchItem) ─> FIN

La poche est garantie fonctionnelle (elle vient de recevoir la tablette), les quêtes sont
posées (délai demandé par le joueur), et la cinématique du réveil ne joue qu'UNE fois par
partie → pas de flag de garde. On patche la COPIE DU RANDO (le marqueur d'ancrage
`FindDungeon_Activated` n'existe que dans sa version) ; pack_builder ré-applique après
chaque régénération de seed. Idempotent (marqueur = présence du Tree Branch du kit).
"""
from __future__ import annotations

import io

import oead
from evfl import EventFlow
from evfl.actor import ActorIdentifier
from evfl.common import StringHolder
from evfl.container import Container
from evfl.event import ActionEvent, Event
from evfl.util import make_index, make_rindex

from . import PatchError

NAME = "starter-kit"
DESCRIPTION = ("Kit de départ à la fin du réveil (après le don de la tablette + les quêtes "
               "du rando) : 1 item par onglet de sacoche — plus de catégorie grisée, les "
               "livraisons AP tombent en liste non vide.")

EVENTPACK_REL = "Event/Demo700_0.sbeventpack"
FLOW_INNER = "EventFlow/Demo700_0.bfevfl"
ANCHOR_FLAG = "FindDungeon_Activated"   # posé UNIQUEMENT par le rando dans ce flow (marqueur)
DELAY_FRAMES = 30                        # petit délai après la pose des quêtes (demande joueur)

# (actor, quantité) — un représentant humble par onglet de sacoche
KIT = [
    ("Weapon_Sword_044", 1),    # Tree Branch          — armes
    ("Weapon_Bow_001", 1),      # Traveler's Bow       — arcs
    ("NormalArrow", 5),         # Flèches              — (verrouillées si vides)
    ("Weapon_Shield_040", 1),   # Pot Lid              — boucliers
    ("Armor_043_Upper", 1),     # Old Shirt            — armures
    ("Armor_043_Lower", 1),     # Well-Worn Trousers
    ("Item_Fruit_A", 1),        # Apple                — matériaux
    ("Item_Roast_03", 1),       # Baked Apple          — nourriture
]
_MARKER = KIT[0][0]             # présence du Tree Branch du kit = déjà patché


def _patched_flow(flow_bytes: bytes) -> bytes | None:
    """Retourne le bfevfl patché, ou None si le kit y est déjà."""
    flow = EventFlow()
    flow.read(flow_bytes)
    fc = flow.flowchart

    for ev in fc.events:
        d = ev.data
        if isinstance(d, ActionEvent) and d.params and \
                str(d.params.data.get("PorchItemName", "")) == _MARKER:
            return None                                   # déjà patché (layering)

    # ancre = la chaîne de flags du RANDO : Demo_FlagON(FindDungeon_Activated) → … → FIN.
    anchor = None
    for ev in fc.events:
        d = ev.data
        if isinstance(d, ActionEvent) and d.params and \
                str(d.params.data.get("FlagName", "")) == ANCHOR_FLAG:
            anchor = ev
            break
    if anchor is None:
        raise PatchError(f"{FLOW_INNER}: marqueur rando {ANCHOR_FLAG} absent — ce patch "
                         "s'applique à la copie DU RANDO (lance via pack_builder/play_local)")
    # queue de la chaîne (suit les nxt d'ActionEvent jusqu'à FIN)
    tail = anchor
    for _ in range(64):
        d = tail.data
        if not isinstance(d, ActionEvent) or d.nxt.v is None:
            break
        tail = d.nxt.v
    if not isinstance(tail.data, ActionEvent):
        raise PatchError(f"{FLOW_INNER}: queue de chaîne inattendue après {ANCHOR_FLAG}")

    esa = fc.find_actor(ActorIdentifier("EventSystemActor"))
    for action_name in ("Demo_IncreasePorchItem", "Demo_WaitFrame"):
        if not any(a.v == action_name for a in esa.actions):
            esa.actions.append(StringHolder(action_name))
    give = esa.find_action("Demo_IncreasePorchItem")
    wait = esa.find_action("Demo_WaitFrame")

    def _action(name: str, action, params: dict, nxt) -> Event:
        ev = Event()
        ev.name = name
        ev.data = ActionEvent()
        ev.data.actor = make_rindex(esa)
        ev.data.actor_action = make_rindex(action)
        ev.data.params = Container()
        ev.data.params.data = dict(params)
        if nxt is not None:
            ev.data.nxt = make_index(nxt)
        fc.events.append(ev)
        return ev

    # chaîne construite à l'envers : dernier item → FIN, puis remontée jusqu'au délai
    nxt = None
    for i, (item, amount) in enumerate(reversed(KIT)):
        nxt = _action(f"BOTWSK{len(KIT) - 1 - i}", give,
                      {"IsWaitFinish": True, "PorchItemName": item, "Value": amount}, nxt)
    delay = _action("BOTWSKW", wait, {"IsWaitFinish": True, "Frame": DELAY_FRAMES}, nxt)
    tail.data.nxt = make_index(delay)

    buf = io.BytesIO()
    flow.write(buf)
    return buf.getvalue()


def build(read_source, log=print) -> dict[str, bytes]:
    raw = read_source(EVENTPACK_REL)
    dec = bytes(oead.yaz0.decompress(raw)) if raw[:4] == b"Yaz0" else raw
    sarc = oead.Sarc(dec)
    inner = next((f for f in sarc.get_files() if f.name == FLOW_INNER), None)
    if inner is None:
        raise PatchError(f"{FLOW_INNER} absent de {EVENTPACK_REL}")

    patched = _patched_flow(bytes(inner.data))
    if patched is None:
        log(f"    {EVENTPACK_REL}: kit déjà présent — inchangé")
        return {}

    # vérif : re-parse + la chaîne rando débouche sur délai puis kit COMPLET puis FIN
    reparsed = EventFlow()
    reparsed.read(patched)
    fc = reparsed.flowchart
    anchor = next(ev for ev in fc.events
                  if isinstance(ev.data, ActionEvent) and ev.data.params and
                  str(ev.data.params.data.get("FlagName", "")) == ANCHOR_FLAG)
    cur, hops = anchor, 0
    while isinstance(cur.data, ActionEvent) and cur.data.nxt.v is not None and hops < 64:
        cur = cur.data.nxt.v
        hops += 1
        if cur.name == "BOTWSKW":
            break
    if cur.name != "BOTWSKW":
        raise PatchError("vérif échouée : le délai BOTWSKW n'est pas atteignable depuis l'ancre")
    given = []
    cur = cur.data.nxt.v
    while cur is not None and isinstance(cur.data, ActionEvent):
        given.append((str(cur.data.params.data["PorchItemName"]),
                      int(cur.data.params.data["Value"])))
        cur = cur.data.nxt.v
    if given != KIT or cur is not None:
        raise PatchError(f"vérif échouée : chaîne kit incorrecte ({given})")

    writer = oead.SarcWriter.from_sarc(sarc)
    writer.set_mode(oead.SarcWriter.Mode.Legacy)
    writer.files[FLOW_INNER] = oead.Bytes(patched)
    _, data = writer.write()
    log(f"    {EVENTPACK_REL}: kit ({len(KIT)} items) en queue du réveil rando "
        f"(après {ANCHOR_FLAG}, délai {DELAY_FRAMES} frames)")
    return {EVENTPACK_REL: bytes(oead.yaz0.compress(bytes(data)))}
