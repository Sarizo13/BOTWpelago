"""
BotW Archipelago Client

Reads Cemu's game_data.sav for shrine/tower/beast completion.
Enforces gate flags (paraglider, champion abilities, master sword) via flag retention.
Communicates with the AP server via WebSocket (standard AP protocol).

Usage (standalone):
  python -m BotWClient.BotWClient --connect archipelago.gg:38281 --name YourSlot
  python -m BotWClient.BotWClient --connect localhost:38281 --name YourSlot --password pw

  # Diagnostic modes (no AP connection):
  python -m BotWClient.BotWClient --debug-save --save path/to/game_data.sav
  python -m BotWClient.BotWClient --diff-saves before.sav after.sav

Save file auto-detected from known Cemu install locations.
Override with: --save "D:/path/to/game_data.sav"

Pin versions: Cemu 1.18.1+ / BotW WiiU 1.5.0 (all regions).
"""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Set

import websockets

from BotWClient.providers.base import GameStateProvider
from BotWClient.providers.save_file import (
    SaveFileProvider, DeferredSaveInjector,
    ap_state_report, get_location_info, _current_save_in_slot, reset_ap_state,
)
from BotWClient.item_map import get_spec
from BotWClient.rando_reader import RandoReader, find_spoiler_log
from BotWClient.memory_injector import CemuMemoryBridge

log = logging.getLogger("BotWClient")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

# Human-readable reason for each location category.
_CHECK_REASON: dict[str, str] = {
    "shrine": "sanctuaire valide",
    "tower":  "tour activee",
    "beast":  "bete divine vaincue",
}

GAME_NAME  = "The Legend of Zelda: Breath of the Wild"
AP_VERSION = {"major": 0, "minor": 5, "build": 0, "class": "Version"}

# Le rando place un placeholder « PutRupee » (rubis vert = 1) dans chaque coffre AP.
# Le coffre n'est qu'un marqueur (l'item réel vient d'AP) -> on retire cette valeur du
# portefeuille à chaque check de coffre détecté. Cf. PLACEHOLDER_ACTOR (worlds/botw).
PLACEHOLDER_RUPEE_VALUE = 1

# BOTWpelago y écrit le config rando reçu via slot_data (source pour la construction
# du pack quand l'utilisateur n'a pas fourni de fichier .apbotw).
SLOT_CONFIG_PATH = Path.home() / ".botwpelago" / "ap_config.json"

BOTW_TITLE_IDS = ["101c9400", "101c9500", "101c9300"]  # USA / EUR / JPN

# Path up to the user-slot directory (one level above the numbered sub-saves).
# Structure: {cemu_root}/mlc01/usr/save/00050000/{tid}/user/{slot}/{sub}/game_data.sav
# where {sub} is a digit folder (0, 1, 2, …).
_SLOT_SUBPATH = "mlc01/usr/save/00050000/{tid}/user/{slot}"
_USER_SUBPATH = "mlc01/usr/save/00050000/{tid}/user"

POLL_INTERVAL   = 2.0   # seconds
INJECT_INTERVAL = 5.0   # seconds


# ── Save discovery ────────────────────────────────────────────────────────────

def _find_slot_dir(cemu_hint: Optional[str], cemu_slot: str) -> Optional[Path]:
    """
    Return the Cemu slot directory for a given slot ID (e.g. '80000002').
    Does NOT scan sub-saves — just returns the directory that contains them.
    """
    roots = _search_roots(cemu_hint)
    for root in roots:
        bases = [root]
        try:
            bases += [d for d in root.iterdir() if d.is_dir()]
        except PermissionError:
            pass
        for base in bases:
            for tid in BOTW_TITLE_IDS:
                slot_dir = base / _SLOT_SUBPATH.format(tid=tid, slot=cemu_slot)
                if slot_dir.exists():
                    log.info("Slot dir: %s", slot_dir)
                    return slot_dir
    log.warning("Slot %s not found in any known Cemu location.", cemu_slot)
    return None


