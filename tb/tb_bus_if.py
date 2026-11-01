"""cocotb tests for src/bus_if.sv, with Python stand-ins for its clients and the MCU."""
import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, Timer

RANDOM_OPS = int(os.environ.get("BUS_OPS", "3000"))

clock_task = None


class Bench:
    """Holds the inputs, and collects bytes and pulses seen each cycle."""

    def __init__(self, dut):
        self.dut = dut
        self.bytes = []
        self.pulses = {}

    def clear(self):
        self.bytes = []
        self.pulses = {}

    async def tick(self, d_nibble=None):
        """Run one cycle, optionally with a D_VALID from the MCU."""
        dut = self.dut
        dut.d_valid.value = int(d_nibble is not None)
        dut.d_data.value = d_nibble or 0
        await Timer(1, unit="ns")
        if int(dut.o_valid.value):
            self.bytes.append(int(dut.o_data.value))
        pulses = {}
        for name in ("req_done", "store_byte_taken", "load_nibble_valid", "redirect_done",
                     "redirect_ack", "halt_done"):
            pulses[name] = int(getattr(dut, name).value)
            self.pulses[name] = self.pulses.get(name, 0) + pulses[name]
        await FallingEdge(dut.clk)
        return pulses

    async def run(self, cycles=8):
        for _ in range(cycles):
            await self.tick()


async def reset(dut):
    # cocotb cancels running tasks when a test ends, so each test needs a clock.
    global clock_task
    if clock_task is None or clock_task.done():
        clock_task = Clock(dut.clk, 10, unit="ns").start()
    for name in ("d_valid", "d_data", "req_valid", "req_is_store", "req_size", "req_addr",
                 "store_byte", "load_done", "redirect_valid", "redirect_addr", "halt_valid",
                 "halt_reason"):
        getattr(dut, name).value = 0
    dut.rst_n.value = 0
    for _ in range(3):
        await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    return Bench(dut)


async def send_frame(bench, name, done):
    """Hold request `name` high until its done pulse."""
    dut = bench.dut
    getattr(dut, name).value = 1
    for _ in range(12):
        if (await bench.tick())[done]:
            getattr(dut, name).value = 0
            return
    raise AssertionError(f"{name} never finished")


async def send_load(bench, addr):
    bench.dut.req_is_store.value = 0
    bench.dut.req_addr.value = addr
    await send_frame(bench, "req_valid", "req_done")


async def send_store(bench, size, addr, data=0):
    dut = bench.dut
    dut.req_is_store.value = 1
    dut.req_size.value = size
    dut.req_addr.value = addr
    dut.store_byte.value = data
    await send_frame(bench, "req_valid", "req_done")


async def send_redirect(bench, addr):
    bench.dut.redirect_addr.value = addr
    await send_frame(bench, "redirect_valid", "redirect_done")


async def finish_load(bench):
    for _ in range(7):
        await bench.tick(1)
    bench.dut.load_done.value = 1
    await bench.tick(1)
    bench.dut.load_done.value = 0


@cocotb.test()
async def test_idle_after_reset(dut):
    bench = await reset(dut)
    await bench.run()
    assert bench.bytes == []


@cocotb.test()
async def test_uio_mapping_values(dut):
    """Header values from the frame table in docs/architecture.md."""
    bench = await reset(dut)
    await send_load(bench, 0xBEEF)
    assert bench.bytes == [0x40, 0xEF, 0xBE]


@cocotb.test()
async def test_store_frames(dut):
    bench = await reset(dut)
    for size, count, header in ((0, 1, 0x80), (1, 2, 0x90), (2, 4, 0xA0)):
        bench.clear()
        await send_store(bench, size, 0x1234, 0x5A)
        assert bench.bytes == [header, 0x34, 0x12] + [0x5A] * count
        assert bench.pulses["store_byte_taken"] == count
        assert bench.pulses["req_done"] == 1


@cocotb.test()
async def test_redirect_frame(dut):
    bench = await reset(dut)
    await send_redirect(bench, 0x4321)
    assert bench.bytes == [0x00, 0x21, 0x43]


@cocotb.test()
async def test_halt_frames(dut):
    bench = await reset(dut)
    for reason in range(3):
        bench.clear()
        dut.halt_reason.value = reason
        await send_frame(bench, "halt_valid", "halt_done")
        assert bench.bytes == [0xC0 | reason, 0, 0]
        pulses = await bench.tick(3)
        assert pulses["redirect_ack"] == 0, "a halt frame has no response"


@cocotb.test()
async def test_load_does_not_take_store_bytes(dut):
    bench = await reset(dut)
    await send_load(bench, 0x10)
    assert bench.pulses["store_byte_taken"] == 0


@cocotb.test()
async def test_second_load_waits_for_the_first(dut):
    bench = await reset(dut)
    await send_load(bench, 0x10)
    bench.clear()
    dut.req_addr.value = 0x20
    dut.req_valid.value = 1
    await bench.run()
    assert bench.bytes == []
    dut.req_valid.value = 0
    await finish_load(bench)
    await send_load(bench, 0x20)
    assert bench.bytes == [0x40, 0x20, 0x00]


