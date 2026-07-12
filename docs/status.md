# BotW Archipelago — Journal de reverse-engineering (historique)

> **Statut de ce fichier (2026-07-09).** C'est le **journal complet du RE** — la mine d'or
> pour la V2 (EventFlow, Ghidra, BCML, calibration mémoire) — mais il est **partiellement
> périmé côté V1** : il a été écrit pendant le développement et les sections « TODO / what
> remains » ne reflètent plus l'état réel. **Pour l'état courant et le backlog, la source
> de vérité est `docs/CHECKLIST.md` + `.claude/CLAUDE.md`** ; en cas de conflit, ce sont EUX
> qui gagnent. Les sections « SOLVED / do not re-litigate » restent, elles, toujours valides.

---

## TL;DR — où en est le projet (résumé 2026-07)

V1 est **construite et fonctionnelle** : détection des checks (sanctuaires, coffres, tours,
créatures, lieux, quêtes, souvenirs), injection live persistante des items (matériaux, armes,
arcs, boucliers, armures, Master Sword…), gate paravoile, goal 2 modes, DeathLink validé,
orchestration BOTWpelago (GUI + pack builder) et pack PopTracker. Reste V1 : potions/plats
(type 8), vrai portefeuille rubis, validation end-to-end multi-slot, test PopTracker — voir
`docs/CHECKLIST.md`. La V2 (mod BCML) démarre sur la base du RE documenté ici (§6 et suiv.).

---

> **Naming / file-location note (reconciled).** Older sections below refer to
> `memory_bridge.py` as a "drafted, unvalidated" v2 component. It shipped as
> **`BotWClient/memory_injector.py`** (`CemuMemoryBridge`) and is now implemented and wired
> (live rupee + PouchItem injection — see §1b). The "item received" overlay (§1c) shipped as
> **`botwpelago/overlay.py`**, not `BotWClient/overlay.py`.

## 1. SOLVED — facts now established (do not re-litigate)

### Save format
- `game_data.sav` is a **custom big-endian binary, NOT BYML** (do not use `oead` on it).
- Layout: **12-byte header + flat array of 8-byte entries (`u32be flag_id`, `u32be value`) + 4-byte trailer.**
- A real save = **128,399 entries**, ~99% with value ≤ 1 (bools). Data offset = **12**.

### Hash recipe (the former blocker)
```
flag_id = zlib.crc32(flag_name.encode("ascii")) & 0xFFFFFFFF   # standard CRC32 IEEE
```
- `flag_id` stored **big-endian** in the save.
- No null terminator, ASCII, original case.
- **Proof:** matched `IsGet_Obj_Magnetglove == 0x795E7BBC` from an Oman Au before/after diff
  (Oman Au = the Magnesis shrine; Magnetglove = Magnesis internal name → semantic + cryptographic
  confirmation), and cross-checked against the embedded `HashValue` fields in `gamedata.ssarc`
  (extract_flag_names prints `N/N HashValue == crc32(name)`).

### Key discoveries
- **Internal shrine numbering ≠ play order.** Oman Au = `Dungeon038`. The 120 base shrines are
  `Dungeon000`–`Dungeon119`; DLC shrines `Dungeon120`–`Dungeon136`.
- **Per-shrine detection flag = `Clear_Dungeon{NNN}`** (clean bool 0→1), NOT the
  `Location_MainField_Dungeon{N}_Enable` the old docs assumed.
- **Towers:** activation flag = `MapTower_{NN}` (bare bool); names from `Tower{NN}` in LocationMarker.
- **Divine Beasts:** completion = `Clear_Remains{Wind|Fire|Water|Electric}` (Medoh/Rudania/Ruta/Naboris).
- **Paraglider = `IsGet_PlayerStole2`** (0xFE4D1501) — it IS a flag (internal name "PlayerStole2"),
  so the plateau-exit gate is flag-based, NOT coupled to inventory.
- **Champion abilities = `IsGet_Obj_HeroSoul_{Rito|Goron|Zora|Gerudo}`** (= Revali/Daruk/Mipha/Urbosa).
  This corrects `item_map.py` which used wrong guesses (`PlayerStageFlg_*`).
- **Master Sword possession = `Get_MasterSword_Finish`** (`Get_MasterSword_Heart52` = the 13-heart gate).
- **No Bow of Light flag** — it's a scripted fight weapon (`Weapon_Bow_Liberation`), not persistent;
  cannot be used as a flag gate. Dropped from the goal.
- **Shrine counter = `DungeonClearCounter`** (0xE605CE62), usable for the goal condition.

---

## 1b. SOLVED — live memory injection (PouchItem + rupees)

`gd_base` (the SAVE_HEADER buffer found by `_scan_for_gamedata`) is a serialization/persist
buffer: writes there do NOT affect live game state (require save reload). The TRUE live
structures are elsewhere, in the same multi-GB `cemu.exe` heap region (~3.6GB on this setup,
"Extended Memory" graphic pack), found by porting AOB patterns from the third-party tool
**"Cemu BotW Editor" (extended memory build)**, decompiled with `ilspycmd`:

- **Live rupees**: AOB pattern `10 ?? ?? ?? 01 07 00×11 0F 42 3F` (20 bytes), address =
  match_pos + 20. Confirmed: value == `CurrentRupee`, and writing it updates the HUD
  **instantly** (no UI refresh needed). Implemented as `CemuMemoryBridge._find_rupees_addresses`
  / `live_get_rupees` / `live_add_rupees`.
  **⚠️ SUPERSEDED (2026-07-11)**: this address is the value field of a `gdt::Flag<s32>`
  object — a **mirror** the game resyncs from the authoritative copy (rupees written there
  "vanished"). The TRUE wallet is the matching entry in the live gdt s32 STORAGE;
  `live_add_rupees` now writes BOTH. See §gdt-live below.
- **Live PouchItem array**: items are 544-byte structs, found via pattern `10 ?? ?? ?? 00 00 00 40`
  repeating every 544 bytes. For a match at `pos`: `itemAddress = pos + 7`, `itemID` = ASCII
  string at `itemAddress+1`, `itemQtDurAddress = itemAddress - 19` (qty/durability, int32 BE),
  `itemEquippedFlagAddress = itemAddress - 15` (byte). Located by scanning the whole heap region
  containing the live rupee address, scoring candidates by recognizable item-ID prefixes
  (`Item_`, `Weapon_`, `Armor_`, etc.) with early-exit. Confirmed: writing `itemQtDurAddress`
  updates the real value instantly (UI just needs inventory close/reopen to redraw — the
  underlying data is live, no save reload).
- Implemented as `CemuMemoryBridge._find_inventory_start` / `_iter_inventory_slots` /
  `live_find_item` / `live_get_item_qty` / `live_add_item_qty`, auto-located in `attach()` via
  `_locate_live_inventory()` (~5-10s, cached for the session — **addresses are NOT stable across
  Cemu restarts**, must rescan every attach).
- The `-4704656` "live ↔ persist" offset constant from the decompiled tool's `SetRupees` does
  **NOT** transfer to this setup (gave a stale/wrong value) — ignore it, rescanning via AOB is
  fast enough (~5-10s) to not need it.
- Wired into `BotWClient/providers/save_file.py::_apply_actions_memory`: `AddPouchItem` actions
  try `live_add_item_qty` first (falls back to gd_base `add_porch_item` if item not currently in
  pouch); `AddS32` for `CurrentRupee` tries `live_add_rupees` first.
