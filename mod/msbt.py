"""
msbt — writer MSBT minimal big-endian (Wii U) pour les messages custom du mod.

Produit un .msbt à 3 sections (LBL1 + ATR1 + TXT2), calqué sur les EventFlowMsg
vanilla (magic MsgStdBn, BOM BE, UTF-16, version 3). Contenu 100 % à nous.

Auto-test : `python mod/msbt.py` compare notre sortie à la structure d'un msbt
vanilla (OperationGuide.msbt) et fait un round-trip de lecture.
"""
from __future__ import annotations

import struct


def _label_hash(label: str, groups: int) -> int:
    h = 0
    for c in label.encode("ascii"):
        h = (h * 0x492 + c) & 0xFFFFFFFF
    return h % groups


def _section(magic: bytes, body: bytes) -> bytes:
    sec = magic + struct.pack(">I", len(body)) + b"\x00" * 8 + body
    pad = (-len(sec)) % 16
    return sec + b"\xab" * pad


def build_msbt(messages: dict[str, str], *, groups: int = 101, attr_size: int = 4,
               attr_value: int = 0x0000000C) -> bytes:
    """messages : {label: texte}. Retourne les octets du .msbt (big-endian).
    attr_value : attribut par chaîne — 0x0C = style des bannières DungeonMessage
    (relevé sur EventFlowMsg/DarkWoods.msbt, la bannière de la forêt perdue)."""
    labels = list(messages.keys())

    # ── LBL1 : table de hachage des labels ──
    buckets: dict[int, list[tuple[str, int]]] = {}
    for idx, lab in enumerate(labels):
        buckets.setdefault(_label_hash(lab, groups), []).append((lab, idx))
    header_size = 4 + groups * 8
    entries = b""
    offsets = []
    for g in range(groups):
        items = buckets.get(g, [])
        offsets.append((len(items), header_size + len(entries)))
        for lab, idx in items:
            raw = lab.encode("ascii")
            entries += struct.pack(">B", len(raw)) + raw + struct.pack(">I", idx)
    lbl1 = struct.pack(">I", groups)
    for count, off in offsets:
        lbl1 += struct.pack(">II", count, off)
    lbl1 += entries

    # ── ATR1 : attributs (style d'affichage, cf. attr_value) ──
    atr1 = (struct.pack(">II", len(labels), attr_size)
            + struct.pack(">I", attr_value) * len(labels))

    # ── TXT2 : chaînes UTF-16BE terminées par NUL ──
    blobs = [messages[lab].encode("utf-16-be") + b"\x00\x00" for lab in labels]
    base = 4 + 4 * len(blobs)
    txt2 = struct.pack(">I", len(blobs))
    pos = base
    for b in blobs:
        txt2 += struct.pack(">I", pos)
        pos += len(b)
    txt2 += b"".join(blobs)

    body = _section(b"LBL1", lbl1) + _section(b"ATR1", atr1) + _section(b"TXT2", txt2)
    header = (b"MsgStdBn" + struct.pack(">HHBBHH", 0xFEFF, 0, 1, 3, 3, 0)
              + struct.pack(">I", 0x20 + len(body)) + b"\x00" * 10)
    assert len(header) == 0x20
    return header + body


def _selftest() -> None:
    import json
    from pathlib import Path

    import oead

    data = build_msbt({"Gate_NoGear": "Test de message."})
    assert data[:8] == b"MsgStdBn" and data[8:10] == b"\xfe\xff"
    print(f"msbt généré : {len(data)} octets, header {data[:16].hex()}")

    cfg = json.loads((Path.home() / ".botwpelago" / "config.json").read_text(encoding="utf-8"))
    pack = Path(cfg["game_update_path"]) / "Pack" / "Bootup_EUfr.pack"
    # oead : garder les Sarc VIVANTS tant qu'on lit leurs vues .data (sinon segfault)
    outer = oead.Sarc(pack.read_bytes())
    inner_raw = bytes(next(iter(outer.get_files())).data)
    msg = oead.Sarc(bytes(oead.yaz0.decompress(inner_raw)))
    ref = bytes(next(f for f in msg.get_files()
                     if f.name == "EventFlowMsg/OperationGuide.msbt").data)
    print(f"référence OperationGuide.msbt : header {ref[:16].hex()}")
    # structure des sections de la référence (magic + tailles)
    off = 0x20
    while off < len(ref):
        magic = ref[off:off + 4]
        size = struct.unpack(">I", ref[off + 4:off + 8])[0]
        extra = ""
        if magic == b"ATR1":
            n, asz = struct.unpack(">II", ref[off + 16:off + 24])
            extra = f"  (attrs={n}, attr_size={asz})"
        print(f"  section {magic.decode()} taille {size}{extra}")
        off += 16 + size + ((-size - 16) % 16)


if __name__ == "__main__":
    _selftest()
