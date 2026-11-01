"""cocotb tests for src/issue_queue.sv."""
import os
import random
from dataclasses import dataclass, field

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, Timer

RANDOM_CYCLES = int(os.environ.get("IQ_CYCLES", "50000"))
PTAG_ZERO = 31

clock_task = None


@dataclass
class Uop:
    src1: int = PTAG_ZERO
    src2: int = PTAG_ZERO
    ready1: int = 1
    ready2: int = 1
    uop_class: int = 0
    alu_op: int = 0
    mem_op: int = 0
    b_is_imm: int = 0
    imm: int = 0
    pdst: int = 0
    rob_tag: int = 0
    id: int = field(default=0, compare=False)


def idle(dut):
    dut.alloc_valid.value = 0
    dut.wakeup_valid.value = 0
    dut.wakeup_tag.value = 0
    dut.issue_hold.value = 0


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


def drive_alloc(dut, uop):
    dut.alloc_valid.value = 1
    dut.alloc_class.value = uop.uop_class
    dut.alloc_alu_op.value = uop.alu_op
    dut.alloc_mem_op.value = uop.mem_op
    dut.alloc_b_is_imm.value = uop.b_is_imm
    dut.alloc_imm.value = uop.imm
    dut.alloc_pdst.value = uop.pdst
    dut.alloc_rob_tag.value = uop.rob_tag
    dut.alloc_src1.value = uop.src1
    dut.alloc_src1_ready.value = uop.ready1
    dut.alloc_src2.value = uop.src2
    dut.alloc_src2_ready.value = uop.ready2


async def tick(dut, alloc=None, wakeup=None, hold=0):
    """Drive one cycle, from one falling edge to the next.

    Returns (alloc_ready, issued), where issued is the fields of the instruction
    issuing this cycle, or None.
    """
    idle(dut)
    if alloc is not None:
        drive_alloc(dut, alloc)
    if wakeup is not None:
        dut.wakeup_valid.value = 1
        dut.wakeup_tag.value = wakeup
    dut.issue_hold.value = hold
    await Timer(1, unit="ns")
    alloc_ready = int(dut.alloc_ready.value)
    issued = None
    if int(dut.issue_valid.value):
        issued = Uop(
            src1=int(dut.issue_src1.value),
            src2=int(dut.issue_src2.value),
            uop_class=int(dut.issue_class.value),
            alu_op=int(dut.issue_alu_op.value),
            mem_op=int(dut.issue_mem_op.value),
            b_is_imm=int(dut.issue_b_is_imm.value),
            imm=int(dut.issue_imm.value),
            pdst=int(dut.issue_pdst.value),
            rob_tag=int(dut.issue_rob_tag.value),
        )
    await FallingEdge(dut.clk)
    return alloc_ready, issued


@cocotb.test()
async def test_reset_is_empty(dut):
    await reset(dut)
    ready, issued = await tick(dut)
    assert ready == 1
    assert issued is None


@cocotb.test()
async def test_issue_is_the_cycle_after_alloc(dut):
    await reset(dut)
    _, issued = await tick(dut, alloc=Uop())
    assert issued is None, "issued during D"
    _, issued = await tick(dut)
    assert issued is not None


@cocotb.test()
async def test_all_fields_reach_issue(dut):
    await reset(dut)
    uop = Uop(src1=3, src2=7, uop_class=4, alu_op=12, mem_op=5, b_is_imm=1,
              imm=0xABC, pdst=18, rob_tag=2)
    await tick(dut, alloc=uop)
    _, issued = await tick(dut)
    expected = Uop(src1=3, src2=7, uop_class=4, alu_op=12, mem_op=5, b_is_imm=1,
                   imm=0xABC, pdst=18, rob_tag=2)
    assert issued == expected


@cocotb.test()
async def test_issues_once(dut):
    await reset(dut)
    await tick(dut, alloc=Uop())
    assert (await tick(dut))[1] is not None
    for _ in range(4):
        assert (await tick(dut))[1] is None


@cocotb.test()
async def test_waits_for_both_sources(dut):
    await reset(dut)
    await tick(dut, alloc=Uop(src1=4, ready1=0, src2=5, ready2=0))
    assert (await tick(dut))[1] is None
    assert (await tick(dut, wakeup=4))[1] is None
    assert (await tick(dut))[1] is None, "issued with src2 not ready"
    assert (await tick(dut, wakeup=5))[1] is None
    assert (await tick(dut))[1] is not None


