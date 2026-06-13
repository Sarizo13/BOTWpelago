# Agent Brief — BotW Archipelago (Cemu / Wii U)

> **How to use this file.** Open the repo (`d:\Project arch BOTW`) in VS Code,
> then in Claude Code: *"Read `docs/AGENT_BRIEF.md` and start with P0."*
> This brief is the single source of truth for the project's current direction.
> Where it conflicts with `CLAUDE.md` / `memory_map.md` / `README.md`, **this file wins**
> until those docs are reconciled (that is task P0).

---

## Mission

Make this AP multiworld client **reliable enough to play with friends and to share publicly**.
Two non-negotiables: (1) detection of in-game checks must be correct, (2) item delivery must
never corrupt the save. Everything below serves those two goals.

Work empirically. Several "facts" already in the repo are community best-effort guesses
(flag names, hash algorithm, memory layout). **Verify before trusting.** When you assert
something, show how you confirmed it.

---

## Ground truth (verified)

- Target: **BotW Wii U v1.5.0** on **Cemu 2.x**, Windows.
- `game_data.sav` is a **custom big-endian binary format — NOT BYML, do not use `oead` on it.**
  - Header: 12 bytes (3 × `uint32` BE).
  - Body: sections of `uint32be count` then `count × (uint32be flag_id, uint32be value)`, entry = 8 B.
  - A real save parses to ~**128,399 entries**, ~96.9% boolean. Parser lives in `save_parser.py` (pure binary).
- `flag_id` is a **hash of the flag name**. The hash recipe is **not yet pinned** (see P1) — this is the
  project's only hard blocker.
- Cemu emulates **big-endian PPC**. Guest RAM is stored BE in the host process:
  1-byte bools are endian-agnostic; any `u16`/`u32` (item id, count, s32 counters) **must be byte-swapped**.

## Known-wrong / stale (do not propagate)

- `memory_map.md` claims the save is BYML and says *"parse with `oead`"* and *"no memory scanning required"*. **False on both counts now.**
- `CLAUDE.md` says *"no memory scanning, no pymem"*. **Stale** — live memory is now in scope (v2).
- `README.md` says the client reads Cemu memory via `pymem`. We use **`ctypes`** (`memory_bridge.py`), not `pymem`.
- Flag names in `item_map.py` and the Divine Beast table in `memory_map.md` are **community guesses marked TODO**. Treat as unverified.

---

## The blocker — resolve the hash mapping (P1, highest value)

CRC32 is the **documented** hash for BotW's GameData (gdt) flags (used by `oead` and `botw_flag_util`).
The user reports CRC32 (and fnv1a/djb2/murmur2/adler32/sdbm) produced **no match**. Given CRC32 is the
documented algorithm, the failure most likely lives in the **parser/preprocessing**, not the algorithm:

- Endianness of the extracted `flag_id` field (BE vs LE in the file vs how Python reads it).
- CRC32 variant (zlib/IEEE poly, init value, final XOR, reflection).
- String preprocessing before hashing (case, encoding ASCII vs UTF-8, trailing NUL, prefix).
- Entry layout itself — confirm the "hash" field is actually the hash and not, e.g., an index.

**Path to resolve (empirical, authoritative):**
1. Harden `save_parser` to expose raw `(flag_id, raw_value)` per section and dump them.
2. Implement/verify `--diff-saves before.sav after.sav` → list of `flag_id`s whose value changed.
3. Build a **hash oracle**: given a known flag name (e.g. `Location_MainField_Dungeon001_Enable`,
   which flips after completing **Oman Au**) and the changed `flag_id` from the diff, brute-force
   {CRC32 variants} × {string transforms} × {endianness} until output == observed `flag_id`.
   Lock the recipe once it reproduces several independent (name → id) pairs.
4. Optional/authoritative: parse `savedataformat.ssarc` for the official flag-name list, hash each
   with the confirmed recipe, emit a complete `id → name` table committed as data.

**Definition of done:** from a fresh save, the client resolves at least the 120 shrine `_Enable`
flags + the 4 Divine Beast flags to names, validated against a before/after diff with 100% match.

---

## New component — `memory_bridge.py`

Low-level live memory access to `cemu.exe` (Windows, `ctypes`). Already drafted; drop it at:

```
BotWClient/providers/memory_bridge.py    # raw RPM/WPM, region scan, BE handling
BotWClient/providers/memory.py           # MemoryProvider/LiveMemoryInjector use it (currently stub)
```

