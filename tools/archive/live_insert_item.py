"""
INSERTION live d'un NOUVEL item (POC approche A) — clone d'un template du meme type.

Methode :
  1. derive cemu_mem_base de la session (via adjacence tableau/liste).
  2. choisit un item TEMPLATE existant du type voulu (donne structure interne + champs
     d'affichage valides).
  3. choisit un noeud LIBRE (slots 0-3, type=0xFFFFFFFF, inner self-ref).
  4. copie le template -> noeud libre, re-base les pointeurs internes auto-referents.
  5. ecrit le nouveau nom + la valeur.
  6. splice le noeud juste APRES le template dans la liste active (meme type -> tri OK).
  (v1 : ne gere pas encore la free-list ni le compteur — test empirique du rendu.)

Backups de tous les noeuds touches + --restore. Usage (PowerShell admin, Cemu en jeu) :
    python tools/live_insert_item.py --name Item_Fruit_A --type 7 --value 1        # DRY-RUN
    python tools/live_insert_item.py --name Item_Fruit_A --type 7 --value 1 --commit
    python tools/live_insert_item.py --restore
"""
import sys
import struct
import json
import argparse
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge, _ITEM_STRIDE

STRIDE = _ITEM_STRIDE
OFF_NAME, OFF_TYPE, OFF_VAL = 0x08, 0x20C, 0x214
LINK, PREV = 0x204, 0x208
SEC = 0x21C   # liste secondaire : node.+0x21C -> next_node.+0x08 (simplement chainee)
BK = Path(__file__).parents[1] / "tmp" / "insert_backup.json"


def rd_u32(bridge, host):
    d = bridge._read(host, 4)
    return struct.unpack_from(">I", d, 0)[0] if d else None


def scan(bridge, inv):
    nodes = []
    for slot in range(80):
        a = inv + slot * STRIDE
        node = bridge._read(a, STRIDE)
        if not node or not (node[0] == 0x10 and node[4] == 0 and node[5] == 0 and node[6] == 0 and node[7] == 0x40):
            break
        name = node[8:8+40].split(b"\x00")[0].decode("ascii", "backslashreplace")
        typ = struct.unpack_from(">I", node, OFF_TYPE)[0]
        val = struct.unpack_from(">I", node, OFF_VAL)[0]
        nodes.append(dict(slot=slot, host=a, name=name, type=typ, val=val, raw=node))
    return nodes


