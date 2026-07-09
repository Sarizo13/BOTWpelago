"""
build_mod — construit les patches mod BOTWpelago depuis le dump local.

Pipeline (100 % local, rien de dérivé du jeu n'entre dans le repo) :
  1. lit les chemins base/update/dlc + graphicPacks dans ~/.botwpelago/config.json
  2. pour chaque patch (mod/patches/) : ouvre les conteneurs (Yaz0/SARC big-endian),
     applique les transforms, RE-PARSE chaque artefact et vérifie les post-conditions
  3. écrit les fichiers DANS LE PACK RANDO « BOTWpelago » s'il existe (un seul pack,
     un seul Bootup.pack — deux packs qui remplacent le même fichier entrent en
     CONFLIT dans Cemu, c'est ce qui a cassé le 1er test in-game), sinon dans un pack
     autonome « BOTWpelago_Enforcement ».

Les sources sont LAYERÉES : un fichier déjà présent dans le pack rando (ex son
Bootup.pack) sert de base à nos patches — ses modifs sont préservées.
⚠️ pack_builder RÉGÉNÈRE le pack rando à chaque seed → relancer build_mod après.

Usage :
    python mod/build_mod.py            # construit + installe (voir ci-dessus)
    python mod/build_mod.py --check    # dry-run : applique + vérifie, n'écrit rien
    python mod/build_mod.py --out DIR  # cible explicite (dossier de pack)
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import oead
from evfl import EventFlow

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patches import PatchError, get_patches, get_file_patches  # noqa: E402

PACK_NAME = "BOTWpelago_Enforcement"

RULES_TXT = """[Definition]
titleIds = 00050000101C9300,00050000101C9400,00050000101C9500
name = BOTWpelago - Enforcement
path = "The Legend of Zelda: Breath of the Wild/BOTWpelago Enforcement"
description = Enforcement dur BOTWpelago (Archipelago) : le paravoile n'est plus donne par le jeu, il arrive par le multiworld.|Genere par mod/build_mod.py - ne pas editer a la main.
version = 4
"""


def _config_paths() -> tuple[list[Path], Path]:
    cfg = json.loads((Path.home() / ".botwpelago" / "config.json").read_text(encoding="utf-8"))
    roots = [Path(cfg[k]) for k in ("game_update_path", "game_base_path", "game_dlc_path")
             if cfg.get(k) and Path(cfg[k]).is_dir()]
    if not roots:
        raise SystemExit("Aucun chemin de dump valide dans ~/.botwpelago/config.json")
    gfx = Path(cfg.get("graphic_packs_folder", ""))
    return roots, gfx


def _resolve(roots: list[Path], rel: str) -> Path:
    for root in roots:
        p = root / rel
        if p.is_file():
            return p
    raise FileNotFoundError(f"{rel} introuvable dans {[str(r) for r in roots]}")


def build_patched_container(src: Path, inner: str, transform, verify, log=print) -> bytes:
    """Retourne les octets du conteneur patché (même compression que l'original)."""
    raw = src.read_bytes()
    was_yaz0 = raw[:4] == b"Yaz0"
    dec = bytes(oead.yaz0.decompress(raw)) if was_yaz0 else raw
    if dec[:4] != b"SARC":
        raise PatchError(f"{src.name} n'est pas un SARC")
    sarc = oead.Sarc(dec)

    flow_bytes = None
    for f in sarc.get_files():
        if f.name == inner:
            flow_bytes = bytes(f.data)
            break
    if flow_bytes is None:
        raise PatchError(f"{inner} absent de {src.name}")

    flow = EventFlow()
    flow.read(flow_bytes)
    transform(flow)
    buf = io.BytesIO()
    flow.write(buf)
    patched = buf.getvalue()

    # vérification sur les octets RÉ-ÉCRITS re-parsés (pas l'objet en mémoire)
    reparsed = EventFlow()
    reparsed.read(patched)
    verify(reparsed)
    log(f"    {inner}: {len(flow_bytes)} -> {len(patched)} octets, vérif OK")

    writer = oead.SarcWriter.from_sarc(sarc)
    writer.set_mode(oead.SarcWriter.Mode.Legacy)      # alignement Wii U (BotW)
    writer.files[inner] = oead.Bytes(patched)
    _, data = writer.write()
    out = bytes(data)
    if was_yaz0:
        out = bytes(oead.yaz0.compress(out))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Construit le graphic pack BOTWpelago_Enforcement")
    ap.add_argument("--check", action="store_true", help="dry-run : patch + vérif, n'écrit rien")
    ap.add_argument("--out", default=None, help="dossier graphicPacks cible (défaut : config)")
    args = ap.parse_args()

    roots, gfx = _config_paths()

    # Cible : le pack rando « BOTWpelago » s'il existe (UN seul pack → pas de conflit
    # Cemu sur Bootup.pack), sinon pack autonome. --out force une cible explicite.
    rando_pack = gfx / "BOTWpelago"
    if args.out:
        pack_dir, standalone = Path(args.out), True
    elif rando_pack.is_dir():
        pack_dir, standalone = rando_pack, False
    else:
        pack_dir, standalone = gfx / PACK_NAME, True

    def read_source(rel: str) -> bytes:
        # layering : le pack cible d'abord (préserve les modifs du rando), puis le dump
        in_pack = pack_dir / "content" / rel
        if in_pack.is_file():
            return in_pack.read_bytes()
        return _resolve(roots, rel).read_bytes()

    patches = get_patches()
    file_patches = get_file_patches()
    print(f"{len(patches) + len(file_patches)} patch(es) ; dump : {roots[0]}")
    print(f"cible : {pack_dir}" + ("" if standalone else "  (fusion dans le pack rando)"))
    results: dict[str, bytes] = {}
    for p in patches:
        print(f"  [{p.name}] {p.description}")
        src = _resolve(roots, p.container)
        results[p.container] = build_patched_container(src, p.inner, p.transform, p.verify)

    for fp in file_patches:
        print(f"  [{fp.NAME}] {fp.DESCRIPTION}")
        results.update(fp.build(read_source, log=print))

    if args.check:
        print("\n--check : tout est patchable et vérifié, rien n'a été écrit.")
        return

    if not pack_dir.parent.is_dir():
        raise SystemExit(f"dossier cible introuvable : {pack_dir.parent}")
    for rel, data in results.items():
        dst = pack_dir / "content" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        print(f"  écrit {dst}")
    if standalone:
        (pack_dir / "rules.txt").write_text(RULES_TXT, encoding="utf-8")
    else:
        # purge l'ancien pack séparé : son Bootup.pack entre en conflit avec le rando
        stale = gfx / PACK_NAME
        if stale.is_dir():
            import shutil
            shutil.rmtree(stale)
            print(f"  supprimé (conflit Bootup.pack) : {stale}")
    print(f"\nPack : {pack_dir}")
    print("Dans Cemu : un SEUL pack à cocher — « BOTWpelago ». Relance le jeu après.")


if __name__ == "__main__":
    main()
