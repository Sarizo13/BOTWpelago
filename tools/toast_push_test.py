"""
toast_push_test — WRITE-TEST du toast natif « item reçu » (profil 80000010, réversible).

Reproduit EXACTEMENT l'enqueue natif (décomp FUN_02ed1f7c + asm FUN_0308e7e8) :
  0. nom d'actor -> ctx+0x2C            (ctx = *(0x1047B054) ; consommé par le refresh)
  1. pop freelist : node = *(reqMgr+0x158) ; *(0x158) = *node
  2. construit le nœud : {type 0xB, top->node+0x10, vt 0x1021D0FC, 0x40, nom d'écran, +0x50=0}
  3. splice front sur le sentinel {next @+0x14C, prev @+0x150} (liste circulaire) :
       link.prev=sent ; link.next=old ; old.prev=link ; head=link   (head publié en dernier)
  4. count++ (+0x154)
  5. bit HUD dirty : *(uiroot+0x4075C) |= 1   (uiroot = *(0x1046BDD8) ; comme FUN_03058b44)

La boucle UI draine la file -> handler type 0xB -> FUN_03080a14(0x24,0) = ouvre l'écran
MessageGet (les handlers n'utilisent PAS la string du nœud, routage par TYPE).

Usage (terminal ADMIN, Cemu+BotW lancés en jeu, file au repos, Link IMMOBILE) :
    python tools/toast_push_test.py --dry                  # état + patchs prévus, 0 write
    python tools/toast_push_test.py --actor Item_Fruit_A   # pousse le toast
    python tools/toast_push_test.py --restore              # restaure le dernier backup

Sécurité : backup par PATCH (adresse, ancien, nouveau) AVANT écriture ; post-check 10 s :
consommé par le jeu -> rien à restaurer (nœud recyclé) ; inchangé -> auto-restore ;
--restore ne réécrit un patch QUE si la mémoire contient encore NOTRE valeur.
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

from toast_queue_watch import (  # noqa: E402
    Q, NODE_VT, CTX_PTR, UIROOT_PTR, DEFSTR_PTR, DIRTY_OFF,
    SENT_NEXT, SENT_PREV, COUNT, FREELIST, CAP, print_snap,
)

BACKUP = Path.home() / ".botwpelago" / "toast_push_backup.json"
TOAST_TYPE = 0xB


class Patcher:
    """Écritures guest journalisées {addr, old, new} pour un restore sûr."""

    def __init__(self, q: Q):
        self.q = q
        self.patches: list[dict] = []

    def stage(self, guest: int, new: bytes, label: str) -> None:
        old = self.q.rd(guest, len(new))
        if len(old) != len(new):
            raise RuntimeError(f"lecture backup impossible @g:0x{guest:08X} ({label})")
        self.patches.append({"guest": f"0x{guest:08X}", "label": label,
                             "old": old.hex(), "new": new.hex()})

    def stage32(self, guest: int, val: int, label: str) -> None:
        self.stage(guest, struct.pack(">I", val), label)

    def commit(self) -> None:
        BACKUP.parent.mkdir(parents=True, exist_ok=True)
        BACKUP.write_text(json.dumps({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "heap_base": f"0x{self.q.heap:X}",
            "patches": self.patches,
        }, indent=1), encoding="utf-8")
        for p in self.patches:
            g, new = int(p["guest"], 16), bytes.fromhex(p["new"])
            if not self.q.b._write(self.q.heap + g, new):
                raise RuntimeError(f"write échoué @g:{p['guest']} ({p['label']})")
            print(f"  write {p['label']:<18} g:{p['guest']}  {p['old'][:16]}.. -> {p['new'][:16]}..")


def restore(q: Q) -> None:
    if not BACKUP.exists():
        print("Pas de backup.")
        return
    data = json.loads(BACKUP.read_text(encoding="utf-8"))
    if int(data["heap_base"], 16) != q.heap:
        print("heap_base du backup ≠ session courante (Cemu relancé) — restore sans objet.")
        return
    n_done = n_skip = 0
    for p in reversed(data["patches"]):
        g = int(p["guest"], 16)
        old, new = bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        cur = q.rd(g, len(new))
        if cur == new:
            q.b._write(q.heap + g, old)
            n_done += 1
        else:
            n_skip += 1
            print(f"  skip {p['label']} @g:{p['guest']} (le jeu a repris la main)")
    print(f"Restore : {n_done} patch(s) réécrits, {n_skip} laissés au jeu.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--actor", default="Item_Fruit_A", help="nom d'actor du toast")
    ap.add_argument("--screen", default=None,
                    help="string du nœud (défaut : copie de la SafeString DAT_10549FEC live)")
    ap.add_argument("--type", type=lambda s: int(s, 0), default=TOAST_TYPE)
    ap.add_argument("--no-ctx", action="store_true", help="ne pas écrire le nom d'actor")
    ap.add_argument("--no-dirty", action="store_true", help="ne pas poser le bit HUD dirty")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    q = Q()
    if args.restore:
        restore(q)
        return

    snap = q.snapshot()
    print_snap("AVANT", snap)
    sent = q.reqmgr + SENT_NEXT

    # ── sanity : état attendu = file vide, freelist peuplée ──────────────────
    head, tail = int(snap["head"], 16), int(snap["tail"], 16)
    count, cap = snap["count"], snap["cap"]
    if cap != 3:
        print(f"ABORT: capacité {cap} != 3 — mauvais objet ?")
        return
    if not snap["empty"] or count != 0:
        print(f"ABORT: file non vide (head={snap['head']} tail={snap['tail']} count={count})"
              " — réessaie au repos (pas de toast en cours).")
        return
    node = int(snap["freelist"], 16)
    if not q.plausible(node):
        print(f"ABORT: freelist head 0x{node:08X} implausible.")
        return
    next_free = q.rd32(node)                      # 1er mot du nœud libre = next libre
    ctx = q.rd32(CTX_PTR)
    uiroot = q.rd32(UIROOT_PTR)
    if not args.no_ctx and (not ctx or q.rd32(ctx + 0x20) != ctx + 0x2C):
        print(f"ABORT: ctx invalide (ctx=0x{ctx:08X}, top=0x{q.rd32(ctx + 0x20):08X}"
              f" attendu 0x{ctx + 0x2C:08X}).")
        return
    if not args.no_dirty and not uiroot:
        print("ABORT: uiroot nul.")
        return

    screen = args.screen
    if screen is None:
        screen = snap["defstr"] or ""             # comportement identique au pickup natif
    print(f"\nPlan : type=0x{args.type:X} screen={screen!r} actor={args.actor!r} "
          f"nœud=g:0x{node:08X} (freelist next=0x{next_free:08X})")

    pt = Patcher(q)
    if not args.no_ctx:
        buf = args.actor.encode("ascii")[:0x3F].ljust(0x40, b"\x00")
        pt.stage(ctx + 0x2C, buf, "ctx.actor")
    pt.stage32(q.reqmgr + FREELIST, next_free, "freelist.pop")
    pt.stage32(node + 0x00, args.type, "node.type")
    pt.stage32(node + 0x04, node + 0x10, "node.top")
    pt.stage32(node + 0x08, NODE_VT, "node.vtable")
    pt.stage32(node + 0x0C, 0x40, "node.bufsize")
    pt.stage(node + 0x10, screen.encode("ascii")[:0x3F].ljust(0x40, b"\x00"), "node.str")
    pt.stage(node + 0x50, b"\x00", "node.byte50")
    pt.stage32(node + 0x58, sent, "link.prev")
    pt.stage32(node + 0x54, head, "link.next")        # head == sent (file vide)
    pt.stage32(head + 4, node + 0x54, "old.prev")     # == sent+4 = tail (+0x150)
    pt.stage32(sent, node + 0x54, "head.publish")
    pt.stage32(q.reqmgr + COUNT, count + 1, "count++")
    if not args.no_dirty:
        pt.stage32(uiroot + DIRTY_OFF, q.rd32(uiroot + DIRTY_OFF) | 1, "hud.dirty")

    if args.dry:
        print("\n--dry : patchs prévus (AUCUNE écriture) :")
        for p in pt.patches:
            print(f"  {p['label']:<18} g:{p['guest']}  {p['old']} -> {p['new']}")
        return

    print("\nÉCRITURE (backup -> ~/.botwpelago/toast_push_backup.json) :")
    pt.commit()

    # ── post-check : consommé / inchangé / autre ─────────────────────────────
    print("\nPost-check (10 s) — REGARDE L'ÉCRAN (bandeau en haut ?)...")
    verdict = "inchangé"
    for _ in range(40):
        time.sleep(0.25)
        h, c = q.rd32(sent), q.rd32(q.reqmgr + COUNT)
        if h == sent and c == 0:
            verdict = "consommé"
            break
        if h != node + 0x54:
            verdict = "autre"
            break
    print(f"Verdict file : {verdict}")
    if verdict == "consommé":
        print("→ le drain UI a dépilé notre nœud (recyclé freelist) — RIEN à restaurer.")
        print("  Si le bandeau s'est affiché : VALIDÉ, on implémente push_toast().")
        print_snap("APRÈS (consommé)", q.snapshot())
    elif verdict == "inchangé":
        print("→ le drain n'a PAS consommé en 10 s — auto-restore.")
        restore(q)
        print_snap("APRÈS restore", q.snapshot())
    else:
        print("→ état intermédiaire/inattendu — PAS de restore automatique.")
        print("  Inspecte puis `--restore` si besoin (il ne réécrit que nos valeurs).")
        print_snap("APRÈS (autre)", q.snapshot())


if __name__ == "__main__":
    main()
