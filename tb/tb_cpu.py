"""Whole-core tests. Every program also runs on the in-order reference model, and the
core must make the same stores in the same order and halt the same way."""
import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge

from mcu import Mcu
from randprog import generate
from refmodel import Model

RANDOM_PROGRAMS = int(os.environ.get("CPU_PROGRAMS", "24"))
IMAGES = os.environ.get("CPU_IMAGES", "")

WAIT_LOAD = 2  # lsu state

clock_task = None


async def reset(dut):
    # cocotb cancels running tasks when a test ends, so each test needs a clock.
    global clock_task
    if clock_task is None or clock_task.done():
        clock_task = Clock(dut.clk, 10, unit="ns").start()
    dut.i_valid.value = 0
    dut.i_data.value = 0
    dut.d_valid.value = 0
    dut.d_data.value = 0
    dut.rst_n.value = 0
    for _ in range(4):
        await FallingEdge(dut.clk)
    dut.rst_n.value = 1


def state(dut):
    """What the core is waiting on, for a test that stops making progress."""
    names = ("u_fetch.pc", "u_fetch.instr_valid", "u_fetch.instr", "u_fetch.redirecting",
             "can_dispatch", "control_wait", "mem_busy", "stopped",
             "u_rename_rob.count", "u_rename_rob.head", "u_rename_rob.done",
             "u_issue_queue.valid", "u_issue_queue.src1_ready", "u_issue_queue.src2_ready",
             "u_issue_queue.src1", "u_issue_queue.src2", "u_issue_queue.uop_class",
             "u_lsu.state", "u_bus_if.wait_load", "u_bus_if.wait_ack", "u_bus_if.active")
    out = []
    for name in names:
        node = dut
        for part in name.split("."):
            node = getattr(node, part)
        out.append(f"{name.split('.')[-1]}={node.value}")
    return " ".join(out)


def compare(name, model, mcu):
    for i, (want, got) in enumerate(zip(model.stores, mcu.stores)):
        assert want == got, f"{name}: store {i}: core {got}, model {want}"
    assert len(mcu.stores) == len(model.stores), f"{name}: store count"
    assert mcu.halt_reason == model.halt_reason, f"{name}: halt reason"


async def run(dut, name, image, rng, **timing):
    model = Model(image).run()
    await reset(dut)
    mcu = Mcu(dut, image, rng, **timing)
    try:
        await mcu.run(2000 + 200 * model.steps)
    except AssertionError:
        dut._log.error(f"{name}: {state(dut)}, model pc after run {model.pc:#x}")
        raise
    compare(name, model, mcu)
    return model, mcu


def timings(r):
    """A random memory speed, from an ideal MCU to a slow and uneven one."""
    return {
        "load_delay": r.choice(((0, 0), (0, 3), (5, 30), (40, 60))),
        "stale": r.choice(((0, 0), (0, 4), (3, 12))),
        "fetch_gap": r.choice((0.0, 0.2, 0.6)),
        "nibble_gap": r.choice((0.0, 0.3)),
    }


def words(*values):
    return b"".join(v.to_bytes(4, "little") for v in values)


@cocotb.test()
async def test_halts_on_ecall(dut):
    await run(dut, "ecall", words(0x00000073), random.Random(1))


@cocotb.test()
async def test_halts_on_ebreak(dut):
    await run(dut, "ebreak", words(0x00100073), random.Random(1))


@cocotb.test()
async def test_halts_on_illegal(dut):
    await run(dut, "illegal", words(0x00000000), random.Random(1))


@cocotb.test()
async def test_halts_on_high_register(dut):
    await run(dut, "x16", words(0x00100813), random.Random(1))  # addi x16, x0, 1


@cocotb.test()
async def test_older_store_lands_before_a_halt(dut):
    image = words(
        0x12300093,  # addi x1, x0, 0x123
        0x10102023,  # sw x1, 0x100(x0)
        0x00000000,  # illegal
    )
    await run(dut, "store then illegal", image, random.Random(1))


@cocotb.test()
async def test_random_programs(dut):
    for seed in range(RANDOM_PROGRAMS):
        r = random.Random(seed)
        await run(dut, f"random {seed}", generate(r), r, **timings(r))


@cocotb.test()
async def test_compiled_programs(dut):
    assert IMAGES, "CPU_IMAGES was not set"
    images = sorted(Path(IMAGES).glob("*.bin"))
    assert images, "no compiled programs"
    r = random.Random(1)
    for path in images:
        model, mcu = await run(dut, path.stem, path.read_bytes(), r, **timings(r))
        dut._log.info(f"{path.stem}: {model.steps} instructions, {mcu.cycles} cycles, "
                      f"result {int.from_bytes(model.stores[-1][1], 'little'):#x}")


async def count_passing(dut, totals):
    """Count instructions that finish while an older load waits for memory."""
    while True:
        await FallingEdge(dut.clk)
        if str(dut.rst_n.value) != "1":
            continue
        if int(dut.u_lsu.state.value) == WAIT_LOAD and int(dut.complete_valid.value):
            totals["passed"] += 1


@cocotb.test()
async def test_execution_is_out_of_order(dut):
    """Younger instructions must finish ahead of a slow load, and the dependent one
    must not. This is the behaviour the project exists to show."""
    image = words(
        0x10002083,  # lw x1, 0x100(x0)
        0x00100113,  # addi x2, x0, 1
        0x00110193,  # addi x3, x2, 1
        0x00118213,  # addi x4, x3, 1
        0x00108293,  # addi x5, x1, 1   depends on the load
        0x20502023,  # sw x5, 0x200(x0)
        0x00000073,  # ecall
    ).ljust(0x104, b"\0")
    totals = {"passed": 0}
    watcher = cocotb.start_soon(count_passing(dut, totals))
    await run(dut, "out of order", image, random.Random(1), load_delay=(60, 60), stale=(0, 0))
    watcher.cancel()
    assert totals["passed"] == 3, f"{totals['passed']} instructions passed the load"


@cocotb.test()
async def test_fetch_continues_during_a_load(dut):
    """Total time must follow the load alone, not the load plus the work after it."""
    async def cycles(delay):
        program = [0x10002083]  # lw x1, 0x100(x0)
        program += [0x00100113, 0x00200193]  # addi x2 and x3, independent of the load
        program += [0x00000073]
        image = words(*program).ljust(0x104, b"\0")
        _, mcu = await run(dut, f"delay {delay}", image, random.Random(1),
                           load_delay=(delay, delay), stale=(0, 0))
        return mcu.cycles

    short, long = await cycles(40), await cycles(140)
    assert long - short == 100, f"{long - short} extra cycles for 100 extra load cycles"
