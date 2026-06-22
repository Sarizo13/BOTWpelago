[BOTWpelago_GiveItem_V208]
moduleMatches = 0x6267BFD0

.origin = codecave

_marker:
.string "BOTWPELAGOMBX1"
.align 4
_trigger:
.int 0
_ss_cstr:
.int 0
_ss_vtab:
.int 0
_name:
.string "Item_Fruit_A"
.align 4
_msgPre:
.string "MBOXPRE vt=%08x\n"
.align 4
_msgPost:
.string "MBOXPOST ssret=%08x\n"
.align 4

frameItemHook:
stwu r1, -0x80(r1)
stw r11, 0x10(r1)
stw r12, 0x14(r1)
lis r11, _trigger@ha
lwz r12, _trigger@l(r11)
cmpwi r12, 0
bne _do
lwz r12, 0x14(r1)
lwz r11, 0x10(r1)
addi r1, r1, 0x80
mr r31, r3
blr
_do:
stw r0, 0x18(r1)
mflr r0
stw r0, 0x1c(r1)
stw r3, 0x20(r1)
stw r4, 0x24(r1)
stw r5, 0x28(r1)
stw r6, 0x2c(r1)
stw r7, 0x30(r1)
stw r8, 0x34(r1)
stw r9, 0x38(r1)
stw r10, 0x3c(r1)
lis r5, _name@ha
addi r5, r5, _name@l
lis r6, _ss_cstr@ha
addi r6, r6, _ss_cstr@l
stw r5, 0(r6)
lis r5, 0x1021
ori r5, r5, 0xB58C
stw r5, 4(r6)
lis r3, _msgPre@ha
addi r3, r3, _msgPre@l
mr r4, r5
bl import.coreinit.OSReport
lis r6, _ss_cstr@ha
addi r6, r6, _ss_cstr@l
lwz r4, 4(r6)
lwz r12, 0x1c(r4)
mtctr r12
mr r3, r6
bctrl
mr r0, r3
lis r3, _msgPost@ha
addi r3, r3, _msgPost@l
mr r4, r0
bl import.coreinit.OSReport
_clear:
li r0, 0
lis r11, _trigger@ha
stw r0, _trigger@l(r11)
lwz r3, 0x20(r1)
lwz r4, 0x24(r1)
lwz r5, 0x28(r1)
lwz r6, 0x2c(r1)
lwz r7, 0x30(r1)
lwz r8, 0x34(r1)
lwz r9, 0x38(r1)
lwz r10, 0x3c(r1)
lwz r0, 0x1c(r1)
mtlr r0
lwz r0, 0x18(r1)
lwz r11, 0x10(r1)
lwz r12, 0x14(r1)
addi r1, r1, 0x80
mr r31, r3
blr

0x031FA9CC = bla frameItemHook
