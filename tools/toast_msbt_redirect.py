"""
toast_msbt_redirect — redirige EN RAM le message MSBT du toast type 0xA vers une
phrase custom AVEC QUANTITÉ, écrite dans une string-victime inutilisée du même MSBT.

Principe (RE 2026-07-12, docs/status.md §6c) : le bloc TXT2 du MSBT référence chaque
message par un OFFSET (table u32be). On compose « Vous avez reçu {item} x{qty}. »
(tag item copié byte-exact, SANS le tag article {201,1} → nom nu) dans la zone d'une
string placeholder de dev (« TESHEIKAHSLATE… », ~0xC6 octets, jamais affichée), puis
on fait pointer l'offset du message 0xA dessus. La string originale reste intacte
(re-localisable par scan) ; la quantité se réécrit à volonté au suffixe.

Usage (terminal ADMIN, Cemu+BotW lancés, jeu en FRANÇAIS) :
    python tools/toast_msbt_redirect.py --status          # inspecte (lecture seule)
    python tools/toast_msbt_redirect.py --install         # installe la redirection
    python tools/toast_msbt_redirect.py --qty 5           # pose le suffixe « x5 »
    python tools/toast_msbt_redirect.py --qty 1           # retire le suffixe
    python tools/toast_msbt_redirect.py --restore         # restaure offset + zone
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from toast_recon import open_bridge, iter_chunks  # noqa: E402

NEEDLE_VANILLA = "Vous avez lâché".encode("utf-16-be")
NEEDLE_PATCHED = "Vous avez gagné".encode("utf-16-be")   # si l'ancien patch-mot est actif
VICTIM_MARK = "TESHEIKAHSLATE".encode("utf-16-be")       # début de la string placeholder
PREFIX = "Vous avez reçu ".encode("utf-16-be")           # notre préfixe (15 unités)
TAG_NOARTICLE = bytes.fromhex("000E00C9000400 00".replace(" ", ""))  # {201,4} size=0
# tag item {2,0x0B,size 0x1C} + data {len 0x18, "UiInfoString", u16 0} — copié de l'original
TAG_ITEM = bytes.fromhex(
    "000E0002000B001C0018"
    + "UiInfoString".encode("utf-16-be").hex()
    + "0000")
DOT_NUL = ".".encode("utf-16-be") + b"\x00\x00"     # « . » + NUL

BACKUP = Path.home() / ".botwpelago" / "toast_msbt_redirect_backup.json"


def find_msbt(b) -> dict:
    """Localise le MSBT en RAM + parse TXT2. Repère l'entrée toast et la victime PAR CONTENU."""
    hit = None
    for base, off, n, chunk in iter_chunks(b, 0x40):
        for needle in (NEEDLE_VANILLA, NEEDLE_PATCHED):
            i = chunk.find(needle)
            if 0 <= i < n:
                hit = base + off + i
                break
        if hit:
            break
    if hit is None:
        raise RuntimeError("string toast introuvable (langue ≠ FR ? MSBT pas chargé ?)")
    hdr = None
    for back in range(0, 4 << 20, 0x10000):
        lo = hit - back - 0x10000
        blob = b._read(lo, 0x10010) or b""
        i = blob.rfind(b"MsgStdBn")
        if i >= 0:
            hdr = lo + i
            break
    if hdr is None:
        raise RuntimeError("header MsgStdBn introuvable en amont de la string")
    nsec, = struct.unpack(">H", b._read(hdr + 14, 2))
    off, txt2, txt2_size = 0x20, None, 0
    for _ in range(nsec):
        sh = b._read(hdr + off, 8)
        magic, size = sh[:4], struct.unpack(">I", sh[4:8])[0]
        if magic == b"TXT2":
            txt2, txt2_size = hdr + off + 0x10, size
            break
        off += 0x10 + size
        off = (off + 0xF) & ~0xF
    if txt2 is None:
        raise RuntimeError("section TXT2 introuvable")
    count, = struct.unpack(">I", b._read(txt2, 4))
    offs = list(struct.unpack(f">{count}I", b._read(txt2 + 4, 4 * count)))
    toast_idx = victim_idx = None
    for k in range(count):
        a = txt2 + offs[k]
        head = b._read(a, 0x20) or b""
        if toast_idx is None and (head.startswith(NEEDLE_VANILLA[:0x20])
                                  or head.startswith(NEEDLE_PATCHED[:0x20])
                                  or head.startswith(PREFIX[:0x20])):
            toast_idx = k
        if victim_idx is None and head.startswith(VICTIM_MARK[:0x20]):
            victim_idx = k
    # si déjà redirigé : la zone victime est réécrite (préfixe custom) et l'entrée toast
    # pointe la MÊME zone. La victime = l'entrée (≠ toast) qui PARTAGE l'offset du toast
    # (redirection active) ; à défaut, celle qui porte notre préfixe.
    if toast_idx is not None and victim_idx is None:
        for k in range(count):
            if k == toast_idx:
                continue
            if offs[k] == offs[toast_idx]:
                victim_idx = k
                break
            head = b._read(txt2 + offs[k], len(PREFIX)) or b""
            if head == PREFIX:
                victim_idx = k
                break
    if toast_idx is None or victim_idx is None:
        raise RuntimeError(f"entrées introuvables (toast={toast_idx} victime={victim_idx})")
    vic_end = offs[victim_idx + 1] if victim_idx + 1 < count else txt2_size
    return {
        "hdr": hdr, "txt2": txt2, "count": count, "offs": offs,
        "toast_idx": toast_idx, "victim_idx": victim_idx,
        "toast_entry_addr": txt2 + 4 + 4 * toast_idx,
        "victim_addr": txt2 + offs[victim_idx],
        "victim_budget": vic_end - offs[victim_idx],
    }


