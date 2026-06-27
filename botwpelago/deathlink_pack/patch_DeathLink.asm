[BOTWpelago_DeathLink_V208]
moduleMatches = 0x6267BFD0

# DeathLink codecave for BOTWpelago / Archipelago.
# Player life object is a stable global pointer at *(0x10463F38); the HP is a float
# at lifeObj+0x64 (read by getLife @ 0x02D49974). We hook the heart-UI update
# (0x02D9D31C = 'mr r31, r3', the function @ 0x02D9D310 that itself loads *(0x10463F38))
# which runs on the game thread, no allocation -> safe. Each call:
#   - KILL    : if _kill != 0  -> write 0.0 to HP (Link dies), clear _kill.
#   - DETECT  : if HP == 0      -> set _died = 1 (the client reads it -> Bounce).
# The client locates this cave by the magic string and reads/writes _died (+16) /
# _kill (+20). Contract must match BotWClient/memory_injector.py.

.origin = codecave

_magic:
.string "BOTWPELAGODLINK"
.align 4
_died:
.int 0
_kill:
.int 0
_tick:
.int 0

dlHook:
stwu r1, -0x20(r1)
stw r11, 0x10(r1)
stw r12, 0x14(r1)
stw r0, 0x18(r1)

# heartbeat: _tick++ each time the hook runs (diagnostic)
lis r11, _tick@ha
lwz r0, _tick@l(r11)
addi r0, r0, 1
stw r0, _tick@l(r11)

# r12 = player life object = *(0x10463F38)
lis r11, 0x1046
lwz r12, 0x3F38(r11)
cmpwi r12, 0
beq _dl_skip

# --- KILL: if _kill != 0 -> HP = 0.0, clear _kill ---
lis r11, _kill@ha
lwz r0, _kill@l(r11)
cmpwi r0, 0
beq _dl_detect
li r0, 0
stw r0, 0x64(r12)
lis r11, _kill@ha
li r0, 0
stw r0, _kill@l(r11)

_dl_detect:
# --- DETECT: HP float bits == 0 -> _died = 1 ---
lwz r0, 0x64(r12)
cmpwi r0, 0
bne _dl_skip
lis r11, _died@ha
li r0, 1
stw r0, _died@l(r11)

_dl_skip:
lwz r0, 0x18(r1)
lwz r12, 0x14(r1)
lwz r11, 0x10(r1)
addi r1, r1, 0x20
# original instruction replaced by the hook:
mr r31, r3
blr

# WIP — both hook points tried (0x031FA9CC swap, 0x02D9D31C heart-UI) run the codecave
# only ONCE then stop/freeze: Cemu's recompiler doesn't re-run a bla-codecave hook on
# these BotW instructions (the documented wall that got the native approach shelved).
# Next direction: pure-Python DeathLink using the player life-object global 0x10463F38
# (no codecave) — needs the bridge to map guest 0x10xxxxxx (RPX .data) to a host address.
0x031FA9CC = bla dlHook
