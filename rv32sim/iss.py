# Copyright (c) Fredrik Andersson, 2026
# All rights reserved

"""
A reference model of the processor: an instruction set simulator of RV32E, written from
the spec independently of the RTL.

It has the same memory map and trap behavior as the RTL, so the test bench can run both
in lockstep and compare every retired instruction.
"""

from __future__ import annotations

from dataclasses import dataclass

from .build import REGISTERS
from .devices import (
    CONSOLE_BASE,
    CONSOLE_EXIT,
    CONSOLE_TX,
    DLM_ADDRESS_WIDTH,
    DLM_BASE,
    ILM_ADDRESS_WIDTH,
    ILM_BASE,
)


MASK = 0xFFFF_FFFF

# Machine mode exception codes
MISALIGNED_FETCH, FETCH_FAULT, ILLEGAL, BREAKPOINT, MISALIGNED_LOAD, MISALIGNED_STORE, ECALL = (
    0,
    1,
    2,
    3,
    4,
    6,
    11,
)


def sx(value: int, bits: int) -> int:
    """Sign extend the low 'bits' bits"""
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def signed(value: int) -> int:
    return sx(value, 32)


def bits(value: int, high: int, low: int) -> int:
    return (value >> low) & ((1 << (high - low + 1)) - 1)


class Trap(Exception):
    def __init__(self, cause: int) -> None:
        super().__init__(cause)
        self.cause = cause


@dataclass
class Retired:
    """What one instruction did"""

    pc: int
    insn: int
    rd: int | None = None  # None if no register was written (or x0)
    value: int | None = None


