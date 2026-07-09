"""
Patch « zone gates » — murs de régions par téléport (style forêt perdue), data-driven.

Source : mod/data/zone_walls.json (polylignes MONDE digitalisées depuis les tracés du
joueur ; destinations = refuges hors murs). Pour chaque région :
  - un entry point `Gate_<région>` dans Event/BOTWpelago_Gate.sbeventpack :
    CheckFlag(armure) → [cheval : descendre | sol : Join | air : rien] → FadeOut →
    WarpToDestination → [encore en l'air : attente] → caméra → FadeIn → bannière.
  - le long de chaque mur : boîtes `Area` (hautes = anti-paravoile) → LinkTagOr →
    EventTag(Gate_<région>) par carré traversé, injectés dans les `_Static.smubin`
    de la couche AOC (celle que le jeu lit avec le DLC).

Toutes les leçons in-game (v3→v5.2) sont encodées ici : params d'acteurs OBLIGATOIRES,
Fader Frame=0, jamais Demo_StopInAir (gèle le joueur), descente paravoile derrière le
noir, monture descendue avant warp, bannière Demo_OpenDungeonMessage + MSBT attr 0x0C,
RSTB à jour pour chaque ressource (sinon crash au boot).

HashIds : plage réservée 0xB0730000+ (idempotence : purge de la plage avant ré-ajout).
"""
from __future__ import annotations

import io
import json
import math
import zlib
from pathlib import Path

import oead
from evfl import EventFlow
from evfl.actor import Actor
from evfl.common import ActorIdentifier, StringHolder
from evfl.container import Container
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, Event, SwitchEvent
from evfl.flowchart import Flowchart
from evfl.util import make_index, make_rindex

from msbt import build_msbt

from . import FlowPatch, PatchError  # noqa: F401  (PatchError utilisé, FlowPatch pour l'API)

NAME = "zone-gates"
DESCRIPTION = ("Murs de régions par téléport : Eldin/Rito/Zora/Gerudo — sans la tenue "
               "requise, franchir le mur renvoie au refuge de la région (fade + message).")

FLOW_NAME = "BOTWpelago_Gate"
MSG_LABEL = "Gate_NoGear"
MSG_TEXTS = {"EUfr": "Il vous manque l'équipement pour cette zone."}
MSG_DEFAULT = "You lack the gear required for this area."
EU_LANGS = ("EUen", "EUfr", "EUde", "EUes", "EUit", "EUnl", "EUru")
FADE_FRAMES = 0                     # vanilla : toujours 0 (≠0 avec IsWaitFinish = stall)

BOOTUP_REL = "Pack/Bootup.pack"
EVENTPACK_REL = f"Event/{FLOW_NAME}.sbeventpack"

WALLS = json.loads((Path(__file__).resolve().parents[1] / "data" / "zone_walls.json")
                   .read_text(encoding="utf-8"))

# Plage de HashId réservée au mod (purge idempotente) + ids hérités du PoC mono-gate.
HASH_BASE = 0xB0730000
HASH_END = 0xB0740000
_LEGACY_IDS = {zlib.crc32(f"BOTWpelago_ZoneGate_Eldin_{k}".encode()) & 0xFFFFFFFF
               for k in ("area", "link", "tag")}

RSTB_PACK_INNER = {
    f"Pack/Bootup_{lang}.pack": [f"Message/Msg_{lang}.product.ssarc"]
    for lang in EU_LANGS
}


# ── flowchart : un entry point par région ─────────────────────────────────────────