def _search_roots(cemu_hint: Optional[str]) -> list[Path]:
    roots: list[Path] = []
    if cemu_hint:
        roots.append(Path(cemu_hint))
    roots += [
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Cemu",
        Path(os.environ.get("LOCALAPPDATA", ""))                 / "Cemu",
        Path("C:/cemu"),
        Path("D:/cemu"),
        Path("C:/emulateurs/cemu"),
        Path("D:/Emulateur/Cemu"),
        Path("C:/emulators/cemu"),
    ]
    return [r for r in roots if r.exists()]


def find_save_file(
    cemu_hint: Optional[str] = None,
    cemu_slot: Optional[str] = None,
) -> Optional[Path]:
    """
    Scan Cemu install locations for BotW saves.
    Structure: {cemu_root}/mlc01/usr/save/00050000/{tid}/user/{slot}/{sub}/game_data.sav

    cemu_hint : override Cemu root folder (instead of auto-detect)
    cemu_slot : Cemu user-slot to search exclusively, e.g. "80000002".
                When given, only that slot is scanned — ignoring other saves.
                When omitted, all slots are scanned and the most recent is used.
    """
    candidates: list[Path] = []
    for root in _search_roots(cemu_hint):
        bases = [root]
        try:
            bases += [d for d in root.iterdir() if d.is_dir()]
        except PermissionError:
            pass
        for base in bases:
            for tid in BOTW_TITLE_IDS:
                user_dir = base / _USER_SUBPATH.format(tid=tid)
                if not user_dir.is_dir():
                    continue
                # cemu_slot demandé → ce profil seul ; sinon TOUS les profils découverts
                # dynamiquement (ne pas coder en dur 80000001..06 — rate 80000010, etc.).
                try:
                    slot_dirs = ([user_dir / cemu_slot] if cemu_slot
                                 else [d for d in user_dir.iterdir() if d.is_dir()])
                except PermissionError:
                    continue
                for slot_dir in slot_dirs:
                    if not slot_dir.exists():
                        continue
                    try:
                        for sub in sorted(slot_dir.iterdir()):
                            if sub.is_dir() and sub.name.isdigit():
                                p = sub / "game_data.sav"
                                if p.exists():
                                    candidates.append(p)
                    except PermissionError:
                        pass

    if not candidates:
        if cemu_slot:
            log.warning(
                "No game_data.sav found in slot %s. "
                "Launch BotW in Cemu on that profile to create a first save, then retry.",
                cemu_slot,
            )
        else:
            log.warning("No game_data.sav found in any known Cemu location.")
        return None

    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    scope = f"slot {cemu_slot}" if cemu_slot else "tous slots"
    log.info("Save sélectionnée (%s, la plus récente sur %d) : %s",
             scope, len(candidates), candidates[0])
    # détail complet uniquement en debug
    for i, c in enumerate(candidates):
        marker = " <-- selected" if i == 0 else ""
        log.debug("  [%d] %s%s", i + 1, c, marker)
    return candidates[0]


# ── AP helpers ────────────────────────────────────────────────────────────────

def _pkt(payload: list) -> str:
    return json.dumps(payload)


# ── Client ────────────────────────────────────────────────────────────────────

