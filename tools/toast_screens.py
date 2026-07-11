"""Liste les 99 écrans du registre UI live : id, instance, vtable, et repère MessageGet.
Lancer `python tools/toast_recon.py base` d'abord (cache heap_base)."""
import struct
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from toast_recon import open_bridge, _load_state  # noqa: E402

REG_PTR = 0x1047E650          # -> registre {.., +0x14 count, +0x18 array}
TOAST_REFRESH = 0x02FD0CE4    # ptr présent dans la vtable de l'écran MessageGet


def main() -> None:
    st = _load_state()
    heap_base = int(st["heap_base"], 16)
    b = open_bridge()

    def rd32(host):
        raw = b._read(host, 4)
        return struct.unpack(">I", raw)[0] if raw else None

    reg = rd32(heap_base + REG_PTR)
    count = rd32(heap_base + reg + 0x14)
    arr = rd32(heap_base + reg + 0x18)
    print(f"registre @g:0x{reg:08X}  count={count}  array @g:0x{arr:08X}")
    for i in range(count):
        sub = rd32(heap_base + arr + i * 4)
        if not sub:
            continue
        base_obj = sub                             # le code du jeu utilise sub directement
        vt = rd32(heap_base + sub + 0xC)           # vtable classe @ sub+0xC
        if vt is None:
            print(f"  [0x{i:02X}] sub g:0x{sub:08X} (déréf impossible)")
            continue
        # sonde la vtable rodata : cherche TOAST_REFRESH dans les 0x600 premiers octets
        hit = -1
        if 0x10000000 <= vt < 0x10463000:
            vt_blob = b._read(heap_base + vt, 0x600) or b""
            for k in range(0, len(vt_blob) - 3, 4):
                if struct.unpack_from(">I", vt_blob, k)[0] == TOAST_REFRESH:
                    hit = k
                    break
        mark = f"  <== TOAST (refresh @vt+0x{hit:X})" if hit >= 0 else ""
        print(f"  [0x{i:02X}] sub g:0x{sub:08X} obj g:0x{base_obj:08X} vt 0x{vt:08X}{mark}")


if __name__ == "__main__":
    main()