It opens the process, scans for a dense `0x00/0x01` region (candidate bool-flag array), and exposes
`read_flag(index)` / `write_item(slot, item_id)`.

**Caveats baked in (respect them):**
- The scan returns an **approximate** base. Exact flag indexing requires **calibration** against a
  known flag's host address (found once in Cheat Engine during discovery, then passed to `set_flag_base`).
- The runtime flag store may be a `sead::Buffer` of flag *objects*, **not** a dense 1-byte array — if the
  scan finds nothing, that's the signal to locate it via CE pointer scan and adapt the stride.
- `write_item` is a **placeholder**: BotW inventory is a list of `PouchItem` structs (name string + count +
  type…), not a flat id array. Naive slot writes don't create valid items and get overwritten by the game.

---

## Target architecture (hybrid, asymmetric)

```
BotWClient.py (AP logic only)
  ├── GameStateProvider.poll() → new AP location IDs
  │     SaveFileProvider   (works today; 2s polling)
  │     MemoryProvider     (v2; live flag read via memory_bridge; falls back if unavailable)
  └── ItemInjector.queue/flush() ← received AP items
        DeferredSaveInjector  (writes save when safe; reliable)
        HybridInjector        (live where safe, else deferred save)
```

Recommended split: **read flags live** (fast, reliable for 1-byte bools), **deliver items via save**
until `PouchItem` is reversed. Items that are pure flags (runes, champion abilities) can also be
delivered via `SetFlag` once P1 confirms their flag names.

---

## Task plan (priority order)

**P0 — Single source of truth.** Reconcile `CLAUDE.md`, `memory_map.md`, `README.md`, `setup.md`:
remove all BYML/`oead`-for-save claims, mark live memory as in-scope (v2, `ctypes` not `pymem`),
pin Cemu 2.x + BotW 1.5.0. *DoD: no internal contradiction remains; a new reader gets one consistent story.*

**P1 — Resolve hash mapping.** As above. *This unblocks everything else.*

**P2 — Wire `MemoryProvider`.** Use `memory_bridge` + the P1 `index↔name` map + calibration.
`is_available` must be `False` off-Windows or on any failure so the client transparently falls back to
`SaveFileProvider`. *DoD: completing a shrine in Cemu flips the right live flag and yields the correct AP location ID.*

**P3 — Hybrid injection.** Implement `HybridInjector`; keep `write_item` guarded/stubbed; deliver items
via save (and flag-based items via `SetFlag`). *DoD: a received AP item appears in-game after a deferred flush, repeatably, with zero save corruption across 20+ cycles.*

**P4 — Reliability for friends.** Rewrite `setup.md` to be followable on a clean Windows machine.
Graceful, specific errors for: Cemu not running, save not found, wrong game version, memory not accessible.
Add a `--doctor` self-check command. Ensure save-write timing (title-screen / idle detection) is robust.
*DoD: a friend connects end-to-end from the docs alone, without you on call.*

**P5 — Shareability (later).** `LICENSE`, `CONTRIBUTING.md`, `pytest` suite (save_parser, hash oracle,
item_map coverage), then prep `.apworld` upstream submission.

---

## Constraints (hard)

- Memory path is **Windows-only**; save path stays cross-platform.
- **Never hardcode Cemu memory addresses** — offsets change across 2.x. Always dynamic scan + calibration.
- **BotW Wii U 1.5.0 only.** Don't mix versions (flag names differ across game updates).
- Cheat Engine is a **discovery-phase tool only** — never a runtime dependency.
- No BizHawk Lua (this is Cemu). No `oead`/BYML for the save. No Korok seeds by default. No soft-locks.
- Endianness: bools 1 B fine; all multi-byte guest values must be byte-swapped (BE).

## DO NOT

- Assume the hash is CRC32 without reproducing a real `(name → id)` pair from a diff.
- Assume the in-memory flag store is a dense 1-byte array without CE calibration.
- Write items into a flat inventory slot (`PouchItem` is structured; naive writes corrupt/get overwritten).
- Trust the existing TODO flag names as correct — verify each by diff before shipping.
- Commit personal paths, `*.sav` files, or game dumps. `settings.local.json` and saves must be gitignored.

---

## Open questions for the human (ask before guessing)

1. Can you capture **before/after saves** around a single shrine (Oman Au) and one Divine Beast? Needed for the hash oracle (P1).
2. Do you have `savedataformat.ssarc` extractable from your dump? Enables the authoritative name list.
3. Region of your 1.5.0 build — USA `101c9400` / EUR `101c9500` / JPN `101c9300`? Confirm for save path + flag table.
