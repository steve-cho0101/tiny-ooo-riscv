"""cocotb tests for src/decode.sv.

GOLDEN holds words from riscv-none-elf-as, so those encodings do not depend on this
file's reading of the spec. reference() is a separate decoder for random words.
"""
import os
import random

import cocotb
from cocotb.triggers import Timer

RANDOM_WORDS = int(os.environ.get("DECODE_WORDS", "100000"))

ALU, LOAD, STORE, BRANCH, JALR, JAL, LUI, AUIPC, NOP, HALT = range(10)
ADD, SUB, SLL, SLT, SLTU, XOR, SRL, SRA, OR, AND, BEQ, BNE, BLT, BGE, BLTU, BGEU = range(16)

# Classes whose alu_op, b_is_imm and imm are used. The rest may leave them as anything.
USES_ALU = (ALU, LOAD, STORE, BRANCH, JALR)
USES_IMM = (LOAD, STORE, BRANCH, JALR, JAL, LUI, AUIPC)
DONE_AT_ALLOC = (JAL, LUI, AUIPC, NOP, HALT)

# word, class, alu_op, b_is_imm, rd, rs1, rs2, imm, mem_op
GOLDEN = [
    ("lui x5,0xabcde", 0xabcde2b7, LUI, None, None, 5, 0, 0, -0x54322000, None),
    ("lui x15,0xfffff", 0xfffff7b7, LUI, None, None, 15, 0, 0, -0x1000, None),
    ("auipc x6,0x12345", 0x12345317, AUIPC, None, None, 6, 0, 0, 0x12345000, None),
    ("jal x1,.+0x7fe", 0x7fe000ef, JAL, None, None, 1, 0, 0, 0x7fe, None),
    ("jal x0,.-4", 0xffdff06f, JAL, None, None, 0, 0, 0, -4, None),
    ("jalr x1,-2(x2)", 0xffe100e7, JALR, ADD, 1, 1, 2, 0, -2, None),
    ("jalr x0,0(x1)", 0x00008067, JALR, ADD, 1, 0, 1, 0, 0, None),
    ("beq x1,x2,.+4094", 0x7e208fe3, BRANCH, BEQ, 0, 0, 1, 2, 4094, None),
    ("bne x3,x4,.-4096", 0x80419063, BRANCH, BNE, 0, 0, 3, 4, -4096, None),
    ("blt x5,x6,.+8", 0x0062c463, BRANCH, BLT, 0, 0, 5, 6, 8, None),
    ("bge x7,x8,.-8", 0xfe83dce3, BRANCH, BGE, 0, 0, 7, 8, -8, None),
    ("bltu x9,x10,.+2", 0x00a4e163, BRANCH, BLTU, 0, 0, 9, 10, 2, None),
    ("bgeu x11,x12,.+16", 0x00c5f863, BRANCH, BGEU, 0, 0, 11, 12, 16, None),
    ("lb x1,-1(x2)", 0xfff10083, LOAD, ADD, 1, 1, 2, 0, -1, 0),
    ("lh x3,2047(x4)", 0x7ff21183, LOAD, ADD, 1, 3, 4, 0, 2047, 1),
    ("lw x5,-2048(x6)", 0x80032283, LOAD, ADD, 1, 5, 6, 0, -2048, 2),
    ("lbu x7,1(x8)", 0x00144383, LOAD, ADD, 1, 7, 8, 0, 1, 4),
    ("lhu x9,2(x10)", 0x00255483, LOAD, ADD, 1, 9, 10, 0, 2, 5),
    ("sb x1,-1(x2)", 0xfe110fa3, STORE, ADD, 1, 0, 2, 1, -1, 0),
    ("sh x3,2047(x4)", 0x7e321fa3, STORE, ADD, 1, 0, 4, 3, 2047, 1),
    ("sw x5,-2048(x6)", 0x80532023, STORE, ADD, 1, 0, 6, 5, -2048, 2),
    ("addi x1,x2,-1", 0xfff10093, ALU, ADD, 1, 1, 2, 0, -1, None),
    ("slti x3,x4,100", 0x06422193, ALU, SLT, 1, 3, 4, 0, 100, None),
    ("sltiu x5,x6,-5", 0xffb33293, ALU, SLTU, 1, 5, 6, 0, -5, None),
    ("xori x7,x8,0x555", 0x55544393, ALU, XOR, 1, 7, 8, 0, 0x555, None),
    ("ori x9,x10,-256", 0xf0056493, ALU, OR, 1, 9, 10, 0, -256, None),
    ("andi x11,x12,15", 0x00f67593, ALU, AND, 1, 11, 12, 0, 15, None),
    ("slli x13,x14,31", 0x01f71693, ALU, SLL, 1, 13, 14, 0, 31, None),
    ("srli x15,x1,1", 0x0010d793, ALU, SRL, 1, 15, 1, 0, 1, None),
    ("srai x2,x3,13", 0x40d1d113, ALU, SRA, 1, 2, 3, 0, None, None),
    ("add x1,x2,x3", 0x003100b3, ALU, ADD, 0, 1, 2, 3, None, None),
    ("sub x4,x5,x6", 0x40628233, ALU, SUB, 0, 4, 5, 6, None, None),
    ("sll x7,x8,x9", 0x009413b3, ALU, SLL, 0, 7, 8, 9, None, None),
    ("slt x10,x11,x12", 0x00c5a533, ALU, SLT, 0, 10, 11, 12, None, None),
    ("sltu x13,x14,x15", 0x00f736b3, ALU, SLTU, 0, 13, 14, 15, None, None),
    ("xor x1,x3,x5", 0x0051c0b3, ALU, XOR, 0, 1, 3, 5, None, None),
    ("srl x2,x4,x6", 0x00625133, ALU, SRL, 0, 2, 4, 6, None, None),
    ("sra x7,x9,x11", 0x40b4d3b3, ALU, SRA, 0, 7, 9, 11, None, None),
    ("or x8,x10,x12", 0x00c56433, ALU, OR, 0, 8, 10, 12, None, None),
    ("and x13,x15,x1", 0x0017f6b3, ALU, AND, 0, 13, 15, 1, None, None),
    ("fence", 0x0ff0000f, NOP, None, None, 0, 0, 0, None, None),
    ("fence.tso", 0x8330000f, NOP, None, None, 0, 0, 0, None, None),
    ("pause", 0x0100000f, NOP, None, None, 0, 0, 0, None, None),
]


