"""
toast_msbt_patch — patche EN RAM le message MSBT du toast type 0xA
(« Vous avez lâché {item}. » → « Vous avez reçu  {item}. ») pour le toast AP natif.

Le remplacement est STRICTEMENT in-place : « lâché » (5 unités UTF-16BE) → « reçu  »
(5 unités), le tag placeholder {item} et le reste du flux MSBT ne bougent pas.

Usage (terminal ADMIN, Cemu+BotW lancés, jeu en FRANÇAIS) :
    python tools/toast_msbt_patch.py            # scan seul (lecture, liste les hits)
    python tools/toast_msbt_patch.py --patch    # patche tous les hits (backup JSON)
    python tools/toast_msbt_patch.py --restore  # restaure depuis le backup
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from toast_recon import open_bridge, iter_chunks  # noqa: E402

# « Vous avez lâché » en UTF-16BE (MSBT WiiU)
NEEDLE = "Vous avez lâché".encode("utf-16-be")
# « lâché » -> « gagné » — 5 unités chacune, in-place strict, espacement original intact
OLD_WORD = "lâché".encode("utf-16-be")
NEW_WORD = "gagné".encode("utf-16-be")
assert len(OLD_WORD) == len(NEW_WORD)
WORD_OFF = len("Vous avez ".encode("utf-16-be"))   # offset du mot dans le motif

BACKUP = Path.home() / ".botwpelago" / "toast_msbt_backup.json"


def scan(b) -> list[int]:
    t0 = time.monotonic()
    hits = []
    for base, off, n, chunk in iter_chunks(b, len(NEEDLE) + 0x40):
        s = 0
        while True:
            i = chunk.find(NEEDLE, s)
            if i < 0 or i >= n:
                break
            hits.append(base + off + i)
            s = i + 1
    print(f"{len(hits)} occurrence(s) en {time.monotonic() - t0:.0f}s")
    for h in hits:
        ctx = b._read(h, 0x60) or b""
        try:
            txt = ctx.decode("utf-16-be", "replace")
        except Exception:
            txt = "?"
        printable = "".join(c if c.isprintable() else "·" for c in txt)
        print(f"  0x{h:012X}: {printable[:44]}")
    return hits


def main() -> None:
    do_patch = "--patch" in sys.argv
    do_restore = "--restore" in sys.argv
    b = open_bridge()

    if do_restore:
        if not BACKUP.exists():
            print("Pas de backup.")
            return
        data = json.loads(BACKUP.read_text(encoding="utf-8"))
        n = 0
        for p in data["patches"]:
            addr, old = int(p["addr"], 16), bytes.fromhex(p["old"])
            cur = b._read(addr, len(old)) or b""
            if cur == bytes.fromhex(p["new"]):
                b._write(addr, old)
                n += 1
            else:
                print(f"  skip 0x{addr:X} (contenu inattendu — adresse périmée ?)")
        print(f"{n} patch(s) restaurés.")
        return

    hits = scan(b)
    if not hits:
        print("Aucun hit — jeu pas en français ? MSBT pas encore chargé ?"
              " (déclenche un toast une fois puis relance)")
        return
    if not do_patch:
        print("\n(lecture seule — relance avec --patch pour appliquer)")
        return

    patches = []
    for h in hits:
        addr = h + WORD_OFF
        old = b._read(addr, len(OLD_WORD)) or b""
        if old != OLD_WORD:
            print(f"  skip 0x{addr:X}: contenu inattendu {old.hex()}")
            continue
        patches.append({"addr": f"0x{addr:X}", "old": old.hex(), "new": NEW_WORD.hex()})
        b._write(addr, NEW_WORD)
        print(f"  patché 0x{addr:X}: "
              f"« {OLD_WORD.decode('utf-16-be')} » -> « {NEW_WORD.decode('utf-16-be')} »")
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    BACKUP.write_text(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                                  "patches": patches}, indent=1), encoding="utf-8")
    print(f"{len(patches)} patch(s) appliqués -> backup {BACKUP}")


if __name__ == "__main__":
    main()
