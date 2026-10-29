# Copyright (c) Fredrik Andersson, 2026
# All rights reserved

"""
New digsim components for the processor's test bench: the local memories (an
instruction local memory, ILM, and a data local memory, DLM) and a console (memory
mapped character output and an exit register).

Both are read combinationally and written on the rising clock edge of a cycle with
d_ready. At the edge they see the values from before it: the processor's registers
change their outputs one delta cycle (1 ns) after the edge.

The memory map:

    0x0000_0000  ILM, 2^ilm_address_width bytes: code and read-only data (the data port
                 reads it, a store to it is an error)
    0x1000_0000  console: a store prints its low byte
    0x1000_0004  exit register
    0x2000_0000  DLM, 2^dlm_address_width bytes: data and the stack
"""

from __future__ import annotations

from digsim.circuit import Circuit
from digsim.circuit.components.atoms import Component, PortIn, PortOutDelta, PortWire


ILM_BASE = 0x0000_0000
CONSOLE_BASE = 0x1000_0000
CONSOLE_TX = CONSOLE_BASE + 0x0  # sb/sw: print the low byte
CONSOLE_EXIT = CONSOLE_BASE + 0x4  # sw: stop the simulation with this exit code
DLM_BASE = 0x2000_0000
# The default address bits of the ILM and the DLM: 64 KiB each
ILM_ADDRESS_WIDTH = 16
DLM_ADDRESS_WIDTH = 16


class LocalMemories(Component):
    """
    The ILM and the DLM, little-endian. The ILM has an instruction port and a read-only
    data port, the DLM a data port: the data port is decoded to them by the address.

    Ports:
        clk: Clock input, stores happen on the rising edge (with d_ready).
        i_addr: Instruction address input, ilm_address_width bits.
        i_data: Output, the 32-bit word at i_addr.
        d_addr: Data address input, 32 bits.
        d_re: Input, 1 for a load (an access outside the map is then an error).
        d_wdata: Write data input, 32 bits.
        d_wstrb: Byte write strobes input, 4 bits, for the bytes of the word at d_addr.
        d_ready: Input, the data port is the processor's in this cycle.
        d_rdata: Output, the aligned 32-bit word at d_addr (0 outside the memories).

    Args:
        circuit: The circuit to add the component to.
        ilm_address_width: The ILM's address bits.
        dlm_address_width: The DLM's address bits.
        image: The bytes to load into the ILM, at address 0.
    """

    def __init__(
        self,
        circuit: Circuit,
        ilm_address_width: int = ILM_ADDRESS_WIDTH,
        dlm_address_width: int = DLM_ADDRESS_WIDTH,
        image: bytes = b"",
    ) -> None:
        super().__init__(circuit, "LocalMemories")
        self.ilm_size = 1 << ilm_address_width
        self.dlm_size = 1 << dlm_address_width
        self.ilm = bytearray(self.ilm_size)
        self.dlm = bytearray(self.dlm_size)
        self._image = b""
        # The addresses the outputs are for: an update for another input (the clock, a bit
        # of the other bus) leaves an output alone
        self._i_addr: int | str | None = None
        self._d_addr: int | str | None = None
        self.load(image)
        self.errors: list[str] = []
        self.add_port(PortIn(self, "clk"))
        self.add_port(PortIn(self, "i_addr", width=ilm_address_width))
        self.add_port(PortIn(self, "d_addr", width=32))
        # Only checked before the edge: it doesn't wake the component
        self.add_port(PortWire(self, "d_re"))
        self.add_port(PortWire(self, "d_wdata", width=32))
        self.add_port(PortWire(self, "d_wstrb", width=4))
        self.add_port(PortWire(self, "d_ready"))
        self.add_port(PortOutDelta(self, "i_data", width=32))
        self.add_port(PortOutDelta(self, "d_rdata", width=32))

    def load(self, image: bytes) -> None:
        """A new ILM image, loaded now and by reload()"""
        if len(image) > self.ilm_size:
            raise ValueError(f"The image is {len(image)} bytes, the ILM {self.ilm_size}")
        self._image = bytes(image)
        self.reload()

    def reload(self) -> None:
        """The ILM image, and a DLM of zeros"""
        self.ilm[:] = bytes(self.ilm_size)
        self.ilm[: len(self._image)] = self._image
        self.dlm[:] = bytes(self.dlm_size)
        self._i_addr = self._d_addr = None

    def region(self, addr: int) -> tuple[bytearray, int] | None:
        """The memory of a byte address and the offset in it, None outside both"""
        if ILM_BASE <= addr < ILM_BASE + self.ilm_size:
            return self.ilm, addr - ILM_BASE
        if DLM_BASE <= addr < DLM_BASE + self.dlm_size:
            return self.dlm, addr - DLM_BASE
        return None

    def word(self, addr: int) -> int:
        """The 32 bits at a byte address, 0 outside the memories"""
        found = self.region(addr)
        if found is None or found[1] + 4 > len(found[0]):
            return 0
        memory, offset = found
        return int.from_bytes(memory[offset : offset + 4], "little")

    def update(self) -> None:
        written = self.clk.is_rising_edge() and self.d_ready.value == 1 and self._write()
        i_addr = self.i_addr.value
        if i_addr != self._i_addr:
            self._i_addr = i_addr
            self.i_data.value = self.word(i_addr & ~3) if isinstance(i_addr, int) else "X"
        d_addr = self.d_addr.value
        if d_addr != self._d_addr or written:
            self._d_addr = d_addr
            self.d_rdata.value = self.word(d_addr & ~3) if isinstance(d_addr, int) else "X"

    def check_load(self) -> None:
        """Before the rising edge: a load outside the memories is an error"""
        d_addr = self.d_addr.value
        if self.d_re.value != 1 or self.d_ready.value != 1 or not isinstance(d_addr, int):
            return
        if self.region(d_addr) is None:
            self.errors.append(f"load from 0x{d_addr:08x} outside the memories")

    def _write(self) -> bool:
        """The store of the cycle, True if the DLM was written"""
        strobe = self.d_wstrb.value
        if strobe == 0 or not isinstance(strobe, int):
            return False
        addr, data = self.d_addr.value, self.d_wdata.value
        if not isinstance(addr, int):
            self.errors.append("store to an undefined address")
            return False
        if CONSOLE_BASE <= addr < CONSOLE_BASE + 8:
            # The console's
            return False
        if ILM_BASE <= addr < ILM_BASE + self.ilm_size:
            self.errors.append(f"store to 0x{addr:08x} in the ILM, which is read-only")
            return False
        if not DLM_BASE <= addr < DLM_BASE + self.dlm_size:
            self.errors.append(f"store to 0x{addr:08x} outside the memories")
            return False
        if not isinstance(data, int):
            self.errors.append(f"store of undefined data to 0x{addr:08x}")
            return False
        base = (addr - DLM_BASE) & ~3
        for lane in range(4):
            if strobe & (1 << lane):
                self.dlm[base + lane] = (data >> (8 * lane)) & 0xFF
        return True