class Iss:
    """
    Args:
        image: The bytes of the ILM, at address 0.
        ilm_address_width: The ILM's address bits.
        dlm_address_width: The DLM's address bits.
    """

    def __init__(
        self,
        image: bytes,
        ilm_address_width: int = ILM_ADDRESS_WIDTH,
        dlm_address_width: int = DLM_ADDRESS_WIDTH,
    ) -> None:
        self.ilm = bytearray(1 << ilm_address_width)
        self.ilm[: len(image)] = image
        self.dlm = bytearray(1 << dlm_address_width)
        self.x = [0] * REGISTERS
        self.pc = 0
        self.halted = False
        self.cause: int | None = None
        self.text = ""
        self.exit_code: int | None = None

    # --- Memory ---------------------------------------------------------------------

    def _region(self, addr: int) -> tuple[bytearray, int]:
        """The memory of an address and the offset in it: the ILM (read-only) or the DLM"""
        if ILM_BASE <= addr < ILM_BASE + len(self.ilm):
            return self.ilm, addr - ILM_BASE
        if DLM_BASE <= addr < DLM_BASE + len(self.dlm):
            return self.dlm, addr - DLM_BASE
        raise RuntimeError(f"access to 0x{addr:08x} outside the memories")

    def _read(self, addr: int, size: int) -> int:
        memory, offset = self._region(addr)
        return int.from_bytes(memory[offset : offset + size], "little")

    def _write(self, addr: int, size: int, value: int) -> None:
        if CONSOLE_BASE <= addr < CONSOLE_BASE + 8:
            if addr & ~3 == CONSOLE_TX:
                self.text += chr(value & 0xFF)
            elif addr == CONSOLE_EXIT and size == 4:
                self.exit_code = value
            return
        memory, offset = self._region(addr)
        if memory is self.ilm:
            raise RuntimeError(f"store to 0x{addr:08x} in the ILM, which is read-only")
        memory[offset : offset + size] = (value & ((1 << (8 * size)) - 1)).to_bytes(size, "little")

    def fetch(self, addr: int) -> int:
        """The 32 bits at an address in the ILM"""
        return int.from_bytes(self.ilm[addr : addr + 4], "little")

    # --- Execution ------------------------------------------------------------------

    def step(self) -> Retired | None:
        """Execute one instruction. None if it trapped (then halted and cause are set)"""
        if self.halted:
            return None
        if not ILM_BASE <= self.pc < ILM_BASE + len(self.ilm):
            # Outside the ILM: nothing to fetch
            self.halted = True
            self.cause = FETCH_FAULT
            return None
        word = self.fetch(self.pc)
        retired = Retired(self.pc, word)
        try:
            # A 16-bit instruction (the low bits aren't 11) is illegal: there is no C
            if word & 3 != 3:
                raise Trap(ILLEGAL)
            next_pc = self._execute(word, retired)
        except Trap as trap:
            self.halted = True
            self.cause = trap.cause
            return None
        self.pc = next_pc
        self.x[0] = 0
        return retired

    def _set(self, retired: Retired, rd: int, value: int) -> None:
        if rd != 0:
            self.x[rd] = value & MASK
            retired.rd = rd
            retired.value = value & MASK

    @staticmethod
    def _jump(target: int) -> int:
        target &= MASK
        # Instructions are 32-bit aligned
        if target & 2:
            raise Trap(MISALIGNED_FETCH)
        return target

    def _load(self, funct3: int, addr: int) -> int:
        addr &= MASK
        size = {0: 1, 1: 2, 2: 4, 4: 1, 5: 2}[funct3]
        if addr % size:
            raise Trap(MISALIGNED_LOAD)
        value = self._read(addr, size)
        return sx(value, 8 * size) if funct3 in (0, 1) else value

    def _store(self, funct3: int, addr: int, value: int) -> None:
        addr &= MASK
        size = {0: 1, 1: 2, 2: 4}[funct3]
        if addr % size:
            raise Trap(MISALIGNED_STORE)
        self._write(addr, size, value)

    @staticmethod
    def alu(funct3: int, alt: bool, a: int, b: int) -> int:
        """OP and OP-IMM: alt is SUB/SRA"""
        shamt = b & 31
        if funct3 == 0:
            return a - b if alt else a + b
        if funct3 == 1:
            return a << shamt
        if funct3 == 2:
            return int(signed(a) < signed(b))
        if funct3 == 3:
            return int((a & MASK) < (b & MASK))
        if funct3 == 4:
            return a ^ b
        if funct3 == 5:
            return signed(a) >> shamt if alt else (a & MASK) >> shamt
        if funct3 == 6:
            return a | b
        return a & b

    @staticmethod
    def _kind(insn: int) -> str | None:
        """The format of a legal instruction (R, I, S, B, U, J or SYSTEM), None if illegal"""
        opcode = bits(insn, 6, 0)
        funct3 = bits(insn, 14, 12)
        funct7 = bits(insn, 31, 25)
        if opcode in (0b0110111, 0b0010111):  # LUI, AUIPC
            return "U"
        if opcode == 0b1101111:  # JAL
            return "J"
        if opcode == 0b1100111 and funct3 == 0:  # JALR
            return "I"
        if opcode == 0b1100011 and funct3 not in (2, 3):  # Branches
            return "B"
        if opcode == 0b0000011 and funct3 in (0, 1, 2, 4, 5):  # Loads
            return "I"
        if opcode == 0b0100011 and funct3 in (0, 1, 2):  # Stores
            return "S"
        if opcode == 0b0010011:  # OP-IMM, the shifts with the bits above shamt
            if funct3 == 1 and funct7 != 0:
                return None
            if funct3 == 5 and funct7 not in (0, 0b0100000):
                return None
            return "I"
        if opcode == 0b0110011:  # OP: no M
            if funct7 == 0 or (funct7 == 0b0100000 and funct3 in (0, 5)):
                return "R"
            return None
        if opcode == 0b0001111 and funct3 in (0, 1):  # FENCE, FENCE.I
            return "SYSTEM"
        if insn in (0x0000_0073, 0x0010_0073):  # ECALL, EBREAK
            return "SYSTEM"
        return None

    def _execute(self, insn: int, retired: Retired) -> int:
        """A 32-bit instruction, returns the next pc"""
        kind = self._kind(insn)
        if kind is None:
            raise Trap(ILLEGAL)
        rd = bits(insn, 11, 7)
        rs1_reg = bits(insn, 19, 15)
        rs2_reg = bits(insn, 24, 20)
        # RV32E: the register fields of the format must name x0..x15
        used = {
            "R": (rd, rs1_reg, rs2_reg),
            "I": (rd, rs1_reg),
            "S": (rs1_reg, rs2_reg),
            "B": (rs1_reg, rs2_reg),
            "U": (rd,),
            "J": (rd,),
            "SYSTEM": (),
        }[kind]
        if any(reg >= REGISTERS for reg in used):
            raise Trap(ILLEGAL)
        x = self.x
        pc = self.pc
        opcode = bits(insn, 6, 0)
        funct3 = bits(insn, 14, 12)
        rs1 = x[rs1_reg] if rs1_reg < REGISTERS else 0
        rs2 = x[rs2_reg] if rs2_reg < REGISTERS else 0
        funct7 = bits(insn, 31, 25)
        imm_i = sx(insn >> 20, 12)
        imm_s = sx((bits(insn, 31, 25) << 5) | bits(insn, 11, 7), 12)
        imm_b = sx(
            (bits(insn, 31, 31) << 12)
            | (bits(insn, 7, 7) << 11)
            | (bits(insn, 30, 25) << 5)
            | (bits(insn, 11, 8) << 1),
            13,
        )
        imm_u = insn & 0xFFFF_F000
        imm_j = sx(
            (bits(insn, 31, 31) << 20)
            | (bits(insn, 19, 12) << 12)
            | (bits(insn, 20, 20) << 11)
            | (bits(insn, 30, 21) << 1),
            21,
        )

        if opcode == 0b0110111:  # LUI
            self._set(retired, rd, imm_u)
        elif opcode == 0b0010111:  # AUIPC
            self._set(retired, rd, pc + imm_u)
        elif opcode == 0b1101111:  # JAL
            target = self._jump(pc + imm_j)
            self._set(retired, rd, pc + 4)
            return target
        elif opcode == 0b1100111:  # JALR
            target = self._jump((rs1 + imm_i) & ~1)
            self._set(retired, rd, pc + 4)
            return target
        elif opcode == 0b1100011:  # Branches
            a, b = rs1, rs2
            taken = {
                0: a == b,
                1: a != b,
                4: signed(a) < signed(b),
                5: signed(a) >= signed(b),
                6: a < b,
                7: a >= b,
            }[funct3]
            if taken:
                return self._jump(pc + imm_b)
        elif opcode == 0b0000011:  # Loads
            self._set(retired, rd, self._load(funct3, rs1 + imm_i))
        elif opcode == 0b0100011:  # Stores
            self._store(funct3, rs1 + imm_s, rs2)
        elif opcode == 0b0010011:  # OP-IMM
            alt = funct3 == 5 and funct7 == 0b0100000
            self._set(retired, rd, self.alu(funct3, alt, rs1, imm_i & MASK))
        elif opcode == 0b0110011:  # OP
            self._set(retired, rd, self.alu(funct3, funct7 != 0, rs1, rs2))
        elif insn == 0x0000_0073:
            raise Trap(ECALL)
        elif insn == 0x0010_0073:
            raise Trap(BREAKPOINT)
        # FENCE and FENCE.I do nothing
        return (pc + 4) & MASK
