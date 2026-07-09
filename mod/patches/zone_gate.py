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

from msbt import build_msbt

from . import PatchError

NAME = "zone-gate-eldin-poc"
DESCRIPTION = ("Gate d'Eldin par téléport (PoC) : sans le plastron Flamebreaker, entrer "
               "par la Montagne de la Mort renvoie au Relais du Pied-de-Mont.")

FLOW_NAME = "BOTWpelago_Gate"
ENTRY_NAME = "Gate_Eldin"
GATE_FLAG = "IsGet_Armor_011_Upper"          # Flamebreaker Armor (plastron)

AREA_POS = (2404.0, 230.0, -1320.0)          # Death Mountain Entrance (sol ≈226)
AREA_RADIUS = 45.0
# Destination en TERRAIN DÉGAGÉ devant le relais (sol ≈253.5) — PAS le bâtiment :
# une arrivée en paravoile sous le toit coinçait Link dans la charpente (test v5).
WARP_DEST = (2578.0, 254.0, -1172.0)
WARP_DIR_Y = 50.0                            # face au relais

MSG_LABEL = "Gate_NoGear"
# Textes COURTS : le halo bleu de la bannière DungeonMessage ne couvre qu'environ
# 45 caractères (test v5 — un texte plus long déborde du halo).
MSG_TEXTS = {                                 # EUfr = joueur ; anglais pour le reste
    "EUfr": "Il vous manque l'équipement pour cette zone.",
}
MSG_DEFAULT = "You lack the gear required for this area."
EU_LANGS = ("EUen", "EUfr", "EUde", "EUes", "EUit", "EUnl", "EUru")
# Fader vanilla : TOUJOURS Frame=0 (ou 1) — ce n'est PAS une durée ; Frame=30 avec
# IsWaitFinish=True bloque l'event indéfiniment (leçon du test v4.1, stall au FadeOut).
# Référence : Electric_Relic_BattleField01 (éjection de zone lancée par tag, comme nous).
FADE_FRAMES = 0

TITLEBG_REL = "Pack/TitleBG.pack"
MUBIN_INNER = "Map/MainField/H-3/H-3_Static.smubin"
# Couche DLC : quand le DLC est monté (cas du joueur), le jeu lit les map units depuis
# l'AOC — c'est là que le rando met ses propres edits de map. SANS cette sortie, le
# patch TitleBG n'est jamais lu (leçon du 2e test in-game).
AOC_MUBIN_REL = "aoc/0010/Map/MainField/H-3/H-3_Static.smubin"
BOOTUP_REL = "Pack/Bootup.pack"
EVENTPACK_REL = f"Event/{FLOW_NAME}.sbeventpack"


def _hash_id(seed: str) -> int:
    return zlib.crc32(seed.encode()) & 0xFFFFFFFF


# ── 1) flowchart (from scratch, contenu 100 % à nous) ────────────────────────────