@dataclass
class BotWClient:
    server_url: str
    slot:       str
    password:   str
    provider:   GameStateProvider
    injector:   DeferredSaveInjector
    rando:      Optional[RandoReader] = None

    connected:   bool       = False
    slot_data:   dict       = field(default_factory=dict)
    checked:     Set[int]   = field(default_factory=set)
    slot_locations: Set[int] = field(default_factory=set)  # all location ids in this slot
    item_index:  int        = 0   # next expected item index from server
    death_link:  bool       = False
    _ignore_death_until: float = 0.0   # ignore self-death right after a received DeathLink
    _pending_rupee_strip: int = 0      # dette de rubis-placeholder à retirer (rejouée jusqu'à succès)
    # Résolution des noms dans les messages AP (DataPackage + infos joueurs)
    _dp_item:   dict = field(default_factory=dict)   # game -> {item_id: name}
    _dp_loc:    dict = field(default_factory=dict)   # game -> {location_id: name}
    _slot_game: dict = field(default_factory=dict)   # slot -> game
    _slot_name: dict = field(default_factory=dict)   # slot -> nom du joueur

    async def run(self) -> None:
        log.info("Connecting to %s as '%s' …", self.server_url, self.slot)
        # Le travail mémoire lourd (flush/poll : scans + re-localisations) est déporté sur un
        # thread dédié MONO-worker (sérialisé → pas de course sur le bridge) pour ne JAMAIS
        # bloquer la boucle réseau : sinon, pendant une grosse rafale d'items, la boucle gèle
        # plusieurs secondes et le ping keepalive AP expire → déconnexion (1011).
        self._exec = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="botw-mem")
        try:
            async with websockets.connect(
                    self.server_url, ping_timeout=60, max_size=None) as ws:
                await ws.send(_pkt([{
                    "cmd":           "Connect",
                    "game":          GAME_NAME,
                    "name":          self.slot,
                    "password":      self.password,
                    "version":       AP_VERSION,
                    "items_handling":0b111,
                    "tags":          ["BotW"],
                    "uuid":          "botw-client-0001",
                }]))
                await asyncio.gather(
                    self._recv_loop(ws),
                    self._poll_loop(ws),
                    self._inject_loop(),
                )
        finally:
            self._exec.shutdown(wait=False)

    # ── Server messages ───────────────────────────────────────────────────────

    async def _recv_loop(self, ws) -> None:
        async for raw in ws:
            for msg in json.loads(raw):
                await self._on_msg(msg, ws)

    async def _on_msg(self, msg: dict, ws) -> None:
        cmd = msg.get("cmd")
        if cmd == "Connected":
            self.connected = True
            self.slot_data = msg.get("slot_data", {})
            self.checked   = set(msg.get("checked_locations", []))
            # The slot's full location set (mode-aware) = checked ∪ missing. The client
            # polls every known flag but only emits checks that belong to this slot.
            self.slot_locations = self.checked | set(msg.get("missing_locations", []))
            # Maps de résolution des noms (slot -> jeu / nom de joueur).
            for sslot, info in msg.get("slot_info", {}).items():
                self._slot_game[int(sslot)] = info.get("game", "")
            for pl in msg.get("players", []):
                self._slot_name[pl["slot"]] = pl.get("alias") or pl.get("name") or str(pl["slot"])
            # Restore item_index from disk so restarts don't re-queue old items.
            self.item_index = self.injector.load_item_index()
            # Restore previously received items into the injector's received set.
            for item in msg.get("items", []):
                self.injector.mark_received(item["item"])
            log.info(
                "Connected. Mode: %s  Shrine target: %d  Champions: %s  Sword: %s",
                self.slot_data.get("game_mode", "?"),
                self.slot_data.get("required_shrine_count", "?"),
                self.slot_data.get("randomize_champion_abilities", "?"),
                self.slot_data.get("randomize_master_sword", "?"),
            )
            # DeathLink : on (dés)active le tag selon le slot_data.
            self.death_link = bool(self.slot_data.get("death_link", False))
            if self.death_link:
                await ws.send(_pkt([{"cmd": "ConnectUpdate", "tags": ["BotW", "DeathLink"]}]))
                log.info("DeathLink ACTIF.")
            # Config rando reçu via slot_data → écrit localement pour que BOTWpelago
            # construise le pack sans aucun fichier à télécharger (héberg. public OK).
            rc = self.slot_data.get("rando_config")
            if rc:
                try:
                    SLOT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
                    SLOT_CONFIG_PATH.write_text(json.dumps(rc, indent=2), encoding="utf-8")
                    log.info("[Config] config rando reçu via slot_data → %s", SLOT_CONFIG_PATH)
                except OSError as e:
                    log.warning("[Config] écriture du config rando échouée : %s", e)
            if self.rando and self.rando.is_loaded:
                for line in self.rando.summary().splitlines():
                    log.info("[Rando] %s", line)

        elif cmd == "RoomInfo":
            # Demande le DataPackage (id<->nom de tous les jeux) pour résoudre les noms
            # d'items/locations dans les messages PrintJSON (sinon ce ne sont que des IDs).
            games = msg.get("games", [])
            if games:
                await ws.send(_pkt([{"cmd": "GetDataPackage", "games": games}]))

        elif cmd == "DataPackage":
            games = msg.get("data", {}).get("games", {})
            for game, gd in games.items():
                self._dp_item[game] = {v: k for k, v in gd.get("item_name_to_id", {}).items()}
                self._dp_loc[game]  = {v: k for k, v in gd.get("location_name_to_id", {}).items()}
            log.debug("[DataPackage] %d jeu(x) résolu(s)", len(games))

        elif cmd == "ReceivedItems":
            # AP protocol: `index` is on the ReceivedItems packet (start of batch),
            # NOT on individual items. Compute per-item index as start + offset.
            start_idx = msg.get("index", 0)
            items     = msg.get("items", [])
            log.debug("[ReceivedItems] %d item(s) from index %d (item_index=%d)",
                      len(items), start_idx, self.item_index)
            for i, item in enumerate(items):
                idx = start_idx + i
                if idx < self.item_index:
                    continue
                self.item_index = idx + 1
                self.injector.persist_item_index(self.item_index)
                spec = get_spec(item["item"])
                self.injector.queue_item(spec)
                log.info("[Item] %s%s",
                         spec.ap_item_name,
                         f"  — {spec.display_note}" if spec.display_note else "")

        elif cmd == "Bounced":
            # DeathLink : le serveur rediffuse les Bounce sous le nom "Bounced".
            # Un autre joueur est mort → on tue Link (sauf si c'est nous).
            if self.death_link and "DeathLink" in msg.get("tags", []):
                data = msg.get("data", {})
                if data.get("source") != self.slot:
                    cause = data.get("cause") or f"{data.get('source','?')} est mort"
                    log.info("[DeathLink] %s — Link meurt.", cause)
                    self._ignore_death_until = time.monotonic() + 8.0
                    self._kill_player()

        elif cmd == "PrintJSON":
            log.info("[AP] %s", self._render_json(msg.get("data", [])))

        elif cmd in ("InvalidPacket", "ConnectionRefused"):
            log.error("AP refused connection: %s", msg)

    def _render_json(self, parts: list) -> str:
        """Rend un message PrintJSON en résolvant les IDs en noms : items/locations via le
        DataPackage du jeu concerné, joueurs via slot_info. Fallback = l'ID si non résolu."""
        out: list[str] = []
        for p in parts:
            t   = p.get("type", "text")
            txt = p.get("text", "")
            if t == "player_id":
                try:
                    out.append(self._slot_name.get(int(txt), f"Joueur {txt}"))
                except (TypeError, ValueError):
                    out.append(str(txt))
            elif t in ("item_id", "location_id"):
                table = self._dp_item if t == "item_id" else self._dp_loc
                game  = self._slot_game.get(p.get("player"), "")
                try:
                    name = table.get(game, {}).get(int(txt))
                except (TypeError, ValueError):
                    name = None
                out.append(name or f"{'Item' if t == 'item_id' else 'Lieu'}#{txt}")
            else:
                out.append(str(txt))
        return "".join(out)

    # ── Game polling ──────────────────────────────────────────────────────────

    async def _poll_loop(self, ws) -> None:
        loop = asyncio.get_event_loop()
        while True:
            await asyncio.sleep(POLL_INTERVAL)
            if not self.connected or not self.provider.is_available:
                continue

            # poll() lit/parse la save → déporté sur le thread dédié (sérialisé avec flush)
            # pour ne pas bloquer le réseau.
            polled = await loop.run_in_executor(self._exec, self.provider.poll)
            new = [ap_id for ap_id in polled
                   if ap_id not in self.checked
                   and (not self.slot_locations or ap_id in self.slot_locations)]
            if new:
                self.checked.update(new)
                chest_count = 0
                for ap_id in new:
                    loc = get_location_info(ap_id)
                    if loc:
                        if loc.get("category") == "shrine_chest":
                            chest_count += 1
                        reason = _CHECK_REASON.get(loc["category"], "check")
                        rando_note = ""
                        if self.rando and loc.get("category") == "shrine":
                            flag_name = loc.get("flag_name", "")
                            item_in_chest = self.rando.shrine_item_by_flag(flag_name)
                            if item_in_chest:
                                rando_note = f"  [rando: {item_in_chest}]"
                        log.info(
                            "[CHECK] [OK] %-38s  %s  (%s)%s",
                            loc["name"],
                            loc.get("region", "?"),
                            reason,
                            rando_note,
                        )
                    else:
                        log.info("[CHECK] ap_id=%d", ap_id)
                self._pending_rupee_strip += chest_count
                await ws.send(_pkt([{"cmd": "LocationChecks", "locations": new}]))

            # Annule la valeur des placeholders rubis des coffres AP ouverts. On accumule une
            # DETTE (rejouée à chaque poll) : si l'inventaire live n'est pas dispo au moment où le
            # coffre est détecté (fenêtre après attach / mid-réallocation, adresse rubis pas encore
            # localisée), le strip était perdu et le +1 restait → "certains rubis pas retirés".
            # On ne solde la dette QUE si live_add_rupees réussit vraiment (retour non-None).
            if self._pending_rupee_strip:
                bridge = self.injector._bridge
                if bridge and bridge.is_attached and bridge.has_live_inventory:
                    n = self._pending_rupee_strip
                    total = bridge.live_add_rupees(-n * PLACEHOLDER_RUPEE_VALUE)
                    if total is not None:
                        self._pending_rupee_strip = 0
                        log.info("[Coffre AP] %d rubis-placeholder retiré(s)  (portefeuille: %s)",
                                 n * PLACEHOLDER_RUPEE_VALUE, total)

            required = self.slot_data.get("required_shrine_count", 20)
            if isinstance(self.provider, SaveFileProvider) and \
               self.provider.is_goal_complete(required):
                await ws.send(_pkt([{"cmd": "StatusUpdate", "status": 30}]))
                log.info("Goal complete! StatusUpdate(30) sent.")

            # DeathLink — détecte notre mort et la diffuse (sauf si on vient d'être tué
            # par un DeathLink reçu, pour ne pas la renvoyer en boucle).
            if self.death_link:
                bridge = self.injector._bridge
                if bridge and bridge.is_attached and bridge.poll_player_death():
                    if time.monotonic() >= self._ignore_death_until:
                        await self._send_death(ws)

    # ── DeathLink helpers ───────────────────────────────────────────────────────

    def _kill_player(self) -> None:
        bridge = self.injector._bridge
        if bridge and bridge.is_attached and bridge.kill_player():
            return
        log.warning("[DeathLink] Impossible de tuer Link (Cemu non attaché ou patch natif absent).")

    async def _send_death(self, ws) -> None:
        await ws.send(_pkt([{
            "cmd":  "Bounce",
            "tags": ["DeathLink"],
            "data": {"time": time.time(), "source": self.slot,
                     "cause": f"{self.slot} (BotW) est tombé au combat"},
        }]))
        log.info("[DeathLink] Mort envoyée au multiworld.")

    # ── Item injection ────────────────────────────────────────────────────────

    async def _inject_loop(self) -> None:
        loop = asyncio.get_event_loop()
        while True:
            await asyncio.sleep(INJECT_INTERVAL)
            # flush() = travail mémoire potentiellement long (créations live, re-localisations)
            # → exécuté sur le thread dédié pour ne pas bloquer le réseau.
            await loop.run_in_executor(self._exec, self.injector.flush)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="BotW Archipelago Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--connect",  default="localhost:38281",
                   help="AP server host:port (default: localhost:38281)")
    p.add_argument("--name",     default=None, help="AP slot name")
    p.add_argument("--password", default="")
    p.add_argument("--cemu",     default=None, help="Cemu install folder (for auto-detect)")
    p.add_argument("--slot",     default=None, metavar="SLOT",
                   help="Cemu user-slot to monitor exclusively, e.g. 80000002. "
                        "Use this when you have multiple saves and only one is for AP.")
    p.add_argument("--save",      default=None, help="Direct path to game_data.sav (overrides --slot)")
    p.add_argument("--reset",     action="store_true",
                   help="Réinitialise l'état AP (file d'attente + items reçus) avant de "
                        "connecter — tous les items seront re-livrés à la reconnexion.")
    p.add_argument("--rando-log", default=None, metavar="PATH",
                   help="Path to the Melonspeedruns randomizer spoiler-log.txt. "
                        "Auto-detected from the Cemu graphicPacks folder if omitted.")

    diag = p.add_argument_group("diagnostics (no AP connection)")
    diag.add_argument("--debug-save",  action="store_true",
                      help="Print low-level save analysis (header, entries, spot-check) and exit")
    diag.add_argument("--check-flags", action="store_true",
                      help="Print AP-relevant flag states (completed locations + progression items) and exit")
    diag.add_argument("--check-rando", action="store_true",
                      help="Print the randomizer seed and item placement summary, then exit")
    diag.add_argument("--diff-saves",  nargs=2, metavar=("BEFORE", "AFTER"),
                      help="Show flags changed between two saves and exit")
    return p