def build_flow_bytes() -> bytes:
    flow = EventFlow()
    flow.name = FLOW_NAME
    fc = Flowchart()
    fc.name = FLOW_NAME
    flow.flowchart = fc

    _BASE_ACTOR_PARAMS = {
        "CreateMode": 0, "IsGrounding": False, "IsWorld": False,
        "PosX": 0.0, "PosY": 0.0, "PosZ": 0.0,
        "RotX": 0.0, "RotY": 0.0, "RotZ": 0.0,
    }

    def make_actor(name: str, actions: list[str], queries: list[str] = (),
                   extra_params: dict | None = None) -> Actor:
        a = Actor()
        a.identifier = ActorIdentifier(name)
        a.actions = [StringHolder(x) for x in actions]
        a.queries = [StringHolder(x) for x in queries]
        a.params = Container()
        a.params.data = dict(_BASE_ACTOR_PARAMS, **(extra_params or {}))
        a.concurrent_clips = 1
        fc.actors.append(a)
        return a

    esa = make_actor("EventSystemActor",
                     ["Demo_WarpPlayerToDestination", "Demo_WaitFrame",
                      "Demo_OpenDungeonMessage"],
                     ["CheckFlag", "CheckPlayerState", "CheckPlayerRideHorse"])
    player = make_actor("GameROMPlayer",
                        ["Demo_PlayerWait", "Demo_Join", "Demo_PlayerHorseGetOff"],
                        extra_params={
                            "Weapon": "", "DisableWeapon": False,
                            "Shield": "", "DisableShield": False,
                            "Bow": "", "DisableBow": False,
                            "ArmorHead": "", "ArmorUpper": "", "ArmorLower": "",
                            "DisableSheikPad": False,
                        })
    fader = make_actor("Fader", ["Demo_FadeOut", "Demo_FadeIn"])
    camera = make_actor("GameRomCamera", ["Demo_GameCamera"])

    def action(actor: Actor, name: str, params: dict, nxt: Event | None) -> Event:
        ev = Event()
        ev.data = ActionEvent()
        ev.data.actor = make_rindex(actor)
        ev.data.actor_action = make_rindex(actor.find_action(name))
        ev.data.params = Container()
        ev.data.params.data = dict(params)
        ev.data.nxt = make_index(nxt)
        fc.events.append(ev)
        return ev

    def switch(query: str, params: dict, cases: dict) -> Event:
        ev = Event()
        ev.data = SwitchEvent()
        ev.data.actor = make_rindex(esa)
        ev.data.actor_query = make_rindex(esa.find_query(query))
        ev.data.params = Container()
        ev.data.params.data = dict(params)
        ev.data.cases = {k: make_rindex(v) for k, v in cases.items()}
        fc.events.append(ev)
        return ev

    for region in sorted(WALLS["regions"]):
        cfg = WALLS["regions"][region]
        wx, wy, wz = cfg["warp"]["pos"]

        wait_end = action(esa, "Demo_WaitFrame", {"IsWaitFinish": True, "Frame": 1}, None)
        banner = action(esa, "Demo_OpenDungeonMessage",
                        {"IsWaitFinish": True,
                         "MessageId": f"EventFlowMsg/{FLOW_NAME}:{MSG_LABEL}"},
                        wait_end)
        fadein = action(fader, "Demo_FadeIn",
                        {"IsWaitFinish": True, "Frame": FADE_FRAMES, "Color": 1,
                         "DispMode": "Auto"}, banner)
        cam = action(camera, "Demo_GameCamera", {"IsWaitFinish": True}, fadein)
        wait_air = action(esa, "Demo_WaitFrame", {"IsWaitFinish": True, "Frame": 120}, cam)
        post_air = switch("CheckPlayerState", {"PlayerState": 5}, {1: cam, 0: wait_air})
        wait_post = action(esa, "Demo_WaitFrame", {"IsWaitFinish": True, "Frame": 40},
                           post_air)
        warp = action(esa, "Demo_WarpPlayerToDestination",
                      {"IsWaitFinish": True, "DestinationX": wx, "DestinationY": wy,
                       "DestinationZ": wz, "DirectionY": cfg["warp"]["dir"]},
                      wait_post)
        fadeout = action(fader, "Demo_FadeOut",
                         {"IsWaitFinish": True, "Frame": FADE_FRAMES, "Color": 1,
                          "DispMode": "Auto"}, warp)
        join = action(player, "Demo_Join", {"IsWaitFinish": True}, fadeout)
        state5 = switch("CheckPlayerState", {"PlayerState": 5}, {1: join, 0: fadeout})
        wait15 = action(esa, "Demo_WaitFrame", {"IsWaitFinish": True, "Frame": 15}, state5)
        pwait = action(player, "Demo_PlayerWait", {"IsWaitFinish": True}, wait15)
        get_off = action(player, "Demo_PlayerHorseGetOff", {"IsWaitFinish": True}, pwait)
        horse = switch("CheckPlayerRideHorse", {}, {1: get_off, 0: state5})
        check = switch("CheckFlag", {"FlagName": cfg["flag"]}, {0: horse})

        ep = EntryPoint(f"Gate_{region}")
        ep.main_event = make_index(check)
        fc.entry_points.append(ep)

    for i, ev in enumerate(fc.events):
        ev.name = f"Event{i}"

    buf = io.BytesIO()
    flow.write(buf)
    return buf.getvalue()


# ── EventInfo : une entrée par région ─────────────────────────────────────────────

