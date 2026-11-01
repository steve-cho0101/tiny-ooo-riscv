# tiny-ooo-riscv

An out-of-order RV32E CPU in SystemVerilog, written for fabrication through
[Tiny Tapeout](https://tinytapeout.com). It runs C compiled with GCC.

The chip has no memory of its own. A microcontroller supplies the clock and 64 KiB
of memory over the chip's pins, so instruction bytes and load data arrive slowly and
on separate paths. That is what makes out-of-order execution worthwhile here: a slow
load does not hold up the independent instructions behind it.

## Status

| Stage | State |
|---|---|
| RTL | All blocks written |
| Simulation | Runs compiled C, matching an in-order reference model |
| Register file hardening | Passed on a 2×2 test harness: routing, timing, LVS, precheck, gate-level test |
| Full CPU hardening | In progress |
| Real hardware | Not started |

The target shuttle is TTSKY27a. Nothing has been fabricated.

## Design

| Item | Choice |
|---|---|
| ISA | RV32E, 40 instructions, ILP32E ABI |
| Width | 1 dispatch, 1 issue, 1 retire per cycle |
| Registers | 19 × 32 physical registers in latches, with a flop fallback |
| Rename | RAT plus ROB-slot swap, with no free list |
| ROB | 4 entries, control only |
| Scheduling | 2-entry reservation station, tags only |
| Execution | One ALU with a barrel shifter, one load/store slot |
| Control flow | No prediction, dispatch waits for branches to resolve |
| Memory | 64 KiB on an external MCU, planned to be the RP2350 on the demo board |
| Clock | 10 MHz target |

The unusual part is the rename scheme. Each ROB slot owns one physical register, and
allocating an instruction swaps it with the old mapping of `rd`. The slot then holds
that old register until the instruction retires, when it becomes the free register
for the next instruction using the slot. This needs no free list, and retirement
touches no register state.

The full specification is in [docs/architecture.md](docs/architecture.md), and the
ISA details are in [docs/isa.md](docs/isa.md).

## Repository layout

| Path | Contents |
|---|---|
| `src/` | RTL. `cpu.sv` connects the blocks, and `project.sv` is the Tiny Tapeout top level |
| `tb/` | Block and whole-core tests, the reference model, the MCU model, and the random program generator |
| `test/` | Top-level test on the Tiny Tapeout pins, for RTL and the gate-level netlist |
| `sw/` | Startup code, linker script, runtime and C test programs |
| `docs/` | Architecture and ISA specifications, and the Tiny Tapeout datasheet page |

## Running the tests

You need Python 3, Verilator, Yosys, Icarus Verilog, and a RISC-V GCC with an
`rv32e/ilp32e` multilib. We use the xPack `riscv-none-elf-gcc` 15.2.0.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r test/requirements.txt

pytest tb        # block tests, bug injection, and whole programs on the CPU
cd test && make  # short program on the Tiny Tapeout pins, on RTL
```

`pytest tb` takes a few minutes. It looks for the compiler on `PATH`, then in
`~/opt/xpack-riscv-none-elf-gcc-*`.

On macOS, if Verilator fails on `<cstddef>`, set:

```bash
export CPLUS_INCLUDE_PATH="$(xcrun --show-sdk-path)/usr/include/c++/v1"
```

## How it is verified

- **Whole programs:** every program also runs on an in-order Python reference model.
  The CPU must make the same stores in the same order and halt the same way, behind
  a Python MCU with randomized memory timing.
- **Undefined behaviour:** the reference model raises an error on it, such as a
  misaligned access, so a test cannot pass by accident.
- **Random programs:** generated programs cover the ALU, loads, stores, branches,
  jumps and loops. Both the latch and flop builds have passed a 400-program run.
- **Bug injection:** the suite deliberately breaks the RTL and requires the tests to
  fail, which shows that they can detect each bug.
- **Out-of-order behaviour:** a test checks that younger instructions finish ahead of
  a slow load, and that the instruction depending on it does not.

## Compiling a program

```bash
cd sw
riscv-none-elf-gcc -march=rv32e -mabi=ilp32e -O1 -ffreestanding -nostdlib \
    -T link.ld -o test.elf startup.S test.c runtime.c -lgcc
riscv-none-elf-objcopy -O binary test.elf test.bin
```

The startup code calls `main`, stores its return value at `0xFFF0`, then executes
ECALL, which halts the core.