def resolve_provider_root(cemu: Optional[str] = None, slot: Optional[str] = None,
                          save: Optional[str] = None) -> Path:
    """Localise la racine save : --save > --slot > auto-détection. Partagé par build_client + reset.

    Sans --slot/--save : renvoie le DOSSIER DE PROFIL (…/<profile>/) et non un fichier figé,
    pour que le provider relise le sous-save le plus récent à chaque poll (BotW alterne 0..7)."""
    if save:
        return Path(save)
    if slot:
        return _find_slot_dir(cemu, slot) or Path("__missing__")
    f = find_save_file(cemu)
    if f is not None:
        # f = …/<profile>/<n>/game_data.sav  -> remonter au dossier de profil (suit la rotation)
        profile_dir = f.parent.parent
        if profile_dir.is_dir():
            return profile_dir
        return f
    return Path("game_data.sav")


def _ws_url(connect: str) -> str:
    """Schéma WebSocket : localhost -> ws:// (pas de TLS), sinon -> wss:// (archipelago.gg).
    Un schéma explicite (ws:// / wss://) dans `connect` est respecté tel quel."""
    if connect.startswith(("ws://", "wss://")):
        return connect
    host = connect.split("/", 1)[0]
    if host.startswith(("localhost", "127.0.0.1")):
        return f"ws://{connect}"
    return f"wss://{connect}"


