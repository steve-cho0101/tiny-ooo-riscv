"""In-order RV32E reference model, written from docs/isa.md and sharing nothing with
the RTL. It raises on everything the ISA leaves undefined, so a test cannot pass by
accident."""


class UndefinedBehaviour(Exception):
    pass


def sign(value, bits):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


class Model:
    def __init__(self, image):
        self.mem = bytearray(0x10000)
        self.mem[:len(image)] = image
        self.regs = [None] * 16  # values at reset are undefined
        self.regs[0] = 0
        self.pc = 0
        self.stores = []  # (addr, bytes), in program order
        self.halt_reason = None
        self.steps = 0

    def get(self, reg):
        if self.regs[reg] is None:
            raise UndefinedBehaviour(f"x{reg} read before it was written, pc {self.pc:#x}")
        return self.regs[reg]

    def put(self, reg, value):
        if reg:
            self.regs[reg] = value & 0xFFFFFFFF

    def address(self, addr, size):
        addr &= 0xFFFFFFFF
        if addr > 0xFFFF or addr + size > 0x10000:
            raise UndefinedBehaviour(f"address {addr:#x}, pc {self.pc:#x}")
        if addr % size:
            raise UndefinedBehaviour(f"misaligned address {addr:#x}, pc {self.pc:#x}")
        return addr

    def jump(self, target):
        target &= 0xFFFFFFFF
        if target > 0xFFFF or target & 2:
            raise UndefinedBehaviour(f"jump to {target:#x}, pc {self.pc:#x}")
        self.pc = target & ~1

    def illegal(self):
        self.halt_reason = 2

    def step(self):
        """Run one instruction. Returns False once halted."""
        if self.pc + 4 > 0x10000:
            raise UndefinedBehaviour("ran off the end of memory")
        word = int.from_bytes(self.mem[self.pc:self.pc + 4], "little")
        self.steps += 1
        opcode = word & 0x7F
        rd = (word >> 7) & 0x1F
        funct3 = (word >> 12) & 7
        rs1 = (word >> 15) & 0x1F
        rs2 = (word >> 20) & 0x1F
        funct7 = word >> 25
        imm_i = sign(word >> 20, 12)
        pc_next = self.pc + 4

        def reg_fields_ok(*fields):
            return all(field < 16 for field in fields)

        if opcode == 0x37 and reg_fields_ok(rd):
            self.put(rd, word & 0xFFFFF000)
        elif opcode == 0x17 and reg_fields_ok(rd):
            self.put(rd, self.pc + (word & 0xFFFFF000))
        elif opcode == 0x6F and reg_fields_ok(rd):
            offset = sign(((word >> 31) << 20) | (word & 0xFF000) | (((word >> 20) & 1) << 11)
                          | (((word >> 21) & 0x3FF) << 1), 21)
            self.put(rd, pc_next)
            self.jump(self.pc + offset)
            return True
        elif opcode == 0x67 and funct3 == 0 and reg_fields_ok(rd, rs1):
            target = self.get(rs1) + imm_i
            self.put(rd, pc_next)
            self.jump(target)
            return True
        elif opcode == 0x63 and funct3 in (0, 1, 4, 5, 6, 7) and reg_fields_ok(rs1, rs2):
            a, b = self.get(rs1), self.get(rs2)
            sa, sb = sign(a, 32), sign(b, 32)
            taken = {0: a == b, 1: a != b, 4: sa < sb, 5: sa >= sb, 6: a < b, 7: a >= b}[funct3]
            if taken:
                offset = sign(((word >> 31) << 12) | (((word >> 7) & 1) << 11)
                              | (((word >> 25) & 0x3F) << 5) | (((word >> 8) & 0xF) << 1), 13)
                self.jump(self.pc + offset)
                return True
        elif opcode == 0x03 and funct3 in (0, 1, 2, 4, 5) and reg_fields_ok(rd, rs1):
            size = 1 << (funct3 & 3)
            addr = self.address(self.get(rs1) + imm_i, size)
            value = int.from_bytes(self.mem[addr:addr + size], "little")
            if funct3 < 4:
                value = sign(value, 8 * size)
            self.put(rd, value)
        elif opcode == 0x23 and funct3 in (0, 1, 2) and reg_fields_ok(rs1, rs2):
            size = 1 << funct3
            offset = sign((funct7 << 5) | rd, 12)
            addr = self.address(self.get(rs1) + offset, size)
            data = (self.get(rs2) & ((1 << (8 * size)) - 1)).to_bytes(size, "little")
            self.mem[addr:addr + size] = data
            self.stores.append((addr, bytes(data)))
        elif opcode == 0x13 and reg_fields_ok(rd, rs1):
            a = self.get(rs1)
            shamt = rs2
            if funct3 == 0:
                self.put(rd, a + imm_i)
            elif funct3 == 2:
                self.put(rd, int(sign(a, 32) < imm_i))
            elif funct3 == 3:
                self.put(rd, int(a < (imm_i & 0xFFFFFFFF)))
            elif funct3 == 4:
                self.put(rd, a ^ imm_i)
            elif funct3 == 6:
                self.put(rd, a | imm_i)
            elif funct3 == 7:
                self.put(rd, a & imm_i)
            elif funct3 == 1 and funct7 == 0:
                self.put(rd, a << shamt)
            elif funct3 == 5 and funct7 == 0:
                self.put(rd, a >> shamt)
            elif funct3 == 5 and funct7 == 0x20:
                self.put(rd, sign(a, 32) >> shamt)
            else:
                self.illegal()
                return False
        elif opcode == 0x33 and reg_fields_ok(rd, rs1, rs2):
            a, b = self.get(rs1), self.get(rs2)
            shamt = b & 31
            key = (funct7, funct3)
            if key == (0, 0):
                self.put(rd, a + b)
            elif key == (0x20, 0):
                self.put(rd, a - b)
            elif key == (0, 1):
                self.put(rd, a << shamt)
            elif key == (0, 2):
                self.put(rd, int(sign(a, 32) < sign(b, 32)))
            elif key == (0, 3):
                self.put(rd, int(a < b))
            elif key == (0, 4):
                self.put(rd, a ^ b)
            elif key == (0, 5):
                self.put(rd, a >> shamt)
            elif key == (0x20, 5):
                self.put(rd, sign(a, 32) >> shamt)
            elif key == (0, 6):
                self.put(rd, a | b)
            elif key == (0, 7):
                self.put(rd, a & b)
            else:
                self.illegal()
                return False
        elif opcode == 0x0F and funct3 == 0:
            pass
        elif word == 0x00000073:
            self.halt_reason = 0
            return False
        elif word == 0x00100073:
            self.halt_reason = 1
            return False
        else:
            self.illegal()
            return False
        self.pc = pc_next
        return True

    def run(self, max_steps=2_000_000):
        for _ in range(max_steps):
            if not self.step():
                return self
        raise UndefinedBehaviour("program did not halt")