@cocotb.test()
async def test_redirect_waits_for_a_load(dut):
    bench = await reset(dut)
    await send_load(bench, 0x10)
    bench.clear()
    dut.redirect_valid.value = 1
    dut.redirect_addr.value = 0x30
    await bench.run()
    assert bench.bytes == []
    await finish_load(bench)
    await send_frame(bench, "redirect_valid", "redirect_done")
    assert bench.bytes == [0x00, 0x30, 0x00]


@cocotb.test()
async def test_load_waits_for_a_redirect(dut):
    bench = await reset(dut)
    await send_redirect(bench, 0x30)
    bench.clear()
    dut.req_is_store.value = 0
    dut.req_addr.value = 0x10
    dut.req_valid.value = 1
    await bench.run()
    assert bench.bytes == []
    assert (await bench.tick(0))["redirect_ack"] == 1
    await send_frame(bench, "req_valid", "req_done")
    assert bench.bytes == [0x40, 0x10, 0x00]


@cocotb.test()
async def test_store_passes_an_outstanding_load(dut):
    bench = await reset(dut)
    await send_load(bench, 0x10)
    bench.clear()
    await send_store(bench, 0, 0x20, 0x77)
    assert bench.bytes == [0x80, 0x20, 0x00, 0x77]


@cocotb.test()
async def test_store_passes_an_outstanding_redirect(dut):
    bench = await reset(dut)
    await send_redirect(bench, 0x30)
    bench.clear()
    await send_store(bench, 0, 0x20, 0x77)
    assert bench.bytes == [0x80, 0x20, 0x00, 0x77]
    assert (await bench.tick(0))["redirect_ack"] == 1


@cocotb.test()
async def test_store_keeps_load_state(dut):
    """A store starting while a load waits must not forget that load."""
    bench = await reset(dut)
    await send_load(bench, 0x10)
    await send_store(bench, 0, 0x20)
    assert (await bench.tick(5))["load_nibble_valid"] == 1


@cocotb.test()
async def test_store_keeps_redirect_state(dut):
    bench = await reset(dut)
    await send_redirect(bench, 0x10)
    await send_store(bench, 0, 0x20)
    assert (await bench.tick(5))["redirect_ack"] == 1


@cocotb.test()
async def test_d_valid_goes_to_the_right_place(dut):
    bench = await reset(dut)
    pulses = await bench.tick(3)
    assert pulses["load_nibble_valid"] == 0 and pulses["redirect_ack"] == 0, "stray D_VALID"

    await send_load(bench, 0)
    pulses = await bench.tick(9)
    assert pulses["load_nibble_valid"] == 1 and pulses["redirect_ack"] == 0
    assert int(dut.load_nibble.value) == 9
    await finish_load(bench)

    await send_redirect(bench, 0)
    pulses = await bench.tick(9)
    assert pulses["load_nibble_valid"] == 0 and pulses["redirect_ack"] == 1
    pulses = await bench.tick(9)
    assert pulses["redirect_ack"] == 0, "a second pulse is stray"


@cocotb.test()
async def test_priority_halt_then_lsu_then_redirect(dut):
    bench = await reset(dut)
    dut.halt_valid.value = 1
    dut.req_valid.value = 1
    dut.req_is_store.value = 1
    dut.redirect_valid.value = 1
    await bench.tick()
    await bench.tick()
    assert bench.bytes[0] == 0xC0
    await bench.run(2)
    dut.halt_valid.value = 0
    bench.clear()
    await bench.run(2)
    assert bench.bytes[0] == 0x80
    bench.dut.req_valid.value = 0


@cocotb.test()
async def test_frames_can_follow_directly(dut):
    bench = await reset(dut)
    await send_store(bench, 0, 0x01, 0xAA)
    await send_store(bench, 0, 0x02, 0xBB)
    assert bench.bytes == [0x80, 0x01, 0, 0xAA, 0x80, 0x02, 0, 0xBB]


@cocotb.test()
async def test_reset_clears_outstanding_state(dut):
    bench = await reset(dut)
    await send_load(bench, 0x10)
    bench = await reset(dut)
    pulses = await bench.tick(3)
    assert pulses["load_nibble_valid"] == 0
    await send_load(bench, 0x10)
    assert bench.bytes == [0x40, 0x10, 0x00]


@cocotb.test()
async def test_random_traffic(dut):
    """A Python MCU parses every frame. Loads and redirects must never overlap."""
    r = random.Random(1)
    bench = await reset(dut)
    want = []
    outstanding = None
    for _ in range(RANDOM_OPS):
        kind = r.randrange(3)
        addr = r.randrange(0x10000)
        if kind == 2:
            size, data = r.randrange(3), r.randrange(256)
            await send_store(bench, size, addr, data)
            want.append([0x80 | size << 4, addr & 0xFF, addr >> 8] + [data] * (1 << size))
            continue
        # The core never starts a second one, which the bus must also enforce.
        if outstanding == "load":
            await finish_load(bench)
        elif outstanding == "redirect":
            assert (await bench.tick(0))["redirect_ack"] == 1
        outstanding = None
        if kind == 0:
            await send_load(bench, addr)
            want.append([0x40, addr & 0xFF, addr >> 8])
            outstanding = "load"
        else:
            await send_redirect(bench, addr)
            want.append([0x00, addr & 0xFF, addr >> 8])
            outstanding = "redirect"
    assert bench.bytes == [b for frame in want for b in frame]