async def apply(dut, word):
    dut.instr.value = word
    await Timer(1, unit="ns")
    return {
        "class": int(dut.uop_class.value),
        "alu_op": int(dut.alu_op.value),
        "b_is_imm": int(dut.b_is_imm.value),
        "rd": int(dut.rd.value),
        "rs1": int(dut.rs1.value),
        "rs2": int(dut.rs2.value),
        "imm": int(dut.imm.value),
        "mem_op": int(dut.mem_op.value),
        "done": int(dut.done.value),
        "halt": int(dut.halt.value),
        "reason": int(dut.halt_reason.value),
    }


def signed_bits(value, bits):
    return value - (1 << bits) if value >> (bits - 1) else value


def illegal():
    return {"class": HALT, "rd": 0, "rs1": 0, "rs2": 0, "reason": 2}


def reference(word):
    """Decode a word from docs/isa.md. Returns the expected fields, omitting don't-cares."""
    opcode = word & 0x7F
    rd, funct3 = (word >> 7) & 0x1F, (word >> 12) & 7
    rs1, rs2 = (word >> 15) & 0x1F, (word >> 20) & 0x1F
    funct7 = word >> 25
    imm_i = signed_bits(word >> 20, 12)
    imm_s = signed_bits(funct7 << 5 | rd, 12)
    imm_b = signed_bits(
        ((word >> 31) << 12) | (((word >> 7) & 1) << 11)
        | (((word >> 25) & 0x3F) << 5) | (((word >> 8) & 0xF) << 1), 13)
    imm_u = signed_bits(word & 0xFFFFF000, 32)
    imm_j = signed_bits(
        ((word >> 31) << 20) | (((word >> 12) & 0xFF) << 12)
        | (((word >> 20) & 1) << 11) | (((word >> 21) & 0x3FF) << 1), 21)

    def result(cls, op=None, b_imm=None, imm=None, mem=None, d=0, s1=0, s2=0):
        for reg in (d, s1, s2):
            if reg > 15:
                return illegal()
        out = {"class": cls, "rd": d, "rs1": s1, "rs2": s2}
        if op is not None:
            out["alu_op"], out["b_is_imm"] = op, b_imm
        if imm is not None:
            out["imm"] = imm & 0xFFFFFFFF
        if mem is not None:
            out["mem_op"] = mem
        return out

    if opcode == 0b0110111:
        return result(LUI, imm=imm_u, d=rd)
    if opcode == 0b0010111:
        return result(AUIPC, imm=imm_u, d=rd)
    if opcode == 0b1101111:
        return result(JAL, imm=imm_j, d=rd)
    if opcode == 0b1100111 and funct3 == 0:
        return result(JALR, ADD, 1, imm_i, d=rd, s1=rs1)
    if opcode == 0b1100011 and funct3 in (0, 1, 4, 5, 6, 7):
        op = {0: BEQ, 1: BNE, 4: BLT, 5: BGE, 6: BLTU, 7: BGEU}[funct3]
        return result(BRANCH, op, 0, imm_b, s1=rs1, s2=rs2)
    if opcode == 0b0000011 and funct3 in (0, 1, 2, 4, 5):
        return result(LOAD, ADD, 1, imm_i, funct3, d=rd, s1=rs1)
    if opcode == 0b0100011 and funct3 in (0, 1, 2):
        return result(STORE, ADD, 1, imm_s, funct3, s1=rs1, s2=rs2)
    if opcode == 0b0010011:
        if funct3 == 1 and funct7 != 0:
            return illegal()
        if funct3 == 5 and funct7 not in (0, 0x20):
            return illegal()
        op = {0: ADD, 1: SLL, 2: SLT, 3: SLTU, 4: XOR, 6: OR, 7: AND,
              5: SRA if funct7 else SRL}[funct3]
        # Only the shifts' low five bits count, and the top bits decide the shift type.
        return result(ALU, op, 1, imm_i & 0x1F if funct3 in (1, 5) else imm_i, d=rd, s1=rs1)
    if opcode == 0b0110011:
        if funct3 in (0, 5):
            if funct7 not in (0, 0x20):
                return illegal()
        elif funct7 != 0:
            return illegal()
        op = {1: SLL, 2: SLT, 3: SLTU, 4: XOR, 6: OR, 7: AND,
              0: SUB if funct7 else ADD, 5: SRA if funct7 else SRL}[funct3]
        return result(ALU, op, 0, d=rd, s1=rs1, s2=rs2)
    if opcode == 0b0001111 and funct3 == 0:
        return result(NOP)
    if word == 0x00000073:
        return {"class": HALT, "rd": 0, "rs1": 0, "rs2": 0, "reason": 0}
    if word == 0x00100073:
        return {"class": HALT, "rd": 0, "rs1": 0, "rs2": 0, "reason": 1}
    return illegal()


