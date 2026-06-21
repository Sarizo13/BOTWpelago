"""
native_mod — côté Python du mod natif « addItem » (V2).

Écrit la MAILBOX lue par le codecave PPC (graphic pack Cemu). Le codecave appelle
PauseMenuDataMgr::addItem -> item ajouté par la voie officielle du jeu (instantané +
persistant + icône/compte corrects, zéro fantôme). Voir docs/native_mod_design.md.

Tant que le codecave/graphic pack n'est pas installé, ce module est inactif (le client
utilise le chemin hybride gd_base + runtime). Activé quand MB (adresse guest de la mailbox)
est connue et que le pack est chargé.

Disposition mailbox (offsets depuis MB) :
  +0x00 u32 trigger   (on écrit 1 ; le codecave remet 0 quand c'est fait)
  +0x04 u32 count
  +0x08 u32 type      (0..9)
  +0x0C u32 cstr_ptr  = MB+0x14
  +0x10 u32 vtable    = 0x1021B58C
  +0x14 char[64] name
"""
from __future__ import annotations

import struct
import time
from typing import Optional

NAME_VTABLE = 0x1021B58C     # vtable sead::SafeString utilisée par le jeu pour les noms
MB_NAME_OFF = 0x14
_TRIGGER, _COUNT, _TYPE, _CSTR, _VTAB = 0x00, 0x04, 0x08, 0x0C, 0x10


class NativeItemGiver:
    """Écrit la mailbox du codecave via CemuMemoryBridge. `mb_guest` = adresse guest de
    la mailbox (origine du codecave + offset). `base` = cemu_mem_base de session
    (host = guest + base) ; dérivable via bridge._derive_heap_base."""

    def __init__(self, bridge, mb_guest: int, base: int) -> None:
        self._b = bridge
        self._mb = mb_guest
        self._base = base

    def _host(self, off: int) -> int:
        return self._mb + off + self._base

    def is_ready(self) -> bool:
        """Le codecave a-t-il remis trigger à 0 (prêt pour une nouvelle demande) ?"""
        raw = self._b._read(self._host(_TRIGGER), 4)
        return bool(raw) and struct.unpack(">I", raw)[0] == 0

    def give(self, item_name: str, item_type: int, count: int,
             timeout_s: float = 1.0) -> bool:
        """Demande l'ajout de `count` × `item_name` (type 0..9). Bloque jusqu'à ce que le
        codecave consomme la demande (trigger -> 0) ou timeout. Retourne True si consommé."""
        if not self.is_ready():
            return False
        nb = item_name.encode("ascii")[:63] + b"\x00"
        nb = (nb + b"\x00" * 64)[:64]
        w = self._b._write
        w(self._host(MB_NAME_OFF), nb)
        w(self._host(_COUNT), struct.pack(">I", count & 0xFFFFFFFF))
        w(self._host(_TYPE), struct.pack(">I", item_type & 0xFFFFFFFF))
        w(self._host(_CSTR), struct.pack(">I", (self._mb + MB_NAME_OFF) & 0xFFFFFFFF))
        w(self._host(_VTAB), struct.pack(">I", NAME_VTABLE))
        # déclenche en dernier
        w(self._host(_TRIGGER), struct.pack(">I", 1))
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.is_ready():
                return True
            time.sleep(0.01)
        return False


def find_mailbox_guest(bridge) -> Optional[int]:
    """Localise la mailbox du codecave en mémoire (si le pack est chargé). À implémenter
    quand l'origine du codecave est fixée (origin fixe -> adresse connue, sinon scan d'une
    signature magique placée en tête de mailbox). Retourne None tant que non installé."""
    return None
