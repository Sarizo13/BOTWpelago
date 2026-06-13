"""
run_ap_server — lance un serveur Archipelago LOCAL pour tester BOTWpelago, sans avoir
a recreer une room a chaque fois.

Pipeline :
  1. (--update-world) reconstruit botw.apworld depuis worlds/botw -> custom_worlds/ de l'install AP
  2. genere une seed depuis players/botw_test.yaml (si aucune seed ou --regen)
  3. heberge la seed la plus recente via ArchipelagoServer.exe (localhost:38281 par defaut)

Le GUI BOTWpelago se connecte alors a  ws://localhost:38281  (nom de slot = celui du yaml).

Usage :
    python tools/run_ap_server.py                 # héberge la seed existante (génère si aucune)
    python tools/run_ap_server.py --regen         # régénère une seed fraîche puis héberge
    python tools/run_ap_server.py --update-world  # rebuild l'apworld depuis worlds/botw d'abord
    python tools/run_ap_server.py --ap-dir "D:\\autre\\Archipelago"
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_AP_DIR = Path(r"C:\ProgramData\Archipelago")
PLAYERS_DIR = PROJECT / "players"


def build_apworld(ap_dir: Path) -> None:
    """Zippe worlds/botw -> custom_worlds/botw.apworld (prefixe 'botw/')."""
    src = PROJECT / "worlds" / "botw"
    if not src.is_dir():
        print(f"  ! worlds/botw introuvable ({src}) — skip build")
        return
    dst = ap_dir / "custom_worlds" / "botw.apworld"
    dst.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for f in src.rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, Path("botw") / f.relative_to(src))
                n += 1
    print(f"  apworld reconstruit -> {dst}  ({n} fichiers)")


def newest_seed(ap_dir: Path) -> Path | None:
    seeds = sorted((ap_dir / "output").glob("AP_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    return seeds[0] if seeds else None


def generate(ap_dir: Path) -> bool:
    gen = ap_dir / "ArchipelagoGenerate.exe"
    if not gen.exists():
        print(f"  ! {gen} introuvable.")
        return False
    print(f"  Génération depuis {PLAYERS_DIR} …")
    # --player_files_path : ne prend QUE notre yaml de test (seed solo BotW)
    res = subprocess.run([str(gen), "--player_files_path", str(PLAYERS_DIR)],
                         cwd=str(ap_dir))
    if res.returncode != 0:
        print(f"  ! Génération échouée (code {res.returncode}).")
        return False
    print("  Génération OK.")
    return True


def host(ap_dir: Path, seed: Path) -> None:
    server = ap_dir / "ArchipelagoServer.exe"
    if not server.exists():
        print(f"  ! {server} introuvable.")
        return
    print(f"\n  Hébergement de {seed.name}  (Ctrl+C pour arrêter)")
    print("  -> Connecte BOTWpelago à  localhost:38281\n")
    subprocess.run([str(server), str(seed)], cwd=str(ap_dir))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ap-dir", default=str(DEFAULT_AP_DIR), help="Dossier install Archipelago")
    ap.add_argument("--regen", action="store_true", help="Régénérer une seed fraîche")
    ap.add_argument("--update-world", action="store_true", help="Rebuild botw.apworld depuis worlds/botw")
    ap.add_argument("--no-host", action="store_true", help="Générer seulement, ne pas héberger")
    args = ap.parse_args()

    ap_dir = Path(args.ap_dir)
    if not ap_dir.is_dir():
        print(f"ERREUR: install Archipelago introuvable: {ap_dir}")
        sys.exit(1)
    print(f"Archipelago: {ap_dir}")

    if args.update_world:
        build_apworld(ap_dir)

    if args.regen or newest_seed(ap_dir) is None:
        if not generate(ap_dir):
            sys.exit(1)

    seed = newest_seed(ap_dir)
    if seed is None:
        print("ERREUR: aucune seed dans output/ après génération.")
        sys.exit(1)
    print(f"Seed: {seed.name}")

    if not args.no_host:
        host(ap_dir, seed)


if __name__ == "__main__":
    main()
