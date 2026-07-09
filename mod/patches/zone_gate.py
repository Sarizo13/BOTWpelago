"""
Patch « zone gate » — PROTOTYPE : gate d'Eldin par téléport (style forêt perdue).

Mécanisme (100 % data, décodé du vanilla — cf. mod/README.md §4) :
  Area (volume) --BasicSig--> LinkTagOr --BasicSig--> EventTag{EventFlowName,EntryName}
  → lance notre flowchart : CheckFlag(armure) → si absente, warp vers un point sûr.

Ce patch produit TROIS fichiers :
  1. Event/BOTWpelago_Gate.sbeventpack   — NOUVEAU : flowchart 100 % à nous (construit
     from scratch avec evfl : Switch CheckFlag → WaitFrame → WarpToDestination → WaitFrame)
  2. Pack/Bootup.pack                    — EventInfo.product.sbyml + entrée
     `BOTWpelago_Gate<Gate_Eldin>` (schéma relevé des 5 784 entrées vanilla)
  3. Pack/TitleBG.pack                   — Area/LinkTagOr/EventTag ajoutés à
     `Map/MainField/H-3/H-3_Static.smubin` DANS TitleBG.pack (74 Mo) : TOUS les
     chaînages de trigger vanilla vivent dans les _Static packés — une Area posée en
     Dynamic (1re tentative) ne se déclenchait pas in-game. Entrée de la Montagne de la
     Mort (2404, 230, −1320 ; sol ≈226) ; renvoi au Relais du Pied-de-Mont (2612, 254, −1144).

Condition : `IsGet_Armor_011_Upper` (plastron Flamebreaker). Le client devra poser les
flags IsGet_Armor_* à la livraison des sets AP.
À VALIDER IN-GAME : re-déclenchement à la ré-entrée, timing du warp, comportement en vol.
"""
from __future__ import annotations

import io
import zlib

import oead
from evfl import EventFlow
from evfl.actor import Actor
from evfl.common import ActorIdentifier, StringHolder
from evfl.container import Container
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, Event, SwitchEvent
from evfl.flowchart import Flowchart
from evfl.util import make_index, make_rindex

from . import PatchError

NAME = "zone-gate-eldin-poc"
DESCRIPTION = ("Gate d'Eldin par téléport (PoC) : sans le plastron Flamebreaker, entrer "
               "par la Montagne de la Mort renvoie au Relais du Pied-de-Mont.")

FLOW_NAME = "BOTWpelago_Gate"
ENTRY_NAME = "Gate_Eldin"
GATE_FLAG = "IsGet_Armor_011_Upper"          # Flamebreaker Armor (plastron)

AREA_POS = (2404.0, 230.0, -1320.0)          # Death Mountain Entrance (sol ≈226)
AREA_RADIUS = 45.0
WARP_DEST = (2612.0, 254.5, -1144.0)         # Relais du Pied-de-Mont
WARP_DIR_Y = 140.0

TITLEBG_REL = "Pack/TitleBG.pack"
MUBIN_INNER = "Map/MainField/H-3/H-3_Static.smubin"
BOOTUP_REL = "Pack/Bootup.pack"
EVENTPACK_REL = f"Event/{FLOW_NAME}.sbeventpack"


def _hash_id(seed: str) -> int:
    return zlib.crc32(seed.encode()) & 0xFFFFFFFF


# ── 1) flowchart (from scratch, contenu 100 % à nous) ────────────────────────────

