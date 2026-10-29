# Copyright (c) Fredrik Andersson, 2026
# All rights reserved

"""
The test bench: a digsim circuit with the processor (a YosysComponent built from the
synthesized RTL), the local memories (ILM and DLM) and the console. The bench drives the
clock, reset and the memories' ready signals itself, one cycle at a time, like the
Fibonacci synthesis example drives its ports.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from digsim.circuit import Circuit
from digsim.circuit.components import YosysComponent

from .build import REGISTERS, netlist
from .devices import DLM_ADDRESS_WIDTH, ILM_ADDRESS_WIDTH, Console, LocalMemories
from .iss import Iss, Retired


# The circuit runs until all events are done after each clock edge, a half period is
# only the longest time the logic may take to settle (1 ns per gate or cell)
HALF_PERIOD_NS = 20_000

CAUSES = {
    0: "instruction address misaligned",
    1: "instruction access fault",
    2: "illegal instruction",
    3: "breakpoint",
    4: "load address misaligned",
    6: "store address misaligned",
    11: "ecall",
}


class Mismatch(AssertionError):
    """The processor and the reference model disagree"""


@dataclass
class Result:
    cycles: int
    exit_code: int | None
    halted: bool
    cause: int | None
    text: str
    seconds: float
    stalls: int = 0  # The cycles with a memory that wasn't ready
    pc: int = 0  # The pc at the end, the trapping instruction's if halted
    trace: list[Retired] = field(default_factory=list)

    @property
    def cause_text(self) -> str:
        return CAUSES.get(self.cause, str(self.cause)) if self.cause is not None else ""


class Bench:
    """
    Args:
        image: The program, loaded into the ILM at address 0.
        functional: Simulate the netlist of functional blocks, or of gates.
        ilm_address_width: The ILM's address bits (a parameter of the RTL too).
        dlm_address_width: The DLM's address bits.
        vcd: Write the waveforms to this VCD file.
        echo: Print the console output while running.
    """

    def __init__(
        self,
        image: bytes,
        functional: bool = True,
        ilm_address_width: int = ILM_ADDRESS_WIDTH,
        dlm_address_width: int = DLM_ADDRESS_WIDTH,
        vcd: str | Path | None = None,
        echo: bool = False,
    ) -> None:
        self.image = bytes(image)
        self.ilm_address_width = ilm_address_width
        self.dlm_address_width = dlm_address_width
        self.circuit = Circuit(vcd=str(vcd) if vcd is not None else None)
        self.cpu = YosysComponent(self.circuit, path=netlist(functional, ilm_address_width))
        self.ram = LocalMemories(self.circuit, ilm_address_width, dlm_address_width, image)
        self.console = Console(self.circuit, echo=echo)
        cpu, ram, console = self.cpu, self.ram, self.console
        cpu.imem_addr.wire = ram.i_addr
        ram.i_data.wire = cpu.imem_rdata
        ram.d_rdata.wire = cpu.dmem_rdata
        for device in (ram, console):
            cpu.dmem_addr.wire = device.d_addr
            cpu.dmem_wdata.wire = device.d_wdata
            cpu.dmem_wstrb.wire = device.d_wstrb
        cpu.dmem_re.wire = ram.d_re
        # The memories that are busy in a cycle, see run(stall=...)
        self._rng = random.Random(0)
        self._stall = 0.0
        self.stalls = 0
        self.cycles = 0
        # x0..x15, from the write-back port (the register file is reset to 0)
        self.x = [0] * REGISTERS

    def load(self, image: bytes) -> None:
        """Replace the program (run() resets the processor and the RAM to it)"""
        self.image = bytes(image)
        self.ram.load(self.image)

    def _set_ready(self, imem: int, dmem: int) -> None:
        """The ready signals of the next cycle (another master has a port without it)"""
        cpu = self.cpu
        if cpu.imem_ready.value != imem:
            cpu.imem_ready.value = imem
        if cpu.dmem_ready.value != dmem:
            cpu.dmem_ready.value = dmem
            self.ram.d_ready.value = dmem
            self.console.d_ready.value = dmem

    def _half_cycle(self, clk: int) -> None:
        self.cpu.clk.value = clk
        self.ram.clk.value = clk
        self.console.clk.value = clk
        self.circuit.run(ns=HALF_PERIOD_NS)
        if self.circuit._circuit_events:
            raise RuntimeError(f"The logic didn't settle in {HALF_PERIOD_NS} ns")

    def reset(self) -> None:
        """Initialize the circuit, and reset the processor for two cycles"""
        self.circuit.init()
        self.ram.reload()
        self.console.text = ""
        self.console.exit_code = None
        self.ram.errors.clear()
        self.cpu.imem_ready.value = 1
        self.cpu.dmem_ready.value = 1
        self.ram.d_ready.value = 1
        self.console.d_ready.value = 1
        self._half_cycle(0)
        self.cpu.rst.value = 1
        for _ in range(2):
            self._half_cycle(1)
            self._half_cycle(0)
        self.cpu.rst.value = 0
        self._half_cycle(0)
        self.cycles = 0
        self.stalls = 0
        self.x = [0] * REGISTERS

    def sample(self) -> Retired | None:
        """The instruction of this cycle (before the rising edge), None if none retires"""
        cpu = self.cpu
        if cpu.retire.value != 1:
            return None
        insn = cpu.imem_rdata.value
        assert isinstance(insn, int)
        retired = Retired(cpu.pc_out.value, insn)
        if cpu.wb_we.value == 1:
            retired.rd = cpu.wb_rd.value
            retired.value = cpu.wb_data.value
        return retired

    def step(self) -> Retired | None:
        """One clock cycle, returns what retired in it"""
        retired = self.sample()
        self.ram.check_load()
        if self.ram.errors:
            raise RuntimeError("; ".join(self.ram.errors))
        if self.cpu.imem_ready.value != 1 or self.cpu.dmem_ready.value != 1:
            self.stalls += 1
        self._half_cycle(1)
        if self._stall:
            # Each port busy in the next cycle with the probability of stall
            stall = self._stall
            self._set_ready(int(self._rng.random() >= stall), int(self._rng.random() >= stall))
        self._half_cycle(0)
        self.cycles += 1
        if retired is not None and retired.rd is not None:
            self.x[retired.rd] = retired.value
        return retired

    @property
    def halted(self) -> bool:
        return self.cpu.halted.value == 1

    def run(
        self,
        max_cycles: int = 100_000,
        lockstep: bool = False,
        trace: bool = False,
        stall: float = 0.0,
        seed: int = 0,
    ) -> Result:
        """
        Reset and run until the program writes the exit register, the processor halts on
        a trap, or max_cycles. With lockstep, every instruction is compared with the
        reference model (Mismatch if they differ). With stall, the ILM and the data port
        are busy in a cycle with that probability each (from a random generator with
        the seed): the processor waits, and runs the same instructions.
        """
        self._stall = stall
        self._rng = random.Random(seed)
        self.reset()
        iss = Iss(self.image, self.ilm_address_width, self.dlm_address_width) if lockstep else None
        result = Result(0, None, False, None, "", 0.0)
        start = time.perf_counter()
        while self.cycles < max_cycles:
            if self.console.exit_code is not None or self.halted:
                break
            retired = self.step()
            if trace and retired is not None:
                result.trace.append(retired)
            # Nothing retired and no trap: a memory stalled the cycle
            if iss is not None and (retired is not None or self.halted):
                self._compare(iss, retired)
        result.seconds = time.perf_counter() - start
        result.cycles = self.cycles
        result.stalls = self.stalls
        result.exit_code = self.console.exit_code
        result.halted = self.halted
        pc = self.cpu.pc_out.value
        result.pc = pc if isinstance(pc, int) else -1
        if result.halted:
            cause = self.cpu.trap_cause.value
            result.cause = cause if isinstance(cause, int) else None
        result.text = self.console.text
        if iss is not None:
            if result.halted != iss.halted or (result.halted and result.cause != iss.cause):
                raise Mismatch(
                    f"Trap: processor halted={result.halted} cause={result.cause}, "
                    f"model halted={iss.halted} cause={iss.cause}"
                )
            if result.text != iss.text or result.exit_code != iss.exit_code:
                raise Mismatch("The console output differs from the model's")
            for name, ours, its in (
                ("ILM", self.ram.ilm, iss.ilm),
                ("DLM", self.ram.dlm, iss.dlm),
            ):
                if ours != its:
                    offset = next(i for i, (a, b) in enumerate(zip(ours, its)) if a != b)
                    raise Mismatch(f"The {name} differs from the model's at offset 0x{offset:x}")
        return result

    def _compare(self, iss: Iss, retired: Retired | None) -> None:
        expected = iss.step()
        if retired != expected:
            raise Mismatch(
                f"cycle {self.cycles}: processor {_text(retired)}, model {_text(expected)}"
            )


def _text(retired: Retired | None) -> str:
    if retired is None:
        return "no instruction retired (trap)"
    text = f"pc=0x{retired.pc:08x} insn=0x{retired.insn:08x}"
    if retired.rd is not None:
        text += f" x{retired.rd}=0x{retired.value:08x}"
    return text
