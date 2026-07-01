"""
play_local — orchestre une session de test BOTWpelago 100 % LOCALE, de bout en bout.

Pipeline :
  1. reconstruit  botw.apworld  depuis  worlds/botw  ->  <AP>/custom_worlds/
  2. génère une seed depuis  players/<yaml>  (défaut : Shorizo.yaml)  [ArchipelagoGenerate.exe]
  3. extrait le config `.apbotw` de la seed  ->  ~/.botwpelago/ap_config.json
  4. reconstruit le graphic pack Cemu depuis ce config (rubis-placeholder dans chaque coffre)
  5. affiche QUOI LANCER (client) puis héberge le serveur AP (localhost:38281, bloquant)

Le client se connecte à localhost:38281 par défaut :
    python -m BotWClient.BotWClient --name Shorizo

Usage :
    python tools/play_local.py                     # tout : génère + pack + héberge
    python tools/play_local.py --yaml players/Autre.yaml
    python tools/play_local.py --reuse-seed         # réutiliser la dernière seed (pas de régénération)
    python tools/play_local.py --no-pack            # sauter la reconstruction du pack
    python tools/play_local.py --no-host            # tout préparer sans héberger
    python tools/play_local.py --ap-dir "D:\\autre\\Archipelago"
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from botwpelago.config import Config, CONFIG_DIR   # noqa: E402
from botwpelago.pack_builder import build_pack, PackBuildError  # noqa: E402

DEFAULT_AP_DIR = Path(r"C:\ProgramData\Archipelago")
DEFAULT_YAML = PROJECT / "players" / "Shorizo.yaml"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def step(n: int, title: str) -> None:
    log(f"\n[{n}/5] {title}")
    log("-" * 60)


# ── 1) apworld ──────────────────────────────────────────────────────────────────
def build_apworld(ap_dir: Path) -> None:
    src = PROJECT / "worlds" / "botw"
    if not src.is_dir():
        log(f"  ! worlds/botw introuvable ({src}) — apworld non reconstruit")
        return
    dst = ap_dir / "custom_worlds" / "botw.apworld"
    dst.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for f in src.rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, Path("botw") / f.relative_to(src))
                n += 1
    log(f"  apworld reconstruit -> {dst}  ({n} fichiers)")


# ── 2) génération ───────────────────────────────────────────────────────────────
def newest_seed(ap_dir: Path) -> Path | None:
    seeds = sorted((ap_dir / "output").glob("AP_*.zip"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return seeds[0] if seeds else None


def generate(ap_dir: Path, yaml_file: Path) -> bool:
    gen = ap_dir / "ArchipelagoGenerate.exe"
    if not gen.exists():
        log(f"  ! {gen} introuvable.")
        return False
    # On isole le yaml choisi dans un dossier temp : --player_files_path prend TOUT le dossier,
    # or players/ contient aussi dltest/ (test DeathLink 2 slots) → sinon multiworld non désiré.
    tmp = Path(tempfile.mkdtemp(prefix="botwpelago_gen_"))
    try:
        shutil.copy2(yaml_file, tmp / yaml_file.name)
        log(f"  Génération depuis {yaml_file.name} …")
        res = subprocess.run([str(gen), "--player_files_path", str(tmp)], cwd=str(ap_dir))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if res.returncode != 0:
        log(f"  ! Génération échouée (code {res.returncode}).")
        return False
    log("  Génération OK.")
    return True


# ── 3) extraction du config .apbotw ──────────────────────────────────────────────
def extract_config(seed_zip: Path, slot_hint: str | None) -> Path:
    """Extrait le .apbotw de la seed -> ~/.botwpelago/ap_config.json. Retourne ce chemin."""
    with zipfile.ZipFile(seed_zip) as z:
        apbotw = [n for n in z.namelist() if n.endswith(".apbotw")]
        if not apbotw:
            raise PackBuildError(f"Aucun .apbotw dans {seed_zip.name} "
                                 "(regénère : l'apworld BotW doit émettre le config).")
        chosen = apbotw[0]
        if slot_hint and len(apbotw) > 1:
            for n in apbotw:
                if slot_hint.lower() in n.lower():
                    chosen = n
                    break
        data = z.read(chosen)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    out = CONFIG_DIR / "ap_config.json"
    out.write_bytes(data)
    cfg = json.loads(data)
    log(f"  Config extrait : {Path(chosen).name}")
    log(f"    seed {cfg.get('seed')} | slot {cfg.get('slot')} | {len(cfg.get('placements', {}))} coffres")
    log(f"    -> {out}")
    return out


# ── 4) pack graphique ────────────────────────────────────────────────────────────
def build_graphic_pack(app_cfg: Config, config_path: Path) -> Path:
    missing = [name for name, val in (
        ("game_base_path", app_cfg.game_base_path),
        ("game_update_path", app_cfg.game_update_path),
        ("game_dlc_path", app_cfg.game_dlc_path),
        ("graphic_packs_folder", app_cfg.graphic_packs_folder),
    ) if not val]
    if missing:
        raise PackBuildError(
            "Chemins manquants dans ~/.botwpelago/config.json : " + ", ".join(missing)
            + "\n  (renseigne-les via le GUI BOTWpelago, ou édite le fichier.)")
    return build_pack(
        config_path,
        base_path=app_cfg.game_base_path,
        update_path=app_cfg.game_update_path,
        dlc_path=app_cfg.game_dlc_path,
        gfx_path=app_cfg.graphic_packs_folder,
        rando_exe=(app_cfg.rando_exe_path or None),
        log=lambda m: log("  " + m),
    )


# ── 5) hébergement ───────────────────────────────────────────────────────────────
def banner(seed: Path, slot: str, pack_dir: Path | None) -> None:
    log("\n" + "=" * 60)
    log("  TOUT EST PRÊT")
    log("=" * 60)
    log(f"  Seed  : {seed.name}")
    log(f"  Slot  : {slot}")
    if pack_dir:
        log(f"  Pack  : {pack_dir}")
    log("")
    log("  ÉTAPES :")
    log("   1. Cemu : Options > Graphic Packs > coche 'BOTWpelago'")
    log("   2. Lance BotW dans Cemu et charge ta save")
    log("   3. Dans un AUTRE terminal, lance le client :")
    log(f"        python -m BotWClient.BotWClient --name {slot}")
    log("      (il se connecte à localhost:38281 par défaut)")
    log("")
    log("  Le serveur AP démarre ci-dessous. Ctrl+C pour l'arrêter.")
    log("=" * 60 + "\n")


def host(ap_dir: Path, seed: Path) -> None:
    server = ap_dir / "ArchipelagoServer.exe"
    if not server.exists():
        log(f"  ! {server} introuvable — héberge la seed manuellement.")
        return
    subprocess.run([str(server), str(seed)], cwd=str(ap_dir))


def main() -> None:
    ap = argparse.ArgumentParser(description="Session de test BOTWpelago 100% locale")
    ap.add_argument("--yaml", default=str(DEFAULT_YAML), help="Fichier joueur (défaut players/Shorizo.yaml)")
    ap.add_argument("--ap-dir", default=str(DEFAULT_AP_DIR), help="Dossier install Archipelago")
    ap.add_argument("--reuse-seed", action="store_true", help="Réutiliser la dernière seed (pas de régénération)")
    ap.add_argument("--no-pack", action="store_true", help="Sauter la reconstruction du pack graphique")
    ap.add_argument("--no-host", action="store_true", help="Tout préparer sans héberger le serveur")
    args = ap.parse_args()

    ap_dir = Path(args.ap_dir)
    yaml_file = Path(args.yaml)
    if not ap_dir.is_dir():
        log(f"ERREUR: install Archipelago introuvable : {ap_dir}")
        sys.exit(1)
    if not yaml_file.is_file():
        log(f"ERREUR: fichier joueur introuvable : {yaml_file}")
        sys.exit(1)

    app_cfg = Config.load()
    log(f"Archipelago : {ap_dir}")
    log(f"Joueur      : {yaml_file}")

    # 1) apworld
    step(1, "Reconstruction de botw.apworld")
    build_apworld(ap_dir)

    # 2) génération
    step(2, "Génération de la seed")
    if args.reuse_seed and newest_seed(ap_dir) is not None:
        log("  --reuse-seed : on garde la dernière seed.")
    else:
        if not generate(ap_dir, yaml_file):
            sys.exit(1)
    seed = newest_seed(ap_dir)
    if seed is None:
        log("ERREUR: aucune seed dans output/ après génération.")
        sys.exit(1)
    log(f"  Seed : {seed.name}")

    # 3) config
    step(3, "Extraction du config AP (.apbotw)")
    slot = yaml_file.stem
    config_path = extract_config(seed, slot_hint=slot)
    # garde l'app cohérente (le GUI/le pack pointeront sur ce config)
    try:
        app_cfg.ap_config_path = str(config_path)
        app_cfg.save()
    except Exception:
        pass

    # 4) pack graphique
    pack_dir = None
    step(4, "Reconstruction du graphic pack Cemu")
    if args.no_pack:
        log("  --no-pack : étape sautée.")
    else:
        try:
            pack_dir = build_graphic_pack(app_cfg, config_path)
        except PackBuildError as exc:
            log(f"  ! Pack NON construit : {exc}")
            log("  (tu peux continuer sans, mais les coffres n'auront pas les placeholders.)")

    # 5) hébergement
    step(5, "Hébergement du serveur AP")
    if args.no_host:
        log("  --no-host : pas d'hébergement. Pour héberger plus tard :")
        log(f'    "{ap_dir / "ArchipelagoServer.exe"}" "{seed}"')
        return
    banner(seed, slot, pack_dir)
    host(ap_dir, seed)


if __name__ == "__main__":
    main()