def check(word, seen, want):
    for field, value in want.items():
        if field == "imm" and want["class"] == ALU and want["alu_op"] in (SLL, SRL, SRA):
            assert seen["imm"] & 0x1F == value, f"{word:08x} shift amount"
            continue
        assert seen[field] == value, f"{word:08x} {field}: {seen[field]} != {value}"
    assert seen["done"] == int(want["class"] in DONE_AT_ALLOC), f"{word:08x} done"
    assert seen["halt"] == int(want["class"] == HALT), f"{word:08x} halt"


@cocotb.test()
async def test_assembler_encodings(dut):
    for name, word, cls, op, b_imm, rd, rs1, rs2, imm, mem in GOLDEN:
        seen = await apply(dut, word)
        assert seen["class"] == cls, name
        assert (seen["rd"], seen["rs1"], seen["rs2"]) == (rd, rs1, rs2), name
        assert seen["halt"] == 0, name
        assert seen["done"] == int(cls in DONE_AT_ALLOC), name
        if cls in USES_ALU:
            assert seen["alu_op"] == op, name
            assert seen["b_is_imm"] == b_imm, name
        if cls in USES_IMM and imm is not None:
            assert seen["imm"] == imm & 0xFFFFFFFF, name
        if mem is not None:
            assert seen["mem_op"] == mem, name


@cocotb.test()
async def test_golden_agrees_with_reference(dut):
    """Checks reference() against the assembler, so the random test can be trusted."""
    for _, word, cls, op, b_imm, rd, rs1, rs2, imm, mem in GOLDEN:
        want = reference(word)
        assert want["class"] == cls
        assert (want["rd"], want["rs1"], want["rs2"]) == (rd, rs1, rs2)
        if cls in USES_ALU:
            assert (want["alu_op"], want["b_is_imm"]) == (op, b_imm)
        if cls in USES_IMM and imm is not None:
            assert want["imm"] == imm & 0xFFFFFFFF
        if mem is not None:
            assert want["mem_op"] == mem