def build_flow_bytes() -> bytes:
    """Chaîne : CheckFlag(armure)=0 → préambule d'état joueur (réplique EXACTE de la
    routine vanilla Common::AirStartUP_Player : état 4 → PlayerWait ; état 5 (au sol)
    → Demo_Join ; sinon (en l'air) → StopInAir — envoyer StopInAir à un joueur au sol
    BLOQUE l'event, leçon du test v4) → FadeOut → warp → FadeIn → message. Flag → rien."""
    flow = EventFlow()
    flow.name = FLOW_NAME
    fc = Flowchart()
    fc.name = FLOW_NAME
    flow.flowchart = fc

    # Params d'acteur OBLIGATOIRES (relevés sur Electric_Relic vanilla) : sans ce
    # conteneur (CreateMode etc.), le jeu ne LIE jamais l'acteur à l'event → toute
    # action sur lui attend à l'infini (cause des soft-locks v4/v4.1/v4.2).
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
        a.concurrent_clips = 1          # « flowcharts: always = 1 » (evfl) — vanilla = 1
        fc.actors.append(a)
        return a

    esa = make_actor("EventSystemActor",
                     ["Demo_WarpPlayerToDestination", "Demo_WaitFrame",
                      "Demo_OpenDungeonMessage"],
                     ["CheckFlag", "CheckPlayerState", "CheckPlayerRideHorse"])
    player = make_actor("GameROMPlayer",
                        ["Demo_StopInAir", "Demo_PlayerWait", "Demo_Join",
                         "Demo_PlayerHorseGetOff"],
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

    # construite à l'envers (chaque event pointe sur son successeur)
    wait_end = action(esa, "Demo_WaitFrame", {"IsWaitFinish": True, "Frame": 1}, None)
    banner = action(esa, "Demo_OpenDungeonMessage",       # bannière type forêt perdue
                    {"IsWaitFinish": True,
                     "MessageId": f"EventFlowMsg/{FLOW_NAME}:{MSG_LABEL}"},
                    wait_end)
    fadein = action(fader, "Demo_FadeIn",
                    {"IsWaitFinish": True, "Frame": FADE_FRAMES, "Color": 1,
                     "DispMode": "Auto"}, banner)
    cam = action(camera, "Demo_GameCamera", {"IsWaitFinish": True}, fadein)
    # arrivé encore en l'air (paravoile) → on laisse descendre derrière le noir
    wait_air = action(esa, "Demo_WaitFrame", {"IsWaitFinish": True, "Frame": 120}, cam)
    post_air = switch("CheckPlayerState", {"PlayerState": 5}, {1: cam, 0: wait_air})
    wait_post = action(esa, "Demo_WaitFrame", {"IsWaitFinish": True, "Frame": 40},
                       post_air)
    warp = action(esa, "Demo_WarpPlayerToDestination",
                  {"IsWaitFinish": True,
                   "DestinationX": WARP_DEST[0], "DestinationY": WARP_DEST[1],
                   "DestinationZ": WARP_DEST[2], "DirectionY": WARP_DIR_Y},
                  wait_post)
    fadeout = action(fader, "Demo_FadeOut",
                     {"IsWaitFinish": True, "Frame": FADE_FRAMES, "Color": 1,
                      "DispMode": "Auto"}, warp)
    # préambule : cheval d'abord (descendre AVANT le warp — sinon la monture est
    # téléportée avec le joueur et reste coincée au relais, cf. test v4.3 ; séquence
    # GetOff→PlayerWait→Wait(15) relevée sur DarkWoods/forêt perdue), puis états air/sol
    # (réplique de Common::AirStartUP_Player).
    player_wait4 = action(player, "Demo_PlayerWait", {"IsWaitFinish": True}, fadeout)
    join = action(player, "Demo_Join", {"IsWaitFinish": True}, fadeout)
    stop_air = action(player, "Demo_StopInAir", {"IsWaitFinish": True, "NoFixed": False},
                      fadeout)
    state5 = switch("CheckPlayerState", {"PlayerState": 5}, {1: join, 0: stop_air})
    state4 = switch("CheckPlayerState", {"PlayerState": 4}, {1: player_wait4, 0: state5})
    wait15 = action(esa, "Demo_WaitFrame", {"IsWaitFinish": True, "Frame": 15}, state4)
    player_wait_h = action(player, "Demo_PlayerWait", {"IsWaitFinish": True}, wait15)
    get_off = action(player, "Demo_PlayerHorseGetOff", {"IsWaitFinish": True},
                     player_wait_h)
    horse = switch("CheckPlayerRideHorse", {}, {1: get_off, 0: state4})
    check = switch("CheckFlag", {"FlagName": GATE_FLAG}, {0: horse})   # 1 → rien

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


# ── packs de langue : ajoute EventFlowMsg/BOTWpelago_Gate.msbt (texte à nous) ─────

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


# entrées RSTB pour les ressources internes aux packs qu'on modifie (lu par build_mod)
RSTB_PACK_INNER = {
    f"Pack/Bootup_{lang}.pack": [f"Message/Msg_{lang}.product.ssarc"]
    for lang in EU_LANGS
}


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

    # 2b) message : MSBT custom dans chaque pack de langue présent
    for lang in EU_LANGS:
        rel = f"Pack/Bootup_{lang}.pack"
        try:
            src = read_source(rel)
        except FileNotFoundError:
            continue
        out[rel] = patched_langpack(src, lang)
        log(f"    {rel}: + EventFlowMsg/{FLOW_NAME}.msbt ({MSG_LABEL})")

    # 3a) mubin Static de la couche AOC (DLC monté = ce que le jeu lit ; layering sur
    #     la copie du rando pour préserver sa randomisation)
    new_aoc = patched_mubin(read_source(AOC_MUBIN_REL))
    oead.byml.from_binary(bytes(oead.yaz0.decompress(new_aoc)))     # vérif parse-back
    out[AOC_MUBIN_REL] = new_aoc
    log(f"    {AOC_MUBIN_REL}: +Area/LinkTagOr/EventTag @ {AREA_POS} (r={AREA_RADIUS})")

    # 3b) même chaîne dans TitleBG.pack (couverture des installs SANS DLC)
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