def derive_base(bridge, inv, nodes):
    """base tel que node_guest = node_host - base. Via adjacence tableau/liste."""
    from collections import Counter
    cands = Counter()
    for i in range(len(nodes) - 1):
        nk, nk1 = nodes[i], nodes[i + 1]
        nxt = struct.unpack_from(">I", nk["raw"], LINK)[0]   # = guest(nk+1) + 0x204
        base = nk1["host"] + LINK - nxt
        cands[base] += 1
    if not cands:
        return None
    return cands.most_common(1)[0][0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="Item_Fruit_A")
    ap.add_argument("--type", type=int, default=7)
    ap.add_argument("--value", type=int, default=1)
    ap.add_argument("--template", default=None, help="nom de l'item a cloner (sinon 1er du type)")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    bridge = CemuMemoryBridge()
    if not bridge.attach() or not bridge.has_live_inventory:
        print("ERREUR attach / inventaire live introuvable.")
        return
    inv = bridge._inv_base

    if args.restore:
        if not BK.exists():
            print("Pas de backup.")
            return
        bk = json.loads(BK.read_text())
        for addr_s, hex_s in bk.items():
            ok = bridge._write(int(addr_s), bytes.fromhex(hex_s))
            print(f"  restore @0x{int(addr_s):012X}: {'OK' if ok else 'ECHEC'}")
        return

    nodes = scan(bridge, inv)
    base = derive_base(bridge, inv, nodes)
    if base is None:
        print("Impossible de deriver cemu_mem_base.")
        return
    print(f"inv_base host=0x{inv:012X}  cemu_mem_base=0x{base:012X}")

    def g2h(g): return g + base
    def h2g(h): return h - base

    # template : item nomme --template si fourni, sinon 1er item du type voulu (self-ref)
    template = None
    for n in nodes:
        if not n["name"]:
            continue
        if args.template is not None and n["name"] != args.template:
            continue
        if args.template is None and n["type"] != args.type:
            continue
        p64 = struct.unpack_from(">I", n["raw"], 0x64)[0]
        ng = h2g(n["host"])
        if ng <= p64 < ng + STRIDE:   # self-ref
            template = n
            break
    if not template:
        print(f"Template introuvable (--template={args.template} / type={args.type}).")
        return

    # noeud libre : type 0xFFFFFFFF, self-ref
    free = None
    for n in nodes:
        if n["type"] == 0xFFFFFFFF and not n["name"]:
            free = n
            break
    if not free:
        print("Aucun noeud libre (type=0xFFFFFFFF) trouve.")
        return

    T_h, F_h = template["host"], free["host"]
    T_g, F_g = h2g(T_h), h2g(F_h)
    print(f"  template = {template['name']!r} slot{template['slot']} host=0x{T_h:012X} guest=0x{T_g:08X}")
    print(f"  free     = slot{free['slot']} host=0x{F_h:012X} guest=0x{F_g:08X}")
    print(f"  -> creer {args.name!r} type={args.type} val={args.value} insere apres le template")

    # construire le contenu du noeud F = clone du template, pointeurs internes re-bases
    raw = bytearray(template["raw"])
    for off in range(0, STRIDE, 4):
        w = struct.unpack_from(">I", raw, off)[0]
        if T_g <= w < T_g + STRIDE:                      # pointeur interne auto-referent
            struct.pack_into(">I", raw, off, F_g + (w - T_g))
    # nom
    nb = args.name.encode("ascii")[:63]; nb = nb + b"\x00" * (64 - len(nb))
    raw[OFF_NAME:OFF_NAME+64] = nb
    # valeur
    struct.pack_into(">i", raw, OFF_VAL, args.value)

    # liste PRIMAIRE : splice F entre T et T.next
    T_next = struct.unpack_from(">I", template["raw"], LINK)[0]     # guest link du noeud suivant
    on_node_h = g2h(T_next - LINK)                                  # host du noeud "old next"
    struct.pack_into(">I", raw, LINK, T_next)                       # F.next = T.next
    struct.pack_into(">I", raw, PREV, T_g + LINK)                   # F.prev = T_link

    # liste SECONDAIRE (+0x21C, simplement chainee node.+0x21C -> next.+0x08) :
    # le clone garde deja l'ancien +0x21C de T (= pointe vers l'ancien suivant secondaire).
    # il suffit de faire pointer T vers le clone.
    T_sec_old = struct.unpack_from(">I", template["raw"], SEC)[0]   # deja dans 'raw' (clone)
    # F.+0x21C reste = T_sec_old (herite du clone) -> rien a changer dans raw.

    print("\n  ECRITURES PREVUES:")
    print(f"    F[0x{F_h:012X}] <- clone template + nom/valeur")
    print(f"        F.next=0x{T_next:08X}  F.prev=0x{T_g+LINK:08X}  F.sec(+21C)=0x{T_sec_old:08X} (herite)")
    print(f"    T[0x{T_h:012X}]+0x204 <- 0x{F_g+LINK:08X}  (T.next = F)")
    print(f"    ON[0x{on_node_h:012X}]+0x208 <- 0x{F_g+LINK:08X}  (oldnext.prev = F)")
    print(f"    T[0x{T_h:012X}]+0x21C <- 0x{F_g+OFF_NAME:08X}  (T.sec = F.+0x08)")

    if not args.commit:
        print("\n  (DRY-RUN — rien ecrit.)")
        return

    # backups
    bk = {}
    for h in (F_h, T_h, on_node_h):
        bk[str(h)] = (bridge._read(h, STRIDE) or b"").hex()
    BK.parent.mkdir(exist_ok=True)
    BK.write_text(json.dumps(bk))
    print(f"\n  Backups -> {BK} ({len(bk)} noeuds)")

    ok1 = bridge._write(F_h, bytes(raw))
    ok2 = bridge._write(T_h + LINK, struct.pack(">I", F_g + LINK))
    ok3 = bridge._write(on_node_h + PREV, struct.pack(">I", F_g + LINK))
    ok4 = bridge._write(T_h + SEC, struct.pack(">I", F_g + OFF_NAME))
    print(f"  ecritures: F={ok1} T.next={ok2} ON.prev={ok3} T.sec={ok4}")
    print("  -> Ouvre/ferme l'inventaire (onglet correspondant au type) et regarde.")
    print("  -> Annuler: python tools/live_insert_item.py --restore")


if __name__ == "__main__":
    main()