def patched_eventinfo(data: bytes) -> bytes:
    info = oead.byml.from_binary(bytes(oead.yaz0.decompress(data)) if data[:4] == b"Yaz0" else data)
    for region in WALLS["regions"]:
        info[f"{FLOW_NAME}<Gate_{region}>"] = oead.byml.Hash({
            "is_startable_air": True,
            "is_timeline": False,
            "mode": "Seamless",
            "vanish_motorcycle": True,
        })
    out = oead.byml.to_binary(info, big_endian=True)
    return bytes(oead.yaz0.compress(out))


# ── packs de langue (bannière) ────────────────────────────────────────────────────

def patched_langpack(data: bytes, lang: str) -> bytes:
    pack = oead.Sarc(data)
    msg_name = f"Message/Msg_{lang}.product.ssarc"
    inner = next((f for f in pack.get_files() if f.name == msg_name), None)
    if inner is None:
        raise PatchError(f"{msg_name} absent de Bootup_{lang}.pack")
    msg = oead.Sarc(bytes(oead.yaz0.decompress(bytes(inner.data))))
    mw = oead.SarcWriter.from_sarc(msg)
    mw.set_mode(oead.SarcWriter.Mode.Legacy)
    text = MSG_TEXTS.get(lang, MSG_DEFAULT)
    mw.files[f"EventFlowMsg/{FLOW_NAME}.msbt"] = oead.Bytes(build_msbt({MSG_LABEL: text}))
    _, msg_out = mw.write()
    pw = oead.SarcWriter.from_sarc(pack)
    pw.set_mode(oead.SarcWriter.Mode.Legacy)
    pw.files[msg_name] = oead.Bytes(bytes(oead.yaz0.compress(bytes(msg_out))))
    _, out = pw.write()
    return bytes(out)


# ── géométrie : polylignes → boîtes par carré ─────────────────────────────────────

