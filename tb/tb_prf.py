"""cocotb tests for src/prf.sv. test_rtl.py runs these on both the latch and flop builds."""
import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, Timer

NPHYS = 19
PTAG_ZERO = 31
RANDOM_OPS = int(os.environ.get("PRF_OPS", "20000"))

clock_task = None


def idle(dut):
    dut.wr_en.value = 0
    dut.wr_tag.value = 0
    dut.wr_data.value = 0
    dut.alloc_valid.value = 0
    dut.alloc_tag.value = 0


async def reset(dut):
    # cocotb cancels running tasks when a test ends, so each test needs a clock.
    global clock_task
    if clock_task is None or clock_task.done():
        clock_task = Clock(dut.clk, 10, unit="ns").start()
    idle(dut)
    dut.rd_tag1.value = PTAG_ZERO
    dut.rd_tag2.value = PTAG_ZERO
    dut.chk_tag1.value = PTAG_ZERO
    dut.chk_tag2.value = PTAG_ZERO
    dut.rst_n.value = 0
    for _ in range(3):
        await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def tick(dut, write=None, alloc=None):
    """Drive one cycle, from one falling edge to the next. write is (tag, data)."""
    idle(dut)
    if write is not None:
        dut.wr_en.value = 1
        dut.wr_tag.value = write[0]
        dut.wr_data.value = write[1]
    if alloc is not None:
        dut.alloc_valid.value = 1
        dut.alloc_tag.value = alloc
    await FallingEdge(dut.clk)


async def read(dut, tag1, tag2=PTAG_ZERO):
    dut.rd_tag1.value = tag1
    dut.rd_tag2.value = tag2
    await Timer(1, unit="ns")
    return int(dut.rd_data1.value), int(dut.rd_data2.value)


async def ready(dut, tag1, tag2=PTAG_ZERO):
    dut.chk_tag1.value = tag1
    dut.chk_tag2.value = tag2
    await Timer(1, unit="ns")
    return int(dut.chk_ready1.value), int(dut.chk_ready2.value)


async def write(dut, tag, data):
    """Write a register and wait until it is readable."""
    await tick(dut, write=(tag, data))
    await tick(dut)


@cocotb.test()
async def test_reset_marks_all_ready(dut):
    await reset(dut)
    await tick(dut)
    for tag in range(NPHYS):
        assert await ready(dut, tag, tag) == (1, 1)
    assert int(dut.wb_valid.value) == 0


@cocotb.test()
async def test_zero_tag(dut):
    await reset(dut)
    await write(dut, 0, 0xFFFFFFFF)
    assert await read(dut, PTAG_ZERO, PTAG_ZERO) == (0, 0)
    assert await ready(dut, PTAG_ZERO, PTAG_ZERO) == (1, 1)
    await tick(dut, alloc=PTAG_ZERO)
    assert await ready(dut, PTAG_ZERO, PTAG_ZERO) == (1, 1)
    # The zero tag must stay ready whatever the other registers are doing.
    for tag in range(NPHYS):
        await tick(dut, alloc=tag)
        assert await ready(dut, PTAG_ZERO, PTAG_ZERO) == (1, 1)


@cocotb.test()
async def test_write_to_zero_tag_touches_nothing(dut):
    await reset(dut)
    for tag in range(NPHYS):
        await write(dut, tag, 0x1000 + tag)
    await write(dut, PTAG_ZERO, 0xDEADBEEF)
    for tag in range(NPHYS):
        assert (await read(dut, tag))[0] == 0x1000 + tag
    assert (await read(dut, PTAG_ZERO))[0] == 0


@cocotb.test()
async def test_every_register_is_independent(dut):
    await reset(dut)
    for tag in range(NPHYS):
        await write(dut, tag, 0xA5A50000 + tag)
    for tag in range(NPHYS):
        other = (tag + 7) % NPHYS
        assert await read(dut, tag, other) == (0xA5A50000 + tag, 0xA5A50000 + other)


