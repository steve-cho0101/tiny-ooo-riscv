"""Python stand-in for the RP2350: memory behind the bus in docs/architecture.md."""
from cocotb.triggers import FallingEdge


class Mcu:
    """Runs on falling edges, so everything it drives is stable at the rising edge."""

    def __init__(self, dut, image, rng, load_delay=(0, 0), stale=(0, 4), fetch_gap=0.0, nibble_gap=0.0):
        self.dut = dut
        self.mem = bytearray(0x10000)
        self.mem[:len(image)] = image
        self.rng = rng
        self.load_delay = load_delay
        self.stale = stale
        self.fetch_gap = fetch_gap
        self.nibble_gap = nibble_gap

        self.stream = 0
        self.frame = []
        self.nibbles = []
        self.response_wait = 0
        self.redirect_wait = None
        self.redirect_to = 0
        self.stores = []
        self.halt_reason = None
        self.cycles = 0

    def idle_pins(self):
        self.dut.i_valid.value = 0
        self.dut.i_data.value = 0
        self.dut.d_valid.value = 0
        self.dut.d_data.value = 0

    def take_frame_byte(self, byte):
        self.frame.append(byte)
        kind = self.frame[0] >> 6
        length = 3
        if kind == 2:
            length = 3 + (1 << ((self.frame[0] >> 4) & 3))
        if len(self.frame) < length:
            return
        frame, self.frame = self.frame, []
        addr = frame[1] | frame[2] << 8
        if kind == 0:
            self.redirect_to = addr
            self.redirect_wait = self.rng.randint(*self.stale)
        elif kind == 1:
            base = addr & ~3
            word = int.from_bytes(self.mem[base:base + 4], "little")
            self.nibbles = [(word >> (4 * i)) & 0xF for i in range(8)]
            self.response_wait = self.rng.randint(*self.load_delay)
        elif kind == 2:
            data = bytes(frame[3:])
            self.mem[addr:addr + len(data)] = data
            self.stores.append((addr, data))
        else:
            self.halt_reason = frame[0] & 0xF

    def cycle(self):
        dut = self.dut
        self.cycles += 1
        self.idle_pins()

        # Instruction stream. Bytes keep coming until the MCU has dealt with a
        # redirect, which is what makes stale bytes possible.
        if self.rng.random() >= self.fetch_gap:
            dut.i_valid.value = 1
            dut.i_data.value = self.mem[self.stream & 0xFFFF]
            if int(dut.i_ready.value):
                self.stream += 1

        if self.redirect_wait is not None:
            if self.redirect_wait == 0:
                self.redirect_wait = None
                self.stream = self.redirect_to
                dut.i_valid.value = 0
                dut.d_valid.value = 1
            else:
                self.redirect_wait -= 1
        elif self.nibbles:
            if self.response_wait:
                self.response_wait -= 1
            elif self.rng.random() >= self.nibble_gap:
                dut.d_valid.value = 1
                dut.d_data.value = self.nibbles.pop(0)

        # Last, so that the earliest response is in the cycle after the frame ends.
        if int(dut.o_valid.value):
            self.take_frame_byte(int(dut.o_data.value))

    async def check_frozen(self):
        """Only reset restarts the core, so nothing may follow the HALT frame."""
        self.idle_pins()
        for _ in range(64):
            await FallingEdge(self.dut.clk)
            assert int(self.dut.o_valid.value) == 0, "a frame followed the HALT frame"

    async def run(self, max_cycles):
        self.idle_pins()
        await FallingEdge(self.dut.clk)
        for _ in range(max_cycles):
            self.cycle()
            await FallingEdge(self.dut.clk)
            if self.halt_reason is not None:
                return await self.check_frozen()
        raise AssertionError(f"no HALT within {max_cycles} cycles, {len(self.stores)} stores seen")
