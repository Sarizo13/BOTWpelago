"""
build_mod — construit le graphic pack Cemu « BOTWpelago_Enforcement » depuis le dump local.

Pipeline (100 % local, rien de dérivé du jeu n'entre dans le repo) :
  1. lit les chemins base/update/dlc + graphicPacks dans ~/.botwpelago/config.json
  2. pour chaque patch (mod/patches/) : ouvre le conteneur SARC (Yaz0 → SARC big-endian),
     parse le .bfevfl avec evfl, applique transform(), RE-PARSE le résultat et vérifie
     verify(), repacke le SARC (mode Legacy Wii U) + recompresse Yaz0 si besoin
  3. émet le pack : graphicPacks/BOTWpelago_Enforcement/{rules.txt, content/…}

Le pack est SÉPARÉ du pack rando « BOTWpelago » : activable/désactivable indépendamment
dans Cemu (Options ▸ Graphic Packs), et le client fonctionne sans lui (mod optionnel).

Usage :
    python mod/build_mod.py            # construit + installe dans graphicPacks
    python mod/build_mod.py --check    # dry-run : applique + vérifie, n'écrit rien
    python mod/build_mod.py --out DIR  # cible autre que graphicPacks
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
    if args.out:
        gfx = Path(args.out)
    pack_dir = gfx / PACK_NAME

    patches = get_patches()
    file_patches = get_file_patches()
    print(f"{len(patches) + len(file_patches)} patch(es) ; dump : {roots[0]}")
    results: dict[str, bytes] = {}
    for p in patches:
        print(f"  [{p.name}] {p.description}")
        src = _resolve(roots, p.container)
        results[p.container] = build_patched_container(src, p.inner, p.transform, p.verify)

    def read_source(rel: str) -> bytes:
        return _resolve(roots, rel).read_bytes()

    for fp in file_patches:
        print(f"  [{fp.NAME}] {fp.DESCRIPTION}")
        results.update(fp.build(read_source, log=print))

    if args.check:
        print("\n--check : tout est patchable et vérifié, rien n'a été écrit.")
        return

    if not gfx.is_dir():
        raise SystemExit(f"graphicPacks introuvable : {gfx}")
    for rel, data in results.items():
        dst = pack_dir / "content" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        print(f"  écrit {dst}")
    (pack_dir / "rules.txt").write_text(RULES_TXT, encoding="utf-8")
    print(f"\nPack généré : {pack_dir}")
    print("Dans Cemu : Options > Graphic Packs > coche « BOTWpelago - Enforcement ».")


if __name__ == "__main__":
    main()
