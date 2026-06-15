"""
Test : écrire un flag dans gd_base (via write_flag, déjà utilisé par le client) et voir
si un simple TRIGGER en jeu (rouvrir le menu / changer de zone) l'active — sans reload.

Si oui : les capacités sont injectables "presque-live" (write + trigger), pas besoin de
trouver un tableau live séparé. Si non : un reload complet reste nécessaire.

Lecture+écriture (réversible : remet à 0 avec --off). PowerShell admin + Cemu en jeu :
    python tools/test_flag_live_write.py                         # met Paraglider=1
    python tools/test_flag_live_write.py --off                   # remet à 0
    python tools/test_flag_live_write.py --flag IsGet_Obj_HeroSoul_Rito
"""
import sys, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from BotWClient.memory_injector import CemuMemoryBridge


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flag", default="IsGet_PlayerStole2", help="flag (def: Paraglider)")
    ap.add_argument("--off", action="store_true", help="remettre le flag à 0")
    args = ap.parse_args()
    val = 0 if args.off else 1

    b = CemuMemoryBridge()
    if not b.attach():
        print("ERREUR attach (admin + Cemu en jeu).")
        return
    before = b.read_flag(args.flag)
    ok = b.write_flag(args.flag, val)
    after = b.read_flag(args.flag)
    print(f"{args.flag}: avant={before}  écrit={val} ({ok})  après={after}")
    if not args.off:
        print("\n-> En jeu, déclenche un re-check SANS recharger :")
        print("   1) ouvre puis ferme la carte / le menu Sheikah")
        print("   2) si rien, change de zone (entre/sors d'un bâtiment) ou fais quelques pas")
        print("   3) regarde si la capacité est dispo (paravoile au saut, etc.)")
        print("   Annuler : python tools/test_flag_live_write.py --off")


if __name__ == "__main__":
    main()