def _square_of(x: float, z: float) -> str:
    col = "ABCDEFGHIJ"[max(0, min(9, int((x + 5000) // 1000)))]
    row = max(1, min(8, int((z + 4000) // 1000) + 1))
    return f"{col}-{row}"


def wall_objects() -> dict[str, list]:
    """Retourne {carré: [objets byml]} — boîtes + LinkTagOr + EventTag par (région, carré)."""
    spacing = float(WALLS["box"]["spacing"])
    base_hlen = float(WALLS["box"]["half_len"])

    # boxes[(region, carré)] = [(x, z, yaw, hw, yc, yh, hl), …]
    boxes: dict[tuple[str, str], list] = {}
    for region in sorted(WALLS["regions"]):
        for wall in WALLS["regions"][region]["walls"]:
            pts = [tuple(map(float, p)) for p in wall["points"]]
            if wall.get("closed"):
                pts.append(pts[0])
            yc, yh = float(wall["y_center"]), float(wall["y_half"])
            hw = float(wall["half_width"])
            for (x0, z0), (x1, z1) in zip(pts, pts[1:]):
                dx, dz = x1 - x0, z1 - z0
                seg = math.hypot(dx, dz)
                if seg < 1:
                    continue
                n = max(1, math.ceil(seg / spacing))
                yaw = math.atan2(dx, dz)
                hl = max(base_hlen, seg / n * 0.75)
                for i in range(n):
                    t = (i + 0.5) / n
                    cx, cz = x0 + dx * t, z0 + dz * t
                    boxes.setdefault((region, _square_of(cx, cz)), []).append(
                        (cx, cz, yaw, hw, yc, yh, hl))

    def f3(x, y, z):
        return oead.byml.Array([oead.F32(x), oead.F32(y), oead.F32(z)])

    def link_to(dest: int):
        return oead.byml.Array([oead.byml.Hash({
            "DefinitionName": "BasicSig", "DestUnitHashId": oead.U32(dest)})])

    out: dict[str, list] = {}
    hid = HASH_BASE
    for (region, square), blist in sorted(boxes.items()):
        objs = out.setdefault(square, [])
        tag_id = hid
        hid += 1
        link_id = hid
        hid += 1
        mx = sum(b[0] for b in blist) / len(blist)
        mz = sum(b[1] for b in blist) / len(blist)
        my = sum(b[4] for b in blist) / len(blist)
        for (cx, cz, yaw, hw, yc, yh, hl) in blist:
            objs.append(oead.byml.Hash({
                "!Parameters": oead.byml.Hash({
                    "AutoSave": False, "CameraPriority": oead.S32(1), "CameraSet": "-",
                    "ForceCalcInEvent": False, "Shape": "Box",
                }),
                "HashId": oead.U32(hid),
                "SRTHash": oead.S32(hid & 0x7FFFFFFF),
                "LinksToObj": link_to(link_id),
                "Rotate": oead.F32(yaw),
                "Scale": f3(hw, yh, hl),
                "Translate": f3(cx, yc, cz),
                "UnitConfigName": "Area",
            }))
            hid += 1
        objs.append(oead.byml.Hash({
            "!Parameters": oead.byml.Hash({
                "IncrementSave": False, "MakeSaveFlag": oead.S32(0),
                "NoChangeSignal": False, "SaveFlagOnOffType": oead.S32(0),
            }),
            "HashId": oead.U32(link_id),
            "SRTHash": oead.S32(link_id & 0x7FFFFFFF),
            "LinksToObj": link_to(tag_id),
            "Translate": f3(mx, my + 10.0, mz),
            "UnitConfigName": "LinkTagOr",
        }))
        objs.append(oead.byml.Hash({
            "!Parameters": oead.byml.Hash({
                "EventFlowEntryName": f"Gate_{region}",
                "EventFlowName": FLOW_NAME,
                "IsEndlessEvent": False,
                "LaunchEventByOffSignal": False,
                "LaunchEventByOnSignal": True,
            }),
            "HashId": oead.U32(tag_id),
            "SRTHash": oead.S32(tag_id & 0x7FFFFFFF),
            "Translate": f3(mx, my + 20.0, mz),
            "UnitConfigName": "EventTag",
        }))
    if hid >= HASH_END:
        raise PatchError(f"plage HashId dépassée ({hid - HASH_BASE} objets)")
    return out


def patched_mubin(data: bytes, new_objs: list) -> bytes:
    mubin = oead.byml.from_binary(bytes(oead.yaz0.decompress(data)) if data[:4] == b"Yaz0" else data)
    objs = mubin["Objs"]
    keep = [o for o in objs
            if not ("HashId" in o and (HASH_BASE <= int(o["HashId"]) < HASH_END
                                       or int(o["HashId"]) in _LEGACY_IDS))]
    existing = {int(o["HashId"]) for o in keep if "HashId" in o}
    for o in new_objs:
        if int(o["HashId"]) in existing:
            raise PatchError(f"collision HashId {int(o['HashId']):#x} avec le vanilla")
        keep.append(o)
    mubin["Objs"] = oead.byml.Array(keep)
    out = oead.byml.to_binary(mubin, big_endian=True)
    return bytes(oead.yaz0.compress(out))


# ── build ─────────────────────────────────────────────────────────────────────────

def build(read_source, log=print) -> dict[str, bytes]:
    out: dict[str, bytes] = {}

    # 1) flowchart (parse-back + entrées vérifiées)
    flow_bytes = build_flow_bytes()
    reparsed = EventFlow()
    reparsed.read(flow_bytes)
    eps = sorted(e.name for e in reparsed.flowchart.entry_points)
    expected = sorted(f"Gate_{r}" for r in WALLS["regions"])
    if eps != expected:
        raise PatchError(f"entry points inattendus : {eps}")
    writer = oead.SarcWriter(oead.Endianness.Big, oead.SarcWriter.Mode.Legacy)
    writer.files[f"EventFlow/{FLOW_NAME}.bfevfl"] = oead.Bytes(flow_bytes)
    _, sarc_data = writer.write()
    out[EVENTPACK_REL] = bytes(oead.yaz0.compress(bytes(sarc_data)))
    log(f"    {EVENTPACK_REL}: {len(eps)} régions, flowchart {len(flow_bytes)} octets")

    # 2) EventInfo
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
    log(f"    {BOOTUP_REL}: EventInfo + {len(WALLS['regions'])} entrées Gate_*")

    # 3) packs de langue
    for lang in EU_LANGS:
        rel = f"Pack/Bootup_{lang}.pack"
        try:
            src = read_source(rel)
        except FileNotFoundError:
            continue
        out[rel] = patched_langpack(src, lang)
    log(f"    packs de langue : EventFlowMsg/{FLOW_NAME}.msbt ({MSG_LABEL})")

    # 4) murs → mubins AOC par carré
    per_square = wall_objects()
    n_objs = sum(len(v) for v in per_square.values())
    for square, objs in sorted(per_square.items()):
        rel = f"aoc/0010/Map/MainField/{square}/{square}_Static.smubin"
        new_mubin = patched_mubin(read_source(rel), objs)
        oead.byml.from_binary(bytes(oead.yaz0.decompress(new_mubin)))   # parse-back
        out[rel] = new_mubin
    log(f"    murs : {n_objs} objets dans {len(per_square)} carrés "
        f"({', '.join(sorted(per_square))})")

    return out
