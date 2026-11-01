"""cocotb tests for src/fetch.sv, with a Python stand-in for the MCU's byte stream."""
import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, Timer

RANDOM_INSTRS = int(os.environ.get("FETCH_INSTRS", "4000"))

clock_task = None


async def reset(dut):
    # cocotb cancels running tasks when a test ends, so each test needs a clock.
    global clock_task
    if clock_task is None or clock_task.done():
        clock_task = Clock(dut.clk, 10, unit="ns").start()
    idle(dut)
    dut.i_data.value = 0
    dut.redirect_target.value = 0
    dut.rst_n.value = 0
    for _ in range(3):
        await FallingEdge(dut.clk)
    dut.rst_n.value = 1


def idle(dut):
    dut.i_valid.value = 0
    dut.advance.value = 0
    dut.redirect_start.value = 0
    dut.redirect_done.value = 0
    dut.redirect_ack.value = 0


async def settle():
    await Timer(1, unit="ns")


async def tick(dut, byte=None, advance=0, start=None, done=0, ack=0):
    """Run one cycle. Returns whether a byte was accepted."""
    idle(dut)
    if byte is not None:
        dut.i_valid.value = 1
        dut.i_data.value = byte
    dut.advance.value = advance
    if start is not None:
        dut.redirect_start.value = 1
        dut.redirect_target.value = start
    dut.redirect_done.value = done
    dut.redirect_ack.value = ack
    await settle()
    taken = byte is not None and int(dut.i_ready.value) == 1
    await FallingEdge(dut.clk)
    idle(dut)
    return taken


async def send_word(dut, word):
    for i in range(4):
        assert await tick(dut, byte=(word >> (8 * i)) & 0xFF), f"byte {i} refused"


async def head(dut):
    await settle()
    return int(dut.instr_valid.value), int(dut.instr.value), int(dut.pc.value)


@cocotb.test()
async def test_reset_state(dut):
    await reset(dut)
    await settle()
    assert int(dut.instr_valid.value) == 0
    assert int(dut.i_ready.value) == 1
    assert int(dut.pc.value) == 0
    assert int(dut.redirect_valid.value) == 0


@cocotb.test()
async def test_bytes_assemble_low_first(dut):
    await reset(dut)
    await send_word(dut, 0x11223344)
    await tick(dut)
    assert await head(dut) == (1, 0x11223344, 0)


@cocotb.test()
async def test_not_valid_before_the_fourth_byte(dut):
    await reset(dut)
    for byte in (1, 2, 3):
        await tick(dut, byte=byte)
        await tick(dut)
        assert (await head(dut))[0] == 0


@cocotb.test()
async def test_accepts_a_byte_every_cycle(dut):
    """A word each four cycles is the fetch rate in the spec."""
    await reset(dut)
    for i in range(8):
        assert await tick(dut, byte=i), f"stalled at byte {i} with the head free"
    await tick(dut)
    assert (await head(dut))[1] == 0x03020100


@cocotb.test()
async def test_ready_drops_when_both_words_are_full(dut):
    await reset(dut)
    await send_word(dut, 0xAAAAAAAA)
    await tick(dut)
    await send_word(dut, 0xBBBBBBBB)
    await settle()
    assert int(dut.i_ready.value) == 0
    assert not await tick(dut, byte=0xFF)
    assert (await head(dut))[1] == 0xAAAAAAAA
    await tick(dut, advance=1)
    assert (await head(dut))[1] == 0xBBBBBBBB, "a refused byte changed the waiting word"


@cocotb.test()
async def test_advance_moves_to_the_next_word(dut):
    await reset(dut)
    await send_word(dut, 0xAAAAAAAA)
    await tick(dut)
    await send_word(dut, 0xBBBBBBBB)
    await tick(dut, advance=1)
    assert await head(dut) == (1, 0xBBBBBBBB, 4)
    assert int(dut.i_ready.value) == 1


@cocotb.test()
async def test_advance_empties_the_head(dut):
    await reset(dut)
    await send_word(dut, 0xAAAAAAAA)
    await tick(dut)
    await tick(dut, advance=1)
    assert (await head(dut))[0] == 0


@cocotb.test()
async def test_head_stays_while_a_branch_waits(dut):
    await reset(dut)
    await send_word(dut, 0xAAAAAAAA)
    await tick(dut)
    await send_word(dut, 0xBBBBBBBB)
    for _ in range(10):
        await tick(dut)
        assert await head(dut) == (1, 0xAAAAAAAA, 0)


@cocotb.test()
async def test_pc_next(dut):
    await reset(dut)
    await settle()
    assert int(dut.pc_next.value) == 4
    await tick(dut, start=0xFFFC)
    await settle()
    assert int(dut.pc.value) == 0xFFFC
    assert int(dut.pc_next.value) == 0, "the PC is 16 bits"


async def redirect(dut, target):
    await tick(dut, start=target)
    await settle()
    assert int(dut.redirect_valid.value) == 1
    assert int(dut.pc.value) == target, "bus_if sends the PC as the address"
    await tick(dut, done=1)
    await settle()
    assert int(dut.redirect_valid.value) == 0
    assert int(dut.i_ready.value) == 0, "ready must stay low until the acknowledge"
    await tick(dut, ack=1)