@cocotb.test()
async def test_all_data_bits(dut):
    await reset(dut)
    for tag in (0, 9, 18):
        for data in (0xFFFFFFFF, 0x00000000, 0xAAAAAAAA, 0x55555555):
            await write(dut, tag, data)
            assert (await read(dut, tag))[0] == data


@cocotb.test()
async def test_write_timing(dut):
    """E: captured. W: wakeup drives. E+2: readable."""
    await reset(dut)
    await write(dut, 4, 0x11111111)
    await tick(dut, write=(4, 0x22222222))
    assert int(dut.wb_valid.value) == 1
    assert int(dut.wb_tag.value) == 4
    await tick(dut)
    assert int(dut.wb_valid.value) == 0
    assert (await read(dut, 4))[0] == 0x22222222


@cocotb.test()
async def test_back_to_back_writes(dut):
    await reset(dut)
    for tag in range(NPHYS):
        await tick(dut, write=(tag, 0xB0000000 + tag))
    await tick(dut)
    for tag in range(NPHYS):
        assert (await read(dut, tag))[0] == 0xB0000000 + tag


@cocotb.test()
async def test_ready_sequence(dut):
    await reset(dut)
    assert (await ready(dut, 6))[0] == 1
    await tick(dut, alloc=6)
    assert (await ready(dut, 6))[0] == 0
    assert (await ready(dut, 7))[0] == 1, "alloc cleared the wrong register"
    await tick(dut, write=(6, 1))
    assert int(dut.wb_valid.value) == 1
    assert (await ready(dut, 6))[0] == 1, "lost wakeup: write-back not bypassed"
    await tick(dut)
    assert (await ready(dut, 6))[0] == 1, "ready bit not set after write-back"


@cocotb.test()
async def test_wakeup_reaches_both_ports(dut):
    await reset(dut)
    await tick(dut, alloc=3)
    assert await ready(dut, 3, 3) == (0, 0)
    await tick(dut, write=(3, 1))
    assert await ready(dut, 3, 3) == (1, 1)


@cocotb.test()
async def test_reset_stops_a_pending_write(dut):
    await reset(dut)
    await write(dut, 2, 0x12345678)
    dut.rst_n.value = 0
    await tick(dut, write=(2, 0x0BADF00D))
    dut.rst_n.value = 1
    assert int(dut.wb_valid.value) == 0
    await tick(dut)
    assert (await read(dut, 2))[0] == 0x12345678


@cocotb.test()
async def test_random_traffic(dut):
    r = random.Random(1)
    await reset(dut)
    model = {}
    for tag in range(NPHYS):
        value = r.getrandbits(32)
        await write(dut, tag, value)
        model[tag] = value
    is_ready = {tag: True for tag in range(NPHYS)}
    just_written = None

    for _ in range(RANDOM_OPS):
        tag1, tag2 = r.randrange(NPHYS), r.randrange(NPHYS)
        data1, data2 = await read(dut, tag1, tag2)
        if tag1 != just_written:
            assert data1 == model[tag1], f"port 1 tag {tag1}"
        if tag2 != just_written:
            assert data2 == model[tag2], f"port 2 tag {tag2}"

        check = r.randrange(NPHYS)
        seen = (await ready(dut, check))[0]
        assert seen == int(is_ready[check] or check == just_written), f"ready {check}"

        wr = None
        if r.random() < 0.5:
            tag = r.randrange(NPHYS)
            if tag != just_written:
                wr = (tag, r.getrandbits(32))
        al = None
        if r.random() < 0.3:
            tag = r.randrange(NPHYS)
            if tag != just_written and (wr is None or wr[0] != tag):
                al = tag
                is_ready[tag] = False
        previous = just_written
        await tick(dut, write=wr, alloc=al)
        if previous is not None:
            is_ready[previous] = True
        if wr is not None:
            model[wr[0]] = wr[1]
        just_written = wr[0] if wr else None
