# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — produit BOTWpelago.exe (GUI + client AP + rando .NET embarqué).

Build :  pyinstaller BOTWpelago.spec
Sortie :  dist/BOTWpelago.exe  (onefile)  ou  dist/BOTWpelago/  (onedir si ONEFILE=False)

Prérequis : publier d'abord le rando self-contained :
    dotnet publish rando/BotwRandoLib.csproj -c Release -r win-x64 --self-contained true
"""
from PyInstaller.utils.hooks import collect_submodules

ONEFILE = True   # True = un seul .exe (démarrage + lent, extraction temp) ; False = dossier

RANDO_PUBLISH = "rando/bin/Release/net8.0-windows/win-x64/publish"

datas = [
    ("data", "data"),            # JSON lus par le client (résolus en _MEIPASS/data)
    (RANDO_PUBLISH, "rando"),    # rando .NET self-contained -> _MEIPASS/rando/BotwRandoCLI.exe
]
hiddenimports = (
    collect_submodules("websockets")
    + collect_submodules("BotWClient")
    + collect_submodules("botwpelago")
)

a = Analysis(
    ["run_botwpelago.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["worlds", "pytest", "tkinter.test"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="BOTWpelago",
        debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
        runtime_tmpdir=None, console=True, disable_windowed_traceback=False,
    )
else:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="BOTWpelago",
        debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
        console=True, disable_windowed_traceback=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="BOTWpelago")