def build_client(connect: str, name: str, password: str = "",
                 cemu: Optional[str] = None, slot: Optional[str] = None,
                 save: Optional[str] = None, rando_log: Optional[str] = None):
    """
    Construit un BotWClient prêt à `.run()`, en localisant la save, le spoiler-log et
    en attachant le bridge mémoire si Cemu tourne. Réutilisé par le CLI et par l'appli GUI.
    Retourne (client, bridge | None).
    """
    # spoiler-log d'un randomizer TIERS (Waikuteru/Melonspeedrun) — chargé UNIQUEMENT
    # si explicitement fourni. Pas d'auto-détection : sans ça, on chargeait un vieux
    # spoiler sans rapport avec la seed AP (logs "Seed HZZE…" trompeurs).
    rando: Optional[RandoReader] = RandoReader(Path(rando_log)) if rando_log else None

    # localisation de la save : --save > --slot > auto-détection
    provider_root = resolve_provider_root(cemu, slot, save)

    # bridge mémoire (injection live si Cemu tourne)
    bridge = CemuMemoryBridge()
    if bridge.attach():
        log.info("[Mem] Cemu attache — DeathLink actif ; objets ecrits dans la save "
                 "(menu titre) puis appliques au rechargement")
    else:
        log.info("[Mem] Cemu non detecte — injection via save file (reload requis)")
        bridge = None

    provider = SaveFileProvider(provider_root)
    injector = DeferredSaveInjector(provider_root, rando=rando, bridge=bridge)
    client   = BotWClient(
        server_url = _ws_url(connect),
        slot       = name,
        password   = password,
        provider   = provider,
        injector   = injector,
        rando      = rando,
    )
    return client, bridge


