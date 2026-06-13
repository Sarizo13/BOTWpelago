"""
Overlay "objet reçu" — toast transparent, toujours au premier plan, par-dessus le jeu.

Affiche "🎁 Objet reçu : <nom>" en haut de l'écran quelques secondes. File d'attente :
les items s'affichent l'un après l'autre. Marche en Cemu fenêtré/borderless (pas en
plein écran exclusif).
"""
from __future__ import annotations

import tkinter as tk


class Overlay:
    def __init__(self, root: tk.Tk, duration_ms: int = 3500) -> None:
        self.root = root
        self.duration = duration_ms
        self._queue: list[str] = []
        self._showing = False

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)            # sans bordure
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
        self.win.withdraw()

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
        self.win.after(self.duration, self._next)

    def destroy(self) -> None:
        try:
            self.win.destroy()
        except tk.TclError:
            pass
