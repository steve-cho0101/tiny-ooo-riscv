"""Top-level test for the Tiny Tapeout harness. Runs on RTL and on the gate-level
netlist, which is the check that the latch array still works after hardening.
"""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, Timer

CMD_SHIFT, CMD_WRITE, CMD_TAG1, CMD_TAG2, CMD_ALLOC, CMD_SEL = 1, 2, 3, 4, 5, 6
NPHYS = 19
PTAG_ZERO = 31
SEL_STATUS = 8


async def start(dut):
    # 10 MHz, the clock target in docs/architecture.md.
    Clock(dut.clk, 100, unit="ns").start()
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def command(dut, cmd, value=0):
    dut.uio_in.value = cmd
    dut.ui_in.value = value
    await FallingEdge(dut.clk)
    dut.uio_in.value = 0


async def write(dut, tag, data):
    for i in range(4):
        await command(dut, CMD_SHIFT, (data >> (8 * i)) & 0xFF)
    await command(dut, CMD_WRITE, tag)
    await FallingEdge(dut.clk)


async def output(dut, sel):
    await command(dut, CMD_SEL, sel)
    await Timer(10, unit="ns")
    return dut.uo_out.value.to_unsigned()


async def read_port(dut, port, tag):
    await command(dut, CMD_TAG1 if port == 1 else CMD_TAG2, tag)
    base = 0 if port == 1 else 4
    value = 0
    for i in range(4):
        value |= await output(dut, base + i) << (8 * i)
    return value


@cocotb.test()
async def test_write_read_all_registers(dut):
    await start(dut)
    r = random.Random(1)
    model = {tag: r.getrandbits(32) for tag in range(NPHYS)}
    for tag, value in model.items():
        await write(dut, tag, value)
    for tag, value in model.items():
        assert await read_port(dut, 1, tag) == value, f"port 1 tag {tag}"
        assert await read_port(dut, 2, tag) == value, f"port 2 tag {tag}"


@cocotb.test()
async def test_data_patterns(dut):
    await start(dut)
    for tag in (0, 9, 18):
        for value in (0xFFFFFFFF, 0, 0xAAAAAAAA, 0x55555555):
            await write(dut, tag, value)
            assert await read_port(dut, 1, tag) == value


@cocotb.test()
async def test_zero_tag(dut):
    await start(dut)
    await write(dut, 0, 0xFFFFFFFF)
    assert await read_port(dut, 1, PTAG_ZERO) == 0
    assert await read_port(dut, 2, PTAG_ZERO) == 0


@cocotb.test()
async def test_ready_and_wakeup(dut):
    await start(dut)
    await command(dut, CMD_TAG1, 5)
    await command(dut, CMD_SEL, SEL_STATUS)
    await Timer(10, unit="ns")
    assert dut.uo_out.value.to_unsigned() >> 7 == 1, "not ready after reset"

    await command(dut, CMD_ALLOC, 5)
    await Timer(10, unit="ns")
    assert dut.uo_out.value.to_unsigned() >> 7 == 0, "still ready after alloc"

    await write(dut, 5, 0x12345678)
    await Timer(10, unit="ns")
    assert dut.uo_out.value.to_unsigned() >> 7 == 1, "not ready after write"
