"""
BOTWpelago — interface graphique (Tkinter, stdlib uniquement).

Deux onglets qui suivent le flux joueur :
  1. Pack       — config AP reçu + chemins du jeu → génère le graphic pack Cemu
  2. Connexion  — serveur AP + Cemu/save → lance le client pendant la partie
Les paramètres sont persistés dans ~/.botwpelago/config.json.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
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
        root.minsize(620, 560)

        self._conn_entries: list[ttk.Entry] = []   # grisés quand le client tourne
        self._pack_entries: list[ttk.Entry] = []   # grisés pendant la construction
        self._build_widgets()
        self._autodetect_cemu()
        self.overlay = Overlay(self.root) if self.cfg.overlay_enabled else None
        self._poll()

        if self.cfg.auto_connect and self.cfg.slot:
            self._connect()

    # ── construction UI ───────────────────────────────────────────────────────
    def _build_widgets(self) -> None:
        self.vars = {
            "server":               tk.StringVar(value=self.cfg.server),
            "slot":                 tk.StringVar(value=self.cfg.slot),
            "password":             tk.StringVar(value=self.cfg.password),
            "cemu_folder":          tk.StringVar(value=self.cfg.cemu_folder),
            "save_path":            tk.StringVar(value=self.cfg.save_path),
            "ap_config_path":       tk.StringVar(value=self.cfg.ap_config_path),
            "game_base_path":       tk.StringVar(value=self.cfg.game_base_path),
            "game_update_path":     tk.StringVar(value=self.cfg.game_update_path),
            "game_dlc_path":        tk.StringVar(value=self.cfg.game_dlc_path),
            "graphic_packs_folder": tk.StringVar(value=self.cfg.graphic_packs_folder),
        }
        self.auto_var = tk.BooleanVar(value=self.cfg.auto_connect)
        self.overlay_var = tk.BooleanVar(value=self.cfg.overlay_enabled)

        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)
        nb = ttk.Notebook(outer)
        nb.pack(fill="x")
        self._build_pack_tab(nb)
        self._build_conn_tab(nb)

        # journal partagé
        logfrm = ttk.Frame(outer)
        logfrm.pack(fill="both", expand=True, pady=(8, 0))
        ttk.Label(logfrm, text="Journal").pack(anchor="w")
        self.log = tk.Text(logfrm, height=14, wrap="word", state="disabled",
                           bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 9))
        self.log.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(logfrm, command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log["yscrollcommand"] = sb.set

    def _path_row(self, frm, r, label, key, entries, browse_cmd):
        pad = dict(padx=6, pady=4)
        ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", **pad)
        ent = ttk.Entry(frm, textvariable=self.vars[key])
        ent.grid(row=r, column=1, sticky="ew", **pad)
        entries.append(ent)
        ttk.Button(frm, text="Parcourir…", command=browse_cmd).grid(row=r, column=2, **pad)

    def _build_pack_tab(self, nb: ttk.Notebook) -> None:
        frm = ttk.Frame(nb, padding=10)
        frm.columnconfigure(1, weight=1)
        nb.add(frm, text="  1. Pack  ")
        e = self._pack_entries
        r = 0
        ttk.Label(frm, text="Config AP reçu, chemins du jeu (Cemu unpacked), puis génère le pack.",
                  foreground="#888").grid(row=r, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 6))
        r += 1
        self._path_row(frm, r, "Config AP (AP_*_P*_*.apbotw)", "ap_config_path", e,
                       self._browse_ap_config); r += 1
        self._path_row(frm, r, "Jeu de base (…/content)", "game_base_path", e,
                       lambda: self._browse_dir("game_base_path", "Jeu de base — dossier content")); r += 1
        self._path_row(frm, r, "Mise à jour v208 (…/content)", "game_update_path", e,
                       lambda: self._browse_dir("game_update_path", "Mise à jour — dossier content")); r += 1
        self._path_row(frm, r, "DLC (…/content, optionnel)", "game_dlc_path", e,
                       lambda: self._browse_dir("game_dlc_path", "DLC — dossier content")); r += 1
        self._path_row(frm, r, "Cemu/graphicPacks (sortie)", "graphic_packs_folder", e,
                       lambda: self._browse_dir("graphic_packs_folder", "Dossier graphicPacks de Cemu")); r += 1
        self.build_btn = ttk.Button(frm, text="Générer le graphic pack", command=self._build)
        self.build_btn.grid(row=r, column=1, sticky="w", padx=6, pady=(8, 4))

    def _build_conn_tab(self, nb: ttk.Notebook) -> None:
        frm = ttk.Frame(nb, padding=10)
        frm.columnconfigure(1, weight=1)
        nb.add(frm, text="  2. Connexion & jeu  ")
        pad = dict(padx=6, pady=4)
        e = self._conn_entries
        r = 0
        for label, key, secret in (("Serveur AP (host:port)", "server", False),
                                   ("Nom du slot", "slot", False),
                                   ("Mot de passe", "password", True)):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", **pad)
            ent = ttk.Entry(frm, textvariable=self.vars[key], show="*" if secret else "")
            ent.grid(row=r, column=1, columnspan=2, sticky="ew", **pad)
            e.append(ent)
            r += 1
        self._path_row(frm, r, "Dossier Cemu (optionnel)", "cemu_folder", e, self._browse_cemu); r += 1
        self._path_row(frm, r, "Save dédiée (optionnel)", "save_path", e, self._browse_save); r += 1

        btns = ttk.Frame(frm)
        btns.grid(row=r, column=1, columnspan=2, sticky="w", **pad)
        self.check_btn = ttk.Button(btns, text="Vérifier Cemu", command=self._check_cemu)
        self.check_btn.pack(side="left")
        self.reset_btn = ttk.Button(btns, text="Réinitialiser (nouvelle seed)", command=self._reset)
        self.reset_btn.pack(side="left", padx=(8, 0))
        r += 1
        ttk.Checkbutton(frm, text="Se connecter au lancement",
                        variable=self.auto_var).grid(row=r, column=1, sticky="w", **pad); r += 1
        ttk.Checkbutton(frm, text="Overlay « objet reçu » par-dessus le jeu",
                        variable=self.overlay_var).grid(row=r, column=1, sticky="w", **pad); r += 1
        self.connect_btn = ttk.Button(frm, text="Connecter", command=self._toggle)
        self.connect_btn.grid(row=r, column=0, **pad)
        self.status_var = tk.StringVar(value="Déconnecté")
        ttk.Label(frm, textvariable=self.status_var, font=("", 10, "bold")).grid(
            row=r, column=1, columnspan=2, sticky="w", **pad)

    # ── browse ────────────────────────────────────────────────────────────────
    def _browse_cemu(self) -> None:
        d = filedialog.askdirectory(title="Dossier d'installation de Cemu")
        if d:
            self.vars["cemu_folder"].set(d)
            self._autodetect_paths()

    def _browse_save(self) -> None:
        d = filedialog.askdirectory(title="Dossier de save dédié (ex: .../user/80000003)")
        if d:
            self.vars["save_path"].set(d)

    def _browse_ap_config(self) -> None:
        f = filedialog.askopenfilename(title="Config AP (AP_*_P*_*.apbotw)",
                                       filetypes=[("Config AP BotW", "*.apbotw"),
                                                  ("JSON", "*.json"), ("Tous", "*.*")])
        if f:
            self.vars["ap_config_path"].set(f)

    def _browse_dir(self, key: str, title: str) -> None:
        d = filedialog.askdirectory(title=title)
        if d:
            self.vars[key].set(d)

    # ── auto-détection ──────────────────────────────────────────────────────────
    def _autodetect_cemu(self) -> None:
        if not self.vars["cemu_folder"].get().strip():
            try:
                st = cemu_status()
            except Exception:
                st = {}
            if st.get("folder"):
                self.vars["cemu_folder"].set(st["folder"])
                self._append(f"Dossier Cemu auto-détecté : {st['folder']}")
        self._autodetect_paths()

    def _autodetect_paths(self) -> None:
        """Déduit graphicPacks depuis le dossier Cemu si vide."""
        cemu = self.vars["cemu_folder"].get().strip()
        if cemu and not self.vars["graphic_packs_folder"].get().strip():
            gp = Path(cemu) / "graphicPacks"
            if gp.is_dir():
                self.vars["graphic_packs_folder"].set(str(gp))

    # ── actions ───────────────────────────────────────────────────────────────
    def _reset(self) -> None:
        if self.runner.is_running:
            self._append("⚠ Déconnecte-toi avant de réinitialiser.")
            return
        try:
            n = reset_progress(self._collect_cfg())
        except Exception as exc:  # noqa: BLE001
            self._append(f"⚠ Réinitialisation impossible : {exc}")
            return
        self._append(f"Progression AP réinitialisée ({n} fichier(s) supprimé(s)).")

    def _check_cemu(self) -> None:
        st = cemu_status()
        if not st["pid"]:
            self._append("⚠ Cemu n'est pas lancé — lance Cemu + BotW pour l'injection live.")
            return
        self._append(f"✓ Cemu détecté (pid {st['pid']}).")
        if st["folder"] and not self.vars["cemu_folder"].get().strip():
            self.vars["cemu_folder"].set(st["folder"])
            self._autodetect_paths()
        if st["admin"]:
            self._append("✓ Admin OK → injection live disponible.")
        else:
            self._append("⚠ PAS en admin → injection save-file (reload requis). "
                         "Relance BOTWpelago en administrateur pour l'injection live.")

    def _build(self) -> None:
        if self.runner.is_building:
            self._append("Construction déjà en cours…")
            return
        cfg = self._collect_cfg()
        self._append("Construction du graphic pack… (peut prendre 1-3 min, ne ferme pas la fenêtre)")
        self.runner.build_pack(cfg)

    def _collect_cfg(self) -> Config:
        self.cfg.server = self.vars["server"].get().strip()
        self.cfg.slot = self.vars["slot"].get().strip()
        self.cfg.password = self.vars["password"].get()
        self.cfg.cemu_folder = self.vars["cemu_folder"].get().strip()
        self.cfg.save_path = self.vars["save_path"].get().strip()
        self.cfg.ap_config_path = self.vars["ap_config_path"].get().strip()
        self.cfg.game_base_path = self.vars["game_base_path"].get().strip()
        self.cfg.game_update_path = self.vars["game_update_path"].get().strip()
        self.cfg.game_dlc_path = self.vars["game_dlc_path"].get().strip()
        self.cfg.graphic_packs_folder = self.vars["graphic_packs_folder"].get().strip()
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
        if not self.overlay_var.get() or not line.startswith("[Item] "):
            return
        name = line[len("[Item] "):].split("  —")[0].split("  -")[0].strip()
        if not name:
            return
        if self.overlay is None:
            self.overlay = Overlay(self.root)
        self.overlay.notify(name)

    def _poll(self) -> None:
        q = self.runner.log_queue
        while not q.empty():
            try:
                line = q.get_nowait()
            except Exception:
                break
            self._append(line)
            self._maybe_overlay(line)

        running = self.runner.is_running
        building = self.runner.is_building
        if running:
            self.connect_btn["text"] = "Déconnecter"
            if self.runner.is_connected:
                mode = "injection live" if self.runner.live_injection else "save-file"
                self.status_var.set(f"Connecté ✓  ({mode})")
            else:
                self.status_var.set("Connexion…")
        else:
            self.connect_btn["text"] = "Connecter"
            self.status_var.set("Construction du pack…" if building else "Déconnecté")

        # grisage : champs connexion pendant le run ; champs pack pendant la construction
        conn_state = "disabled" if running else "normal"
        for ent in self._conn_entries:
            if str(ent["state"]) != conn_state:
                ent["state"] = conn_state
        self.reset_btn["state"] = conn_state
        pack_state = "disabled" if building else "normal"
        for ent in self._pack_entries:
            if str(ent["state"]) != pack_state:
                ent["state"] = pack_state
        self.build_btn["state"] = pack_state
        self.root.after(200, self._poll)


def run() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
