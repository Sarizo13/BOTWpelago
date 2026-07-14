"""
Patch « kit de départ » — débloque TOUS les onglets de la sacoche dès le socle de la tablette.

Problème : un item AP livré dans un onglet JAMAIS débloqué corrompt la poche (crash plat du
2026-07-14) ; le client REPORTE désormais ces créations (garde « onglet verrouillé »), mais
sans kit les livraisons attendent les premiers ramassages du joueur.

Point d'accroche (RÉVISÉ 2026-07-14) : l'entry `CommonFirst` de `Demo003_0.bfevfl` (variante
« premier téléchargement » du socle) NE JOUE JAMAIS sur une partie moddée — le rando pré-valide
les démos d'intro et la première tour (InitValue `MapTower_DemoFirst`, `IsPlayed_Demo*`), donc
c'est la variante `Common` qui joue au socle de la chambre. Le kit est maintenant greffé sur
LES DEUX entries, gardé par un flag « déjà donné » :

    entry ── Switch CheckFlag(TestQuest_shimizu01_Finish) ──1──> tête d'origine
                        └──0──> kit (8 × Demo_IncreasePorchItem) ─> Demo_FlagON ─> tête d'origine

Le flag de garde = `TestQuest_shimizu01_Finish` : quête de TEST interne Nintendo, bool inerte
présent dans gamedata (vérifié à 0 sur save réelle), jamais posé par le jeu/le rando/le client,
exclu des locations AP (motif TestQuest de build_locations). Même famille que la mailbox du mur
Ganon (`TestQuest_Takano_01_Finish` — NE PAS réutiliser celle-là).

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
from evfl.event import ActionEvent, Event, SwitchEvent
from evfl.util import make_index, make_rindex

from . import PatchError

NAME = "starter-kit"
DESCRIPTION = ("Kit de départ au socle de la tablette : 1 item par onglet de sacoche — "
               "plus de catégorie grisée, les livraisons AP tombent en liste non vide. "
               "Gardé par flag (une seule fois), greffé sur Common ET CommonFirst.")

EVENTPACK_REL = "Event/Demo003_0.sbeventpack"
FLOW_INNER = "EventFlow/Demo003_0.bfevfl"
ENTRIES = ("Common", "CommonFirst")     # Common = ce qui JOUE réellement sur partie moddée
GUARD_FLAG = "TestQuest_shimizu01_Finish"

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
    for action_name in ("Demo_IncreasePorchItem", "Demo_FlagON"):
        if not any(a.v == action_name for a in esa.actions):
            esa.actions.append(StringHolder(action_name))
    if not any(q.v == "CheckFlag" for q in esa.queries):
        esa.queries.append(StringHolder("CheckFlag"))
    give = esa.find_action("Demo_IncreasePorchItem")
    flag_on = esa.find_action("Demo_FlagON")
    check = esa.find_query("CheckFlag")

    def _action(name: str, params: dict, nxt) -> Event:
        ev = Event()
        ev.name = name
        ev.data = ActionEvent()
        ev.data.actor = make_rindex(esa)
        ev.data.params = Container()
        ev.data.params.data = dict(params)
        if nxt is not None:
            ev.data.nxt = make_index(nxt)
        fc.events.append(ev)
        return ev

    for tag, entry_name in (("A", "Common"), ("B", "CommonFirst")):
        entry = next((e for e in fc.entry_points if e.name == entry_name), None)
        if entry is None:
            raise PatchError(f"entry {entry_name} absente de {FLOW_INNER} "
                             "(structure rando inattendue)")
        old_head = entry.main_event.v
        # garde : le kit ne se donne qu'UNE fois (le flag survit dans la save)
        done = _action(f"BOTWSK{tag}F", {"IsWaitFinish": True, "FlagName": GUARD_FLAG},
                       old_head)
        done.data.actor_action = make_rindex(flag_on)
        # chaîne du kit, construite à l'envers : dernier item → Demo_FlagON → tête d'origine
        nxt = done
        for i, (item, amount) in enumerate(reversed(KIT)):
            ev = _action(f"BOTWSK{tag}{len(KIT) - 1 - i}",
                         {"IsWaitFinish": True, "PorchItemName": item, "Value": amount}, nxt)
            ev.data.actor_action = make_rindex(give)
            nxt = ev
        sw = Event()
        sw.name = f"BOTWSK{tag}S"
        sw.data = SwitchEvent()
        sw.data.actor = make_rindex(esa)
        sw.data.actor_query = make_rindex(check)
        sw.data.params = Container()
        sw.data.params.data = {"FlagName": GUARD_FLAG}
        # cases = RequiredIndex (cf. evfl.event.SwitchEvent), pas Index comme nxt
        sw.data.cases = {0: make_rindex(nxt), 1: make_rindex(old_head)}
        fc.events.append(sw)
        entry.main_event = make_index(sw)

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

    # vérif : re-parse + chaque entry commence par le Switch gardé, dont le cas 0 mène au kit
    reparsed = EventFlow()
    reparsed.read(patched)
    for tag, entry_name in (("A", "Common"), ("B", "CommonFirst")):
        ep = next(e for e in reparsed.flowchart.entry_points if e.name == entry_name)
        head = ep.main_event.v
        if not (isinstance(head.data, SwitchEvent) and head.data.params and
                str(head.data.params.data.get("FlagName", "")) == GUARD_FLAG):
            raise PatchError(f"vérif échouée : {entry_name} ne commence pas par le Switch gardé")
        kit_head = head.data.cases[0].v
        if not (isinstance(kit_head.data, ActionEvent) and kit_head.data.params and
                str(kit_head.data.params.data.get("PorchItemName", "")) == _MARKER):
            raise PatchError(f"vérif échouée : le cas 0 de {entry_name} ne mène pas au kit")

    writer = oead.SarcWriter.from_sarc(sarc)
    writer.set_mode(oead.SarcWriter.Mode.Legacy)
    writer.files[FLOW_INNER] = oead.Bytes(patched)
    _, data = writer.write()
    log(f"    {EVENTPACK_REL}: kit gardé ({GUARD_FLAG}) greffé sur "
        f"{' + '.join(ENTRIES)} ({len(KIT)} items)")
    return {EVENTPACK_REL: bytes(oead.yaz0.compress(bytes(data)))}
