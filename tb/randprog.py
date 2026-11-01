"""Random RV32E programs that always terminate and never hit undefined behaviour.

x15 holds the data pointer. Each program sets up every register, runs random atoms,
then stores all registers and executes ECALL. Atoms are built last to first, so a
forward branch can skip whole atoms and never lands inside a loop.
"""

DATA = 0x8000
DUMP = 0x8200
POINTER = 15
COUNTER = 14


def r_type(funct7, rs2, rs1, funct3, rd, opcode=0x33):
    return funct7 << 25 | rs2 << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | opcode


def i_type(imm, rs1, funct3, rd, opcode=0x13):
    return (imm & 0xFFF) << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | opcode


def s_type(imm, rs2, rs1, funct3):
    imm &= 0xFFF
    return (imm >> 5) << 25 | rs2 << 20 | rs1 << 15 | funct3 << 12 | (imm & 0x1F) << 7 | 0x23


def b_type(imm, rs2, rs1, funct3):
    imm &= 0x1FFF
    return ((imm >> 12) << 31 | ((imm >> 5) & 0x3F) << 25 | rs2 << 20 | rs1 << 15
            | funct3 << 12 | ((imm >> 1) & 0xF) << 8 | ((imm >> 11) & 1) << 7 | 0x63)


def u_type(value, rd, opcode):
    return (value & 0xFFFFF) << 12 | rd << 7 | opcode


def j_type(imm, rd):
    imm &= 0x1FFFFF
    return ((imm >> 20) << 31 | ((imm >> 1) & 0x3FF) << 21 | ((imm >> 11) & 1) << 20
            | ((imm >> 12) & 0xFF) << 12 | rd << 7 | 0x6F)


def load_constant(rd, value):
    upper = (value + 0x800) >> 12
    return [u_type(upper, rd, 0x37), i_type(value, rd, 0, rd)]


class Generator:
    def __init__(self, rng, reg_limit=COUNTER):
        self.r = rng
        self.reg_limit = reg_limit

    def rd(self):
        return self.r.randrange(self.reg_limit)  # includes x0, excludes the fixed registers

    def rs(self):
        # Reusing recent registers gives long dependency chains.
        return self.r.randrange(self.reg_limit)

    def alu(self):
        r = self.r
        if r.random() < 0.5:
            funct3 = r.choice((0, 1, 2, 3, 4, 5, 6, 7))
            funct7 = r.choice((0, 0x20)) if funct3 in (0, 5) else 0
            return [r_type(funct7, self.rs(), self.rs(), funct3, self.rd())]
        funct3 = r.choice((0, 1, 2, 3, 4, 5, 6, 7))
        if funct3 in (1, 5):
            funct7 = r.choice((0, 0x20)) if funct3 == 5 else 0
            return [r_type(funct7, r.randrange(32), self.rs(), funct3, self.rd(), 0x13)]
        return [i_type(r.getrandbits(12), self.rs(), funct3, self.rd())]

    def memory(self):
        r = self.r
        if r.random() < 0.55:
            funct3 = r.choice((0, 1, 2, 4, 5))
            step = {0: 1, 4: 1, 1: 2, 5: 2, 2: 4}[funct3]
            offset = r.randrange(0, 128, step)
            return [i_type(offset, POINTER, funct3, self.rd(), 0x03)]
        funct3 = r.randrange(3)
        offset = r.randrange(0, 128, 1 << funct3)
        return [s_type(offset, self.rs(), POINTER, funct3)]

    def upper(self):
        r = self.r
        kind = r.randrange(3)
        if kind == 0:
            return [u_type(r.getrandbits(20), self.rd(), 0x37)]
        if kind == 1:
            return [u_type(r.getrandbits(20), self.rd(), 0x17)]
        return [i_type(r.getrandbits(12), r.randrange(32), 0, r.randrange(32), 0x0F)]

    def loop(self):
        body = []
        for _ in range(self.r.randrange(1, 4)):
            body += self.r.choice((self.alu, self.memory, self.upper))()
        count = self.r.randrange(1, 5)
        return ([i_type(count, 0, 0, COUNTER)] + body
                + [i_type(-1, COUNTER, 0, COUNTER)]
                + [b_type(-4 * (len(body) + 1), 0, COUNTER, 1)])

    def atom(self, following):
        r = self.r
        pick = r.random()
        if pick < 0.55:
            return self.alu()
        if pick < 0.80:
            return self.memory()
        if pick < 0.85:
            return self.upper()
        if pick < 0.90:
            return self.loop()
        skip = sum(len(a) for a in following[:r.randrange(1, 4)])
        if pick < 0.95:
            funct3 = r.choice((0, 1, 4, 5, 6, 7))
            return [b_type(4 * (skip + 1), self.rs(), self.rs(), funct3)]
        if r.random() < 0.5:
            return [j_type(4 * (skip + 1), self.rd())]
        # auipc x14 then jalr, landing the same distance past the jalr.
        return [u_type(0, COUNTER, 0x17), i_type(4 * (skip + 2), COUNTER, 0, self.rd(), 0x67)]


def generate(rng, atoms=200):
    """Returns the program image as bytes."""
    gen = Generator(rng)
    body = []
    for _ in range(atoms):
        body.insert(0, gen.atom(body))

    words = load_constant(POINTER, DATA)
    for reg in range(1, 15):
        words += load_constant(reg, rng.getrandbits(32))
    for atom in body:
        words += atom
    words += load_constant(POINTER, DUMP)
    for reg in range(1, 15):
        words.append(s_type(4 * reg, reg, POINTER, 2))
    words.append(0x00000073)

    image = bytearray(0x8100)
    for i, word in enumerate(words):
        image[4 * i:4 * i + 4] = word.to_bytes(4, "little")
    assert 4 * len(words) < DATA
    image[DATA:DATA + 0x100] = rng.randbytes(0x100)
    return bytes(image)