def main() -> None:
    from BotWClient.save_parser import parse, diff_saves, inspect_save

    args = _parser().parse_args()

    # ── Diff ──────────────────────────────────────────────────────────────────
    if args.diff_saves:
        before = parse(Path(args.diff_saves[0]).read_bytes())
        after  = parse(Path(args.diff_saves[1]).read_bytes())
        result = diff_saves(before, after)
        for section, items in result.items():
            if items:
                print(f"\n{section}:")
                for it in items:
                    print(f"  {it}")
        return

    # ── Rando reader (optional) ───────────────────────────────────────────────
    rando: Optional[RandoReader] = None
    if getattr(args, "rando_log", None):
        rando = RandoReader(Path(args.rando_log))
    else:
        # Auto-detect from known Cemu roots
        for root in _search_roots(args.cemu):
            spoiler = find_spoiler_log(root)
            if spoiler:
                rando = RandoReader(spoiler)
                break

    # ── --check-rando ─────────────────────────────────────────────────────────
    if getattr(args, "check_rando", False):
        if rando and rando.is_loaded:
            print(rando.summary())
        else:
            print("No spoiler log found. Use --rando-log <path> or ensure the BOTWpelago "
                  "graphic pack is installed in your Cemu graphicPacks folder.")
        return

    # ── Locate save ───────────────────────────────────────────────────────────
    # --save <file>  → exact path (provider uses it directly)
    # --slot <id>    → slot directory (provider always picks most-recent sub-save)
    # (neither)      → auto-detect exact file (legacy behaviour)
    is_diag = args.debug_save or getattr(args, "check_flags", False)

    if args.save:
        provider_root = Path(args.save)
    elif args.slot:
        provider_root = _find_slot_dir(args.cemu, args.slot)
        if provider_root is None:
            if is_diag:
                print(f"ERROR: slot {args.slot} not found. "
                      "Launch BotW in Cemu on that profile first.")
                sys.exit(1)
            provider_root = Path("__missing__")   # provider will report unavailable
    else:
        # Legacy: pick the single most-recent file across all slots.
        provider_root = find_save_file(args.cemu) or Path("game_data.sav")

    # ── Debug: low-level ──────────────────────────────────────────────────────
    if args.debug_save:
        p = provider_root if provider_root.is_file() else \
            (_current_save_in_slot(provider_root) if provider_root.is_dir() else None)
        if p is None:
            print("ERROR: no save file found.")
            sys.exit(1)
        print(inspect_save(p.read_bytes()))
        return

    # ── Debug: AP state ───────────────────────────────────────────────────────
    if getattr(args, "check_flags", False):
        p = provider_root if provider_root.is_file() else \
            (_current_save_in_slot(provider_root) if provider_root.is_dir() else None)
        if p is None:
            print("ERROR: no save file found.")
            sys.exit(1)
        print(ap_state_report(p))
        return

    # ── Normal client ─────────────────────────────────────────────────────────
    if not args.name:
        print("ERROR: --name <slot> is required.")
        sys.exit(1)

    if args.reset:
        n = reset_ap_state(resolve_provider_root(args.cemu, args.slot, args.save))
        log.info("[Reset] État AP effacé (%d fichier(s)). Tous les items seront re-livrés.", n)

    client, _ = build_client(
        connect=args.connect, name=args.name, password=args.password,
        cemu=args.cemu, slot=args.slot, save=args.save,
        rando_log=getattr(args, "rando_log", None),
    )
    asyncio.run(client.run())


if __name__ == "__main__":
    main()
