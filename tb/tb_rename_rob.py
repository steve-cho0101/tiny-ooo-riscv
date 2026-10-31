"""cocotb tests for src/rename_rob.sv.

Directed tests cover the known corner cases. test_random_dataflow runs real
values through the renamed tags with random completion order, and compares
every retired result with plain in-order execution, so it checks behaviour
rather than repeating the RTL's algorithm.
"""
import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, Timer

NPHYS = 19
PTAG_ZERO = 31
MASK = 0xFFFFFFFF
RANDOM_INSTRUCTIONS = int(os.environ.get("RR_INSTRUCTIONS", "5000"))


def rat_map(dut):
    """Return {x1..x15: physical register}."""
    v = dut.rat.value.to_unsigned()
    return {x: (v >> (5 * (x - 1))) & 31 for x in range(1, 16)}


def slot_map(dut):
    v = dut.slot_p.value.to_unsigned()
    return [(v >> (5 * i)) & 31 for i in range(4)]


def check_permutation(dut):
    held = sorted(list(rat_map(dut).values()) + slot_map(dut))
    assert held == list(range(NPHYS)), f"physical registers not a permutation: {held}"


clock_task = None


async def reset(dut):
    # cocotb cancels running tasks when a test ends, so each test needs a clock.
    global clock_task
    if clock_task is None or clock_task.done():
        clock_task = Clock(dut.clk, 10, unit="ns").start()
    idle(dut)
    dut.rst_n.value = 0
    for _ in range(3):
        await FallingEdge(dut.clk)
    dut.rst_n.value = 1


def idle(dut):
    dut.alloc_valid.value = 0
    dut.alloc_rd.value = 0
    dut.alloc_rs1.value = 0
    dut.alloc_rs2.value = 0
    dut.alloc_done.value = 0
    dut.alloc_halt.value = 0
    dut.complete_valid.value = 0
    dut.complete_tag.value = 0
    dut.retire_ready.value = 1


async def cycle(dut, alloc=None, complete=None, retire_ready=1):
    """Drive one cycle from a falling edge and return outputs seen before the rising edge.

    alloc is (rd, rs1, rs2) with optional done and halt flags. complete is a tag.
    """
    idle(dut)
    dut.retire_ready.value = retire_ready
    if alloc is not None:
        rd, rs1, rs2, *flags = alloc
        dut.alloc_valid.value = 1
        dut.alloc_rd.value = rd
        dut.alloc_rs1.value = rs1
        dut.alloc_rs2.value = rs2
        dut.alloc_done.value = flags[0] if len(flags) > 0 else 0
        dut.alloc_halt.value = flags[1] if len(flags) > 1 else 0
    if complete is not None:
        dut.complete_valid.value = 1
        dut.complete_tag.value = complete
    await Timer(1, unit="ns")
    out = {
        "alloc_ready": int(dut.alloc_ready.value),
        "tag": int(dut.alloc_tag.value),
        "pdst": int(dut.alloc_pdst.value),
        "psrc1": int(dut.alloc_psrc1.value),
        "psrc2": int(dut.alloc_psrc2.value),
        "retire_valid": int(dut.retire_valid.value),
        "retire_halt": int(dut.retire_halt.value),
        "head": int(dut.head_tag.value),
        "empty": int(dut.rob_empty.value),
    }
    check_permutation(dut)
    await FallingEdge(dut.clk)
    return out


@cocotb.test()
async def test_reset_state(dut):
    await reset(dut)
    assert rat_map(dut) == {x: x - 1 for x in range(1, 16)}
    assert slot_map(dut) == [15, 16, 17, 18]
    out = await cycle(dut)
    assert out["empty"] == 1
    assert out["alloc_ready"] == 1
    assert out["retire_valid"] == 0
    assert out["tag"] == 0


@cocotb.test()
async def test_x0_is_never_renamed(dut):
    await reset(dut)
    before = rat_map(dut), slot_map(dut)
    out = await cycle(dut, alloc=(0, 0, 0))
    assert out["pdst"] == PTAG_ZERO
    assert out["psrc1"] == PTAG_ZERO
    assert out["psrc2"] == PTAG_ZERO
    assert (rat_map(dut), slot_map(dut)) == before
    assert (await cycle(dut))["empty"] == 0, "x0 instruction must still take a slot"


@cocotb.test()
async def test_sources_read_before_swap(dut):
    """add x1, x1, x1 must read the old x1, or it would wait on itself."""
    await reset(dut)
    old = rat_map(dut)[1]
    out = await cycle(dut, alloc=(1, 1, 1))
    assert out["psrc1"] == old
    assert out["psrc2"] == old
    assert out["pdst"] == 15
    assert rat_map(dut)[1] == 15
    assert slot_map(dut)[0] == old


