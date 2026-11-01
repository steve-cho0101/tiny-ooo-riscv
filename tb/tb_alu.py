"""cocotb tests for src/alu.sv, checked against a Python model."""
import os
import random

import cocotb
from cocotb.triggers import Timer

RANDOM_OPS = int(os.environ.get("ALU_OPS", "100000"))

ADD, SUB, SLL, SLT, SLTU, XOR, SRL, SRA, OR, AND, BEQ, BNE, BLT, BGE, BLTU, BGEU = range(16)
BRANCHES = (BEQ, BNE, BLT, BGE, BLTU, BGEU)
NAMES = "ADD SUB SLL SLT SLTU XOR SRL SRA OR AND BEQ BNE BLT BGE BLTU BGEU".split()

MASK = 0xFFFFFFFF
CORNERS = (0, 1, 2, 31, 32, 0x7FFFFFFF, 0x80000000, 0x80000001, 0xFFFFFFFE, MASK, 0x55555555, 0xAAAAAAAA)


def signed(value):
    return value - (1 << 32) if value >> 31 else value


def model(op, a, b):
    """Returns the expected y, or the expected branch_taken for a branch operation."""
    shift = b & 31
    return {
        ADD: lambda: (a + b) & MASK,
        SUB: lambda: (a - b) & MASK,
        SLL: lambda: (a << shift) & MASK,
        SLT: lambda: int(signed(a) < signed(b)),
        SLTU: lambda: int(a < b),
        XOR: lambda: a ^ b,
        SRL: lambda: a >> shift,
        SRA: lambda: (signed(a) >> shift) & MASK,
        OR: lambda: a | b,
        AND: lambda: a & b,
        BEQ: lambda: int(a == b),
        BNE: lambda: int(a != b),
        BLT: lambda: int(signed(a) < signed(b)),
        BGE: lambda: int(signed(a) >= signed(b)),
        BLTU: lambda: int(a < b),
        BGEU: lambda: int(a >= b),
    }[op]()


async def check(dut, op, a, b):
    dut.op.value = op
    dut.a.value = a
    dut.b.value = b
    await Timer(1, unit="ns")
    want = model(op, a, b)
    seen = int(dut.branch_taken.value) if op in BRANCHES else int(dut.y.value)
    assert seen == want, f"{NAMES[op]} a={a:08x} b={b:08x}: got {seen:x}, want {want:x}"


@cocotb.test()
async def test_directed(dut):
    for op, a, b, want in (
        (ADD, MASK, 1, 0),
        (SUB, 0, 1, MASK),
        (SLL, 1, 31, 0x80000000),
        (SRL, 0x80000000, 31, 1),
        (SRA, 0x80000000, 31, MASK),
        (SRA, 0x40000000, 30, 1),
        (SLT, 0x80000000, 0, 1),
        (SLTU, 0x80000000, 0, 0),
        (SLT, 0x7FFFFFFF, 0x80000000, 0),
    ):
        dut.op.value = op
        dut.a.value = a
        dut.b.value = b
        await Timer(1, unit="ns")
        assert int(dut.y.value) == want, NAMES[op]


@cocotb.test()
async def test_corner_values(dut):
    for op in range(16):
        for a in CORNERS:
            for b in CORNERS:
                await check(dut, op, a, b)


@cocotb.test()
async def test_every_shift_amount(dut):
    for op in (SLL, SRL, SRA):
        for shift in range(64):  # amounts above 31 must use only the low five bits
            for a in (1, 0x80000000, 0xDEADBEEF, 0x12345678, MASK):
                await check(dut, op, a, shift)


@cocotb.test()
async def test_equal_operands(dut):
    r = random.Random(3)
    for _ in range(200):
        value = r.getrandbits(32)
        for op in (SLT, SLTU, BEQ, BNE, BLT, BGE, BLTU, BGEU):
            await check(dut, op, value, value)


@cocotb.test()
async def test_random(dut):
    r = random.Random(1)
    for _ in range(RANDOM_OPS):
        await check(dut, r.randrange(16), r.getrandbits(32), r.getrandbits(32))
