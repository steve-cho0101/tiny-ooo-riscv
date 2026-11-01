"""cocotb tests for src/lsu.sv, with a Python stand-in for bus_if and the MCU."""
import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, Timer

RANDOM_OPS = int(os.environ.get("LSU_OPS", "3000"))

PTAG_ZERO = 31
LB, LH, LW, LBU, LHU = 0, 1, 2, 4, 5
SB, SH, SW = 0, 1, 2

clock_task = None


def idle(dut):
    dut.start_valid.value = 0
    dut.req_done.value = 0
    dut.store_byte_taken.value = 0
    dut.load_nibble_valid.value = 0
    dut.load_nibble.value = 0


async def reset(dut):
    # cocotb cancels running tasks when a test ends, so each test needs a clock.
    global clock_task
    if clock_task is None or clock_task.done():
        clock_task = Clock(dut.clk, 10, unit="ns").start()
    idle(dut)
    dut.head_tag.value = 0
    dut.start_is_store.value = 0
    dut.start_mem_op.value = 0
    dut.start_addr.value = 0
    dut.start_data.value = 0
    dut.start_pdst.value = 0
    dut.start_rob_tag.value = 0
    dut.rst_n.value = 0
    for _ in range(3):
        await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def settle():
    await Timer(1, unit="ns")


async def next_cycle(dut):
    await FallingEdge(dut.clk)
    idle(dut)


async def start(dut, is_store, mem_op, addr, data=0, pdst=0, rob_tag=0):
    dut.start_valid.value = 1
    dut.start_is_store.value = is_store
    dut.start_mem_op.value = mem_op
    dut.start_addr.value = addr
    dut.start_data.value = data
    dut.start_pdst.value = pdst
    dut.start_rob_tag.value = rob_tag
    await next_cycle(dut)
    # Issue moves on, so whatever was on these wires must have been captured.
    dut.start_addr.value = 0xFFFF ^ addr
    dut.start_data.value = 0xFFFFFFFF ^ data
    dut.start_pdst.value = 0x1F ^ pdst
    dut.start_rob_tag.value = 3 ^ rob_tag
    dut.start_mem_op.value = 7 ^ mem_op
    dut.start_is_store.value = 1 ^ is_store


async def check_request(dut, is_store, addr, size=None):
    await settle()
    assert int(dut.req_valid.value) == 1
    assert int(dut.req_is_store.value) == is_store
    assert int(dut.req_addr.value) == addr, "the MCU needs the exact address"
    if size is not None:
        assert int(dut.req_size.value) == size


async def finish_request(dut):
    await settle()
    assert int(dut.req_valid.value) == 1
    dut.req_done.value = 1
    await next_cycle(dut)


async def send_word(dut, word, gaps=None):
    """Send a word as the MCU does. Returns the load_done value at each nibble."""
    seen = []
    for i in range(8):
        for _ in range(gaps.randrange(4) if gaps else 0):
            await next_cycle(dut)
        dut.load_nibble_valid.value = 1
        dut.load_nibble.value = (word >> (4 * i)) & 0xF
        await settle()
        seen.append(int(dut.load_done.value))
        await next_cycle(dut)
    return seen


async def take_result(dut):
    await settle()
    assert int(dut.result_valid.value) == 1
    out = (int(dut.result_tag.value), int(dut.result_data.value), int(dut.result_rob_tag.value))
    await next_cycle(dut)
    await settle()
    assert int(dut.result_valid.value) == 0, "result lasted more than one cycle"
    return out


async def load(dut, mem_op, addr, word, pdst=5, rob_tag=1, gaps=None):
    await start(dut, 0, mem_op, addr, pdst=pdst, rob_tag=rob_tag)
    await check_request(dut, 0, addr)
    await finish_request(dut)
    await send_word(dut, word, gaps)
    return await take_result(dut)