@cocotb.test()
async def test_issue_is_after_wakeup_not_during(dut):
    """Issuing during W would read the latch while it is open."""
    await reset(dut)
    await tick(dut, alloc=Uop(src1=4, ready1=0))
    _, during = await tick(dut, wakeup=4)
    assert during is None
    _, after = await tick(dut)
    assert after is not None


@cocotb.test()
async def test_one_wakeup_wakes_both_sources(dut):
    await reset(dut)
    await tick(dut, alloc=Uop(src1=6, ready1=0, src2=6, ready2=0))
    await tick(dut, wakeup=6)
    assert (await tick(dut))[1] is not None


@cocotb.test()
async def test_wakeup_reaches_only_matching_sources(dut):
    await reset(dut)
    await tick(dut, alloc=Uop(src1=4, ready1=0, src2=5, ready2=0))
    for tag in (0, 3, 6, 18, PTAG_ZERO):
        await tick(dut, wakeup=tag)
    dut.wakeup_valid.value = 0
    dut.wakeup_tag.value = 4
    await FallingEdge(dut.clk)  # a tag without wakeup_valid is not a wakeup
    assert (await tick(dut))[1] is None


@cocotb.test()
async def test_first_cycle_wakeup_is_not_missed(dut):
    """A wakeup in the first cycle after alloc must reach the new entry."""
    await reset(dut)
    await tick(dut, alloc=Uop(src1=9, ready1=0))
    await tick(dut, wakeup=9)
    assert (await tick(dut))[1] is not None


@cocotb.test()
async def test_alloc_ready_bits_are_stored(dut):
    """The ready bits carry the bypass from prf, for a wakeup during alloc."""
    await reset(dut)
    await tick(dut, alloc=Uop(src1=9, ready1=1, src2=10, ready2=1), wakeup=9)
    assert (await tick(dut))[1] is not None


@cocotb.test()
async def test_wakeup_during_alloc_reaches_the_other_entry(dut):
    await reset(dut)
    await tick(dut, alloc=Uop(src1=4, ready1=0, pdst=1))
    await tick(dut, alloc=Uop(src1=5, ready1=0, pdst=2), wakeup=4)
    _, issued = await tick(dut)
    assert issued is not None and issued.pdst == 1


@cocotb.test()
async def test_hold_blocks_issue_for_that_cycle(dut):
    await reset(dut)
    await tick(dut, alloc=Uop(pdst=3))
    assert (await tick(dut, hold=1))[1] is None
    assert (await tick(dut, hold=1))[1] is None
    _, issued = await tick(dut)
    assert issued is not None and issued.pdst == 3


@cocotb.test()
async def test_wakeup_is_not_lost_during_hold(dut):
    await reset(dut)
    await tick(dut, alloc=Uop(src1=8, ready1=0))
    await tick(dut, wakeup=8, hold=1)
    assert (await tick(dut))[1] is not None


@cocotb.test()
async def test_full_ignores_same_cycle_issue(dut):
    await reset(dut)
    await tick(dut, alloc=Uop(pdst=1))
    await tick(dut, alloc=Uop(pdst=2), hold=1)
    ready, issued = await tick(dut)
    assert ready == 0 and issued is not None
    ready, issued = await tick(dut)
    assert ready == 1 and issued is not None


@cocotb.test()
async def test_alloc_while_full_is_dropped(dut):
    await reset(dut)
    await tick(dut, alloc=Uop(pdst=1), hold=1)
    await tick(dut, alloc=Uop(pdst=2), hold=1)
    await tick(dut, alloc=Uop(pdst=3), hold=1)
    seen = [(await tick(dut))[1].pdst, (await tick(dut))[1].pdst]
    assert seen == [1, 2]
    assert (await tick(dut))[1] is None


@cocotb.test()
async def test_slot_zero_issues_first(dut):
    await reset(dut)
    await tick(dut, alloc=Uop(pdst=1), hold=1)
    await tick(dut, alloc=Uop(pdst=2), hold=1)
    assert (await tick(dut))[1].pdst == 1
    assert (await tick(dut))[1].pdst == 2


