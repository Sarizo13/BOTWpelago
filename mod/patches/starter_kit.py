"""
Patch « kit de départ » — débloque TOUS les onglets de la sacoche dès le réveil.

Problème : un item AP livré dans une catégorie VIDE (jamais débloquée) reste invisible
jusqu'au reload (onglet grisé — couche ksys::ui non rafraîchissable de l'extérieur,
investigué côté client et différé). Idée du joueur : débloquer les sections au démarrage,
comme le rando valide la tour du Prélude.

Solution : greffer en TÊTE de l'entry `CommonFirst` de `Demo003_0.bfevfl` (l'événement du
SOCLE de la tablette Sheikah — premier téléchargement de la partie, une seule fois, c'est
là que le rando pose les flags des runes) une chaîne de `Demo_IncreasePorchItem` silencieux :
un item humble par onglet. Grant NATIF → le jeu construit ses onglets normalement → plus
jamais de catégorie grisée, et les livraisons AP tombent toujours dans des listes non vides.

Layering : on patche la copie DU RANDO (préservée), et pack_builder ré-applique après
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
DESCRIPTION = ("Kit de départ au socle de la tablette : 1 item par onglet de sacoche — "
               "plus de catégorie grisée, les livraisons AP tombent en liste non vide.")

EVENTPACK_REL = "Event/Demo003_0.sbeventpack"
FLOW_INNER = "EventFlow/Demo003_0.bfevfl"
ENTRY = "CommonFirst"

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

    esa = fc.find_actor(ActorIdentifier("EventSystemActor"))
    if not any(a.v == "Demo_IncreasePorchItem" for a in esa.actions):
        esa.actions.append(StringHolder("Demo_IncreasePorchItem"))
    give = esa.find_action("Demo_IncreasePorchItem")

    entry = next((e for e in fc.entry_points if e.name == ENTRY), None)
    if entry is None:
        raise PatchError(f"entry {ENTRY} absente de {FLOW_INNER} "
                         "(structure rando inattendue)")

    # chaîne construite à l'envers, dernier item → ancienne tête de l'entry
    nxt = entry.main_event.v
    for i, (item, amount) in enumerate(reversed(KIT)):
        ev = Event()
        ev.name = f"BOTWSK{len(KIT) - 1 - i}"
        ev.data = ActionEvent()
        ev.data.actor = make_rindex(esa)
        ev.data.actor_action = make_rindex(give)
        ev.data.params = Container()
        ev.data.params.data = {"IsWaitFinish": True, "PorchItemName": item,
                               "Value": amount}
        ev.data.nxt = make_index(nxt)
        fc.events.append(ev)
        nxt = ev
    entry.main_event = make_index(nxt)

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

    # vérif : re-parse + le kit est bien en tête de l'entry
    reparsed = EventFlow()
    reparsed.read(patched)
    ep = next(e for e in reparsed.flowchart.entry_points if e.name == ENTRY)
    head = ep.main_event.v
    if not (isinstance(head.data, ActionEvent) and head.data.params and
            str(head.data.params.data.get("PorchItemName", "")) == _MARKER):
        raise PatchError("vérif échouée : le kit n'est pas en tête de l'entry")

    writer = oead.SarcWriter.from_sarc(sarc)
    writer.set_mode(oead.SarcWriter.Mode.Legacy)
    writer.files[FLOW_INNER] = oead.Bytes(patched)
    _, data = writer.write()
    log(f"    {EVENTPACK_REL}: kit de {len(KIT)} items en tête de {ENTRY}")
    return {EVENTPACK_REL: bytes(oead.yaz0.compress(bytes(data)))}