def compose(qty: int) -> bytes:
    """« Vous avez reçu {item}[ xN]. » — tag article omis → nom nu (« Flèche »)."""
    suffix = f" x{qty}".encode("utf-16-be") if qty > 1 else b""
    return PREFIX + TAG_NOARTICLE + TAG_ITEM + suffix + DOT_NUL


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--qty", type=int, default=None)
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    b = open_bridge()
    t0 = time.monotonic()
    m = find_msbt(b)
    print(f"MSBT @0x{m['hdr']:012X}  TXT2 @0x{m['txt2']:012X}  ({time.monotonic()-t0:.0f}s)\n"
          f"toast idx={m['toast_idx']} (offset table @0x{m['toast_entry_addr']:012X})  "
          f"victime idx={m['victim_idx']} @0x{m['victim_addr']:012X} budget=0x{m['victim_budget']:X}")

    cur_off, = struct.unpack(">I", b._read(m["toast_entry_addr"], 4))
    redirected = cur_off == m["offs"][m["victim_idx"]]
    print(f"offset toast actuel = 0x{cur_off:X} -> {'REDIRIGE (custom)' if redirected else 'original'}")

    if args.restore:
        if not BACKUP.exists():
            print("Pas de backup.")
            return
        data = json.loads(BACKUP.read_text(encoding="utf-8"))
        b._write(m["toast_entry_addr"], bytes.fromhex(data["entry_old"]))
        b._write(m["victim_addr"], bytes.fromhex(data["victim_old"]))
        print("Redirection + zone restaurées (vanilla).")
        return

    if args.install:
        qty = args.qty if args.qty is not None else 1
        payload = compose(qty)
        if len(payload) > m["victim_budget"]:
            print(f"ABORT: payload 0x{len(payload):X} > budget 0x{m['victim_budget']:X}")
            return
        if not BACKUP.exists() or not redirected:
            BACKUP.parent.mkdir(parents=True, exist_ok=True)
            BACKUP.write_text(json.dumps({
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "entry_old": (b._read(m["toast_entry_addr"], 4) or b"").hex(),
                "victim_old": (b._read(m["victim_addr"], m["victim_budget"]) or b"").hex(),
            }, indent=1), encoding="utf-8")
        b._write(m["victim_addr"], payload.ljust(min(m["victim_budget"], len(payload) + 8), b"\x00"))
        b._write(m["toast_entry_addr"], struct.pack(">I", m["offs"][m["victim_idx"]]))
        print(f"INSTALLE : Vous avez recu {{item}}{' x' + str(qty) if qty > 1 else ''}. "
              f"(payload 0x{len(payload):X} octets)")
        return

    if args.qty is not None:
        if not redirected:
            print("Pas encore installe -- lance d'abord --install.")
            return
        payload = compose(args.qty)
        b._write(m["victim_addr"], payload.ljust(len(payload) + 8, b"\x00"))
        print(f"Suffixe quantite -> {'x' + str(args.qty) if args.qty > 1 else '(aucun)'}")
        return

    # --status : décode la phrase actuellement pointée
    a = m["txt2"] + cur_off
    raw = b._read(a, 0x80) or b""
    out, i = [], 0
    while i + 1 < len(raw):
        u, = struct.unpack_from(">H", raw, i)
        if u == 0:
            break
        if u == 0x0E:
            g, t, sz = struct.unpack_from(">HHH", raw, i + 2)
            out.append(f"{{tag {g}/{t}}}")
            i += 8 + sz
            continue
        out.append(chr(u))
        i += 2
    print(f"phrase active : {''.join(out)!r}")


if __name__ == "__main__":
    main()
