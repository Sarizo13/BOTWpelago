[BOTWpelago_HookTest_V208]
moduleMatches = 0x6267BFD0

.origin = codecave

_msg:
.string "BOTWPELAGO_FRAME %d\n"
.align 4
_counter:
.int 0

; hook par-frame (swap GX2) : incremente _counter, OSReport tous les 128 frames.
; remplace 'mr r31, r3' @0x031FA9CC. Preserve r0 (LR du jeu) / r3 / r4 / r11 / r12.
frameCounterHook:
stwu r1, -0x20(r1)
stw r0, 0x1c(r1)
mflr r0
stw r0, 0x18(r1)
stw r3, 0x14(r1)
stw r4, 0x10(r1)
stw r11, 0xc(r1)
stw r12, 0x8(r1)
lis r11, _counter@ha
lwz r12, _counter@l(r11)
addi r12, r12, 1
stw r12, _counter@l(r11)
andi. r11, r12, 0x7F
bne _skip
lis r3, _msg@ha
addi r3, r3, _msg@l
mr r4, r12
bl import.coreinit.OSReport
_skip:
lwz r0, 0x18(r1)
mtlr r0
lwz r0, 0x1c(r1)
lwz r3, 0x14(r1)
lwz r4, 0x10(r1)
lwz r11, 0xc(r1)
lwz r12, 0x8(r1)
addi r1, r1, 0x20
mr r31, r3
blr

0x031FA9CC = bla frameCounterHook
