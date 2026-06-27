"""
ClientRunner — execute le BotWClient AP dans un thread d'arriere-plan (boucle asyncio)
et expose : demarrage/arret, statut, et un flux de logs (queue) pour l'UI.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
from typing import Optional

from BotWClient.BotWClient import build_client, resolve_provider_root
from BotWClient.providers.save_file import reset_ap_state
from .config import Config

_ROOT_LOGGER = "BotWClient"


def reset_progress(cfg: Config) -> int:
    """Réinitialise l'état AP persisté (pour une nouvelle seed). Retourne le nb de fichiers supprimés."""
    root = resolve_provider_root(cfg.cemu_folder or None, cfg.user_slot or None, cfg.save_path or None)
    return reset_ap_state(root)


def cemu_status() -> dict:
    """Pré-vol : Cemu lancé ? appli en admin ? dossier d'install Cemu détecté ?"""
    import ctypes
    from ctypes import wintypes
    from pathlib import Path
    from BotWClient.memory_injector import _find_pid, _k32

    pid = _find_pid("cemu.exe")
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        is_admin = False

    folder = ""
    if pid:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if h:
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    folder = str(Path(buf.value).parent)
            except Exception:
                pass
            finally:
                _k32.CloseHandle(h)
    return {"pid": pid, "admin": is_admin, "folder": folder}


class _QueueHandler(logging.Handler):
    """Pousse chaque log formate dans une queue thread-safe (lue par l'UI)."""
    def __init__(self, q: "queue.Queue[str]") -> None:
        super().__init__()
        self.q = q
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.q.put_nowait(self.format(record))
        except Exception:
            pass


class ClientRunner:
    def __init__(self) -> None:
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._task: Optional[asyncio.Task] = None
        self._client = None
        self._bridge = None
        self._handler = _QueueHandler(self.log_queue)
        self._pack_thread: Optional[threading.Thread] = None

    # ── etat ──────────────────────────────────────────────────────────────────
    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def is_building(self) -> bool:
        return self._pack_thread is not None and self._pack_thread.is_alive()

    # ── construction du graphic pack (etapes 2-3) ──────────────────────────────
    def build_pack(self, cfg: Config) -> None:
        """Construit le graphic pack en arriere-plan (config AP -> rando -> pack)."""
        if self.is_building:
            return
        self._pack_thread = threading.Thread(
            target=self._build_pack, args=(cfg,), daemon=True, name="BOTWpelagoPack")
        self._pack_thread.start()

    def _build_pack(self, cfg: Config) -> None:
        from .pack_builder import build_pack, PackBuildError
        try:
            missing = [name for name, val in (
                ("config AP", cfg.ap_config_path),
                ("jeu de base", cfg.game_base_path),
                ("mise à jour", cfg.game_update_path),
                ("dossier graphicPacks Cemu", cfg.graphic_packs_folder),
            ) if not val]
            if missing:
                self._log("⚠ Champs requis manquants : " + ", ".join(missing))
                return
            pack = build_pack(
                cfg.ap_config_path, cfg.game_base_path, cfg.game_update_path,
                cfg.game_dlc_path, cfg.graphic_packs_folder,
                rando_exe=cfg.rando_exe_path or None, log=self._log,
            )
            self._log(f"[OK] Pack prêt : {pack}")
            self._log("→ Active le pack dans Cemu (Options ▸ Graphic Packs), puis lance le jeu.")
        except PackBuildError as exc:
            self._log(f"⚠ Échec de la construction du pack : {exc}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"⚠ Erreur inattendue : {exc}")

    @property
    def is_connected(self) -> bool:
        return bool(self._client and getattr(self._client, "connected", False))

    @property
    def live_injection(self) -> bool:
        return self._bridge is not None

    # ── controle ────────────────────────────────────────────────────────────────
    def start(self, cfg: Config) -> None:
        if self.is_running:
            return
        self._thread = threading.Thread(target=self._run, args=(cfg,), daemon=True,
                                        name="BOTWpelagoClient")
        self._thread.start()

    def stop(self) -> None:
        loop, task = self._loop, self._task
        if loop and task and not task.done():
            loop.call_soon_threadsafe(task.cancel)

    # ── interne ─────────────────────────────────────────────────────────────────
    def _log(self, msg: str) -> None:
        self.log_queue.put_nowait(msg)

    def _run(self, cfg: Config) -> None:
        root = logging.getLogger(_ROOT_LOGGER)
        root.setLevel(logging.INFO)
        root.addHandler(self._handler)
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            self._client, self._bridge = build_client(
                connect=cfg.server, name=cfg.slot, password=cfg.password,
                cemu=cfg.cemu_folder or None, slot=cfg.user_slot or None,
                save=cfg.save_path or None,
            )
            self._log(f"Injection live: {'ACTIVE' if self._bridge else 'save-file (reload requis)'}")
            self._task = loop.create_task(self._client.run())
            loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            self._log("Deconnecte.")
        except Exception as exc:  # noqa: BLE001
            self._log(f"ERREUR: {exc}")
        finally:
            root.removeHandler(self._handler)
            try:
                loop.close()
            except Exception:
                pass
            self._client = None
            self._bridge = None
            self._loop = None
            self._task = None
            self._thread = None