@cocotb.test()
async def test_chained_writes_to_one_register(dut):
    """WAW: each write gets its own register, and readers follow the chain."""
    await reset(dut)
    last = rat_map(dut)[5]
    seen = set()
    for _ in range(4):
        out = await cycle(dut, alloc=(5, 5, 0))
        assert out["psrc1"] == last
        assert out["pdst"] not in seen
        seen.add(out["pdst"])
        last = out["pdst"]
    assert seen == {15, 16, 17, 18}


@cocotb.test()
async def test_full_rob_ignores_alloc(dut):
    await reset(dut)
    for _ in range(4):
        assert (await cycle(dut, alloc=(1, 0, 0)))["alloc_ready"] == 1
    before = rat_map(dut), slot_map(dut)
    out = await cycle(dut, alloc=(2, 0, 0))
    assert out["alloc_ready"] == 0
    assert (rat_map(dut), slot_map(dut)) == before, "full ROB changed rename state"

    # Ready must not depend on a same-cycle retirement.
    await cycle(dut, complete=0)
    out = await cycle(dut, alloc=(2, 0, 0))
    assert out["retire_valid"] == 1
    assert out["alloc_ready"] == 0
    assert (await cycle(dut))["alloc_ready"] == 1


@cocotb.test()
async def test_out_of_order_completion_retires_in_order(dut):
    await reset(dut)
    for i in range(4):
        await cycle(dut, alloc=(i + 1, 0, 0))
    for tag in (2, 3, 1):
        out = await cycle(dut, complete=tag)
        assert out["retire_valid"] == 0, "retired past the unfinished head"
    await cycle(dut, complete=0)
    for expect in range(4):
        out = await cycle(dut)
        assert out["retire_valid"] == 1
        assert out["head"] == expect
    assert (await cycle(dut))["empty"] == 1


@cocotb.test()
async def test_alloc_and_retire_same_cycle(dut):
    await reset(dut)
    await cycle(dut, alloc=(1, 0, 0, 1), retire_ready=0)
    await cycle(dut, alloc=(2, 0, 0, 1), retire_ready=0)
    assert int(dut.count.value) == 2
    out = await cycle(dut, alloc=(3, 0, 0, 1))
    assert out["retire_valid"] == 1 and out["alloc_ready"] == 1
    assert int(dut.count.value) == 2, "simultaneous alloc and retire changed the count"


@cocotb.test()
async def test_alloc_and_complete_same_cycle(dut):
    await reset(dut)
    await cycle(dut, alloc=(1, 0, 0))
    await cycle(dut, alloc=(2, 0, 0), complete=0)
    out = await cycle(dut)
    assert out["retire_valid"] == 1 and out["head"] == 0
    assert int(dut.done.value) & 2 == 0, "new entry must not inherit a completion"


@cocotb.test()
async def test_slot_reuse_clears_done(dut):
    """A reused slot must not look finished because of its previous instruction."""
    await reset(dut)
    for _ in range(4):
        await cycle(dut, alloc=(1, 0, 0, 1))
        await cycle(dut)
    for tag in range(4):
        await cycle(dut, alloc=(1, 0, 0))
    assert (await cycle(dut))["retire_valid"] == 0


@cocotb.test()
async def test_tag_wraparound(dut):
    await reset(dut)
    for n in range(40):
        out = await cycle(dut, alloc=(1 + n % 15, 0, 0, 1))
        assert out["tag"] == n % 4
        out = await cycle(dut)
        assert out["retire_valid"] == 1 and out["head"] == n % 4


@cocotb.test()
async def test_retire_ready_holds_the_head(dut):
    await reset(dut)
    await cycle(dut, alloc=(0, 0, 0, 1, 1))
    for _ in range(3):
        out = await cycle(dut, retire_ready=0)
        assert out["retire_valid"] == 1
        assert out["retire_halt"] == 1
        assert out["empty"] == 0
    await cycle(dut, retire_ready=1)
    assert (await cycle(dut))["empty"] == 1


@cocotb.test()
async def test_reset_while_in_flight(dut):
    await reset(dut)
    await cycle(dut, alloc=(3, 1, 2))
    await cycle(dut, alloc=(4, 3, 2, 1))
    await reset(dut)
    assert rat_map(dut) == {x: x - 1 for x in range(1, 16)}
    assert slot_map(dut) == [15, 16, 17, 18]
    out = await cycle(dut)
    assert out["empty"] == 1 and out["tag"] == 0 and out["head"] == 0
    assert out["retire_valid"] == 0


def alu(op, a, b):
    return {0: (a + b) & MASK, 1: (a - b) & MASK, 2: a ^ b, 3: a & b}[op]


