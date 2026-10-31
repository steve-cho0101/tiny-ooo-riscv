## How it works

This is a test harness for the physical register file of a planned out-of-order
RV32E CPU. It holds 19 32-bit registers in a latch array, with two read ports,
one write port and a ready bit per register.

## How to test

Drive a command on `uio[2:0]` and its value on `ui[7:0]`, one per clock.

| Command | Action |
|---|---|
| 1 | Shift `ui` into the 32-bit write data, least significant byte first |
| 2 | Write that data to register `ui[4:0]` |
| 3 | Select register `ui[4:0]` for read port 1 |
| 4 | Select register `ui[4:0]` for read port 2 |
| 5 | Clear the ready bit of register `ui[4:0]` |
| 6 | Select what `uo` shows, from `ui[3:0]` |

Output selects 0 to 3 show port 1 bytes, and 4 to 7 show port 2 bytes. Any higher
select shows port 1 ready, port 2 ready, write-back valid and write-back tag.
Register 31 always reads as zero.

## External hardware

None. The demo board can drive all pins.
