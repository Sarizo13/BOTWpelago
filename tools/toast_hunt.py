"""
toast_hunt — localise la structure/file UI du TOAST de ramassage (« item — Sacoche ^ »).

Méthode = diff par OCCURRENCES du nom d'actor entre AVANT et APRÈS un ramassage
naturel. Quand Link ramasse un objet, le jeu écrit des structures qui référencent
l'actor (file du toast UI, event pickup…) : les NOUVELLES occurrences post-ramassage,
croisées entre 2+ items différents, isolent la file du toast des structures propres
à l'item. Conseils de session :
  - ramasser un item DÉJÀ possédé en stock (le pouch fait un simple bump de quantité
    -> pas de nouvelle string côté inventaire -> moins de bruit) ;
  - le POSER soi-même au sol d'abord (l'actor au sol existe dès la baseline) ;
  - rester immobile entre les deux passes.

Session live (Cemu + BotW) :
    python tools/toast_hunt.py baseline Item_Fruit_A   # AVANT (pomme posée au sol)
    #   -> ramasse LA pomme, ne touche plus à rien
    python tools/toast_hunt.py diff Item_Fruit_A       # APRÈS : nouvelles occurrences
    #   répéter baseline/diff avec un 2e item (ex: Item_Mushroom_E), puis :
    python tools/toast_hunt.py cross                   # contextes COMMUNS aux items
    python tools/toast_hunt.py context 0x<addr>        # hexdump large d'une adresse

État persisté entre les passes : ~/.botwpelago/toast_hunt.json
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from BotWClient.memory_injector import CemuMemoryBridge  # noqa: E402

STATE = Path.home() / ".botwpelago" / "toast_hunt.json"
CHUNK = 16 * 1024 * 1024
CTX_BEFORE, CTX_AFTER = 0x60, 0x60
MAX_NEW_DUMPED = 48


def _bridge() -> CemuMemoryBridge:
    b = CemuMemoryBridge()
    if not b.attach():
        print("ERREUR: Cemu/BotW non attaché.")
        sys.exit(1)
    return b


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st), encoding="utf-8")


def scan_str(b: CemuMemoryBridge, needle: bytes) -> list[int]:
    hits: list[int] = []
    for base, size in b._iter_regions():
        off = 0
        while off < size:
            n = min(CHUNK, size - off)
            chunk = b._read(base + off, min(n + len(needle) + 8, size - off))
            if chunk:
                start = 0
                while True:
                    i = chunk.find(needle, start)
                    if i < 0 or i >= n:
                        break
                    hits.append(base + off + i)
                    start = i + 1
            off += n
    return hits


def hexdump(b: CemuMemoryBridge, addr: int, before: int, after: int) -> str:
    blob = b._read(addr - before, before + after) or b""
    out = []
    for i in range(0, len(blob), 16):
        row = blob[i:i + 16]
        rel = i - before
        hexs = " ".join(f"{x:02X}" for x in row)
        asci = "".join(chr(x) if 32 <= x < 127 else "." for x in row)
        out.append(f"    {rel:+05X}: {hexs:<47}  {asci}{'  <== hit' if rel <= 0 < rel + 16 else ''}")
    return "\n".join(out)


def guest_ptrs_around(b: CemuMemoryBridge, addr: int) -> list[str]:
    """Constantes guest 0x10xxxxxx (vtables v208, STABLES) dans la fenêtre du hit —
    la signature qui permettra un localisateur AOB indépendant de la session."""
    blob = b._read(addr - CTX_BEFORE, CTX_BEFORE + CTX_AFTER) or b""
    found = []
    for off in range(0, len(blob) - 3, 4):
        w = struct.unpack_from(">I", blob, off)[0]
        if 0x10000000 <= w < 0x10400000:
            found.append(f"{off - CTX_BEFORE:+#x}:0x{w:08X}")
    return found


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]

    if cmd == "baseline":
        actor = sys.argv[2]
        b = _bridge()
        hits = scan_str(b, actor.encode("ascii"))
        st = _load()
        st[actor] = {"baseline": hits}
        _save(st)
        print(f"baseline {actor} : {len(hits)} occurrence(s).")
        print("-> ramasse L'OBJET (rien d'autre), reste immobile, puis :  diff", actor)

    elif cmd == "diff":
        actor = sys.argv[2]
        st = _load()
        if actor not in st or "baseline" not in st[actor]:
            print(f"pas de baseline pour {actor} — lance d'abord : baseline {actor}")
            return
        b = _bridge()
        before = set(st[actor]["baseline"])
        now = scan_str(b, actor.encode("ascii"))
        new = [a for a in now if a not in before]
        gone = len(before) - len(set(now) & before)
        print(f"diff {actor} : {len(now)} occurrences ({len(new)} NOUVELLES, {gone} disparues)")
        contexts = {}
        for a in new[:MAX_NEW_DUMPED]:
            print(f"\n  NOUVELLE @0x{a:012X}")
            print(hexdump(b, a, CTX_BEFORE, CTX_AFTER))
            ptrs = guest_ptrs_around(b, a)
            if ptrs:
                print(f"    vtables/consts guest: {' '.join(ptrs)}")
            contexts[f"0x{a:X}"] = ptrs
        st[actor]["new"] = [f"0x{a:X}" for a in new]
        st[actor]["contexts"] = contexts
        _save(st)
        if len(new) > MAX_NEW_DUMPED:
            print(f"  (+{len(new) - MAX_NEW_DUMPED} non affichées)")

    elif cmd == "cross":
        st = _load()
        actors = [a for a in st if st[a].get("contexts")]
        if len(actors) < 2:
            print(f"il faut les diffs d'au moins 2 items (actuellement: {actors})")
            return
        # signatures = multiset des (offset:vtable) — les structures de la FILE TOAST
        # ont la même signature quel que soit l'item ramassé.
        sigs: dict[str, list[tuple[str, str]]] = {}
        for actor in actors:
            for addr, ptrs in st[actor]["contexts"].items():
                key = "|".join(ptrs) or "(aucune const)"
                sigs.setdefault(key, []).append((actor, addr))
        print(f"signatures de contexte croisées ({len(actors)} items: {actors}) :\n")
        for key, where in sorted(sigs.items(), key=lambda kv: -len({a for a, _ in kv[1]})):
            n_actors = len({a for a, _ in where})
            mark = "  <== COMMUNE (file toast probable)" if n_actors == len(actors) else ""
            print(f"  [{n_actors}/{len(actors)} items] {key}{mark}")
            for actor, addr in where:
                print(f"      {actor} @ {addr}")

    elif cmd == "context":
        addr = int(sys.argv[2], 0)
        b = _bridge()
        print(hexdump(b, addr, 0x100, 0x100))

    else:
        print(f"commande inconnue: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