async def run_dataflow(dut, seed, n, p_alloc, p_complete, p_retire):
    r = random.Random(seed)
    await reset(dut)

    prf = {p: r.getrandbits(32) for p in range(NPHYS)}
    prf[PTAG_ZERO] = 0
    ready = {p: True for p in prf}
    golden = {x: prf[p] for x, p in rat_map(dut).items()}
    golden[0] = 0

    rob = []         # in-flight instructions, oldest first
    generated = 0
    retired = 0
    issued_ahead = 0
    limit = 200 * n + 1000

    for _ in range(limit):
        if retired == n:
            break

        # Finish one instruction whose sources are available, in any order.
        waiting = [
            e for e in rob
            if not e["done"] and ready[e["p1"]] and ready[e["p2"]]
        ]
        finish = r.choice(waiting) if waiting and r.random() < p_complete else None

        alloc = None
        if generated < n and r.random() < p_alloc:
            rd = 0 if r.random() < 0.15 else r.randrange(1, 16)
            alloc = (rd, r.randrange(16), r.randrange(16), int(r.random() < 0.1))
        retire_ready = int(r.random() < p_retire)

        out = await cycle(
            dut,
            alloc=alloc,
            complete=finish["tag"] if finish else None,
            retire_ready=retire_ready,
        )

        # Outputs must match what this cycle's in-flight state requires.
        assert out["alloc_ready"] == int(len(rob) < 4)
        assert out["empty"] == int(not rob)
        head_done = bool(rob) and rob[0]["done"]
        assert out["retire_valid"] == int(head_done)

        if finish:
            if any(e["seq"] < finish["seq"] and not e["done"] for e in rob):
                issued_ahead += 1
            value = alu(finish["op"], prf[finish["p1"]], prf[finish["p2"]])
            finish["value"] = value
            finish["done"] = True
            if finish["pd"] != PTAG_ZERO:
                prf[finish["pd"]] = value
                ready[finish["pd"]] = True

        if out["retire_valid"] and retire_ready:
            e = rob.pop(0)
            assert out["head"] == e["tag"]
            assert e["value"] == e["expect"], (
                f"seed {seed} instruction {e['seq']}: got {e['value']:#x}, "
                f"expected {e['expect']:#x}"
            )
            retired += 1

        if alloc and out["alloc_ready"]:
            rd, rs1, rs2, instant = alloc
            pd = out["pdst"]
            assert (pd == PTAG_ZERO) == (rd == 0)
            if pd != PTAG_ZERO:
                assert ready[pd], f"p{pd} allocated with a write still in flight"
                readers = {x for e in rob if not e["done"] for x in (e["p1"], e["p2"])}
                assert pd not in readers, f"p{pd} allocated with a reader in flight"
            op = r.randrange(4)
            if instant:
                # Dispatch write: the value is known and needs no sources.
                expect = r.getrandbits(32)
                p1 = p2 = PTAG_ZERO
            else:
                expect = alu(op, golden[rs1], golden[rs2])
                p1, p2 = out["psrc1"], out["psrc2"]
            if rd:
                golden[rd] = expect
            entry = dict(
                seq=generated, tag=out["tag"], op=op, p1=p1, p2=p2, pd=pd,
                expect=expect, done=False, value=None,
            )
            if pd != PTAG_ZERO:
                ready[pd] = False
            if instant:
                entry.update(done=True, value=expect)
                if pd != PTAG_ZERO:
                    prf[pd] = expect
                    ready[pd] = True
            rob.append(entry)
            generated += 1
    else:
        raise AssertionError(f"seed {seed}: no forward progress, retired {retired} of {n}")

    final = rat_map(dut)
    for x in range(1, 16):
        assert prf[final[x]] == golden[x], f"x{x} wrong after drain"
    return issued_ahead


@cocotb.test()
async def test_random_dataflow(dut):
    """Random programs under varied pressure, including a mostly full ROB."""
    profiles = [
        (0.9, 0.5, 0.9),   # steady flow
        (1.0, 0.2, 0.3),   # ROB mostly full
        (0.3, 0.9, 1.0),   # ROB mostly empty
        (1.0, 1.0, 1.0),   # maximum rate
    ]
    total = 0
    ahead = 0
    for seed in range(20):
        p = profiles[seed % len(profiles)]
        ahead += await run_dataflow(dut, seed, RANDOM_INSTRUCTIONS, *p)
        total += RANDOM_INSTRUCTIONS
    dut._log.info("Retired %d instructions, %d finished ahead of an older one", total, ahead)
    assert ahead > total // 20, "stimulus produced too little out-of-order completion"