@cocotb.test()
async def test_ready_entry_passes_a_waiting_one(dut):
    """This is the out-of-order part: the younger instruction goes first."""
    await reset(dut)
    await tick(dut, alloc=Uop(src1=4, ready1=0, pdst=1))
    await tick(dut, alloc=Uop(pdst=2))
    _, issued = await tick(dut)
    assert issued is not None and issued.pdst == 2
    assert (await tick(dut, wakeup=4))[1] is None
    assert (await tick(dut))[1].pdst == 1


@cocotb.test()
async def test_freed_entries_are_reused(dut):
    await reset(dut)
    await tick(dut, alloc=Uop(src1=4, ready1=0, pdst=1))
    await tick(dut, alloc=Uop(pdst=2))
    await tick(dut, alloc=Uop(pdst=9))  # full, so this is not accepted
    await tick(dut)
    await tick(dut, alloc=Uop(src1=5, ready1=0, pdst=3))  # goes in the freed slot 1
    await tick(dut, wakeup=5)
    assert (await tick(dut))[1].pdst == 3
    await tick(dut, wakeup=4)
    assert (await tick(dut))[1].pdst == 1


@cocotb.test()
async def test_reset_empties_the_queue(dut):
    await reset(dut)
    await tick(dut, alloc=Uop(pdst=1), hold=1)
    await tick(dut, alloc=Uop(pdst=2), hold=1)
    await reset(dut)
    ready, issued = await tick(dut)
    assert ready == 1 and issued is None
    assert (await tick(dut))[1] is None


def fields(uop):
    return (uop.uop_class, uop.alu_op, uop.mem_op, uop.b_is_imm, uop.imm,
            uop.pdst, uop.rob_tag, uop.src1, uop.src2)


@cocotb.test()
async def test_random_traffic(dut):
    """Each instruction must issue exactly once, intact, and only once its sources
    were woken by an earlier cycle. Anything ready and unheld must issue."""
    r = random.Random(1)
    await reset(dut)
    held = []  # instructions accepted and not yet issued, as [uop, waiting_tags]
    pending = []  # tags with a wakeup still to come
    accepted = issued_count = passed = 0

    for _ in range(RANDOM_CYCLES):
        alloc = None
        if r.random() < 0.45:
            tags = list(range(19))
            r.shuffle(tags)
            # A tag is waited for by at most two sources, and is woken only once.
            uop = Uop(
                uop_class=r.randrange(5), alu_op=r.randrange(16), mem_op=r.randrange(8),
                b_is_imm=r.randrange(2), imm=r.getrandbits(12), pdst=r.randrange(32),
                rob_tag=r.randrange(4),
            )
            uop.src1, uop.src2 = tags[0], tags[1]
            uop.ready1, uop.ready2 = r.randrange(2), r.randrange(2)
            alloc = uop

        wakeup = None
        if pending and r.random() < 0.4:
            wakeup = pending.pop(r.randrange(len(pending)))
        hold = int(r.random() < 0.15)

        must_issue = any(not waiting for _, waiting in held) and not hold

        ready, issued = await tick(dut, alloc=alloc, wakeup=wakeup, hold=hold)

        assert ready == int(len(held) < 2)
        if hold:
            assert issued is None
        if must_issue:
            assert issued is not None, "a ready instruction did not issue"

        if issued is not None:
            match = [e for e in held if fields(e[0]) == fields(issued)]
            assert match, "issued an instruction that was not held"
            assert not match[0][1], "issued with a source still waiting"
            if held[0] is not match[0]:
                passed += 1
            held.remove(match[0])
            issued_count += 1

        for _, waiting in held:
            waiting.discard(wakeup)

        if alloc is not None and ready:
            waiting = set()
            if not alloc.ready1:
                waiting.add(alloc.src1)
            if not alloc.ready2:
                waiting.add(alloc.src2)
            pending.extend(tag for tag in waiting if tag not in pending)
            held.append([alloc, waiting])
            accepted += 1

    assert accepted > RANDOM_CYCLES // 10
    assert issued_count > RANDOM_CYCLES // 10
    if RANDOM_CYCLES >= 10000:
        assert passed > 100, "the test never exercised out-of-order issue"