@cocotb.test()
async def test_halt_reasons(dut):
    for word, reason in ((0x00000073, 0), (0x00100073, 1), (0x00000000, 2), (0xFFFFFFFF, 2)):
        seen = await apply(dut, word)
        assert seen["halt"] == 1 and seen["done"] == 1
        assert seen["class"] == HALT
        assert seen["reason"] == reason, f"{word:08x}"
        assert (seen["rd"], seen["rs1"], seen["rs2"]) == (0, 0, 0)


@cocotb.test()
async def test_system_needs_exact_encoding(dut):
    for word in (0x00200073, 0x00000873, 0x00008073, 0x00001073, 0x30200073, 0x10500073):
        seen = await apply(dut, word)
        assert (seen["class"], seen["reason"]) == (HALT, 2), f"{word:08x}"


@cocotb.test()
async def test_rv32e_rejects_high_registers(dut):
    for word in (
        0x00028837,  # lui x16
        0x00080067 | 1 << 7,  # jalr x1, 0(x16)
        0x010000b3,  # add x1, x0, x16
        0x00080093,  # addi x1, x16, 0
        0x01002023,  # sw x16, 0(x0)
        0x01000063,  # beq x0, x16
    ):
        seen = await apply(dut, word)
        assert (seen["class"], seen["reason"]) == (HALT, 2), f"{word:08x}"
        assert (seen["rd"], seen["rs1"], seen["rs2"]) == (0, 0, 0)


@cocotb.test()
async def test_shift_amount_is_not_a_register(dut):
    """Bit 24 of SLLI is shamt[4], and must not trip the RV32E register check."""
    for word in (0x01f71693, 0x0100d793, 0x4101d113):
        seen = await apply(dut, word)
        assert seen["class"] == ALU, f"{word:08x}"
        assert seen["rs2"] == 0, "a shift immediate must not read rs2"
        assert seen["b_is_imm"] == 1


@cocotb.test()
async def test_unused_fields_read_as_x0(dut):
    """Stray bits must not become register numbers, or rename would use them."""
    assert (await apply(dut, 0xfffff7b7))["rs1"] == 0  # lui with ones in the rs1 bits
    assert (await apply(dut, 0xfffff7b7))["rs2"] == 0
    seen = await apply(dut, 0xfe110fa3)  # sb has no rd, though those bits are imm
    assert seen["rd"] == 0
    seen = await apply(dut, 0x7e208fe3)  # beq
    assert seen["rd"] == 0
    seen = await apply(dut, 0x0ff5828f & ~0x7000 | 0x0000000f)  # fence with stray fields
    assert seen["class"] == NOP
    assert (seen["rd"], seen["rs1"], seen["rs2"]) == (0, 0, 0)


@cocotb.test()
async def test_addi_with_bit_30_is_not_sub(dut):
    seen = await apply(dut, 0x40010093)  # addi x1, x2, 1024
    assert seen["alu_op"] == ADD
    assert seen["imm"] == 1024


@cocotb.test()
async def test_every_opcode_funct3_funct7(dut):
    r = random.Random(2)
    for opcode in range(128):
        for funct3 in range(8):
            for funct7 in (0, 0x20, 0x01, 0x7F, 0x40):
                body = r.getrandbits(32) & 0x01FF8F80 & ~(1 << 11 | 1 << 19 | 1 << 24)
                word = funct7 << 25 | funct3 << 12 | opcode | body
                check(word, await apply(dut, word), reference(word))


@cocotb.test()
async def test_random_words(dut):
    r = random.Random(1)
    opcodes = (0x37, 0x17, 0x6F, 0x67, 0x63, 0x03, 0x23, 0x13, 0x33, 0x0F, 0x73)
    for _ in range(RANDOM_WORDS):
        word = r.getrandbits(32)
        if r.random() < 0.9:
            word = (word & ~0x7F) | r.choice(opcodes)
        if r.random() < 0.7:
            word &= ~(1 << 11 | 1 << 19 | 1 << 24)
        check(word, await apply(dut, word), reference(word))