- **New-item injection (slot 0-4) tested — DOES NOT WORK, root cause understood**: slots
  0-4 of the 544-byte array have `itemQtDurAddress == 0` and a distinct `FF FF FF FF FF`
  header (vs. `00 00 00 00 01` for real items) — these are **free-list nodes**, not entries
  in any category's render list. Writing a valid item ID/qty into one (`Item_Wood`, qty=5)
  round-trips correctly on readback but never appears in-game (verified by
  `tools/live_inventory_inspect.py`). Cross-checked against the decompiled BotW Editor's
  own "update item" handler (`btnItemUpdate_Click`): it only **renames an existing selected
  `itemdata`** (rewrites the ID string + qty/bonus of an item already linked into a
  category's list) — even that tool does not create new slots. True new-item creation would
  require inserting a node into the target category's linked list (head/next pointers),
  which is unreverse-engineered and not worth pursuing via blind scanning. **Conclusion**:
  for items the player doesn't already have a slot for, keep using the save-file
  `add_porch_item` fallback (works, requires reload/idle at title screen).
- **Still NOT found**: the live bool-flag array (`IsGet_*`, `Clear_Dungeon*`). Exhaustively
  scanned (full 12GB diff scans, ±128MB around `gd_base`, and the entire 3.6GB heap region for
  1-byte/bitmask packed arrays) — zero matches. Likely a hashmap/tree keyed by CRC32, not a flat
  DataIndex array. Flag injection (Paraglider, runes, gate retention, shrine-clear) **still uses
  the save-file path** (works, requires reload/idle at title screen — see `DeferredSaveInjector`).
  Further progress here would need x64dbg hardware watchpoints, not blind scanning.

Scripts: `tools/live_scan.py` (rupee AOB + bool-array dead-end), `tools/live_inventory.py`
(inventory scanner/dumper), `tools/test_live_inventory_api.py`, `tools/test_live_rupees.py`.

---

## 1c. SOLVED — "item received" overlay (V1, stdlib-only)

`BotWClient/overlay.py` (`Overlay` class): a Tkinter toast notifier running in its own
daemon thread (`start()`), driven by a thread-safe queue (`notify(title, subtitle)`).
On `ReceivedItems`, `BotWClient._on_msg` calls `self.overlay.notify(spec.ap_item_name,
spec.display_note)` ([BotWClient.py](../BotWClient/BotWClient.py)). Shows a small
translucent toast top-right ("Archipelago — Item reçu / <name>"), fades in/out over
~5s, stacks multiple toasts. No extra dependency (Tkinter is stdlib) — minimal install
friction, per user request. Enabled by default; `--no-overlay` to disable. Confirmed
working visually by the user.

This is the user-confirmed **V1** of the "polished presentation" goal (custom item
names/popup like other Zelda AP clients). **V2** (discussed, not started): a proper
BOTW mod ("BOTWpelago") — see §6 — for in-game HUD popups with real item icons and a
fully mod-driven randomizer/AP connection. V1 (this overlay) stays as the always-works
fallback even after a V2 mod exists.

---

## 2. TESTS / VALIDATIONS performed (chronological)

1. **Parser** — confirmed offset 12, 128,399 entries, 99.1% values ≤1 (before & after saves identical length 1,027,208).
2. **Capture** — `save_watch.py` produced clean before/after snapshots of an Oman Au completion (debounced copy, no torn files).
3. **Hash oracle** — `hash_oracle.py` on the diff: 28 flags flipped 0→1; cross-matched against candidate names → recipe `crc32 / asis / ascii / nonul`, id big-endian, single but semantically decisive match (`IsGet_Obj_Magnetglove`).
4. **Recipe re-verification** — independently confirmed `crc32("IsGet_Obj_Magnetglove") == 0x795E7BBC`; and against embedded `HashValue` across the gamedata corpus.
5. **Flag corpus** — `extract_flag_names.py` pulled **~42,537 names** from `content/Pack/Bootup.pack` → `GameData/{gamedata,savedataformat}.ssarc`.
6. **Name extraction** — `extract_msg_names.py` parsed MSBT from `Bootup_EUen.pack`: `Dungeon.msbt` (360 entries) → `dungeon_names.json`, validated **`Dungeon038 = "Oman Au Shrine"`**; `LocationMarker.msbt` (702 entries) → 15 towers (`Tower01 = "Hebra Tower"`).
7. **Location scaffold** — `scaffold_locations.py` produced **139 locations** = 120 shrines + 15 towers + 4 beasts, all named.
8. **Gate flags** — identified and CRC32-verified: paraglider, 5 runes, 4 HeroSouls, Master Sword, DungeonClearCounter (see `gate_items.json`).
9. **Memory bridge** — `memory_bridge.py` drafted (OpenProcess + RPM/WPM + region scan, BE-aware) but NOT yet validated live against Cemu; calibration step pending.

Environment: BotW Wii U **1.5.0**, region **EUR (`101c9500` / `[ALZP01]`)**, **Cemu 1.18.1** (note: project pins 2.x; for save/flag work only the *game* version matters — Cemu version only matters for the live-memory path).

---

## 3. ARTIFACTS produced

### Data (commit these into `data/`)
| File | Content |
|------|---------|
| `flag_names.txt` | ~42,537 flag names from the dump (game-derived; gitignore if you don't want game data in the repo) |
| `dungeon_names.json` | `Dungeon{NNN}` → shrine name (+ `_master` monk) |
| `location_marker.json` | towers / locations / etc. |
| `locations.json` | 139 AP locations: category, flag_name, flag_hash, ap_id, name |
| `gate_items.json` | key items: flag, hash, role (ap_progression / starting), + goal condition |

### Tools (the reusable pipeline — keep in e.g. `tools/`)
| Script | Role |
|--------|------|
| `save_watch.py` | snapshot `game_data.sav` on each stabilized write (clean before/after capture) |
| `hash_oracle.py` | brute-force the hash recipe from a before/after diff × candidate names |
| `flag_db.py` | canonical resolver: `flag_id()`, parse save, name↔id, `--diff` |
| `extract_flag_names.py` | pull all flag names from `Bootup.pack` GameData (oead) |
| `extract_msg_names.py` | MSBT parser → shrine/tower names from `Bootup_<lang>.pack` |
| `find_flags.py` | grep flag_names.txt by regex + show CRC32 |
| `scaffold_shrines.py` / `scaffold_locations.py` | build shrines/locations JSON from flags + names |
| `memory_bridge.py` | (v2) live RPM/WPM on cemu.exe — drafted, unvalidated |

### AP id ranges (in use)
- Items: `6_080_000`+ (paraglider 0, runes 1–5, master sword 6, champions 10–13)
- Locations: shrines `6_081_000 + dungeon_id`; beasts `6_081_201–204`; towers `6_081_300 + n`

---

## 4. ARCHITECTURE & design decisions

### The two-layer model
- **Logic** (apworld, Python): item→location dependencies for the generator. Always doable; doesn't enforce anything in-game.
- **Enforcement** (in-game): physically preventing actions without the item. BotW is open-world → **few natural gates**.

### Outgoing items are FREE
When the player completes a check, the client only sends `LocationChecks(ap_id)`. The **server** (using the seed's placement) decides what item is there and routes it to its owner (possibly another game). **The client injects nothing when sending.** Injection only matters for items the BotW player RECEIVES.

### Detection
Poll flags → on 0→1, emit the matching `ap_id`. Save-file polling works today; live memory (`memory_bridge`) is the v2 fast path with save fallback.

### Gating via flag retention
For `ap_progression` items: the client **forces the flag to 0** until the AP delivers the item, then sets it to 1. Natural mechanics do the rest (no paraglider ⇒ stuck on plateau). Caveat: retention "chases the game" → a brief flicker when vanilla grants the item; invisible if polled fast, but it's the main argument for a romfs mod (see §6).

### Goal (client-side, all flag-based)
Send `StatusUpdate(goal)` only when: `Get_MasterSword_Finish` AND the 4 `IsGet_Obj_HeroSoul_*` AND `DungeonClearCounter >= N` (apworld option). Hylian Shield (PouchItem) deferred to v2.

### Injection (the remaining hard part)
- **Flag items** (paraglider, runes, champion abilities, master sword): easy — set the flag.
- **Inventory items** (armor incl. Hylian Shield, weapons, bows, arrows, consumables): **PouchItem** structures (name string + count + type…), NOT flat ids. Naive memory writes corrupt/get overwritten. Approach via save-edit of the porch, or reverse `PouchItem` for 1.5.0. This is the biggest remaining engineering task.

---

## 5. TODO (prioritized)

- **TODO-1 — Reconcile docs.** `CLAUDE.md`/`memory_map.md`/`README.md` still say BYML/oead/pymem and the wrong shrine flag pattern. Make them match §1.
- **TODO-2 — Fix `item_map.py`.** Champion abilities → `IsGet_Obj_HeroSoul_*`; paraglider → `IsGet_PlayerStole2`; use `gate_items.json` as source of truth.
- **TODO-3 — Wire detection.** `SaveFileProvider` reads `locations.json`, resolves flag→hash→id, polls save, emits checks on 0→1.
- **TODO-4 — Wire gating + goal.** Injector that (a) forces `ap_progression` flags to 0 until received, (b) sets them on receipt, (c) evaluates the goal condition. Driven by `gate_items.json`.
- **TODO-5 — Item injection (inventory). SOLVED (live path) for items already in the pouch.** See §1b — `CemuMemoryBridge.live_add_item_qty` / `live_add_rupees` do instant, no-reload injection for PouchItem materials/weapons/arrows and rupees, wired into `_apply_actions_memory`. **New-item creation (item not yet in the pouch) tested and confirmed NOT achievable live** — free-list slots (0-4) aren't part of any category's render list, and even the reference tool only renames existing entries. Falls back to gd_base save-buffer `add_porch_item`, which requires reload — this fallback is final, not a TODO.
- **TODO-6 — Quests.** No clean flag pattern; identify per-quest via `save_watch` + `flag_db --diff`. Add as locations incrementally.
- **TODO-7 — Region assignment.** `locations.json` has empty `region`; fill for apworld access rules (from objmap region grouping or by hand).
- **TODO-8 — (v2) Chests as locations.** Instance-hashed flags; enumerate desired chests (objmap lists IDs per shrine/region).
- **TODO-9 — (v2) Validate `memory_bridge` live** + calibrate against a known flag; only matters on Cemu 2.x.

---

## 6. ENFORCEMENT OPTION — romfs mod (v2, optional)

Flag-retention gives **soft enforcement**: it works, but (a) flickers when vanilla grants an item, (b) can't block things with no natural mechanic (e.g., physically barring the Ganon fight), (c) can't stop a determined glitcher (plateau-skip glitches exist).

A small **romfs mod** (a Cemu graphic pack that overrides game files) gives **hard enforcement** by editing the game at the source:
- Remove the vanilla paraglider grant (King's Temple-of-Time event) → no flicker, the only paraglider is the AP one.
- Optionally remove Spirit Orbs from shrines, remove vanilla rune/ability grants, etc.
- Gate the Ganon fight (event-flow / flag check on entry).

**How:** edit EventFlow (`.bfevfl`) and game data, repack via SARC, ship as a Cemu graphic pack (`rules.txt`). Tooling: BCML, EventFlow editors, `oead`/sarc. This is the layer MelonSpeedruns/Waikuteru live in.

**Recommendation:** ship **v1 with flag-retention only** (no mod, fully functional, AP-meaningful). Add a romfs mod in v2 only if flicker/sequence-breaks become a real problem. Keep the mod as a *separate, optional* component — the AP client must still work without it (just with softer enforcement).

### V2 vision — "BOTWpelago" mod (discussed, not started)

Beyond hard enforcement (above), the user wants a V2 **installable Cemu graphic pack
("BOTWpelago")** that would also own:
- Custom item names/icons for AP items in the inventory/get-popup, matching the polish
  of other Zelda AP clients (ALTTPR/OOTR-style "item get" banners).
- An in-game HUD popup when an item arrives from another world (replacing/augmenting
  the V1 desktop overlay in §1c).
- Randomizer logic configurable from the mod itself.

This is a major scope jump from the Python client (EventFlow/.bfevfl editing, SARC
repack, custom BFRES/icon assets, BCML pipeline) — not started, no design work done
yet. The V1 overlay (§1c) is the interim solution and remains the fallback even once a
V2 mod exists. Revisit when there's bandwidth for Wii U asset/EventFlow modding.

#### Agreed phase order (V2)

1. **Item injection (in-game, EventFlow-driven)** — the foundation. Build a custom,
   always-running EventFlow flowchart that polls an external "mailbox" signal and, on
   match, runs the native item-grant action (correct PouchItem-list insertion + native
   "item get" popup) for a **vanilla item ID** (skip custom items for the MVP).
2. **Custom items (icons/names)** — extends phase 1's mechanism with AP-branded actors/
   icons/MSBT entries once the trigger pipeline is proven on vanilla items.
3. **Randomizer & logic migration** — move check-detection/placement logic from
   save-polling into the mod once injection is solid.
4. **Final multi-game integration test.**

#### Phase 1 research findings (toolchain confirmed viable)

A research pass (web search + reasoning, see chat log) confirmed **no tooling blocker**
for Wii U:
- **BCML** (NiceneNerd/BCML) — mod manager/merger, confirmed Wii U + Switch. Packs
  SARC/YAZ0, needs Wii U-specific `--be` / `-b` flags when building.
- **evfl** (zeldamods/evfl, Python) + **EventEditor** (zeldamods/event-editor) — parse/
  edit `.bfevfl` flowcharts. Endianness note: EventFlow binaries are often
  little-endian **even on Wii U** — don't assume BE like the save file; verify per file.
- **Switch Toolbox** — BFRES/icon editing. Wii U needs an extra `Tex1.sbfres`/
  `Tex2.sbfres` pair per item icon vs. Switch's two files (per ZeldaMods "Help:Adding
  Items").
- Custom item creation (new actor pack + icon + MSBT name/desc, packaged with
  `--be`/`-b`) is "an afternoon per item once you've done it once" — real but bounded,
  deferred to phase 2.

**Key reframing of the "flags need reload" assumption**: `GameDataMgr::
getAndSetShrineQuestAndKassFlags()` runs **every frame from GameScene**, reading/writing
live GameData flags that EventFlow conditions query — i.e. the in-memory flag table
(NOT the on-disk save buffer `gd_base`) is plausibly live-readable by EventFlow without
reload. Our earlier "flag array not found" scans were generic (bool/bitmask arrays over
12GB) and found nothing — but a **targeted scan for known CRC32 hash constants** (e.g.
`0x795E7BBC` Magnesis, `0xFE4D1501` Paraglider from `gate_items.json`) as 4-byte values
in the live heap is much cheaper and hasn't been tried. This is the next concrete
experiment (`tools/live_flag_scan.py`, not yet run).

**Mailbox candidates** (external signal → in-game trigger) ranked by how proven the
underlying write is:
- Rupee count (`Money` GameData value) — write already confirmed live/instant. Could
  serve as a crude PoC mailbox (e.g. a sentinel value like 999999 = "item pending").
- A specific PouchItem material's quantity — also confirmed live-writable.
- A dedicated new GameData flag added by the mod itself — cleanest long-term, but
  requires the mod build pipeline (phase 1 deliverable) to exist first.

**Other leads**: Waikuteru's "BOTW Randomizer" (Wii U/Cemu, Patreon) reportedly already
solves "external logic replaces native item grant with popup" — closed source, but
their Discord (`discord.gg/ZU5cPYbYWZ`) may give a pointer worth an afternoon of
outreach. MelonSpeedruns/BotwRandomizer source is public and may contain reusable
EventFlow edits.

**Immediate next step**: run a targeted live-memory scan for known flag-hash constants
near the already-located inventory heap region, to test whether the in-memory
`GameDataMgr` flag table is findable/writable the same way rupees/PouchItem are.

**`tools/live_flag_scan.py` — RUN, result non-blocking**: 46 hits across two clusters
outside `gd_base`. Neither cluster is directly a live "current value" table usable from
outside the process (one looked like a sorted index/metadata table, the other like
`gdt::TriggerParam`-style objects with vtable pointers). Conclusion: don't pursue this
further — it's not needed. EventFlow reads/writes GameData via the engine's own internal
APIs (guaranteed live, per the `getAndSetShrineQuestAndKassFlags()` reframing above), so
our mod's EventFlow code doesn't need to find that table externally. Only the external
→ in-game "mailbox" signal needs an externally-writable address, and that's already
solved (rupees / PouchItem quantities, both confirmed live-writable).

#### EventFlow trace — found the native "give item + popup" action (major milestone)

Traced `EventFlow/GetDemo.bfevfl` (extracted from `TitleBG.pack`, generic "item get"
flowchart used everywhere — chests, quest rewards, shrines, etc.) using `evfl` 1.2.0.
17 entry points found; the relevant one is **`GetManyItemsByName`** (event chain
104→103→105→101→102):

1. `EventSystemActor.Demo_SetGameDataInt` — `GameDataIntName='GiveItemNumber'`,
   `Value='GetNumber'` (param)
2. `EventSystemActor.Demo_IncreasePorchItem` — `PorchItemName='IncreaseTargetActorName'`
   (param, item **actor name** string e.g. `"Item_Fruit_A"`), `Value='GetNumber'`
   — **this is the actual pouch-increment action**
3. `EventSystemActor.Demo_WaitFrame` (`Frame=0`)
4. `SubFlowEvent` → local entry point `ShowGetDemoDialogByName`
   (`CheckTargetActorName='ShowDialogTargetActorName'`) — **this shows the native
   "you got an X!" popup + sound**, via a Fork into `Demo_OpenGetDemoDialog`
   (`EventSystemActor`, `TargetActorName=..., EnableMultiGet=...`)
5. `EventSystemActor.Demo_SetGetFlagByActorName` (`ActorName='IncreaseTargetActorName'`)
   — sets the item's "got" flag

So `GetManyItemsByName(IncreaseTargetActorName=<item actor name>, GetNumber=<count>,
ShowDialogTargetActorName=<item actor name>, Current=<arg>,
Arg_IsInvalidOpenPouch=<arg>)` is **the** generic "give the player N of item X, show the
popup, set the flag" routine — exactly the primitive Phase 1 needs.

(There's also a simpler `GetItemByName` entry point, event chain 54→53→96: skips the
`Demo_IncreasePorchItem`/`Demo_SetGameDataInt` steps and goes straight to
`Demo_CheckAndCreateEquip` → `ShowGetDemoDialogByName` → `Demo_SetGetFlagByActorName`.
Likely used for equipment/key-item actors that are added to the pouch by other means.)

**No example external caller found yet**: grepped `RemainsWind.pack` and
`Dungeon038.pack` for `.bfevfl` files referencing `GetManyItemsByName`/`GetItemByName` —
neither pack contains any `.bfevfl` at all (chest/reward "give item" is wired through
native Action/AI classes in the RPX, not a flowchart `SubFlowEvent`). This means: no
reference flowchart to copy the calling convention from, but also confirms our approach
(a custom flowchart that `SubFlowEvent`s into `GetDemo`'s `GetManyItemsByName` with
`res_flowchart_name='GetDemo'`) doesn't need to match an existing caller exactly — we
control both ends.

**Confirmed for the "ambient mailbox poller" design**: `EventSystemActor` exposes a
`CheckFlag` query (seen in `GetDemo.bfevfl` events 68/70/72/74, e.g.
`CheckFlag(FlagName='Guide_ShortCutSword')`) — i.e. a `SwitchEvent` on `EventSystemActor`
can read a GameData bool flag directly. This is the mechanism for a per-frame-ish
"is the mailbox flag set?" check in our custom flowchart (modeled on the
Kass/quest-flag-checker pattern).

**Next steps for Phase 1 design**:
- Find/confirm the equivalent int-reading query (likely `CheckGameDataInt` or similar —
  not present in `GetDemo.bfevfl`'s actor-query list, but `EventSystemActor` almost
  certainly supports more queries than this one flowchart uses; check another flowchart,
  e.g. a Kass quest one, or the RPX symbol table).
- Design the custom flowchart: an always-running entry point (registered how? — need to
  find how "ambient" flowcharts like the Kass checker get auto-started, vs. needing an
  actor/trigger) that polls the mailbox value/flag, and on trigger does
  `SubFlowEvent(res_flowchart_name='GetDemo', entry_point_name='GetManyItemsByName',
  params={...})` then clears the mailbox.
- Validate item actor name strings for AP items (e.g. `Item_Fruit_A` etc.) against
  `data/gate_items.json` / `data/locations.json`.

#### Tips system found, then closed — gd_base flag writes don't trigger native UI live

Found `Bootup.pack/EventFlow/Tips*.bfevfl` (`TipsItem`, `TipsCommon`, `TipsNotify`, etc.):
a generic "tip popup" system where each entry point (e.g. `IsGet_AncientArrow`) is just
`CheckFlag(FlagName='IsGet_AncientArrow')` -> `Demo_TipsDisplayOK`/`Demo_TipsDisplayNG`.
Structurally this looked like exactly the "flag -> in-game popup" mailbox we wanted —
add a custom Tips entry checking a custom flag, write that flag from Python.

**Tested live (`tools/test_tips_flag_live.py`)**: wrote `IsGet_AncientArrow` 0->1 via
`write_flag()` (gd_base, already-located buffer) while in-game (not at title screen).
Read-back confirmed the write stuck (1), but **no Tips popup appeared**. Reverted to 0
afterward.

**Conclusion**: `gd_base` is not a table that's continuously polled live by either the
`Tips` system or `GetDemo`'s popup logic — both are almost certainly triggered by
discrete in-game *events* (item-pickup event, menu-open event, etc.), not by passive
GameData flag state. This is consistent with the original (pre-V2) "flags need reload"
finding — it's not specific to writing the on-disk save file, `gd_base` itself behaves
the same way at runtime. **Both the `GetDemo` SubFlow route and the `Tips` flag route
are closed for triggering a native in-game popup from an external Python write.**

**What's NOT closed**: V1 desktop overlay (`BotWClient/overlay.py`) — already built,
confirmed working, stdlib-only, shows AP item name on receive. For a true *in-game*
popup, the remaining option is native code-level hooking (CafeOS/RPX function hooks via
something like a Cemu plugin or binary patch) to directly invoke the engine's
"give item + show popup" C++ function — a substantially larger, separate research
project (different tooling than EventFlow/.bfevfl editing). Not started; treat as a
stretch goal, not a Phase 1 blocker. V1 overlay remains the practical solution for
"tell the player they got an AP item" until/unless that's pursued.

### V2 — MAJOR LEAD: "Accio" community cheat already implements the mailbox we need

Before continuing manual RE, found that the BotW Wii U modding community already built
**exactly** the "spawn item by name via a memory mailbox" mechanism we were trying to
reverse-engineer, via Gecko/Cafe codes (`m-byte918/BotW-Cheat-Codes`, "Accio" — all
versions, all regions):
- A **Master Code** (`All Versions/Accio/MasterCode [MrBean35000vr & Chadderz]`, must
  stay enabled) polls a fixed memory region and, when triggered, spawns an
  actor/item by name.
- **Protocol** (per the Accio README):
  - `0x10024060` — ASCII (hex-encoded) object/item **name** string (e.g. writing
    `PutRupee_Gold` spawns gold rupees — confirmed by decoding the "100 Gold Rupees"
    script code's embedded string).
  - `0x10024038` — spawn **quantity**.
  - Manual spawning works by writing these two values directly — no script code needed.
- These addresses are in the `0x10000000`-based region — the **same addressing scheme**
  our `CemuMemoryBridge`/`gd_base` already uses for `game_data.sav` flags. If the offset
  arithmetic is the same (RPX `.rodata`-relative), `CemuMemoryBridge` can likely write to
  `0x10024060`/`0x10024038` with the same base-address technique already proven to work.
- Saved locally for reference: `tmp/accio/Accio/` (full code dump, all item/NPC/actor
  spawn scripts + MasterCode, cloned from
  [m-byte918/BotW-Cheat-Codes](https://github.com/m-byte918/BotW-Cheat-Codes)).

**Why this matters**: if this works, we may not need to write our own PPC code cave at
all for the "give item" half of V2 — just ship the Master Code as an always-on Cemu
cheat (`cheats.txt` in the game's graphic pack / cheat folder, Cemu's built-in cheat
engine since ~1.15 supports Gecko-style codes), and have the Python client write the AP
item's internal actor/object name + quantity to the two mailbox addresses. The item
name strings used by `PutRupee_Gold`-style spawning are likely the same
`PorchItemName`/actor names already known from `data/gate_items.json` and the EventFlow
trace (`Demo_IncreasePorchItem(PorchItemName, Value)`).

**Open questions for next session**:
1. Does writing to `0x10024060`/`0x10024038` via `CemuMemoryBridge` (with the Master
   Code enabled in Cemu) actually trigger a spawn live? (Empirical test — same style as
   `tools/test_tips_flag_live.py`, much cheaper than more Ghidra RE.)
2. What's the exact trigger condition — is setting quantity != 0 sufficient (poll-based,
   auto-resets to 0 when consumed), or is there a separate trigger byte/button-combo?
   Decode the MasterCode's PPC (capstone `CS_ARCH_PPC | CS_MODE_BIG_ENDIAN` confirmed
   available in this env) to find the poll/reset logic if empirical testing is
   ambiguous.
3. Does this spawn mechanism produce a "got item!" popup (the UI we actually want), or
   does it just drop a physical actor in the world (which would still need the
   EventFlow `GetManyItemsByName`-style popup separately)? The "Gold Rupees on head"
   / "Rupee Rain" style codes suggest **physical actor spawn near the player**, not a
   pouch-increment-with-popup — needs live verification.

**If this pans out**: V2 becomes "ship a `cheats.txt` graphic pack + Python writes to 2
fixed addresses" instead of a from-scratch PPC code cave — a massive scope reduction.
**If it doesn't** (e.g. only spawns world actors, no popup/pouch increment): the Ghidra
RE below remains the fallback, and the decoded MasterCode PPC may still reveal useful
function addresses (its `bl`/`bctrl` targets likely point into `U-King.rpx`'s actor-spawn
code).

**`tools/test_accio_live.py`** — RUN, calibration too imprecise for `--write`, don't
pursue further without more grounding. Findings:
- Fixed `CemuMemoryBridge._iter_regions()`: it only included `PAGE_READWRITE`/
  `PAGE_EXECUTE_READWRITE` regions, so `.rodata` (read-only) was invisible. Now includes
  `PAGE_READONLY`/`PAGE_EXECUTE`/`PAGE_EXECUTE_READ`/etc. (fix kept — improves all future
  memory scans).
- Calibrated via the single in-memory hit for `"HorseCustom_ShopSaddleName"` →
  `cemu_mem_base = host - (0x10000000 + rodata_offset)`. Reading
  `cemu_mem_base + 0x10024060/0x10024038` gave non-zero, pointer-/string-looking garbage
  (`0x021Fxxxx`-style values, partial ASCII) — not an empty mailbox.
- Cross-check (`tools/verify_calib.py` + `tools/scan_cemu_string.py`): searched 4 known
  `.rodata` strings (`IsGet_Obj_Magnetglove`, `PutRupee_Gold`, `DungeonClearCounter`,
  `HorseCustom_ShopSaddleName`) live in Cemu memory. Their host addresses, minus their
  `tmp/rodata.bin` file offsets, should all yield the same `cemu_mem_base + 0x10000000`
  if the dump is a byte-exact mirror of the runtime `.rodata` — but they differ by
  ~0xb00–0x1000+ and the drift **grows with distance** between strings. So
  `tmp/rodata.bin` is NOT a byte-exact mirror of runtime `.rodata` (likely
  alignment/padding differences from the RPL section extraction). `0x10024060` is
  ~0x1A4000 bytes before the nearest verified string — at that distance the accumulated
  drift could be kilobytes, so a blind `--write` there risks corrupting unrelated
  memory/crashing Cemu. **Don't run `--write` without a better calibration.**

**Conclusion for this lead**: the Accio mailbox protocol may well be correct for some
BotW versions, but confirming/locating it precisely for our v1.5.0/V208 dump needs
either (a) a byte-exact `.rodata` reference (re-extract more carefully / dump `.rodata`
directly from live Cemu memory instead of the RPX file), or (b) decoding the Accio
**MasterCode**'s actual PPC — which first requires parsing the Gecko/Cafe code-type
header (`C00000DE 60000000`-style words interleave metadata with raw instructions; not
a direct capstone feed). Both are bigger sub-tasks — **deprioritized**. Pivot to the
Ghidra GUI lead below (`0x029FFB3C`), which needs no live memory writes.

---

### V2 — cross-check: official Cemu BotW cheat patches confirm address space + give a new actor-spawn lead

Cross-referenced our Ghidra candidates against the **official Cemu graphic-packs repo**
(`cemu-project/cemu_graphic_packs`, `src/BreathOfTheWild/Cheats/`, sparse-cloned to
`tmp/cemu_graphic_packs_cheats/Cheats/` for reference) — 16 official `.asm` cheat
patches for BotW (InfiniteHearts, InfiniteStamina, InfiniteArrows, Durability,
PreventRandomSpawns, etc.).

**Confirmed: `V208` = BotW WiiU 1.5.0 (our pinned version).** Every patch has a
`[BotW_<Name>_V208]` section with `moduleMatches = 0x6267BFD0` — a version-identifying
hash shared by *all* V208 patches. This validates that the `.text` addresses these
patches reference (`0x02EBxxxx`, `0x02CExxxx`, `0x02D7xxxx`, `0x02D9xxxx`, `0x029Exxxx`,
`0x029Fxxxx`, `0x02A3xxxx`, `0x0316xxxx`, `0x02AFxxxx`, `0x024Axxxx`, `0x020Axxxx`-range)
live in the **same address space** as our Ghidra-analyzed `U-King.rpx` 1.5.0 — i.e.
`0x02cbb0d4`, `0x023acecc`, `0x02cf16xx`, `0x02ce2b64` are directly comparable/nearby.

**Confirmed Cemu codecave syntax** (from `PreventRandomSpawns/patch_PreventActorSpawns.asm`):
- `.origin = codecave` + labeled blocks for injected code, `.string "..."`, `.int`,
  `.align 4`.
- Hook injection: `0xADDRESS = bla <label>` — **`bla`** (Branch-Link-Absolute) is how
  Cemu code caves call into injected code from anywhere in the >32MB `.text` (normal
  `bl` can't reach a far codecave).
- Calling Cabal/OS imports from a codecave: `bl import.coreinit.OSReport`.

**NEW LEAD — `0x029FFB3C`, actor-spawn-by-name check.** `PreventActorSpawns` hooks
`0x029FFB3C = bla preventAutoPlacementSpawn`. Inside the codecave: reads a string
pointer via `addi r4, r1, 0x40 / lwz r4, 0(r4)`, then does byte-by-byte `lbz`/`cmpwi`
ASCII comparisons of that string against actor-type-name prefixes (`"Enemy_Assassin_"`,
`"Enemy_BokoblinBon"`, `"Enemy_Stalmoblin_Bone"`, `"Enemy_Lizalfos_Mori"`, `"Animal_"`,
`"Enemy_"`), returning 0 (prevent spawn) vs. the original `cmpwi r3, 0 / blr` for
everything else.

This proves there's a native **"should this actor placement spawn?"** function at/near
`0x029FFB3C` in `U-King.rpx` that receives an **actor-name string**. Since PorchItems
(inventory items) are themselves actors, this function — or whatever calls it — is a
strong candidate for being either:
- the function the Accio Master Code calls to spawn an item/actor by name, or
- directly adjacent/related code that could be repurposed/hooked for "give item by
  name" in the V2 mod.

**Next session candidates (in order of cost)**:
1. Run `tools/test_accio_live.py` live (cheap, empirical — see above).
2. If Accio's spawn mechanism turns out to be world-actor-only (no popup/pouch), open
   `D:\Tools\GhidraProjects\BotW.gpr` in the Ghidra **GUI** and inspect `0x029FFB3C` and
   its callers/callees — now that we have a community-validated, version-confirmed
   address in the same binary, this is a much more targeted starting point than the
   earlier blind `FUN_02cbb0d4` search.

---

### V2 — followed the 0x029FFB3C lead to a vtable; reached a semantic dead end for "give item"

Used new headless scripts (`D:\Tools\GhidraScripts\Analyze029FFB3C.java`,
`Refs029FFB3C.java`, `ProbeTableFuncs.java`, `Decompile020642a8.java`) to trace
`0x029FFB3C`:

- `0x029FFB3C` is **not** inside any Ghidra-defined function — it's part of a small
  "return-constant stub farm" at `0x029ff9bc`–`0x029ffb90` (lots of `li r3,0|1 / blr`).
  Raw bytes at the hook: `38 60 00 01` (`li r3,1`) / `4e 80 00 20` (`blr`) — i.e. the
  **default return value is `true`**.
- Found via raw byte search of `tmp/rodata.bin` (search for the 4-byte BE pointer
  `0x029FFB3C`): it's **entry #16 of a 22-entry function-pointer table at WiiU
  `0x1018377C`** (`.rodata`), stride 8 bytes, each entry `{func_ptr, 0x00000000}`.
- Several "real" (non-stub) entries in this table — `FUN_029fe13c` (#1), `FUN_029fe190`
  (#5), `FUN_029fe198` (#12) — are called **directly** (not via the table) from
  `FUN_020642a8` (a 1164-byte per-frame actor physics/water-submersion update function)
  and `FUN_0202b5d0`. This strongly suggests the table is a **vtable for a base actor
  class** (likely `LiveActor` or similar), and entry #16 is a virtual method most actor
  subclasses don't override, defaulting to `return true`.
- `029ff814`/`029ff940` (constructor/destructor pair using vtable `&DAT_10183730`,
  which sits 0x4C bytes before our table) are in the same `.rodata` region —
  consistent with a class-layout data block.
- **Could not find the call site** for vtable slot #16 specifically (`vtable+0x80`
  indirect call) — would require a heavy indirect-call pattern search across ~35MB of
  `.text`.

**Why this is a dead end for V2's "give item" goal**: `PreventActorSpawns` (the cheat
that uses this hook) governs **world-actor spawning** (enemies/animals/horses via
"auto placement"), not inventory items or `Demo_IncreasePorchItem`-style item grants.
Even if we found the call site, it's the wrong subsystem. **Don't continue down the
vtable-slot-#16 path.**

**Recommended pivot**: go back to the previously-identified **right** native primitive —
`GetManyItemsByName` / `ShowGetDemoDialogByName` / `Demo_IncreasePorchItem` (EventFlow
actions, see `#### EventFlow trace` section above). The earlier string/CRC32 search for
these names in `.text`/`.rodata` failed (closed, don't retry as literal strings). Next
idea: search Ghidra's **symbol table / exports** for these names directly (RPX exports
or debug symbols may carry the C++ mangled names of the EventFlow action classes
`UKAct*`/`*ActionXXX`, which Ghidra may have already demangled during auto-analysis,
independent of string-literal search). This is a cheap symbol-table query, not a new
disassembly trawl.

**RESULT — also a dead end**: ran `SearchSymbols.java` (`tmp/search_symbols.txt`)
against all 693,951 symbols in the Ghidra DB for `GetManyItems`, `ShowGetDemo`,
`IncreasePorch`, `PorchItem`, `GetFlagByActor`, `TipsDisplay`, `DemoAct`, `UKAct`,
`EventFlow`, `ActionFlag`, `GiveItem`, `AddItem` — **zero matches for all**. The symbol
table is entirely auto-generated `FUN_xxxxxxxx`/`DAT_xxxxxxxx` (no debug info, no
demangled C++ names, no RPX-exported names for these). EventFlow action-name resolution
happens via a mechanism invisible to both string search and symbol search from this
binary alone.

### V2 RE — session conclusion: three leads, three dead ends

This session tried, in order: (1) Accio mailbox (calibration too imprecise/risky for a
live write), (2) `PreventActorSpawns`/`0x029FFB3C` vtable slot (found the vtable, but
it's actor-world-spawn permission, not item-grant — wrong subsystem), (3) symbol-table
search for EventFlow action names (zero hits, no debug info). **The pure-RE path for
"give item by name + native popup" has not yielded a usable function address after
two sessions of effort.**

**Open strategic options for V2** (for discussion with user, not yet decided):
- Accept the **V1 desktop overlay** (`BotWClient/overlay.py`, already working) as the
  permanent solution — it already solves "show AP item received" without any RPX
  modification, at zero further RE cost.
- Revisit Accio with better tooling: dump `.rodata` directly from **live Cemu memory**
  (byte-exact, no RPL-extraction alignment drift) instead of `tmp/rodata.bin`, to get a
  trustworthy `cemu_mem_base` for testing `0x10024060`/`0x10024038`.
- Decode the Accio **MasterCode**'s Gecko/Cafe-format PPC properly (parse the
  `C00000DE 60000000`-style code-type headers first) — its `bl`/`bctrl` targets would
  point at the *actual* spawn function used by a cheat that's known to work on real
  hardware, sidestepping our blind .text search entirely.
- Try EventFlow from the **data side**: extract a `.bfevfl` flow that's known to call
  `GetManyItemsByName` (e.g. a shrine reward flow) and trace how the EventFlow VM
  resolves action names at runtime (may point to a small interpreter/dispatch loop in
  `.text` that takes the action name as a *runtime string* from the `.bfevfl` file,
  rather than a compile-time literal — explaining why string search failed).

---

### V2 RE — ROOT CAUSE of all calibration failures found + live-memory calibration SOLVED

**Root cause**: `D:\Tools\GhidraProjects\BotW.gpr` (and `tmp/rodata.bin`/`tmp/text.bin`)
were built from the **base game RPX** (`.../usr/title/00050000/101c9500/code/U-King.rpx`,
22,029,888 bytes, `.rodata` size `0x3F8A20`), **not** the v1.5.0/V208 update that Cemu
actually runs (`.../usr/title/0005000e/101c9500/code/U-King.rpx`, 23,268,032 bytes,
`.rodata` size `0x462BBC`). Different binary, different `.text`/`.rodata` layout and
sizes — every address from the Ghidra analysis so far (`0x02cbb0d4`, `0x029FFB3C`,
`0x1018377C` vtable, etc.) is a **base-game address** and may not correspond to the
same code/data in the running v208 process. This fully explains why every
`.rodata`-offset-based calibration attempt drifted unpredictably.

**Fix applied**: `python tools/rpx_extract.py "<mlc01>/usr/title/0005000e/101c9500/code/U-King.rpx" tmp/rpx_v208` re-extracted all sections from the correct v208 RPX
(`tmp/rpx_v208/03_rodata.bin` = 0x462BBC bytes, single contiguous section,
`addr=0x10000000`, `align=0x20` — no concatenation/alignment ambiguity).

**Live calibration SOLVED**: using v208 `.rodata` offsets, `host_addr = cemu_mem_base +
vaddr` with **`cemu_mem_base = 0x247E4440000`** (constant!) — verified exactly against
5 independent strings (`Access_AllTerminalFire`, `IsGet_Obj_Magnetglove`,
`PutRupee_Gold`, `DungeonClearCounter`, `HorseCustom_ShopSaddleName`), all landing on
the correct string at the predicted host address. `tools/calib_anchor.py`,
`tools/calib_distance.py`, `tools/check_accio_mailbox.py` document this derivation.
**This `cemu_mem_base` formula is the reusable result of this session** — any future
live-memory work (verifying writes, finding runtime tables, etc.) can convert a known
v208 `.rodata`/`.data` vaddr directly to a host address with no further calibration.

**Accio mailbox (`0x10024060`/`0x10024038`) — confirmed dead, don't retry**: with the
correct `cemu_mem_base`, `0x10024060` lands squarely inside the RPX's actual `.rodata`
(reads back as live string-table data: `"kStopSpeed\x00\x00..."`, `0x10024038` reads
`"s\x00\x00\x00Targ"` — fragments of adjacent strings). On Cemu, `.rodata` is loaded at
`0x10000000` and occupies up to `0x10462BBC`, so `0x10024060` is just an offset into
real static game data, not free scratch RAM. Accio's mailbox addresses are real-Wii-U
(JGecko-U) addresses that don't correspond to free memory under Cemu's emulation layout
— **this closes options 2 and 3 (Accio) permanently**, independent of the MasterCode
PPC decode.

**DONE**: full Ghidra headless analysis re-run on the *correct* v208 RPX → project
`D:\Tools\GhidraProjects\BotW_v208.gpr` (`analyzeHeadless ... -import
"<mlc01>/usr/title/0005000e/101c9500/code/U-King.rpx" -loader CafeLoader
-analysisTimeoutPerFile 3600`, ~21 min, 92,999 functions). v208 section dumps at
`tmp/rpx_v208/{02_text.bin,03_rodata.bin,04_data.bin}` via `tools/rpx_extract.py`.
**Base-game addresses (`0x02cbb0d4`/`0x029FFB3C`/`0x1018377C`) are NOT valid for v208 —
use `BotW_v208` project from now on.**

---

### V2 RE — option 4 (EventFlow) PROVEN on v208; "give item" is a context-blackboard flow, not one callable function

Re-checked the earlier "EventFlow action names absent" conclusion against the **correct**
v208 `tmp/rpx_v208/03_rodata.bin` — it was a wrong-binary artifact. v208 DOES contain
the EventFlow VM metadata and a contiguous block of **Demo event-actor action names** at
rodata `0x1EB0E4`–`0x1EB3EC` (vaddr `0x101EB0E4`+), including the prize
**`Demo_SetItemDataToPouch`** (`0x101EB1B0`), `Demo_CheckAndCreateEquip`,
`Demo_AdvanceQuest`, plus `Demo_TipsDisplayOK/NG`/`Demo_FlagOn` (popup/flag actions, in a
separate reflection-metadata region near `0x10215A14`).

**Action-name resolver found** — `FUN_02e4fcfc` (v208) walks flowchart action nodes
(12-byte structs `{handler_ptr, _, name_ptr}`) and patches in handler pointers by
string-matching the node name against a small table:
`Demo_TipsDisplayOK→LAB_02e52e08`, `Demo_TipsDisplayNG→LAB_02e52eb4`,
`Demo_FlagOn→FUN_02e52fa0`, default→`LAB_02e52d70`. This is the dispatch mechanism that
the (wrong-binary) string/symbol searches could never find.

**`Demo_SetItemDataToPouch` handler traced** — its name string is loaded by `lis r4,0x101F
/ addi r4,r4,-0x4E50` at `0x02DC2E0C`/`0x02DC2E14` (found with a hand-rolled PPC lis/addi
decoder in Python; capstone NOT installed in this env, only the `ghidra`-side disassembler
+ manual decode). Containing handler = `FUN_02dc2e04` (Ghidra left it undefined; force-
created via `createFunction`). It compares the node name vs `Demo_SetItemDataToPouch` /
`Demo_CheckAndCreateEquip` (both via comparator `FUN_02dc3b30`), and on match calls
`FUN_0249cd98(lookedUpData, ctx)`.

**Architectural boundary (decisive)**: `FUN_0249cd98` does NOT add an item. It reads two
values from the looked-up struct and calls `FUN_030ec67c(ctx, value, key, -1)` twice —
i.e. it **stores item data (type + value) into the EventFlow context/blackboard by key**
(`FUN_02de16dc`/`FUN_02de16e8` return the two keys). The real pouch insertion + "got item"
popup happen LATER in the GetDemo flowchart, which reads those context keys. **So there is
no single clean `giveItem(name,count)+popup` function reachable via EventFlow dispatch —
the give-item+popup is a multi-node, context-passing flow.** Helper `FUN_03394870(x,
0x9dc91bb3)` seen in the handler is a generic `getProc/getSubsystem`-by-type-hash accessor
(200+ callers), not item-specific.

**Scripts (v208)**: `D:\Tools\GhidraScripts\{ProgramInfo,FindDemoActions,ProbeEventFlow,
DecompileAt}.java`. `DecompileAt.java` takes `<outfile> <addr...>`, force-creates a
function if Ghidra left the address undefined. Outputs in `tmp/decompile_*.txt`,
`tmp/demo_actions_xrefs.txt`, `tmp/probe_eventflow.txt`.

**Refined V2 conclusion**: live item-*quantity* injection already works (see
`project_live_memory_injection` — TODO-5 solved); the genuine remaining gaps are
(a) **new-item insertion** (linked-list add — `PauseMenuDataMgr::createPorchItem`) and
(b) the **native "got item" popup**. The clean next target is `createPorchItem` itself
(directly callable from a code cave, and the exact "list-add function" the live-injection
note flagged as the missing lead) — NOT the EventFlow blackboard path. Popup is a separate
GetDemo-trigger sub-task. Hooking remains the FPS++-style per-frame codecave + mailbox.

---

### V2 RE — PouchItem live list structure REVERSE-ENGINEERED + createPorchItem cluster located

Used the verified calibration to dump live PouchItem nodes from Cemu
(`tools/dump_pouch_node.py`, read-only, annotates each 4-byte big-endian word + flags
guest pointers that resolve into the inventory array). **The same `cemu_mem_base`
(`0x247E4440000`) maps the heap too** (guest `0x6F16xxxx` app-heap → host verified), so
any node's internal guest pointers convert cleanly. Cemu stores guest memory big-endian.

**PouchItem node = 0x220 (544) bytes, contiguous array at `inv_base`, stride 0x220.**
Per-node layout (offsets within the node):
- `+0x000`: inner vtable `0x1021B524` (sead `FixedSafeString<64>`; its vtable slot +0x1c =
  `FUN_030b0fbc`, the string-init seen in EventFlow code), `+0x004` = `0x40` (buf size 64),
  `+0x008` = 64-byte item-name buffer (the AOB `10 ?? ?? ?? 00 00 00 40` matches here).
- 6 inner sead structures with vtable `0x1021B524` at `+0x00,+0x74,+0xC0,+0x10C,+0x158,
  +0x1A4` (stride 0x4C); each holds self-referential pointers = **empty sead lists**
  (modifier/effect slots).
- `+0x054`: `0xBF800000` (= -1.0f, a default modifier/value field).
- `+0x200`: **PouchItem class vtable `0x1021B5D4`**; `+0x204` = **list NEXT**, `+0x208` =
  **list PREV** (intrusive circular doubly-linked list; links point at sibling nodes'
  `+0x204`). `+0x21C` = pointer into the next node's `+0x08` (a second/secondary list).

**Category list root (sentinel)** sits just BEFORE the array: at `inv_base-0x20` =
vtable `0x1021B5D4`, `inv-0x1C` = next → slot0`+0x204`, `inv-0x18` = prev (tail);
`inv-0x08` = `0x00010000` (count/flags); `inv-0x14/-0x10` = `0xFFFFFFFF`. So slot0's PREV
(`+0x208`) loops back to `inv-0x1C` — confirms the circular list with an external root.

**createPorchItem cluster**: the only code that references the PouchItem vtable
`0x1021B5D4` lives in the **`0x02ea`–`0x02ec` PauseMenuDataMgr/PorchItem cluster**
(`FUN_02eae294`, `FUN_02eadaac`, `FUN_02ead6cc`, `FUN_02eb5ea0`, `FUN_02ec2424`).
`FUN_02eae294(this)` is construction code — a chain of `FUN_0308e578(0x4c/0xc/8/0x1a4/…)`
sead-heap allocations building the sub-objects. Scripts:
`D:\Tools\GhidraScripts\FindVtableRefs.java` → `tmp/vtable_refs.txt`;
`tmp/decompile_pouch_ctor.txt`. (Note: these "vtables" are sparse — mix of function
pointers and small-int data slots — normal for sead.)

**Two concrete V2 paths now** (decision pending with user):
- **(A) Pure-Python insertion** (no RPX mod, no code cave): copy an existing populated
  0x220 node into a free slot as a template, patch name(+8)+value, re-base its 6 inner
  self-referential list pointers to the new node address, then splice into the category
  list (set new `+0x204/+0x208`, fix neighbours, bump count at `inv-0x08`). The V1 overlay
  already covers the popup. Risk: intricate, must be tested live carefully (bad splice can
  crash Cemu). Strong template available from the dump.
- **(B) Code-cave calls the native add fn**: finish pinning `createPorchItem`/`addItem`
  in the `0x02ea` cluster (signature `(this, name, value, …)`), ship an FPS++-style
  per-frame codecave reading a mailbox that calls it. Native construction (and possibly
  the popup) for free; more toolchain (PPC asm codecave) + more RE to confirm the fn.

`tools/dump_pouch_node.py` outputs at `tmp/dump_pouch_out2.txt`. Inventory base + heap
guest addresses are **session-specific** (rescanned each `attach()`); the vtable consts
(`0x1021B5D4`, `0x1021B524`) and node offsets are stable for v208.

---

### V2 — RESOLVED: live NEW-ITEM insertion WORKS in pure Python (validated in-game 2026-06-13)

`tools/live_insert_item.py` added a brand-new clean apple to a running game (correct
icon/name/description, x1, inventory intact, NO freeze, survives the inventory re-sort) —
**no save reload, no RPX mod, no code cave, no native call**. This closes the
long-standing "new-item live injection unsolved" gap.

**Per-node header (decoded, confirmed vs live items)**: name `FixedSafeString<64>` @+0x08;
`+0x20C`=PouchItemType (0=Sword,1=Bow,2=Arrow/Shield,3..6=Armor,7=Material,8=Food,
9=KeyItem); `+0x210`=sub/use (8=plain ingredient, 0xA=cooked dish — cooked uses a
recipe-derived icon that ignores the name); `+0x214`=value/qty; `+0x218`=flags;
list links `+0x204`(next)/`+0x208`(prev) primary, `+0x21C`(→next.+0x08) secondary.

**Working recipe** (see `BotWClient`/memory note for full steps): derive session
`cemu_mem_base` from array/list adjacency (changes per reload — never hardcode); clone a
same-type INGREDIENT template (self-ref inner lists; not a cooked dish); copy its 0x220
into a free node (type==0xFFFFFFFF) and re-base inner self-pointers; set name + value;
splice into BOTH primary AND secondary lists (primary-only splice FROZE Cemu — the
secondary `+0x21C` splice was the fix). No item-count write needed. Free-list unlink of the
reused node was skipped (worked for display; do it in production to be fully safe).
`--restore` recovered a frozen Cemu without restart.

**Verdict: approach A (pure-Python live insertion) is the V2 item-delivery mechanism.**
Combined with the existing V1 overlay (the "item received" popup), V2 needs NO RPX
modification. Approach B (native `createPorchItem` call via code cave) is now unnecessary
for delivery — keep the `0x02ea` cluster notes as reference only.

**NEXT (productionization into `BotWClient`)**: map each AP item → (PouchItemType,
+0x210, template selection by type); add free-list unlink; handle the
no-same-type-template-present fallback (e.g. keep a clean free node as a universal
template, or set all fields on a bare free node); wire into `_apply_actions_memory` in
`BotWClient/providers/save_file.py` alongside the existing `live_add_item_qty`.

---

### V2 stretch goal — RPX code hooking (started, needs Ghidra)

User opted to pursue the RPX-hooking stretch goal (precedent: Cemu's **FPS++** graphic
pack hooks a per-frame instruction at `0x031FA97C` via `patch_*.asm` code caves —
confirmed viable approach, see [Cemu Wiki](https://wiki.cemu.info/wiki/Cemu_patches),
[BOTW-ModdingGuide/CemuCodecaves](https://github.com/Torphedo/BOTW-ModdingGuide/blob/main/CemuCodecaves.md)).

**`tools/rpx_extract.py`** (NEW): decompresses RPX/RPL zlib sections (format: ELF32 BE,
`e_type=0xFE01`, sections with `SHF_RPL_ZLIB=0x08000000` have a u32be decompressed-size
header + zlib stream). Run against
`<dump>/code/U-King.rpx` (22MB file, BotW WiiU 1.5.0) to get raw `.text` (~35MB) /
`.rodata` (~4MB) / etc.

**String/hash search — inconclusive**: action/query names used by EventFlow
(`Demo_IncreasePorchItem`, `GetManyItemsByName`, `ShowGetDemoDialogByName`,
`Demo_SetGetFlagByActorName`, `Demo_TipsDisplayOK`) are **not present as literal strings**
in `.text`/`.rodata`, and their CRC32 (the `game_data.sav` flag-hash recipe) doesn't
match any 4-byte value found either (only `CheckFlag`'s hash had one BE hit, likely
coincidental — not verified). EventFlow action/query dispatch evidently uses a different
resolution mechanism than the save-flag hash recipe. **Don't re-try string/hash grepping
for these names — closed.**

**Conclusion**: finding the target "give item + show popup" function requires real
static analysis (Ghidra with an RPL/Cafe-PPC loader), not string search. This is a
genuine multi-session RE project. `tools/rpx_extract.py` is ready to feed `.text`/`.rodata`
dumps into Ghidra once that's set up.

**AP item icon**: user is providing a generic Archipelago icon at `img/ap.png` (project
root) for future use in custom item popups — relevant once V2 (any flavor) gets to the
"custom item display" stage.

#### Ghidra setup DONE — static analysis underway (checkpoint)

**Tooling confirmed working** (outside the project repo, at `D:\Tools\Ghidra\`):
- Ghidra 12.1.2 PUBLIC + `Maschell/GhidraRPXLoader` v0.9.2 (Gekko/Broadway/Espresso PPC
  sleigh language, compiled via `support/sleigh.bat`).
- Headless import of `U-King.rpx` (BotW WiiU 1.5.0, 22MB) via loader class **`CafeLoader`**
  (NOT `RPXLoader` — that name doesn't exist; found via `jar tf GhidraRPXLoader.jar`).
- Full headless auto-analysis (`-import ... -loader CafeLoader`) succeeded in ~18.5 min
  (1112s). Project at `D:\Tools\GhidraProjects\BotW.gpr`.
- **Ghidra 12 has no Jython** — post-analysis scripts must be Java `GhidraScript`
  subclasses (`.java` files), run via `-process U-King.rpx -noanalysis -scriptPath
  <dir> -postScript <Script>.java`. Scripts created at `D:\Tools\GhidraScripts\`:
  - `FindPorchItemXrefs.java` — finds all defined strings containing
    `Porch`/`IsGet`/`CheckFlag`/`GameData` and lists their xrefs + containing functions
    (1458 hits, written to `tmp/porchitem_xrefs.txt`).
  - `DecompileCandidates.java`, `DecompileFlagFunc.java`, `FuncInfo.java` — decompile /
    inspect specific candidate functions.

**Candidates examined**:
- `FUN_023acecc` @ `0x023acecc` — references `PorchItemName_Weapon/Shield/Bow/ArmorHead/
  ArmorUpper/ArmorLower/Arrow` etc. Decompiled fully: this is **save-file load logic**
  (reads equipped-item params like `UnequipWeapon`/`UnequipShield`/... from a save param
  object). **Ruled out** — not the item-grant function.
- `FUN_02cbb0d4` @ `0x02cbb0d4` — directly references the `IsGet_AncientArrow` string
  (the exact flag live-tested earlier). **Too large to decompile** (162,448 bytes ≈
  ~40,600 instructions, decompile times out even at 240s). Disassembly shows a repeating
  pattern: load a `.rodata` string address near `IsGet_AncientArrow` (0x101dXXXX) + a
  `.text` function-pointer constant (0x1023XXXX), call a registration helper
  (`bl 0x02f3ed08` / `bl 0x0309173c`). This is almost certainly the **GameData parameter
  registration table** — a giant startup function registering every `IsGet_*`/`Clear_*`/
  etc. flag name + accessor into a global lookup table. Each flag is one entry among
  thousands; **not itself the "set flag + show popup" function**. Only caller:
  `thunk_FUN_02cbb0d4 @ 0x02ce2b64`.

**Next steps (not started)**:
1. Don't decompile `FUN_02cbb0d4` further — it's a registration table, not actionable.
2. Two possible directions for next session:
   - (a) Trace `thunk_FUN_02cbb0d4`'s caller chain upward to find where/when GameData
     registration happens, which may lead to the EventFlow action-dispatch table
     (mapping `Demo_IncreasePorchItem` etc. to native functions) — likely a similar
     "registration table" pattern elsewhere in `.text`.
   - (b) Pivot to finding a **per-frame update function** first (FPS++-style hook
     point), independent of the item-grant function — i.e. find where to inject the
     code cave, then come back to (a) for what to call from it.
3. `D:\Tools\GhidraProjects\BotW.gpr` is fully analyzed and ready for the GUI (not just
   headless) — opening it in the Ghidra UI may be much faster for manual exploration
   than further headless scripting.

---

## 6b. §gdt-live — vrai portefeuille, storage s32 live, piste bools (2026-07-10/11)

**Contexte** : la chasse au portefeuille (`tools/hunt_wallet.py`, change-detection 10219→3
candidats, preuve par achat : write 55555 → achat −60 → écran 55495) puis la session recon
du 2026-07-11 ont révélé la topologie **gdt LIVE** complète des flags s32. Le jeu tient
**TROIS copies** de `CurrentRupee` (les 3 candidats du narrow, deltas identiques entre
sessions car allocations Cemu déterministes) :

1. **save-buffer** (`gd_base`) : paire `{hash u32be, value u32be}` triée — sérialisation.
2. **objet `gdt::Flag<s32>`** (vtable guest `0x102984C8`) : layout
   `{vtable, 0x0107, min=0, initial=0, max (999999), value @+0x14, hash @+0x18}`.
   L'AOB `_RUPEE_PATTERN` (vtable + 0107 + zéros + max 999999) matche CET objet →
   l'« adresse rubis » historique = son champ value (miroir HUD, resynchronisé).
3. **storage s32 live** — LA copie autoritaire (le jeu débite ICI) : array de ~2792
   entrées de 12 o `{typeinfo guest 0x10297C88, ptr guest → flagobj, value}`.
   ⚠️ cadrage : la value du flag est le 3e champ de l'entrée qui RÉFÉRENCE son flagobj
   (backref+4), pas le 1er mot lu à côté (piège du premier parse).

**Localisateur STABLE (implémenté `memory_injector._find_wallet`)** : flagobj candidat =
`_rupees_addr − 0x14` (validé vtable + hash `crc32("CurrentRupee")=0x23149BF8`, fallback
scan du hash) → guest = host − heap_base (base dérivée des nœuds pouch, FIXE pour la vie
du process) → scan backref du guest, entrée validée par typeinfo → value = backref+4.
Re-validation structurelle 3-lectures avant chaque write (`_wallet_valid`) → adresse
périmée impossible par construction. Écriture = storage + flagobj (HUD). Validé sur Cemu
relancé : ±1 rubis cohérent sur les 2 copies. Coût : +~40 s à l'attach (scan backref
one-shot, thread lourd) — optimisable en restreignant le scan à la région du heap.

**BOOLS live — STRUCTURE CONFIRMÉE + WRITE PERSISTANT (2026-07-11, recon4→6)** : le hash
d'un bool (`IsGet_Obj_Magnetglove` 0x795E7BBC) sort à 4 endroits + le storage :
1. save-buffer (paires hash/value) ; 2. table de lookup `{hash, index u32, offset u32, 0}`
stride 16 triée par hash (mapping hash→index) ; 3. **table des objets bool**, stride 16 :
`{hash @+0, 0 @+4, vtable guest 0x10298410 @+8, meta @+C}` — meta = `{cat u16, value u8,
x u8}` (Magnetglove `000F0101`→1, RemoteBomb `000F0100`→1, Takano `000C0000`→0) ;
4. table reset `{hash, 0x80000000, 0, 0x12}` ; et surtout :
5. **STORAGE bool live** (l'équivalent exact du storage s32 du wallet) : entrées 12 o
`{typeinfo guest 0x10297BD0, ptr → SOUS-OBJET {vt,meta} à hash+8, value u8<<24}`.
⚠️ Pièges de cadrage résolus : le dump périodique est ambigu ({hash,0,vt,meta} vs
{vt,meta,hash,0}) — le backref du storage tranche : il pointe hash+8 (le sous-objet) ;
et la value storage est le PREMIER octet (u8 de poids fort en BE).
Localisateur : hash → table bool (vérif vt@+8 & pad@+4==0) → backref guest(hash+8)
(vérif typeinfo) → value = backref+4. **Write-test validé** (Takano_Finish, flag inerte) :
storage 0→1 persiste (22 s, pas réécrit), miroir meta+2 aligné, restauré à 0.
**VERDICT IN-GAME (2026-07-12, test mur Ganon + saves manuelles)** :
(a) **PAS de sérialisation** : write storage+meta puis 3 saves manuelles → `.sav` resté à 0.
Le jeu ne resérialise que ses flags marqués « dirty » par son API interne (setBool) ; un
write mémoire brut ne marque rien → jamais repris au save. (b) **PAS de lecture live par
la couche map** : storage+meta à 1 → le mur TP quand même (cohérent avec le test mailbox
du 07-10). CONCLUSION : le storage bool reste utile en LECTURE (état runtime réel) et
peut-être pour les queries EventFlow, mais la voie de LIVRAISON des flags reste
**gd_base/fichier + reload** (gd_base RAM est flushé INTÉGRALEMENT au fichier lors d'un
save → nos octets y survivent, contrairement au storage). Corollaire s32/RUBIS : un
crédit AP écrit au seul storage n'est sérialisé QUE si le joueur fait ensuite une
transaction (le jeu setInt → dirty) → `live_add_rupees` écrit désormais AUSSI l'entrée
gd_base (ceinture + bretelles).

**CookData (PouchItem type 8)** : offsets nœud host-cadré `+0x68 heal (¼-cœurs),
+0x6C durée (s), +0x70 prix, +0x74 effect_type (f32 CookEffectId, −1.0 = aucun),
+0x78 effect_level (f32)`. Câblé : `InjectionSpec.AddCookedItem` → `live_create_item(...,
cook_data=...)` (live-only, préfère un template sub=0xA, ne stack jamais). Validé live :
Mushroom Skewer (heal 16) + Spicy Elixir (fx 5.0 lvl 1 600 s) créés et relus conformes.
Énum CookEffectId (decomp uking) à confirmer à l'écran au premier élixir goûté.

---

## 6c. §toast-natif — architecture du toast « item reçu » RE (session 2026-07-11, décomp v208 + live)

**Méthode** : xrefs statiques depuis les strings rodata (`find_str_refs`, décodeur lis/addi
numpy) + DecompileAt Ghidra headless + lecture live des singletons (heap_base **mappe TOUT
l'espace guest**, .data/.bss inclus : host = heap_base + guest, y compris `DAT_10xxxxxx` —
lire les globals statiques ne coûte AUCUN scan). Scripts session (scratchpad, jetables) :
`toast_recon.py` (handles/stockitem/base/backrefs/scanvals/dump/watch), `scan_screens.py`,
`find_str_refs.py`/`find_vtable_refs.py`/`find_ptrs.py` (offline sur tmp/rpx_v208).

**Chaîne du toast reconstituée** :
1. **Source nom** : singleton contexte `ctx = *(0x1047B054)` (~115 lecteurs, alloué heap ;
   vtable 0x102F7A08). `ctx+0x20` = SafeString nom d'actor : layout WiiU **{mStringTop
   @+0x20 → ctx+0x2C, vtable 0x102F78E0 @+0x24, bufsize 0x40 @+0x28, buffer inline @+0x2C}**.
   VIDÉE après consommation (lue vide en idle). NB : le « slot pickup vt 0x1024BDA8 » de
   toast_watch est un AUTRE miroir (l'acteur monde), pas cette source.
2. **Source item** : `PauseMenuDataMgr+0x37cec` = tête de mLastAddedItems ;
   `getLastAddedItem = FUN_02eb6d00` (skippe `Weapon_Sword_070`, exige mInInventory=1).
   Le refresh **tolère item absent** (fallback nom seul via `FUN_02eae914(name,0)` +
   `FUN_03084370`) mais FERME si l'item existe et mInInventory==0.
3. **Écran toast** = « MessageGet_00Screen », **créé à la demande puis détruit** (absent du
   registre hors affichage — vérifié live). Registre écrans : `reg = *(0x1047E650)`,
   `reg+0x14` = count (99), `reg+0x18` = array de ptrs (id → screen). Écran très
   probablement **id 0x24** (2 événements UI l'ouvrent, cf. 5). Layout écran : vtable
   classe @ `screen+0xC` (base commune @+0xC=0x10260ED4 pour l'interface interne) ; état
   FSM @+0x96 ; champs toast : +0x1b68 byte «open request», +0x1b6c/+0x1b70 msg-handles,
   +0x1b74..+0x1b84 panes/anims, +0x1b88 «wait-anim lancée», +0x1b89 «textes posés»,
   +0x1b8c handle texte MSBT async, +0x1b90..98 = 2 panes texte (flag visible @pane+0x44
   bit0), refresh lit aussi type/dye de l'item. Slots vtable : +0x14 getAs(key),
   **+0x2C trigger/replay**, +0x34 close(code).
4. **Refresh** = `FUN_02fd0ce4` (vtable rodata, ptr @ 0x102455AC) : early-close si nom ctx
   vide ; construit `UI/StockItem/<actor>.bitemico` (`FUN_03084370` générique — gère
   Weapon_Sword_502→503 Master Sword éveillée + suffixe teinture `.%02d` ;
   `FUN_03084b64` = variante ActorInfo, clés hash 0x216a3a63/0xefb9041d non résolues) ;
   pose le texte via le système de messages (`FUN_037e63a4`) ; anime les panes. Strings
   pivot rodata : `UI/StockItem/%s` @0x1025DE90 (3 sites .text), `%s.bitemico` @0x1025DEEC.
5. **CHEMIN DE L'ÉVÉNEMENT PICKUP tracé de bout en bout** (le vrai canal du bandeau) :
   `FUN_0236f994` (traite l'acteur ramassé) → `FUN_03076e94(actor, doShow)` qui fait
   DEUX choses : (a) `FUN_02eb7a70(mgr, actor)` = **ajoute à mLastAddedItems** [DÉJÀ fait
   par notre injection pouch] ; (b) si doShow : `FUN_030731ec(0xB)` → `FUN_03073184(0xB,
   &str)` → `FUN_02fbcaf8(HUD)` **= `FUN_02ed1f7c(reqMgr=*(HUD+0x1B84), 0xB, &str)`**
   [ENQUEUE] + `FUN_03058b44(uiroot, 0)` = `uiroot+0x4075C |= 1<<0` [bit « HUD dirty »].
   → **IL Y A BIEN UNE FILE DE DONNÉES drainée par la boucle UI** = piste 2 confirmée.
6. **LA FILE (structure EXACTE, décomp 2026-07-12)** : `HUD MainScreen` = **registre
   écran id 0x25** (`reg = *(0x1047E650)`, `HUD = *(*(reg+0x18) + 0x25*4)`, vtable
   0x102433D4). Son **request manager** `reqMgr = *(HUD+0x1B84)` : critsec @+0x110
   (le jeu locke l'enqueue) ; **sentinel ListNode {next @+0x14C = head, prev @+0x150 =
   tail}** (liste circulaire ; self-référent = vide — les DEUX mots = reqMgr+0x14C) ;
   count @+0x154 ; **freelist head @+0x158** (pop : `node=*0x158 ; *0x158=*node` — le
   1er mot du nœud libre = chaînage) ; capacité @+0x160 (=3, lu live). **Nœud = 0x54
   octets de données + ListNode 8 o** : {type @+0x00 (0xB=toast), mStringTop @+0x04
   → node+0x10, vtable **0x1021D0FC** @+0x08, bufsize 0x40 @+0x0C, char[64] @+0x10,
   u8 flag=0 @+0x50, **link {next @+0x54, prev @+0x58}**} — les links pointent les
   +0x54 des voisins / le sentinel (asm `FUN_0308e7e8` pushBack-front : link.prev=sent,
   link.next=old, old.prev=link, head=link ; `FUN_0308e808` = unlink standard ; sur
   liste vide `old.prev` retombe sur +0x150 → cohérent avec le self-référent lu live).
   `FUN_02ed1f7c` = enqueue complet : guard count≥cap (purge du plus ancien), DÉDUP par
   comparaison de string si non-vide, pop freelist (sinon alloc `FUN_0308e578(0x54)`),
   placement-new (chaîne de ctors SafeString→…→FixedSafeString<64>, vtable finale
   0x1021D0FC, `FUN_030b0fbc`), copie de la string, pushBack, `count++` — le tout sous
   critsec +0x110 (nous écrivons SANS lock : fenêtre de course ~µs vs frame 33 ms,
   accepté ; publication head/count en dernier). En amont `FUN_03073184` : guard
   `FUN_03089a30()==0`, HUD «actif» (vtable(+0xC)+0x14), puis enqueue + **bit dirty
   `*(uiroot+0x4075C) |= 1<<0` avec uiroot = *(0x1046BDD8)** (`FUN_03058b44`). La
   string par défaut du pickup = SafeString **DAT_10549FEC (.bss** — pas de contenu
   statique dans le RPX, à lire LIVE ; probablement vide). **Les handlers du type 0xB**
   (`FUN_0207ec78`/`FUN_020800b0`, appelés par table de ptrs — callers vides) ouvrent
   l'écran par ID : `FUN_03080a14(0x24,0)` + re-lookup + trigger `vt+0x2C(screen,1)`,
   **sans lire la string du nœud** → le routage est par TYPE ; la string semble
   accessoire pour 0xB. Au repos la file est VIDE. Outils : `tools/toast_queue_watch.py`
   (v2 2026-07-12 : busy-loop ~kHz — la v1 à 30 Hz a raté la transition, capture #1
   vide — + **post-mortem freelist** : les nœuds recyclés gardent la string résiduelle
   du dernier toast → layout confirmable sans attraper la transition) et
   `tools/toast_push_test.py` (write-test : reproduit l'enqueue à l'identique, backup
   par patch, post-check consommé/inchangé/autre, restore intelligent qui ne réécrit
   que nos valeurs).
7. **Ouverture finale** : `FUN_03080a14(id) → FUN_03058e84` (tables d'exclusion mutuelle
   `DAT_105481e0/e4` stride 12 = pré-décodées : id, prio, flag, arg — MessageGet est
   l'entrée id 0x24 prio 0) `→ FUN_030806f0` = **factory native par nom**
   (`thunk_FUN_030a857c` = `new Screen(name)` + alloc sead) + enregistrement + trigger
   (`screen.vtable+0x2C`). La factory elle-même = **appel natif irréductible** (comme
   GetDemo), MAIS on ne l'appelle PAS : on pousse dans la file (6) et la boucle UI l'appelle.

**VERDICT (voie pur-mémoire OUVERTE, pas fermée) :** contrairement au popup GetDemo (qui
n'était atteignable que par un appel natif → mur du recompilateur), le toast de ramassage
a un **canal de données** — la file du HUD reqMgr — que la boucle UI draine seule. Pousser
`{type 0xB, nom d'écran}` dans cette file + peupler le nom d'actor dans le contexte
`*(0x1047B054)+0x2C` déclencherait le bandeau SANS aucun appel natif de notre part. C'est
le même patron que l'insertion pouch (déjà maîtrisée) : dépiler la freelist, construire la
FixedSafeString, splicer, `count++`.

**VALIDÉ IN-GAME 2026-07-12 (boucle utilisateur, ~40 pushs) — résultats complets** :
- Le drain CONSOMME nos nœuds (recyclés freelist en <1 s) et OUVRE l'écran MessageGet à
  CHAQUE push conforme — la voie pur-mémoire fonctionne, reproductible à 100 %.
- **Le pickup naturel n'utilise PAS cette file** (capture 104 kHz pendant un ramassage
  réel : file inerte, ctx inerte, slot écran 0x24 jamais créé → le petit encart de
  ramassage est une pane du HUD, pas un écran). Les nœuds freelist étaient VIERGES depuis
  le boot. `FUN_03076e94(bool,bool)` (2 seuls callers : (0,0) silencieux et (1,1) gated
  par le TIMER DE RECHARGE de la Master Sword) → le type 0xB = « MS rechargée », pas le
  ramassage. La « signature (actor,doShow) » de la veille était fausse.
- **Cartographie COMPLÈTE des types 0x00-0x2F** (pushs in-game, tous les textes notés) :
  0-7 « compartiment X plein »/limites ; **8/9/0xA = messages À PLACEHOLDER**
  (« Votre {item} va bientôt se briser » / « s'est brisé » / « Vous avez lâché {item} ») ;
  0xB/0xC/0xD Master Sword (rechargée/s'amenuise/rassemble ses forces) ; 0xE-0x11
  cheval/compagnon (nom du cheval résolu : « Epona ») ; 0x12-0x14 « rien à exposer » ;
  0x15-0x17 « pas équipé » ; 0x18 MS pas exposable ; 0x19/0x1A amiibo ; 0x1B/0x25
  ennemis ; 0x1C/0x22/0x26 pas maintenant ; 0x1D/0x1E balises ; 0x1F/0x20 rubis/matériaux
  insuffisants ; 0x21 MS retournée en forêt ; 0x23/0x2D pas ici ; 0x24 énergie vitale ;
  0x27 obstacle ; 0x28 Link loup ; 0x29/0x2E/0x2A pas plus loin ; 0x2B charge complète ;
  0x2C destrier 0.1 ; 0x2F bandeau vide. **AUCUN « vous obtenez » natif** (les obtentions
  BotW passent par GetDemo/dialogue). NE PAS pousser de type > 0x2F (hors table dispatch).
- **Le placeholder {item} est rempli par la STRING DU NŒUD** (callers directs de
  FUN_03073184 : ils passent le nom d'arme — types 8 vs 0xC etc. choisis selon MS ou non).
  Poussé avec la string « Weapon_Sword_001 » → « Vous avez lâché Épée de voyageur. » : le
  jeu résout le nom LOCALISÉ (articles français corrects).
- **SOLUTION FINALE : type 0xA + REDIRECTION MSBT en RAM (phrase custom + QUANTITÉ).**
  Le bloc TXT2 du MSBT (header « MsgStdBn » retrouvé en amont de la string, table
  d'offsets u32be) référence chaque message par OFFSET. Les entrées [257]-[262] sont des
  **placeholders de dev jamais affichés** (« TESHEIKAHSLATE… », ~0xC6 octets). On écrit
  « **Vous avez reçu {tag item} xN.** » dans la zone [257] (tag item {2,0x0B}+UiInfoString
  copié byte-exact ; le tag article {201,1} OMIS → nom nu « flèche en bois », pas
  « la flèche ») et on redirige l'offset de l'entrée toast dessus. La QUANTITÉ (« xN »,
  masquée si N≤1) est réécrite au suffixe avant chaque bandeau (budget large, NUL-padded).
  VALIDÉ in-game : « Vous avez reçu flèche en bois x5 », « Vous avez reçu pomme x5 ».
  La string originale reste INTACTE (localisateur par scan toujours valide). Outils :
  `tools/toast_msbt_redirect.py` (--install/--qty/--restore/--status, backup JSON) ;
  `tools/toast_msbt_patch.py` (patch-mot « gagné », 1re itération — OBSOLÈTE, gardé
  pour référence). Un patch-mot résiduel en RAM est inoffensif (string plus référencée).

**IMPLÉMENTÉ (BotWClient)** : `CemuMemoryBridge.push_toast(actor, qty)` +
`toast_enqueue(actor, qty)` (deque maxlen 20) + `toast_pump()` (1 bandeau max/cycle,
throttle 4 s) dans `memory_injector.py` ; préparation (dérivation heap_base si absente +
localisation MSBT + REDIRECTION) sur THREAD DAEMON au 1er toast ; revalidation avant
chaque bandeau (offset d'entrée + préfixe de la zone — MSBT rechargeable par le jeu →
re-préparation auto) ; sanity stricte avant chaque push (file vide, freelist plausible,
cap==3) → best-effort intégral, ne bloque JAMAIS une livraison. Câblage :
`_apply_actions_memory` → toast_enqueue((actor, qty)) (pouch/plats : item_name+amount ;
SetFlag `IsGet_<actor>` → actor, qty 1 — convention BotW) ; `flush()` → toast_pump.
Langue ≠ FR : motif introuvable → texte vanilla ; prévoir des motifs par langue si
demande. RESTE : validation end-to-end en session AP réelle.

**Dispatcher priorité** (slot vtable+8, `FUN_02fd1534`) : les écrans guides/tips
0x1a/0x19/0x49 passent avant (`FUN_03074fc0/af8`, `FUN_030756b4(0..3)` → `FUN_030751f0(n)`
→ `FUN_02f8f608(screen49, n)`). L'écran 0x49 (guides) : état @+0x1b90 (2=open), type
courant @+0x1bbc, show direct = `FUN_02f8f3f0`. (Non bloquant pour le toast.)

**Correction structurelle POUCH (importante, hors toast)** : le layout SafeString WiiU est
`{mStringTop, vtable, [size], buf}` → dans le nœud PouchItem le nom est un
FixedSafeString<64> à S+0x1C : {top @S+0x1C → S+0x28, vt 0x1021B524 @S+0x20, 0x40 @S+0x24,
buf @S+0x28}. **La « liste secondaire +0x21C » des notes précédentes N'EXISTE PAS** :
c'était le mStringTop du nœud SUIVANT (cadrage décalé de 0x20). Le « splice secondaire »
de live_create_item réécrit en réalité un mStringTop — à réauditer (il marche parce qu'il
re-pointe le buffer du même cadre, mais le code mérite un nettoyage V1.1).

**NB outillage** : la base .text du RPX v208 est **0x02000020** (pas 0x02000000 — décalage
0x20 corrigé dans `tools/disasm_func.py` et les scripts `rpx_find_*`) ; la base .data est
**0x10462BC0**. Le mapping guest→host de `toast_recon` couvre TOUT l'espace guest (les
singletons `DAT_10xxxxxx` se lisent en direct via `g:0x...`).

---

## 7. MelonSpeedruns rando — can we reuse / modify it?

**What it is:** a **static** randomizer (.NET app) that generates a Cemu **graphic pack**, shuffling items by editing romfs. Self-contained, single-game, **no server/AP hooks**. Relevant gating it already implements: paraglider placed in a random Great Plateau chest, Master Sword required to enter Ganon (⇒ 13 hearts), shrines no longer grant Spirit Orbs.

**Can we bolt AP onto it?** No. It's not AP-aware and has no concept of a server, remote items, or live item delivery. You cannot merge our connector client into its static-shuffle pipeline.

**What IS reusable:** its **romfs-editing techniques** are a valuable reference if/when you build the v2 mod (§6) — specifically *how* it removes the vanilla paraglider grant, gates Ganon, and strips Spirit Orbs. Study those edits as a blueprint, but:
- **Check its license** before reusing any code or data.
- **Do not redistribute** its files with your project.

**Realistic stance:** our project stays the AP connector. If you want hard enforcement, write your **own minimal romfs patch** for the few gates you need (paraglider grant removal is the high-value one), informed by how Melon does it — not by forking the whole rando.

---

## 8. CONSTRAINTS

- Save/flag work depends on **BotW 1.5.0** (game version), independent of Cemu version. Live memory (`memory_bridge`) depends on **Cemu 2.x** and is Windows-only.
- **CRC32 recipe is locked** — don't reinvent it.
- **Never retain runes** — they're needed to clear the plateau shrines (which are checks).
- **Outgoing items need no injection** — only report checks.
- **Don't commit** personal paths, `*.sav`, or game-derived files you don't intend to ship; don't redistribute third-party mod files.

## 9. OPEN QUESTIONS

- `require_shrine_count` for the goal — pick a default (e.g. 20) and expose as an apworld option.
- Should champion abilities & Master Sword be retained (AP items) or left vanilla + goal-checked? Current `gate_items.json` marks them `ap_progression` (retained) for a meaningful multiworld; confirm the design intent.
- Region grouping source for TODO-7 (objmap export vs manual).
