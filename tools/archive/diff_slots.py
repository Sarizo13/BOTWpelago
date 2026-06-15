"""
Compare octet par octet deux slots PouchItem (0x220) pour identifier les champs
qui pilotent l'identite/l'icone d'un item (au-dela du nom + type + valeur).

Les pointeurs internes auto-referents et les liens de liste sont normalises (rebases
sur 0) pour ne montrer que les VRAIES differences de contenu.

Lecture seule. Usage (PowerShell admin, Cemu en jeu) :
    python tools/diff_slots.py 4 26        # compare slot 4 (notre essai) et slot 26 (vraie pomme)
"""
import sys
import struct
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge, _ITEM_STRIDE

CEMU_MEM_BASE = 0x247E4440000
STRIDE = _ITEM_STRIDE


def norm_word(word, node_guest):
    """Si word est un pointeur dans [node, node+0x220), le rebaser sur 0 (offset interne)."""
    if node_guest <= word < node_guest + STRIDE:
        return ("SELF+0x%X" % (word - node_guest))
    return "0x%08X" % word


def main():
    a_slot = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    b_slot = int(sys.argv[2]) if len(sys.argv) > 2 else 26

    bridge = CemuMemoryBridge()
    if not bridge.attach() or not bridge.has_live_inventory:
        print("ERREUR attach / inventaire live introuvable.")
        return
    inv = bridge._inv_base

    a_h = inv + a_slot * STRIDE
    b_h = inv + b_slot * STRIDE
    a_g = a_h - CEMU_MEM_BASE
    b_g = b_h - CEMU_MEM_BASE
    a = bridge._read(a_h, STRIDE)
    b = bridge._read(b_h, STRIDE)
    if not a or not b:
        print("Lecture echouee.")
        return

    print(f"slot {a_slot} guest=0x{a_g:08X}  vs  slot {b_slot} guest=0x{b_g:08X}")
    a_name = a[8:8+40].split(b"\x00")[0].decode("ascii", "backslashreplace")
    b_name = b[8:8+40].split(b"\x00")[0].decode("ascii", "backslashreplace")
    print(f"  nom A={a_name!r}  nom B={b_name!r}\n")
    print("  offsets differents (apres normalisation des pointeurs internes) :")

    LINK_OFFS = {0x204, 0x208, 0x21C}  # liens de liste (attendus differents)
    diffs = 0
    for off in range(0, STRIDE, 4):
        wa = struct.unpack_from(">I", a, off)[0]
        wb = struct.unpack_from(">I", b, off)[0]
        na = norm_word(wa, a_g)
        nb = norm_word(wb, b_g)
        if na != nb:
            tag = "  (lien de liste)" if off in LINK_OFFS else ""
            # zone nom = +0x08..+0x48
            if 0x08 <= off < 0x48:
                tag = "  (buffer nom)"
            print(f"    +0x{off:03X}: A={na:14s}  B={nb:14s}{tag}")
            diffs += 1
    print(f"\n  {diffs} mots differents.")


if __name__ == "__main__":
    main()