def build_flow_bytes() -> bytes:
    flow = EventFlow()
    flow.name = FLOW_NAME
    fc = Flowchart()
    fc.name = FLOW_NAME
    flow.flowchart = fc

    actor = Actor()
    actor.identifier = ActorIdentifier("EventSystemActor")
    actor.actions = [StringHolder("Demo_WarpPlayerToDestination"),
                     StringHolder("Demo_WaitFrame")]
    actor.queries = [StringHolder("CheckFlag")]
    fc.actors.append(actor)

    def action(name: str, params: dict, nxt: Event | None) -> Event:
        ev = Event()
        ev.data = ActionEvent()
        ev.data.actor = make_rindex(actor)
        ev.data.actor_action = make_rindex(actor.find_action(name))
        ev.data.params = Container()
        ev.data.params.data = dict(params)
        ev.data.nxt = make_index(nxt)
        fc.events.append(ev)
        return ev

    # chaîne d'actions encadrée de WaitFrame (quirk BotW, cf. evfl botw_add_action_chain)
    wait_end = action("Demo_WaitFrame", {"IsWaitFinish": True, "Frame": 1}, None)
    warp = action("Demo_WarpPlayerToDestination",
                  {"IsWaitFinish": True,
                   "DestinationX": WARP_DEST[0], "DestinationY": WARP_DEST[1],
                   "DestinationZ": WARP_DEST[2], "DirectionY": WARP_DIR_Y},
                  wait_end)
    wait_start = action("Demo_WaitFrame", {"IsWaitFinish": True, "Frame": 1}, warp)

    check = Event()
    check.data = SwitchEvent()
    check.data.actor = make_rindex(actor)
    check.data.actor_query = make_rindex(actor.find_query("CheckFlag"))
    check.data.params = Container()
    check.data.params.data = {"FlagName": GATE_FLAG}
    check.data.cases = {0: make_rindex(wait_start)}     # 0 = flag absent → warp ; 1 → rien
    fc.events.append(check)

    for i, ev in enumerate(fc.events):
        ev.name = f"Event{i}"

    ep = EntryPoint(ENTRY_NAME)
    ep.main_event = make_index(check)
    fc.entry_points.append(ep)

    buf = io.BytesIO()
    flow.write(buf)
    return buf.getvalue()


# ── 2) EventInfo (Bootup.pack) ────────────────────────────────────────────────────

def patched_eventinfo(data: bytes) -> bytes:
    info = oead.byml.from_binary(bytes(oead.yaz0.decompress(data)) if data[:4] == b"Yaz0" else data)
    key = f"{FLOW_NAME}<{ENTRY_NAME}>"
    # idempotent : la source peut être notre propre build précédent (layering) → on écrase
    info[key] = oead.byml.Hash({
        "is_startable_air": True,          # le joueur peut arriver en paravoile
        "is_timeline": False,
        "mode": "Seamless",
        "vanish_motorcycle": True,
    })
    out = oead.byml.to_binary(info, big_endian=True)
    return bytes(oead.yaz0.compress(out))


# ── 3) mubin (Area → LinkTagOr → EventTag) ─────────────────────────────────────────

def patched_mubin(data: bytes) -> bytes:
    mubin = oead.byml.from_binary(bytes(oead.yaz0.decompress(data)) if data[:4] == b"Yaz0" else data)
    objs = mubin["Objs"]
    ids = {kind: _hash_id(f"BOTWpelago_ZoneGate_Eldin_{kind}")
           for kind in ("area", "link", "tag")}

    # idempotent : retire nos objets d'un build précédent avant de les re-poser
    ours = set(ids.values())
    keep = [o for o in objs if not ("HashId" in o and int(o["HashId"]) in ours)]
    if len(keep) != len(objs):
        mubin["Objs"] = oead.byml.Array(keep)
        objs = mubin["Objs"]

    def f3(x, y, z):
        return oead.byml.Array([oead.F32(x), oead.F32(y), oead.F32(z)])

    def link_to(dest: int):
        return oead.byml.Array([oead.byml.Hash({
            "DefinitionName": "BasicSig",
            "DestUnitHashId": oead.U32(dest),
        })])

    x, y, z = AREA_POS
    area = oead.byml.Hash({
        "!Parameters": oead.byml.Hash({
            "AutoSave": False, "CameraPriority": oead.S32(1), "CameraSet": "-",
            "ForceCalcInEvent": False, "Shape": "Sphere",
        }),
        "HashId": oead.U32(ids["area"]),
        "SRTHash": oead.S32(ids["area"] & 0x7FFFFFFF),
        "LinksToObj": link_to(ids["link"]),
        "Scale": oead.F32(AREA_RADIUS),
        "Translate": f3(x, y, z),
        "UnitConfigName": "Area",
    })
    link = oead.byml.Hash({
        "!Parameters": oead.byml.Hash({
            "IncrementSave": False, "MakeSaveFlag": oead.S32(0),
            "NoChangeSignal": False, "SaveFlagOnOffType": oead.S32(0),
        }),
        "HashId": oead.U32(ids["link"]),
        "SRTHash": oead.S32(ids["link"] & 0x7FFFFFFF),
        "LinksToObj": link_to(ids["tag"]),
        "Translate": f3(x, y + 10.0, z),
        "UnitConfigName": "LinkTagOr",
    })
    tag = oead.byml.Hash({
        "!Parameters": oead.byml.Hash({
            "EventFlowEntryName": ENTRY_NAME,
            "EventFlowName": FLOW_NAME,
            "IsEndlessEvent": False,
            "LaunchEventByOffSignal": False,
            "LaunchEventByOnSignal": True,
        }),
        "HashId": oead.U32(ids["tag"]),
        "SRTHash": oead.S32(ids["tag"] & 0x7FFFFFFF),
        "Translate": f3(x, y + 20.0, z),
        "UnitConfigName": "EventTag",
    })
    for o in (area, link, tag):
        objs.append(o)
    out = oead.byml.to_binary(mubin, big_endian=True)
    return bytes(oead.yaz0.compress(out))


