"""
Patches EventFlow du mod BOTWpelago (V2).

Chaque patch décrit UN fichier .bfevfl à modifier dans UN conteneur du dump, via :
  - transform(flow) : modifie l'EventFlow en place (lève PatchError si la cible est absente),
  - verify(flow)    : post-condition, relancée sur les octets RÉ-ÉCRITS puis re-parsés.

RÈGLE LÉGALE : ce package ne contient QUE notre code. Les fichiers du jeu sont lus depuis
le dump local du joueur au moment du build et le résultat va dans graphicPacks/ (hors repo).
Rien de dérivé du jeu n'est jamais commité.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from evfl import EventFlow


class PatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class FlowPatch:
    name: str                                  # identifiant court (logs)
    container: str                             # chemin relatif à content/ (ex Event/FindDungeon.sbeventpack)
    inner: str                                 # fichier DANS le SARC (ex EventFlow/FindDungeon.bfevfl)
    transform: Callable[[EventFlow], None]
    verify: Callable[[EventFlow], None]
    description: str = ""


def get_patches() -> list[FlowPatch]:
    from . import paraglider
    return [paraglider.PATCH]


def get_file_patches():
    """Patches « fichiers entiers » : modules exposant NAME, DESCRIPTION et
    build(read_source, log) -> dict[rel_path, bytes]."""
    from . import starter_kit, zone_gate
    return [zone_gate, starter_kit]
