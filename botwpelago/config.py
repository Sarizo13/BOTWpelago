"""
Configuration persistee de BOTWpelago.

Stockee dans %USERPROFILE%/.botwpelago/config.json (survit aux deplacements de l'.exe,
toujours inscriptible). Tous les champs ont un defaut raisonnable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path


CONFIG_DIR = Path.home() / ".botwpelago"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass
class Config:
    # Connexion Archipelago
    server: str = "archipelago.gg:38281"   # host:port
    slot: str = ""                          # nom du slot AP
    password: str = ""

    # Cemu / save
    cemu_folder: str = ""                   # dossier d'install Cemu (auto-detect si vide)
    user_slot: str = ""                     # sous-slot Cemu a surveiller (ex: 80000002), optionnel
    save_path: str = ""                     # chemin direct vers game_data.sav, optionnel

    # Divers
    graphic_packs_folder: str = ""          # dossier Cemu/graphicPacks (pour install future du pack)
    auto_connect: bool = False              # se connecter au lancement
    overlay_enabled: bool = True            # toast "objet reçu" par-dessus le jeu

    @classmethod
    def load(cls) -> "Config":
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()
        # ne garde que les champs connus (tolerant aux versions)
        known = {f for f in cls().__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
