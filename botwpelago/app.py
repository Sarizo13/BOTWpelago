"""
BOTWpelago — interface graphique (Tkinter, stdlib uniquement).

Saisie des parametres AP/Cemu, bouton Connecter/Deconnecter, statut et journal en direct.
Les parametres sont persistes dans ~/.botwpelago/config.json.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog

from .config import Config
from .runner import ClientRunner, cemu_status, reset_progress
from .overlay import Overlay
from . import __version__


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.cfg = Config.load()
        self.runner = ClientRunner()

        root.title(f"BOTWpelago v{__version__}")
        root.minsize(560, 460)

        self._entries: list[ttk.Entry] = []
        self._build_widgets()
        self._autodetect_cemu()
        self.overlay = Overlay(self.root) if self.cfg.overlay_enabled else None
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
            "save_path":   tk.StringVar(value=self.cfg.save_path),
        }
        self.auto_var = tk.BooleanVar(value=self.cfg.auto_connect)
        self.overlay_var = tk.BooleanVar(value=self.cfg.overlay_enabled)

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
            self._entries.append(ent)
            r += 1

        # dossier Cemu + Parcourir
        ttk.Label(frm, text="Dossier Cemu (optionnel)").grid(row=r, column=0, sticky="w", **pad)
        cemu_ent = ttk.Entry(frm, textvariable=self.vars["cemu_folder"])
        cemu_ent.grid(row=r, column=1, sticky="ew", **pad)
        self._entries.append(cemu_ent)
        self.browse_btn = ttk.Button(frm, text="Parcourir…", command=self._browse_cemu)
        self.browse_btn.grid(row=r, column=2, **pad)
        r += 1

        # dossier de save dédié (profil) — surveille UNIQUEMENT ce dossier (save propre/neuve)
        ttk.Label(frm, text="Dossier de save dédié (optionnel)").grid(row=r, column=0, sticky="w", **pad)
        save_ent = ttk.Entry(frm, textvariable=self.vars["save_path"])
        save_ent.grid(row=r, column=1, sticky="ew", **pad)
        self._entries.append(save_ent)
        self.browse_save_btn = ttk.Button(frm, text="Parcourir…", command=self._browse_save)
        self.browse_save_btn.grid(row=r, column=2, **pad)
        r += 1

        # boutons pré-vol "Vérifier Cemu" + "Réinitialiser progression"
        btns = ttk.Frame(frm)
        btns.grid(row=r, column=1, columnspan=2, sticky="w", **pad)
        self.check_btn = ttk.Button(btns, text="Vérifier Cemu", command=self._check_cemu)
        self.check_btn.pack(side="left")
        self.reset_btn = ttk.Button(btns, text="Réinitialiser (nouvelle seed)", command=self._reset)
        self.reset_btn.pack(side="left", padx=(8, 0))
        r += 1

        ttk.Checkbutton(frm, text="Se connecter au lancement",
                        variable=self.auto_var).grid(row=r, column=1, sticky="w", **pad)
        r += 1
        ttk.Checkbutton(frm, text="Overlay « objet reçu » par-dessus le jeu",
                        variable=self.overlay_var).grid(row=r, column=1, sticky="w", **pad)
        r += 1

        # bouton connexion + statut
        self.connect_btn = ttk.Button(frm, text="Connecter", command=self._toggle)
        self.connect_btn.grid(row=r, column=0, **pad)
        self.status_var = tk.StringVar(value="Déconnecté")
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

    def _browse_save(self) -> None:
        d = filedialog.askdirectory(
            title="Dossier de save dédié (ex: .../user/80000003 — profil neuf pour l'AP)")
        if d:
            self.vars["save_path"].set(d)

    def _autodetect_cemu(self) -> None:
        """Si le dossier Cemu est vide, le déduire du process Cemu en cours (si lancé)."""
        if self.vars["cemu_folder"].get().strip():
            return
        try:
            st = cemu_status()
        except Exception:
            return
        if st.get("folder"):
            self.vars["cemu_folder"].set(st["folder"])
            self._append(f"Dossier Cemu auto-détecté : {st['folder']}")

    def _reset(self) -> None:
        """Efface l'état AP persisté (file d'attente + item_index) pour repartir de zéro."""
        if self.runner.is_running:
            self._append("⚠ Déconnecte-toi avant de réinitialiser.")
            return
        cfg = self._collect_cfg()
        try:
            n = reset_progress(cfg)
        except Exception as exc:  # noqa: BLE001
            self._append(f"⚠ Réinitialisation impossible : {exc}")
            return
        self._append(f"Progression AP réinitialisée ({n} fichier(s) supprimé(s)). "
                     "À la prochaine connexion, tous les items seront re-reçus.")

    def _check_cemu(self) -> None:
        """Pré-vol : Cemu lancé ? appli en admin ? injection live attendue ?"""
        st = cemu_status()
        if not st["pid"]:
            self._append("⚠ Cemu n'est pas lancé — lance Cemu + BotW pour l'injection live.")
            return
        self._append(f"✓ Cemu détecté (pid {st['pid']}).")
        if st["folder"] and not self.vars["cemu_folder"].get().strip():
            self.vars["cemu_folder"].set(st["folder"])
        if st["admin"]:
            self._append("✓ Admin OK → injection live disponible.")
        else:
            self._append("⚠ PAS en admin → injection en mode save-file (reload requis). "
                         "Relance BOTWpelago en administrateur pour l'injection live.")

    def _collect_cfg(self) -> Config:
        self.cfg.server = self.vars["server"].get().strip()
        self.cfg.slot = self.vars["slot"].get().strip()
        self.cfg.password = self.vars["password"].get()
        self.cfg.cemu_folder = self.vars["cemu_folder"].get().strip()
        self.cfg.save_path = self.vars["save_path"].get().strip()
        self.cfg.auto_connect = self.auto_var.get()
        self.cfg.overlay_enabled = self.overlay_var.get()
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

    def _maybe_overlay(self, line: str) -> None:
        """Affiche un toast overlay quand une ligne '[Item] <nom>' passe dans le journal."""
        if not self.overlay_var.get() or not line.startswith("[Item] "):
            return
        name = line[len("[Item] "):].split("  —")[0].split("  -")[0].strip()
        if not name:
            return
        if self.overlay is None:
            self.overlay = Overlay(self.root)
        self.overlay.notify(name)

    def _poll(self) -> None:
        # vide la queue de logs
        q = self.runner.log_queue
        while not q.empty():
            try:
                line = q.get_nowait()
            except Exception:
                break
            self._append(line)
            self._maybe_overlay(line)
        # statut + libelle bouton + grisage des champs
        running = self.runner.is_running
        if running:
            self.connect_btn["text"] = "Déconnecter"
            if self.runner.is_connected:
                mode = "injection live" if self.runner.live_injection else "save-file"
                self.status_var.set(f"Connecté ✓  ({mode})")
            else:
                self.status_var.set("Connexion…")
        else:
            self.connect_btn["text"] = "Connecter"
            self.status_var.set("Déconnecté")

        field_state = "disabled" if running else "normal"
        for ent in self._entries:
            if str(ent["state"]) != field_state:
                ent["state"] = field_state
        self.browse_btn["state"] = field_state
        self.browse_save_btn["state"] = field_state
        self.reset_btn["state"] = field_state
        self.root.after(200, self._poll)


def run() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
