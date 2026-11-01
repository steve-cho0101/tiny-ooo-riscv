## How it works

This is a genuinely out-of-order RV32E CPU. It renames registers onto 19 physical
registers held in latches, tracks four instructions in a reorder buffer, and issues
from a two-entry reservation station. A slow load does not hold up the independent
instructions behind it, and everything still retires in program order.

The chip has no memory of its own. A microcontroller holds 64 KiB of memory, supplies
the clock, streams instruction bytes in, and answers load frames. It runs C compiled
with GCC for `rv32e`/`ilp32e`.

## How to test

The RP2350 on the demo board acts as the memory. It streams instructions from address
0 on `ui` after reset, and reads frames from `uo` while `uio[6]` is high.

| Header bits | Field |
|---|---|
| `[7:6]` | 00 redirect, 01 load, 10 store, 11 halt |
| `[5:4]` | Store size: 0 byte, 1 halfword, 2 word |
| `[3:0]` | Halt reason: 0 ECALL, 1 EBREAK, 2 illegal |

Each frame continues with the address, low byte first, and a store then sends its data
bytes. Answer a load with 8 nibbles of the aligned word on `uio[3:0]`, low nibble first,
strobing `uio[5]`. Answer a redirect with one `uio[5]` pulse, then stream from the new
address.

## External hardware

None. The demo board's RP2350 provides the memory and the clock.