class Console(Component):
    """
    Memory mapped output: a store to CONSOLE_TX prints its low byte, a store to
    CONSOLE_EXIT sets exit_code (the test bench then stops).

    Ports:
        clk: Clock input.
        d_addr: Data address input, 32 bits.
        d_wdata: Write data input, 32 bits.
        d_wstrb: Byte write strobes input, 4 bits.
        d_ready: Input, the store happens in a cycle with d_ready.

    Args:
        circuit: The circuit to add the component to.
        echo: Also print the characters to stdout.
    """

    def __init__(self, circuit: Circuit, echo: bool = False) -> None:
        super().__init__(circuit, "Console")
        self.add_port(PortIn(self, "clk"))
        self.add_port(PortWire(self, "d_addr", width=32))
        self.add_port(PortWire(self, "d_wdata", width=32))
        self.add_port(PortWire(self, "d_wstrb", width=4))
        self.add_port(PortWire(self, "d_ready"))
        self.echo = echo
        self.text = ""
        self.exit_code: int | None = None

    def update(self) -> None:
        if not self.clk.is_rising_edge() or self.d_ready.value != 1:
            return
        strobe = self.d_wstrb.value
        if strobe == 0 or not isinstance(strobe, int):
            return
        addr, data = self.d_addr.value, self.d_wdata.value
        if not isinstance(addr, int) or not isinstance(data, int):
            return
        if addr & ~3 == CONSOLE_TX:
            char = chr((data >> (8 * (addr & 3))) & 0xFF)
            self.text += char
            if self.echo:
                print(char, end="", flush=True)
        elif addr == CONSOLE_EXIT:
            self.exit_code = data
