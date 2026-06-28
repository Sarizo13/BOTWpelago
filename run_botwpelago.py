"""Point d'entrée du build figé (PyInstaller) — BOTWpelago.exe.

Utilise des imports absolus (le `python -m botwpelago` passe par __main__.py avec
import relatif, ce qui ne fonctionne pas comme script d'entrée figé).
"""
from botwpelago.app import run

if __name__ == "__main__":
    run()
