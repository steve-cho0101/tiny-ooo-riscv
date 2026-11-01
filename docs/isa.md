# ISA

Status: agreed scope. C compiled with xPack GCC 15.2.0 runs on the core in
simulation, but not yet on real hardware.

## Scope

The core implements RV32E: 16 registers, x0 hardwired to zero, ABI ILP32E, and
little-endian data. Extensions M, A, F, C and Zicsr are not implemented.

All 37 base instructions are implemented, plus FENCE, ECALL and EBREAK.

| Group | Instructions |
|---|---|
| Upper immediate | LUI, AUIPC |
| Jumps | JAL, JALR |
| Branches | BEQ, BNE, BLT, BGE, BLTU, BGEU |
| Loads | LB, LH, LW, LBU, LHU |
| Stores | SB, SH, SW |
| Immediate ALU | ADDI, SLTI, SLTIU, XORI, ORI, ANDI, SLLI, SRLI, SRAI |
| Register ALU | ADD, SUB, SLL, SLT, SLTU, XOR, SRL, SRA, OR, AND |
| System | FENCE, ECALL, EBREAK |

## Encoding

| Opcode `[6:0]` | Format | Instructions | Selected by |
|---|---|---|---|
| `0110111` | U | LUI | |
| `0010111` | U | AUIPC | |
| `1101111` | J | JAL | |
| `1100111` | I | JALR | funct3 = 000 |
| `1100011` | B | Branches | funct3: 000 BEQ, 001 BNE, 100 BLT, 101 BGE, 110 BLTU, 111 BGEU |
| `0000011` | I | Loads | funct3: 000 LB, 001 LH, 010 LW, 100 LBU, 101 LHU |
| `0100011` | S | Stores | funct3: 000 SB, 001 SH, 010 SW |
| `0010011` | I | Immediate ALU | funct3: 000 ADDI, 010 SLTI, 011 SLTIU, 100 XORI, 110 ORI, 111 ANDI, 001 SLLI, 101 SRLI or SRAI |
| `0110011` | R | Register ALU | funct3: 000 ADD or SUB, 001 SLL, 010 SLT, 011 SLTU, 100 XOR, 101 SRL or SRA, 110 OR, 111 AND |
| `0001111` | I | FENCE | funct3 = 000 |
| `1110011` | I | ECALL, EBREAK | All other fields 0, bit 20: 0 ECALL, 1 EBREAK |

SUB and SRA use funct7 `0100000`, with ADD and SRL using `0000000`. The same
applies to SRAI and SRLI through instruction bits `[31:25]`. SLLI, SLL, SLT,
SLTU, XOR, OR and AND require funct7 `0000000`.

## Implementation-defined behaviour

| Case | Behaviour |
|---|---|
| Unrecognised encoding | Halt with reason 2 at retirement |
| Register field with bit 4 set | Illegal in RV32E: halt with reason 2. Applies to every register field the instruction uses |
| FENCE | Treated as a no-op. Includes FENCE.TSO and PAUSE, which share its encoding. FENCE.I is illegal |
| CSR instructions | Illegal |
| ECALL, EBREAK | No trap. Halt with reason 0 or 1 at retirement |
| Interrupts | None |
| Register values at reset | Undefined. `startup.S` must initialise every register |

## Undefined behaviour

The hardware does not detect these cases, to save area. **The reference model
must raise an error on each of them**, so a test can never pass by accident.

| Case | Note |
|---|---|
| Misaligned load or store | GCC read a packed `int` field with four `lbu`, so compiled code avoids these |
| Jump or taken branch to an address with bit 1 set | The core has no compressed instructions |
| Any address above 0xFFFF | Upper 16 bits are ignored. PC is 16 bits, and link values are zero-extended |

## Memory map

The address space is 64 KiB of unified memory, held by the MCU. The chip decodes
no addresses, so there is no on-chip MMIO.

| Address | Use |
|---|---|
| `0x0000` | Reset vector, `.text` |
| After `.text` | `.rodata`, `.data`, `.bss` |
| Below `0x10000` | Stack, growing down |

The instruction and data paths see the same memory, so loads can read `.rodata`.
Self-modifying code is not supported, because the MCU streams ahead of the PC.

## Software requirements

Compile command, using the files in `sw/`. `-lgcc` must come last, and the xPack
toolchain uses the `riscv-none-elf-` prefix:

```bash
riscv-none-elf-gcc -march=rv32e -mabi=ilp32e -O1 \
    -ffreestanding -nostdlib -T link.ld -o test.elf startup.S test.c runtime.c -lgcc
```

- `startup.S`: clear every register, set `sp`, copy `.data` if it needs a separate
  load image, clear `.bss`, call `main`, then run the exit routine.
- Linker script: places sections as in the memory map above.
- Exit routine: stores `main`'s return value and any registers of interest, then
  executes ECALL.

- `runtime.c`: supplies `memset`, `memcpy`, `memmove` and `memcmp`.

Tested toolchain results:

- The xPack toolchain includes an `rv32e/ilp32e` multilib, so `-lgcc` supplies
  `__mulsi3`, `__divsi3` and `__umodsi3`. We do not need to write these.
- The test file called `memset` even with `-ffreestanding`, and `-lgcc` did not
  supply it. `memcpy` and the others are included as the same risk applies. The
  struct copy in the test did not call `memcpy`, so that one is unconfirmed.
- Object code used these instructions: ADDI, JALR, LW, SW, ADD, AUIPC, SLLI, LUI,
  LHU, JAL, BNE, SRAI, SB, LBU, BLTU, BLT, BGE and ANDI. Unlinked code overstates
  AUIPC and JALR, as calls start as an AUIPC and JALR pair.
- One test file does not cover every instruction, so all 40 stay in scope.

From the ABI, not tested: ILP32E passes 6 arguments in registers and uses 4-byte
stack alignment.
