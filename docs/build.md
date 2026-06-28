# Build de `BOTWpelago.exe`

Application unique pour le joueur BotW : GUI (Tkinter) + client AP + rando .NET embarqué.
Le joueur lance **un seul exe** ; il fournit le fichier config AP reçu de l'hôte, génère
le graphic pack Cemu (via le rando embarqué) et lance le client pendant la partie.

## Prérequis
- **Python 3.11+** avec `pip install pyinstaller websockets`
- **.NET 8 SDK** (pour publier le rando self-contained)
- Les DLL tierces du rando dans `rando/libs/` (cf. `rando/README.md`)

## Étapes

1. **Publier le rando .NET en self-contained** (embarque le runtime .NET → l'exe ne
   dépend pas d'une install .NET sur la machine du joueur) :
   ```
   dotnet publish rando/BotwRandoLib.csproj -c Release -r win-x64 --self-contained true
   ```
   Sortie : `rando/bin/Release/net8.0-windows/win-x64/publish/` (~170 Mo).

2. **Geler l'application** avec PyInstaller :
   ```
   pyinstaller BOTWpelago.spec --noconfirm --clean
   ```
   - `ONEFILE = True` (défaut) → `dist/BOTWpelago.exe` (~100 Mo, un seul fichier ;
     démarrage un peu lent car extraction temp à chaque lancement).
   - `ONEFILE = False` → `dist/BOTWpelago/` (dossier, démarrage rapide, recommandé si
     l'exe unique est trop lent).

## Notes
- Point d'entrée : `run_botwpelago.py` (imports absolus ; le `python -m botwpelago`
  passe par un import relatif incompatible avec un script d'entrée figé).
- Données (`data/*.json`) et rando sont embarqués et résolus depuis `_MEIPASS`
  (`pack_builder.locate_rando_exe` cherche `_MEIPASS/rando/BotwRandoCLI.exe`).
- `console=True` laissé pour la phase beta (visibilité des erreurs) ; passer à `False`
  pour une release "propre" sans fenêtre console.
- Live-injection mémoire Cemu → lancer l'exe **en administrateur**.
