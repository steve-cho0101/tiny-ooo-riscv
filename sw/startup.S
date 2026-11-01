# Reset entry. See "Software requirements" in docs/isa.md.
    .section .text.start
    .globl _start
_start:
    li x1, 0
    li x3, 0
    li x4, 0
    li x5, 0
    li x6, 0
    li x7, 0
    li x8, 0
    li x9, 0
    li x10, 0
    li x11, 0
    li x12, 0
    li x13, 0
    li x14, 0
    li x15, 0
    li sp, 0xFF00

    # Clear .bss.
    la t0, __bss_start
    la t1, __bss_end
1:  bgeu t0, t1, 2f
    sw zero, 0(t0)
    addi t0, t0, 4
    j 1b
2:
    call main

    # Exit routine: store the result where the MCU can see it, then halt.
    li t0, 0xFFF0
    sw a0, 0(t0)
    ecall
