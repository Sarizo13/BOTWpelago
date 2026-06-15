"""
BotW WiiU game_data.sav parser.

Confirmed format (empirically verified against BotW 1.5.0 EUR, Cemu 1.18.1):
  [12 bytes header]
    uint32 be  version      (e.g. 0x0000471B)
    uint32 be  0xFFFFFFFF   (magic)
    uint32 be  0x00000001   (constant)
  [128,399 × 8 bytes: flat sorted array]
    uint32 be  flag_id      = crc32(flag_name.encode("ascii")) & 0xFFFFFFFF
    uint32 be  flag_value   (mostly 0/1 for bools; s32/f32 for other types)
  [4 bytes trailer: 0x00000000]

Hash recipe (proven):
    flag_id = zlib.crc32(flag_name.encode("ascii")) & 0xFFFFFFFF
    Proof: IsGet_Obj_Magnetglove → 0x795E7BBC matches Oman Au before/after diff,
           and all 42,537 flag names in gamedata.ssarc verify against their embedded HashValue.
"""
from __future__ import annotations

import struct
import zlib
import logging
from dataclasses import dataclass, field

log = logging.getLogger("BotW.SaveParser")

HEADER_SIZE = 12   # version(4) + magic(4) + constant(4)
ENTRY_SIZE  = 8    # flag_id(4) + value(4)


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class ParsedSave:
    version: int = 0
    raw_header: bytes = b""
    flags: dict[int, int] = field(default_factory=dict)

    def get_bool(self, flag_id: int) -> bool:
        return bool(self.flags.get(flag_id, 0))

    def get_s32(self, flag_id: int) -> int:
        raw = self.flags.get(flag_id, 0)
        return struct.unpack(">i", struct.pack(">I", raw))[0]

    def has_id(self, flag_id: int) -> bool:
        return flag_id in self.flags


# ── Hash recipe ───────────────────────────────────────────────────────────────

def flag_id(name: str) -> int:
    """CRC32 of the ASCII flag name. The confirmed BotW hash recipe."""
    return zlib.crc32(name.encode("ascii")) & 0xFFFFFFFF


# ── Format detection ──────────────────────────────────────────────────────────

def detect_format(data: bytes) -> str:
    if len(data) < 8:
        return "Unknown"
    if data[:2] == b"BY":
        return "BYML_BE"
    if data[:2] == b"YB":
        return "BYML_LE"
    if struct.unpack_from(">I", data, 4)[0] == 0xFFFFFFFF:
        return "BotW_Binary"
    return f"Unknown (magic={data[:4].hex()})"


# ── Hex dump ──────────────────────────────────────────────────────────────────

def dump_hex(data: bytes, n: int = 64, offset: int = 0) -> str:
    end = min(offset + n, len(data))
    lines = []
    for i in range(offset, end, 16):
        chunk = data[i: i + 16]
        h = " ".join(f"{b:02X}" for b in chunk)
        a = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"  {i:06X}: {h:<48}  |{a}|")
    return "\n".join(lines)


# ── Parser ────────────────────────────────────────────────────────────────────

def parse(data: bytes) -> ParsedSave:
    """
    Parse game_data.sav into a ParsedSave.
    Raises ValueError with a hex dump on format mismatch.
    """
    fmt = detect_format(data)
    if fmt != "BotW_Binary":
        raise ValueError(
            f"Not a BotW WiiU save ({fmt}).\nHeader:\n{dump_hex(data, 32)}"
        )
    result = ParsedSave()
    result.raw_header = data[:HEADER_SIZE]
    result.version    = struct.unpack_from(">I", data, 0)[0]
    n = (len(data) - HEADER_SIZE) // ENTRY_SIZE
    for i in range(n):
        off = HEADER_SIZE + i * ENTRY_SIZE
        fid, val = struct.unpack_from(">II", data, off)
        result.flags[fid] = val
    log.debug("Parsed %d entries (version=0x%04X)", n, result.version)
    return result


# ── Diff ──────────────────────────────────────────────────────────────────────

def diff_saves(before: ParsedSave, after: ParsedSave) -> dict[str, list]:
    """
    Return which flag IDs changed between two saves.
    Use after completing a shrine to identify its flag_id empirically.

    Workflow:
      1. Copy game_data.sav before shrine → before.sav
      2. Complete shrine, let BotW auto-save → after.sav
      3. python -m BotWClient.BotWClient --diff-saves before.sav after.sav
      4. The ID in bool_new_true is the shrine's flag_id (= crc32("Clear_DungeonNNN"))
    """
    result: dict[str, list] = {
        "bool_new_true":  [],
        "bool_new_false": [],
        "value_changed":  [],
    }
    for fid in sorted(set(before.flags) | set(after.flags)):
        bv = before.flags.get(fid, 0)
        av = after.flags.get(fid, 0)
        if bv == av:
            continue
        tag = f"0x{fid:08X}"
        if bv in (0, 1) and av in (0, 1):
            result["bool_new_true" if av == 1 else "bool_new_false"].append(tag)
        else:
            result["value_changed"].append({
                "id": tag,
                "before": bv,
                "after": av,
                "before_s32": struct.unpack(">i", struct.pack(">I", bv))[0],
                "after_s32":  struct.unpack(">i", struct.pack(">I", av))[0],
            })
    return result


# ── Debug inspector ───────────────────────────────────────────────────────────

def inspect_save(data: bytes) -> str:
    out = ["=" * 60]
    size = len(data)
    out.append(f"File size : {size:,} bytes  ({detect_format(data)})")
    if size >= HEADER_SIZE:
        out.append(f"Version   : 0x{struct.unpack_from('>I', data, 0)[0]:08X}")
        n = (size - HEADER_SIZE) // ENTRY_SIZE
        out.append(f"Entries   : {n:,}")
    out.append("")
    out.append("── Header (first 64 bytes) ──")
    out.append(dump_hex(data, 64))
    out.append("")
    if size < HEADER_SIZE:
        return "\n".join(out)

    saved = parse(data)
    bool_count = sum(1 for v in saved.flags.values() if v in (0, 1))
    set_count  = sum(1 for v in saved.flags.values() if v == 1)
    out.append("── Flag summary ──")
    out.append(f"  Total entries : {len(saved.flags):,}")
    out.append(f"  Bool (0 or 1) : {bool_count:,}  ({100*bool_count/len(saved.flags):.1f}%)")
    out.append(f"  Set to True   : {set_count:,}")
    out.append("")
    out.append("── First 30 entries ──")
    out.append(f"  {'#':>4}  {'flag_id':>12}  {'value':>10}  bool")
    for i, (fid, val) in enumerate(list(sorted(saved.flags.items()))[:30]):
        mark = "*TRUE*" if val == 1 else ("     0" if val == 0 else "")
        out.append(f"  {i:4d}  0x{fid:08X}  0x{val:08X}  {mark}")
    out.append("")

    # Spot-check shrine flags
    out.append("── Shrine spot-check (first 5 shrines) ──")
    for n in range(5):
        name = f"Clear_Dungeon{n:03d}"
        fid  = flag_id(name)
        val  = saved.flags.get(fid, "MISSING")
        out.append(f"  {name}  → 0x{fid:08X}  = {val}")
    return "\n".join(out)
