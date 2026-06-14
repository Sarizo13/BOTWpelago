"""
Overlay "objet reçu" — toast transparent, toujours au premier plan, par-dessus le jeu.

Affiche "» Objet reçu : <nom>" en haut-droite quelques secondes. File d'attente.
Utilise WS_EX_TOPMOST | WS_EX_NOACTIVATE (API Windows) pour s'afficher par-dessus le
plein écran BORDERLESS de Cemu sans lui voler le focus. (Le plein écran exclusif DX,
rare, ne peut pas être survolé par une fenêtre — utiliser le borderless dans ce cas.)
"""
from __future__ import annotations

import tkinter as tk

try:
    import ctypes
    from ctypes import wintypes
    _user32 = ctypes.windll.user32
    _GWL_EXSTYLE = -20
    _WS_EX_TOPMOST = 0x00000008
    _WS_EX_NOACTIVATE = 0x08000000
    _WS_EX_TOOLWINDOW = 0x00000080
    _HWND_TOPMOST = wintypes.HWND(-1)
    _SWP = 0x0001 | 0x0002 | 0x0010 | 0x0040  # NOSIZE|NOMOVE|NOACTIVATE|SHOWWINDOW
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowLongW.restype = ctypes.c_long
    _HAVE_WIN = True
except Exception:
    _HAVE_WIN = False


class Overlay:
    def __init__(self, root: tk.Tk, duration_ms: int = 3500) -> None:
        self.root = root
        self.duration = duration_ms
        self._queue: list[str] = []
        self._showing = False
        self._hwnd = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", 0.90)
        except tk.TclError:
            pass
        self.win.configure(bg="#0e1116")
        self._frame = tk.Frame(self.win, bg="#0e1116", highlightthickness=2,
                               highlightbackground="#2ea043")
        self._frame.pack(fill="both", expand=True)
        self.lbl = tk.Label(self._frame, text="", bg="#0e1116", fg="#7ee787",
                            font=("Segoe UI", 14, "bold"), padx=22, pady=12)
        self.lbl.pack()
        self.win.update_idletasks()
        self._apply_win_styles()
        self.win.withdraw()

    def _apply_win_styles(self) -> None:
        """Fenêtre topmost SANS activation (ne vole pas le focus au jeu plein écran)."""
        if not _HAVE_WIN:
            return
        try:
            self._hwnd = self.win.winfo_id()
            ex = _user32.GetWindowLongW(self._hwnd, _GWL_EXSTYLE)
            ex |= _WS_EX_TOPMOST | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW
            _user32.SetWindowLongW(self._hwnd, _GWL_EXSTYLE, ex)
        except Exception:
            self._hwnd = None

    def _assert_topmost(self) -> None:
        if _HAVE_WIN and self._hwnd:
            try:
                _user32.SetWindowPos(self._hwnd, _HWND_TOPMOST, 0, 0, 0, 0, _SWP)
            except Exception:
                pass

    def notify(self, name: str) -> None:
        self._queue.append(name)
        if not self._showing:
            self._next()

    def _next(self) -> None:
        if not self._queue:
            self._showing = False
            self.win.withdraw()
            return
        self._showing = True
        name = self._queue.pop(0)
        self.lbl.config(text=f"»  Objet reçu : {name}")
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        sw = self.win.winfo_screenwidth()
        self.win.geometry(f"{w}x{h}+{sw - w - 24}+48")   # haut-droite
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self._assert_topmost()                            # topmost sans activation
        self.win.after(self.duration, self._next)

    def destroy(self) -> None:
        try:
            self.win.destroy()
        except tk.TclError:
            pass
