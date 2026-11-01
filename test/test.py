"""Top-level test on the Tiny Tapeout pins. It runs on RTL and on the gate-level
netlist, which checks that real instructions still work after hardening. Whole
programs run in tb/tb_cpu.py.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

# Encodings from riscv-none-elf-as.
PROGRAM = [
    0x01200093,  # addi x1, x0, 0x12
    0x02108113,  # addi x2, x1, 0x21
    0x10202023,  # sw x2, 0x100(x0)
    0x10002183,  # lw x3, 0x100(x0)
    0x00218233,  # add x4, x3, x2
    0x00218463,  # beq x3, x2, .+8
    0x00000213,  # addi x4, x0, 0    skipped
    0x008002ef,  # jal x5, .+8
    0x00000213,  # addi x4, x0, 0    skipped
    0x00421313,  # slli x6, x4, 4
    0x10602223,  # sw x6, 0x104(x0)
    0x10502423,  # sw x5, 0x108(x0)
    0x00000073,  # ecall
]

EXPECTED_STORES = [
    (0x100, [0x33, 0, 0, 0]),
    (0x104, [0x60, 0x06, 0, 0]),
    (0x108, [0x20, 0, 0, 0]),  # the link value from the JAL at 0x1C
]

I_VALID, D_VALID, O_VALID, I_READY = 1 << 4, 1 << 5, 1 << 6, 1 << 7


async def run_program(dut, image):
    """Serve memory over the pins until HALT. Returns the stores and the reason."""
    # 10 MHz, the clock target in docs/architecture.md.
    Clock(dut.clk, 100, unit="ns").start()
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    mem = bytearray(0x200)
    mem[:len(image)] = image
    stream, frame, nibbles, ack = 0, [], [], False
    stores = []

    for _ in range(2000):
        await FallingEdge(dut.clk)
        pins = int(dut.uio_out.value)
        out = int(dut.uo_out.value) if pins & O_VALID else 0

        uio = 0
        ui = 0
        if ack:
            uio |= D_VALID
            ack = False
        else:
            uio |= I_VALID
            ui = mem[stream]
            if pins & I_READY:
                stream += 1
            if nibbles:
                uio |= D_VALID | nibbles.pop(0)
        dut.ui_in.value = ui
        dut.uio_in.value = uio

        if pins & O_VALID:
            frame.append(out)
            kind = frame[0] >> 6
            length = 3 + (1 << ((frame[0] >> 4) & 3)) if kind == 2 else 3
            if len(frame) == length:
                addr = frame[1] | frame[2] << 8
                if kind == 0:
                    stream, ack = addr, True
                elif kind == 1:
                    word = int.from_bytes(mem[addr & ~3:(addr & ~3) + 4], "little")
                    nibbles = [(word >> (4 * i)) & 0xF for i in range(8)]
                elif kind == 2:
                    mem[addr:addr + length - 3] = bytes(frame[3:])
                    stores.append((addr, frame[3:]))
                else:
                    return stores, frame[0] & 0xF
                frame = []
    raise AssertionError(f"no HALT frame, stores so far: {stores}")


@cocotb.test()
async def test_runs_a_program(dut):
    image = b"".join(word.to_bytes(4, "little") for word in PROGRAM)
    stores, reason = await run_program(dut, image)
    assert stores == EXPECTED_STORES
    assert reason == 0


@cocotb.test()
async def test_illegal_instruction_halts(dut):
    stores, reason = await run_program(dut, bytes(4))
    assert stores == []
    assert reason == 2
