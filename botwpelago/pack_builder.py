"""
PackBuilder — étapes 2-3 du flux BOTWpelago.

À partir du config AP reçu par le joueur (BotW_AP_config_*.json), pilote le rando
.NET embarqué pour produire le graphic pack Cemu (placeholder rubis vert dans chaque
coffre de sanctuaire), directement dans le dossier graphicPacks de Cemu.

Le rando lit :
  - args[0] : un settings.json {StringSettings:{BasePath,UpdatePath,DlcPath,GfxPackPath}}
  - args[1] : la seed (déterminisme du shuffle overworld)
  - env BOTW_AP_CONFIG : le config AP {settings, placements}
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

PACK_DIR_NAME = "BOTWpelago"        # nom de sortie du rando (doit matcher Randomizer.cs)


class PackBuildError(RuntimeError):
    pass


def locate_rando_exe(override: str | None = None) -> Path:
    """
    Trouve l'exe du rando .NET embarqué.

    Ordre : override explicite → env BOTW_RANDO_EXE → bundle (exe figé) → arbre dev.
    """
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    env = os.environ.get("BOTW_RANDO_EXE")
    if env:
        candidates.append(Path(env))
    # PyInstaller : ressources dépaquetées dans _MEIPASS, ou à côté de l'exe figé
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates += [
            base / "rando" / "BotwRandoCLI.exe",
            Path(sys.executable).parent / "rando" / "BotwRandoCLI.exe",
        ]
    # Arbre de dev (source du rando GPL dans le repo)
    repo = Path(__file__).resolve().parents[1]
    candidates.append(
        repo / "rando" / "bin" / "Release" / "net8.0-windows" / "BotwRandoCLI.exe"
    )
    for c in candidates:
        if c.is_file():
            return c
    raise PackBuildError(
        "Exécutable du rando introuvable. Cherché : "
        + ", ".join(str(c) for c in candidates)
    )


def _content_dir(game_root: str) -> str:
    """
    Le rando attend des chemins '.../content'. Accepte aussi un dossier parent
    contenant 'content' et le complète automatiquement.
    """
    p = Path(game_root)
    if p.name.lower() == "content":
        return str(p)
    if (p / "content").is_dir():
        return str(p / "content")
    return str(p)   # laisse tel quel ; le rando lèvera une erreur claire si invalide


def build_pack(
    config_path: str | Path,
    base_path: str,
    update_path: str,
    dlc_path: str,
    gfx_path: str,
    *,
    rando_exe: str | None = None,
    log: Callable[[str], None] = print,
    timeout: int = 1200,
) -> Path:
    """
    Construit le graphic pack à partir du config AP. Retourne le dossier du pack produit.
    Lève PackBuildError en cas d'échec.
    """
    config_path = Path(config_path)
    if not config_path.is_file():
        raise PackBuildError(f"Config AP introuvable : {config_path}")
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PackBuildError(f"Config AP illisible : {exc}") from exc
    if "placements" not in cfg or "settings" not in cfg:
        raise PackBuildError("Config AP invalide (sections 'settings'/'placements' manquantes).")

    seed = str(cfg.get("seed", "APSEED"))
    exe = locate_rando_exe(rando_exe)
    gfx = Path(gfx_path)
    gfx.mkdir(parents=True, exist_ok=True)

    # settings.json temporaire à côté du config
    settings = {
        "StringSettings": {
            "BasePath":    {"Value": _content_dir(base_path)},
            "UpdatePath":  {"Value": _content_dir(update_path)},
            "DlcPath":     {"Value": _content_dir(dlc_path)},
            "GfxPackPath": {"Value": str(gfx)},
        }
    }
    settings_path = config_path.with_name("_botwpelago_rando_settings.json")
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    placements = cfg.get("placements", {})
    log(f"Construction du pack : {len(placements)} coffres, seed {seed}")
    log(f"  rando  : {exe.name}")
    log(f"  sortie : {gfx}")

    env = os.environ.copy()
    env["BOTW_AP_CONFIG"] = str(config_path)

    try:
        proc = subprocess.run(
            [str(exe), str(settings_path), seed],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise PackBuildError(f"Le rando a dépassé le délai ({timeout}s).") from exc
    finally:
        settings_path.unlink(missing_ok=True)

    tail = "\n".join((proc.stdout or "").splitlines()[-3:])
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[-600:]
        raise PackBuildError(f"Le rando a échoué (code {proc.returncode}) :\n{err}")

    pack_dir = gfx / PACK_DIR_NAME
    if not pack_dir.is_dir():
        raise PackBuildError(
            f"Le rando s'est terminé mais le pack est introuvable : {pack_dir}\n{tail}"
        )
    log(f"  [OK] Pack généré : {pack_dir}")
    return pack_dir
