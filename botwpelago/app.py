"""
BOTWpelago — interface graphique (Tkinter, stdlib uniquement).

Saisie des parametres AP/Cemu, bouton Connecter/Deconnecter, statut et journal en direct.
Les parametres sont persistes dans ~/.botwpelago/config.json.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog

from .config import Config
from .runner import ClientRunner
from . import __version__


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.cfg = Config.load()
        self.runner = ClientRunner()

        root.title(f"BOTWpelago v{__version__}")
        root.minsize(560, 460)

        self._build_widgets()
        self._poll()  # boucle de rafraichissement UI

        if self.cfg.auto_connect and self.cfg.slot:
            self._connect()

    # ── construction UI ───────────────────────────────────────────────────────
    def _build_widgets(self) -> None:
        pad = dict(padx=8, pady=4)
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        self.vars = {
            "server":      tk.StringVar(value=self.cfg.server),
            "slot":        tk.StringVar(value=self.cfg.slot),
            "password":    tk.StringVar(value=self.cfg.password),
            "cemu_folder": tk.StringVar(value=self.cfg.cemu_folder),
        }
        self.auto_var = tk.BooleanVar(value=self.cfg.auto_connect)

        rows = [
            ("Serveur AP (host:port)", "server", False),
            ("Nom du slot",            "slot",   False),
            ("Mot de passe",           "password", True),
        ]
        r = 0
        for label, key, secret in rows:
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", **pad)
            ent = ttk.Entry(frm, textvariable=self.vars[key], show="*" if secret else "")
            ent.grid(row=r, column=1, columnspan=2, sticky="ew", **pad)
            r += 1

        # dossier Cemu + Parcourir
        ttk.Label(frm, text="Dossier Cemu (optionnel)").grid(row=r, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.vars["cemu_folder"]).grid(row=r, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Parcourir…", command=self._browse_cemu).grid(row=r, column=2, **pad)
        r += 1

        ttk.Checkbutton(frm, text="Se connecter au lancement",
                        variable=self.auto_var).grid(row=r, column=1, sticky="w", **pad)
        r += 1

        # bouton connexion + statut
        self.connect_btn = ttk.Button(frm, text="Connecter", command=self._toggle)
        self.connect_btn.grid(row=r, column=0, **pad)
        self.status_var = tk.StringVar(value="Deconnecte")
        ttk.Label(frm, textvariable=self.status_var, font=("", 10, "bold")).grid(
            row=r, column=1, columnspan=2, sticky="w", **pad)
        r += 1

        # journal
        ttk.Label(frm, text="Journal").grid(row=r, column=0, sticky="w", **pad)
        r += 1
        self.log = tk.Text(frm, height=14, wrap="word", state="disabled",
                           bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 9))
        self.log.grid(row=r, column=0, columnspan=3, sticky="nsew", **pad)
        frm.rowconfigure(r, weight=1)
        sb = ttk.Scrollbar(frm, command=self.log.yview)
        sb.grid(row=r, column=3, sticky="ns")
        self.log["yscrollcommand"] = sb.set

    # ── actions ───────────────────────────────────────────────────────────────
    def _browse_cemu(self) -> None:
        d = filedialog.askdirectory(title="Dossier d'installation de Cemu")
        if d:
            self.vars["cemu_folder"].set(d)

    def _collect_cfg(self) -> Config:
        self.cfg.server = self.vars["server"].get().strip()
        self.cfg.slot = self.vars["slot"].get().strip()
        self.cfg.password = self.vars["password"].get()
        self.cfg.cemu_folder = self.vars["cemu_folder"].get().strip()
        self.cfg.auto_connect = self.auto_var.get()
        self.cfg.save()
        return self.cfg

    def _toggle(self) -> None:
        if self.runner.is_running:
            self.runner.stop()
        else:
            self._connect()

    def _connect(self) -> None:
        cfg = self._collect_cfg()
        if not cfg.slot:
            self._append("⚠ Renseigne un nom de slot avant de te connecter.")
            return
        self._append(f"Connexion a {cfg.server} en tant que '{cfg.slot}'…")
        self.runner.start(cfg)

    # ── boucle de rafraichissement ──────────────────────────────────────────────
    def _append(self, line: str) -> None:
        self.log["state"] = "normal"
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log["state"] = "disabled"

    def _poll(self) -> None:
        # vide la queue de logs
        q = self.runner.log_queue
        while not q.empty():
            try:
                self._append(q.get_nowait())
            except Exception:
                break
        # statut + libelle bouton
        if self.runner.is_running:
            self.connect_btn["text"] = "Deconnecter"
            if self.runner.is_connected:
                mode = "injection live" if self.runner.live_injection else "save-file"
                self.status_var.set(f"Connecte ✓  ({mode})")
            else:
                self.status_var.set("Connexion…")
        else:
            self.connect_btn["text"] = "Connecter"
            self.status_var.set("Deconnecte")
        self.root.after(200, self._poll)


def run() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