@cocotb.test()
async def test_redirect_hides_the_head_at_once(dut):
    await reset(dut)
    await send_word(dut, 0xAAAAAAAA)
    await tick(dut)
    await tick(dut, start=0x100)
    assert (await head(dut))[0] == 0


@cocotb.test()
async def test_ready_is_low_until_the_acknowledge(dut):
    await reset(dut)
    await tick(dut, start=0x100)
    for _ in range(5):
        assert not await tick(dut, byte=0xEE)
    await tick(dut, done=1)
    for _ in range(5):
        assert not await tick(dut, byte=0xEE)
    await tick(dut, ack=1)
    await settle()
    assert int(dut.i_ready.value) == 1


@cocotb.test()
async def test_redirect_flushes_everything(dut):
    await reset(dut)
    await send_word(dut, 0xAAAAAAAA)
    await tick(dut)
    await send_word(dut, 0xBBBBBBBB)
    await redirect(dut, 0x200)
    await send_word(dut, 0xCCCCCCCC)
    await tick(dut)
    assert await head(dut) == (1, 0xCCCCCCCC, 0x200)


@cocotb.test()
async def test_partial_word_does_not_misalign(dut):
    """This is the race the redirect handshake exists to prevent."""
    await reset(dut)
    await tick(dut, byte=0x11)
    await tick(dut, byte=0x22)
    await redirect(dut, 0x200)
    await send_word(dut, 0x44332211)
    await tick(dut)
    assert await head(dut) == (1, 0x44332211, 0x200)


@cocotb.test()
async def test_byte_accepted_in_the_decision_cycle_is_dropped(dut):
    await reset(dut)
    assert await tick(dut, byte=0x99, start=0x200)
    await tick(dut, done=1)
    await tick(dut, ack=1)
    await send_word(dut, 0x44332211)
    await tick(dut)
    assert await head(dut) == (1, 0x44332211, 0x200)


@cocotb.test()
async def test_redirect_wins_over_advance(dut):
    await reset(dut)
    await send_word(dut, 0xAAAAAAAA)
    await tick(dut)
    await tick(dut, advance=1, start=0x300)
    await settle()
    assert int(dut.pc.value) == 0x300


@cocotb.test()
async def test_second_redirect_after_the_first(dut):
    await reset(dut)
    await redirect(dut, 0x100)
    await redirect(dut, 0x200)
    await send_word(dut, 0x12345678)
    await tick(dut)
    assert await head(dut) == (1, 0x12345678, 0x200)


@cocotb.test()
async def test_reset_during_a_redirect(dut):
    await reset(dut)
    await tick(dut, byte=1)
    await tick(dut, start=0x100)
    await reset(dut)
    await settle()
    assert int(dut.i_ready.value) == 1
    assert int(dut.redirect_valid.value) == 0
    assert int(dut.pc.value) == 0
    await send_word(dut, 0x12345678)
    await tick(dut)
    assert await head(dut) == (1, 0x12345678, 0)


def mem_word(addr):
    """A word that identifies its own address."""
    return (addr * 0x9E3779B1 + 0x1234567) & 0xFFFFFFFF


@cocotb.test()
async def test_random_control_flow(dut):
    """Every instruction seen must be the word at its PC, in program order."""
    r = random.Random(1)
    await reset(dut)
    stream = 0  # next byte address the MCU sends
    expect_pc = 0
    seen = 0
    state = "run"
    wait = 0
    for _ in range(RANDOM_INSTRS * 100):
        if seen >= RANDOM_INSTRS:
            break
        byte = None
        if state in ("run", "stale") and r.random() < 0.8:
            byte = (mem_word(stream & ~3) >> (8 * (stream & 3))) & 0xFF

        advance = 0
        start = None
        valid, instr, pc = await head(dut)
        if state == "run" and valid:
            assert pc == expect_pc, f"pc {pc:x} != {expect_pc:x}"
            assert instr == mem_word(pc), f"wrong word at {pc:x}"
            seen += 1
            if r.random() < 0.2:
                start = r.randrange(0x4000) * 4
            elif r.random() < 0.7:
                advance = 1
                expect_pc = (pc + 4) & 0xFFFF
            else:
                seen -= 1  # still at the head, as a branch would be

        taken = await tick(dut, byte=byte, advance=advance, start=start,
                           done=int(state == "frame"), ack=int(state == "ack"))
        if taken:
            stream = (stream + 1) & 0xFFFF

        if start is not None:
            expect_pc = start
            state, wait = "stale", r.randrange(6)  # bytes keep coming until the MCU sees it
        elif state == "stale":
            if wait == 0:
                state = "frame"
            wait -= 1
        elif state == "frame":
            state = "ack"
        elif state == "ack":
            state, stream = "run", expect_pc
    assert seen >= RANDOM_INSTRS, "fetch stopped delivering instructions"
