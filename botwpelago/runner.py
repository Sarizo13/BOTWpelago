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

from BotWClient.BotWClient import build_client
from .config import Config

_ROOT_LOGGER = "BotWClient"


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

    # ── etat ──────────────────────────────────────────────────────────────────
    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

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
