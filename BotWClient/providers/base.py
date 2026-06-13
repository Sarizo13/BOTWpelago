"""
Abstract interfaces for game state reading and item injection.

Two independent concerns:
  GameStateProvider  — reads what the game has completed (shrine flags, etc.)
  ItemInjector       — writes received AP items back into the game

Concrete implementations live next to this file:
  save_file.py  — reads/writes game_data.sav (MVP, no memory access)
  memory.py     — reads/writes Cemu live memory (v2, faster injection)

The client (BotWClient.py) only imports from this module.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


# ── Item injection spec ───────────────────────────────────────────────────────

@dataclass
class InjectionSpec:
    """
    Describes how to give one AP item to Link.
    One AP item → one or more actions; actions are tried in priority order.
    """

    @dataclass
    class SetFlag:
        """Set a boolean flag to 1 in game_data.sav."""
        flag_name: str
        value: bool = True

    @dataclass
    class AddS32:
        """Add `amount` to an S32 counter in game_data.sav (e.g. DungeonClearSealNum for Spirit Orbs)."""
        flag_name: str
        amount: int = 1

    @dataclass
    class AddPouchItem:
        """
        Add `amount` to a stackable PouchItem (arrows, materials, food).
        If the item is not in the pouch yet, adds it to an empty slot.
        item_name is the BotW internal actor name stored in the pouch.
        """
        item_name: str
        amount: int = 1

    @dataclass
    class GiveActor:
        """
        Spawn an actor (weapon/shield/bow/food) in Link's inventory.
        Only usable with live-memory injection (v2).
        Actor names from Actor/ActorInfo.product.sbyml.
        """
        actor_name: str
        modifier: int = 0  # durability/value bonus

    ap_item_id: int
    ap_item_name: str
    # Ordered list of injection actions; the injector tries each until one succeeds.
    actions: list = field(default_factory=list)
    # Human-readable note shown in client log when item is received.
    display_note: str = ""


# ── Provider interface ─────────────────────────────────────────────────────────

class GameStateProvider(ABC):
    """
    Read the current game state and return newly completed location IDs.

    The provider is stateful: it remembers which locations it has already
    reported. Calling poll() twice without the game changing returns [].
    """

    @abstractmethod
    def poll(self) -> list[int]:
        """
        Return location IDs that have been completed since the last poll().
        Thread-safe: called from the asyncio event loop.
        """
        ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """True when the underlying data source (save file, process) is accessible."""
        ...

    @abstractmethod
    def verify_flag_names(self, sample_names: list[str]) -> dict[str, bool]:
        """
        Given a list of expected flag names, return which ones exist in the
        data source with their current values. Used for diagnostics only.
        """
        ...


# ── Injector interface ────────────────────────────────────────────────────────

class ItemInjector(ABC):
    """
    Write AP-received items into the game.

    Items are enqueued immediately when received from the AP server but may
    not be injected until the game reaches a safe state (e.g. title screen).
    """

    @abstractmethod
    def queue_item(self, spec: InjectionSpec) -> None:
        """
        Add item to the pending queue.
        Must be safe to call at any time (even mid-gameplay).
        """
        ...

    @property
    @abstractmethod
    def can_inject_now(self) -> bool:
        """
        True when it is safe to write to the game without data loss.
        For save-file injection: True when game is at title screen.
        For live-memory injection: True when Cemu process is attached.
        """
        ...

    @abstractmethod
    def flush(self) -> list[InjectionSpec]:
        """
        Attempt to inject all pending items.
        Returns list of successfully injected specs.
        Raises nothing — log errors internally.
        """
        ...

    @property
    @abstractmethod
    def pending_count(self) -> int:
        """Number of items waiting to be injected."""
        ...