async def store(dut, size, addr, data, rob_tag=1):
    """Run a store at the ROB head. Returns the bytes sent and the result."""
    dut.head_tag.value = rob_tag
    await start(dut, 1, size, addr, data=data, rob_tag=rob_tag)
    await check_request(dut, 1, addr, size)
    sent = []
    for _ in range(1 << size):
        await settle()
        sent.append(int(dut.store_byte.value))
        dut.store_byte_taken.value = 1
        await next_cycle(dut)
    await finish_request(dut)
    return sent, await take_result(dut)


def expected_load(mem_op, addr, word):
    shift = 8 * (addr & 3)
    if mem_op == LW:
        return word
    if mem_op in (LB, LBU):
        value = (word >> shift) & 0xFF
        return value - 0x100 & 0xFFFFFFFF if mem_op == LB and value >> 7 else value
    value = (word >> (shift & 16)) & 0xFFFF
    return value - 0x10000 & 0xFFFFFFFF if mem_op == LH and value >> 15 else value


@cocotb.test()
async def test_reset_is_idle(dut):
    await reset(dut)
    await settle()
    assert int(dut.req_valid.value) == 0
    assert int(dut.result_valid.value) == 0


@cocotb.test()
async def test_load_requests_after_issue(dut):
    await reset(dut)
    await start(dut, 0, LW, 0x1234, pdst=7, rob_tag=2)
    await settle()
    assert int(dut.req_valid.value) == 1
    assert int(dut.req_is_store.value) == 0
    assert int(dut.req_addr.value) == 0x1234


@cocotb.test()
async def test_load_does_not_wait_for_the_rob_head(dut):
    await reset(dut)
    dut.head_tag.value = 0
    await start(dut, 0, LW, 0x10, rob_tag=3)
    await settle()
    assert int(dut.req_valid.value) == 1


@cocotb.test()
async def test_store_waits_for_the_rob_head(dut):
    await reset(dut)
    dut.head_tag.value = 0
    await start(dut, 1, SW, 0x20, data=1, rob_tag=2)
    for tag in (0, 1, 3):
        dut.head_tag.value = tag
        await settle()
        assert int(dut.req_valid.value) == 0, "store left before reaching the head"
        await next_cycle(dut)
    dut.head_tag.value = 2
    await settle()
    assert int(dut.req_valid.value) == 1
    assert int(dut.req_is_store.value) == 1
    assert int(dut.req_size.value) == SW


@cocotb.test()
async def test_done_is_ignored_while_store_is_blocked(dut):
    await reset(dut)
    dut.head_tag.value = 0
    await start(dut, 1, SW, 0x20, data=1, rob_tag=2)
    dut.req_done.value = 1
    await next_cycle(dut)
    dut.head_tag.value = 2
    await settle()
    assert int(dut.req_valid.value) == 1, "the store was dropped before it was sent"
    assert int(dut.result_valid.value) == 0


@cocotb.test()
async def test_store_keeps_low_address_bits(dut):
    await reset(dut)
    for addr, size in ((0x1237, SB), (0x1236, SH), (0xFFFC, SW)):
        dut.head_tag.value = 0
        await store(dut, size, addr, 0, rob_tag=0)


@cocotb.test()
async def test_request_holds_until_done(dut):
    await reset(dut)
    await start(dut, 0, LW, 0x40)
    for _ in range(5):
        await settle()
        assert int(dut.req_valid.value) == 1
        await next_cycle(dut)
    await finish_request(dut)
    await settle()
    assert int(dut.req_valid.value) == 0


@cocotb.test()
async def test_store_bytes_low_first(dut):
    await reset(dut)
    assert (await store(dut, SB, 0x100, 0x11223344))[0] == [0x44]
    assert (await store(dut, SH, 0x100, 0x11223344))[0] == [0x44, 0x33]
    assert (await store(dut, SW, 0x100, 0x11223344))[0] == [0x44, 0x33, 0x22, 0x11]


@cocotb.test()
async def test_store_uses_the_zero_tag(dut):
    await reset(dut)
    _, (tag, _, rob_tag) = await store(dut, SW, 0x100, 5, rob_tag=2)
    assert tag == PTAG_ZERO, "a store must not write a register"
    assert rob_tag == 2


