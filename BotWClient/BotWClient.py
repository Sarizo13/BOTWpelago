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
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Set

import websockets

from BotWClient.providers.base import GameStateProvider, ItemInjector
from BotWClient.providers.save_file import (
    SaveFileProvider, DeferredSaveInjector,
    ap_state_report, get_location_info, _current_save_in_slot,
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

BOTW_TITLE_IDS = ["101c9400", "101c9500", "101c9300"]  # USA / EUR / JPN
CEMU_SLOT_IDS  = [f"8000000{i}" for i in range(1, 7)]

# Path up to the user-slot directory (one level above the numbered sub-saves).
# Structure: {cemu_root}/mlc01/usr/save/00050000/{tid}/user/{slot}/{sub}/game_data.sav
# where {sub} is a digit folder (0, 1, 2, …).
_SLOT_SUBPATH = "mlc01/usr/save/00050000/{tid}/user/{slot}"

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
    slots_to_scan = [cemu_slot] if cemu_slot else CEMU_SLOT_IDS
    candidates: list[Path] = []
    for root in _search_roots(cemu_hint):
        bases = [root]
        try:
            bases += [d for d in root.iterdir() if d.is_dir()]
        except PermissionError:
            pass
        for base in bases:
            for tid in BOTW_TITLE_IDS:
                for slot in slots_to_scan:
                    slot_dir = base / _SLOT_SUBPATH.format(tid=tid, slot=slot)
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
    if cemu_slot:
        log.info("Slot %s: found %d sub-save(s):", cemu_slot, len(candidates))
    else:
        log.info("Found %d save(s) across all slots:", len(candidates))
    for i, c in enumerate(candidates):
        marker = " <-- selected (most recent)" if i == 0 else ""
        log.info("  [%d] %s%s", i + 1, c, marker)
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
    item_index:  int        = 0   # next expected item index from server

    async def run(self) -> None:
        log.info("Connecting to %s as '%s' …", self.server_url, self.slot)
        async with websockets.connect(self.server_url) as ws:
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
            # Restore item_index from disk so restarts don't re-queue old items.
            self.item_index = self.injector.load_item_index()
            # Restore previously received items into the injector's received set.
            for item in msg.get("items", []):
                self.injector.mark_received(item["item"])
            log.info(
                "Connected. Shrine target: %d  Champions: %s  Sword: %s",
                self.slot_data.get("required_shrine_count", "?"),
                self.slot_data.get("randomize_champion_abilities", "?"),
                self.slot_data.get("randomize_master_sword", "?"),
            )
            if self.rando and self.rando.is_loaded:
                for line in self.rando.summary().splitlines():
                    log.info("[Rando] %s", line)

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

        elif cmd == "PrintJSON":
            log.info("[AP] %s", "".join(p.get("text", "") for p in msg.get("data", [])))

        elif cmd in ("InvalidPacket", "ConnectionRefused"):
            log.error("AP refused connection: %s", msg)

    # ── Game polling ──────────────────────────────────────────────────────────

    async def _poll_loop(self, ws) -> None:
        while True:
            await asyncio.sleep(POLL_INTERVAL)
            if not self.connected or not self.provider.is_available:
                continue

            new = [ap_id for ap_id in self.provider.poll() if ap_id not in self.checked]
            if new:
                self.checked.update(new)
                for ap_id in new:
                    loc = get_location_info(ap_id)
                    if loc:
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
                await ws.send(_pkt([{"cmd": "LocationChecks", "locations": new}]))

            required = self.slot_data.get("required_shrine_count", 20)
            if isinstance(self.provider, SaveFileProvider) and \
               self.provider.is_goal_complete(required):
                await ws.send(_pkt([{"cmd": "StatusUpdate", "status": 30}]))
                log.info("Goal complete! StatusUpdate(30) sent.")

    # ── Item injection ────────────────────────────────────────────────────────

    async def _inject_loop(self) -> None:
        while True:
            await asyncio.sleep(INJECT_INTERVAL)
            self.injector.flush()


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
    # spoiler-log du randomizer (optionnel, auto-détecté)
    rando: Optional[RandoReader] = None
    if rando_log:
        rando = RandoReader(Path(rando_log))
    else:
        for root in _search_roots(cemu):
            spoiler = find_spoiler_log(root)
            if spoiler:
                rando = RandoReader(spoiler)
                break

    # localisation de la save : --save > --slot > auto-détection
    if save:
        provider_root = Path(save)
    elif slot:
        provider_root = _find_slot_dir(cemu, slot) or Path("__missing__")
    else:
        provider_root = find_save_file(cemu) or Path("game_data.sav")

    # bridge mémoire (injection live si Cemu tourne)
    bridge = CemuMemoryBridge()
    if bridge.attach():
        log.info("[Mem] Injection memoire active — items apparaissent instantanement")
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
            print("No spoiler log found. Use --rando-log <path> or ensure the BotW Randomizer "
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

    client, _ = build_client(
        connect=args.connect, name=args.name, password=args.password,
        cemu=args.cemu, slot=args.slot, save=args.save,
        rando_log=getattr(args, "rando_log", None),
    )
    asyncio.run(client.run())


if __name__ == "__main__":
    main()
