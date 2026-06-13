"""
save_watch.py — Capture propre des écritures de game_data.sav par Cemu.

Surveille un fichier game_data.sav et en fait une copie horodatée à CHAQUE
écriture, mais uniquement une fois l'écriture stabilisée (pas de fichier corrompu
copié en plein milieu d'un flush Cemu). Dédup par hash de contenu.

Usage :
    python save_watch.py --save "D:\\...\\user\\80000002\\2\\game_data.sav"
    python save_watch.py --save "...\\game_data.sav" --out snapshots --label oman_au_

Workflow type pour résoudre le mapping de hash :
    1. Lance le watcher AVANT de toucher au jeu.
    2. In-game : sauvegarde manuelle (slot 2) -> snapshot "before".
    3. Recharge ce save (pour repartir d'un état identique).
    4. Fais UNE seule action qui complète le shrine (coffre intérieur), rien d'autre.
    5. Sauvegarde manuelle (slot 2) -> snapshot "after".
    6. Ctrl+C. Tu as before/after avec un delta minimal.

stdlib uniquement, Windows/Linux/Mac.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path


def _stat(p: Path) -> tuple[int, float] | None:
    try:
        st = p.stat()
        return st.st_size, st.st_mtime
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _sha1(p: Path) -> str | None:
    try:
        h = hashlib.sha1()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except (PermissionError, OSError):
        return None  # fichier verrouillé / en cours d'écriture


def watch(save: Path, out: Path, label: str,
          interval: float, stable: float) -> None:
    out.mkdir(parents=True, exist_ok=True)
    print(f"[*] watch   : {save}")
    print(f"[*] out     : {out.resolve()}")
    print(f"[*] règle   : copie après {stable:.1f}s sans changement (poll {interval:.1f}s)")
    print("[*] Ctrl+C pour arrêter.\n")

    counter = 0
    last_copied_hash: str | None = None
    snapshots: list[tuple[int, Path, str]] = []

    pending_sig: tuple[int, float] | None = None
    pending_since = 0.0

    # snapshot initial de l'état courant (= ta baseline)
    cur = _stat(save)
    if cur is not None:
        pending_sig, pending_since = cur, 0.0  # forcera une copie immédiate

    try:
        while True:
            now = time.monotonic()
            sig = _stat(save)

            if sig is None:
                # fichier momentanément absent/verrouillé
                pending_sig = None
                time.sleep(interval)
                continue

            if sig != pending_sig:
                # le fichier vient de changer -> on (re)démarre le compteur de stabilité
                pending_sig = sig
                pending_since = now
            else:
                # inchangé depuis pending_since : stable ?
                if pending_since is not None and (now - pending_since) >= stable:
                    digest = _sha1(save)
                    if digest is None:
                        # encore verrouillé, on retentera
                        pending_since = now
                    elif digest != last_copied_hash:
                        counter += 1
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        dest = out / f"{label}game_data_{ts}_{counter:03d}.sav"
                        shutil.copy2(save, dest)
                        last_copied_hash = digest
                        snapshots.append((counter, dest, digest))
                        print(f"[snapshot {counter:03d}] {dest.name}  "
                              f"size={sig[0]}  sha1={digest[:12]}")
                        pending_since = now  # évite recopie tant que ça ne rebouge pas

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n[*] arrêt. Snapshots capturés :")
        for n, path, digest in snapshots:
            print(f"    {n:03d}  {path.name}  ({digest[:12]})")
        if len(snapshots) >= 2:
            b = snapshots[0][1]
            a = snapshots[-1][1]
            print("\n[*] diff le plus probable (premier vs dernier) :")
            print(f'    python -m BotWClient.BotWClient --diff-saves "{b}" "{a}"')


def main() -> None:
    ap = argparse.ArgumentParser(description="Watcher de game_data.sav (Cemu).")
    ap.add_argument("--save", required=True, help="chemin vers game_data.sav à surveiller")
    ap.add_argument("--out", default="snapshots", help="dossier de sortie des snapshots")
    ap.add_argument("--label", default="", help="préfixe de nom (ex: oman_au_)")
    ap.add_argument("--interval", type=float, default=1.0, help="période de poll (s)")
    ap.add_argument("--stable", type=float, default=2.0,
                    help="durée sans changement avant copie (s)")
    args = ap.parse_args()

    save = Path(args.save)
    if not save.parent.exists():
        print(f"ERREUR: dossier introuvable : {save.parent}", file=sys.stderr)
        sys.exit(1)
    watch(save, Path(args.out), args.label, args.interval, args.stable)


if __name__ == "__main__":
    main()