@cocotb.test()
async def test_no_result_before_the_last_nibble(dut):
    await reset(dut)
    await start(dut, 0, LW, 0)
    await finish_request(dut)
    for i in range(8):
        await settle()
        assert int(dut.result_valid.value) == 0, f"result after {i} nibbles"
        dut.load_nibble_valid.value = 1
        await next_cycle(dut)
    await settle()
    assert int(dut.result_valid.value) == 1


@cocotb.test()
async def test_load_done_is_the_last_nibble_only(dut):
    await reset(dut)
    await start(dut, 0, LW, 0)
    await finish_request(dut)
    assert await send_word(dut, 0) == [0] * 7 + [1]


@cocotb.test()
async def test_load_reassembles_nibbles(dut):
    await reset(dut)
    assert (await load(dut, LW, 0, 0x89ABCDEF, pdst=9, rob_tag=3)) == (9, 0x89ABCDEF, 3)


@cocotb.test()
async def test_every_load_at_every_offset(dut):
    await reset(dut)
    for word in (0x80FF7F01, 0x7F8001FF, 0x12345678, 0xFFFFFFFF, 0x00000000):
        for offset in range(4):
            for mem_op, step in ((LB, 1), (LBU, 1), (LH, 2), (LHU, 2), (LW, 4)):
                if offset % step:
                    continue
                addr = 0x2000 + offset
                _, value, _ = await load(dut, mem_op, addr, word)
                want = expected_load(mem_op, addr, word)
                assert value == want, f"op {mem_op} offset {offset} word {word:08x}"


@cocotb.test()
async def test_nibble_gaps(dut):
    await reset(dut)
    r = random.Random(4)
    for _ in range(20):
        word = r.getrandbits(32)
        assert (await load(dut, LW, 0, word, gaps=r))[1] == word


@cocotb.test()
async def test_back_to_back(dut):
    await reset(dut)
    for i in range(6):
        assert (await load(dut, LW, 0, 0xA0000000 + i))[1] == 0xA0000000 + i
        assert (await store(dut, SW, 0, 0xB0000000 + i))[0][0] == i


@cocotb.test()
async def test_start_while_busy_is_ignored(dut):
    """Dispatch prevents this. If it ever happens the slot must not be overwritten."""
    await reset(dut)
    await start(dut, 0, LW, 0x10, pdst=4, rob_tag=1)
    await settle()
    await start(dut, 1, SW, 0x20, pdst=8, rob_tag=2)
    await finish_request(dut)
    await send_word(dut, 0x55)
    assert await take_result(dut) == (4, 0x55, 1)


@cocotb.test()
async def test_reset_during_a_load(dut):
    """The nibble count must not carry over."""
    await reset(dut)
    await start(dut, 0, LW, 0)
    await finish_request(dut)
    for _ in range(3):
        dut.load_nibble_valid.value = 1
        await next_cycle(dut)
    await reset(dut)
    await settle()
    assert int(dut.req_valid.value) == 0
    assert (await load(dut, LW, 0, 0x01020304))[1] == 0x01020304


@cocotb.test()
async def test_random_operations(dut):
    r = random.Random(1)
    await reset(dut)
    for _ in range(RANDOM_OPS):
        rob_tag = r.randrange(4)
        if r.random() < 0.6:
            mem_op = r.choice((LB, LH, LW, LBU, LHU))
            step = 4 if mem_op == LW else 2 if mem_op in (LH, LHU) else 1
            addr = r.randrange(0x10000) & ~(step - 1)
            word = r.getrandbits(32)
            pdst = r.randrange(19)
            got = await load(dut, mem_op, addr, word, pdst, rob_tag, r)
            assert got == (pdst, expected_load(mem_op, addr, word), rob_tag)
        else:
            size = r.randrange(3)
            data = r.getrandbits(32)
            sent, result = await store(dut, size, r.randrange(0x10000), data, rob_tag)
            assert sent == [(data >> (8 * i)) & 0xFF for i in range(1 << size)]
            assert (result[0], result[2]) == (PTAG_ZERO, rob_tag)