# ── build : rel_path → bytes ──────────────────────────────────────────────────────

def build(read_source, log=print) -> dict[str, bytes]:
    """`read_source(rel) -> bytes` lit un fichier du dump (update > base)."""
    out: dict[str, bytes] = {}

    # 1) event pack (SARC BE, mode Legacy, Yaz0)
    flow_bytes = build_flow_bytes()
    reparsed = EventFlow()
    reparsed.read(flow_bytes)                       # vérif : parse-back
    eps = [e.name for e in reparsed.flowchart.entry_points]
    if eps != [ENTRY_NAME]:
        raise PatchError(f"flowchart invalide (entry points : {eps})")
    writer = oead.SarcWriter(oead.Endianness.Big, oead.SarcWriter.Mode.Legacy)
    writer.files[f"EventFlow/{FLOW_NAME}.bfevfl"] = oead.Bytes(flow_bytes)
    _, sarc_data = writer.write()
    out[EVENTPACK_REL] = bytes(oead.yaz0.compress(bytes(sarc_data)))
    log(f"    {EVENTPACK_REL}: flowchart {len(flow_bytes)} octets, parse-back OK")

    # 2) Bootup.pack avec EventInfo enrichi
    bootup = oead.Sarc(read_source(BOOTUP_REL))
    ei = next((f for f in bootup.get_files() if f.name == "Event/EventInfo.product.sbyml"), None)
    if ei is None:
        raise PatchError("EventInfo.product.sbyml absent de Bootup.pack")
    new_ei = patched_eventinfo(bytes(ei.data))
    bw = oead.SarcWriter.from_sarc(bootup)
    bw.set_mode(oead.SarcWriter.Mode.Legacy)
    bw.files["Event/EventInfo.product.sbyml"] = oead.Bytes(new_ei)
    _, bootup_data = bw.write()
    out[BOOTUP_REL] = bytes(bootup_data)
    log(f"    {BOOTUP_REL}: EventInfo + {FLOW_NAME}<{ENTRY_NAME}>")

    # 3) mubin Static DANS TitleBG.pack (les triggers vanilla vivent là)
    titlebg = oead.Sarc(read_source(TITLEBG_REL))
    inner = next((f for f in titlebg.get_files() if f.name == MUBIN_INNER), None)
    if inner is None:
        raise PatchError(f"{MUBIN_INNER} absent de TitleBG.pack")
    new_mubin = patched_mubin(bytes(inner.data))
    oead.byml.from_binary(bytes(oead.yaz0.decompress(new_mubin)))   # vérif parse-back
    tw = oead.SarcWriter.from_sarc(titlebg)
    tw.set_mode(oead.SarcWriter.Mode.Legacy)
    tw.files[MUBIN_INNER] = oead.Bytes(new_mubin)
    _, titlebg_data = tw.write()
    out[TITLEBG_REL] = bytes(titlebg_data)
    log(f"    {TITLEBG_REL}: {MUBIN_INNER} +Area/LinkTagOr/EventTag @ {AREA_POS} (r={AREA_RADIUS})")

    return out
