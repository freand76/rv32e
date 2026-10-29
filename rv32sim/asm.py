# Copyright (c) Fredrik Andersson, 2026
# All rights reserved

"""
A small assembler for writing instruction tests in Python, without a toolchain.

    p = Program()
    p.li(5, 1234)
    p.label("loop")
    p.addi(5, 5, -1)
    p.bne(5, 0, "loop")
    p.exit(0)
    image = p.assemble()

Registers are numbers. The processor has x0..x15 (RV32E), the assembler encodes any of
x0..x31, so a test can build the reserved encodings. Branches and jumps take a label or a
byte offset. Raw encodings are written with p.word() (and p.half() for 16 bits).
"""

from __future__ import annotations

from collections.abc import Callable

from .devices import CONSOLE_EXIT, CONSOLE_TX


def _check(value: int, bits: int, signed: bool = True, align: int = 1) -> int:
    low, high = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)
    if not low <= value <= high or value % align:
        raise ValueError(f"{value} doesn't fit in {bits} bits (aligned to {align})")
    return value & ((1 << bits) - 1)


def r_type(funct7: int, rs2: int, rs1: int, funct3: int, rd: int, opcode: int) -> int:
    return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def i_type(imm: int, rs1: int, funct3: int, rd: int, opcode: int) -> int:
    return (_check(imm, 12) << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def s_type(imm: int, rs2: int, rs1: int, funct3: int) -> int:
    imm = _check(imm, 12)
    return (
        ((imm >> 5) << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | ((imm & 31) << 7) | 0x23
    )


def b_type(offset: int, rs2: int, rs1: int, funct3: int) -> int:
    imm = _check(offset, 13, align=2)
    return (
        ((imm >> 12) << 31)
        | (((imm >> 5) & 0x3F) << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (funct3 << 12)
        | (((imm >> 1) & 0xF) << 8)
        | (((imm >> 11) & 1) << 7)
        | 0x63
    )


def u_type(imm20: int, rd: int, opcode: int) -> int:
    return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | opcode


def j_type(offset: int, rd: int) -> int:
    imm = _check(offset, 21, align=2)
    return (
        ((imm >> 20) << 31)
        | (((imm >> 1) & 0x3FF) << 21)
        | (((imm >> 11) & 1) << 20)
        | (((imm >> 12) & 0xFF) << 12)
        | (rd << 7)
        | 0x6F
    )


ALU = {"add": 0, "sll": 1, "slt": 2, "sltu": 3, "xor": 4, "srl": 5, "or": 6, "and": 7}
BRANCH = {"beq": 0, "bne": 1, "blt": 4, "bge": 5, "bltu": 6, "bgeu": 7}
LOAD = {"lb": 0, "lh": 1, "lw": 2, "lbu": 4, "lhu": 5}
STORE = {"sb": 0, "sh": 1, "sw": 2}


class Program:
    """A program at address 0, built instruction by instruction"""

    def __init__(self) -> None:
        # (address, size, encoder from the labels)
        self._items: list[tuple[int, int, Callable[[dict[str, int]], int]]] = []
        self._labels: dict[str, int] = {}
        self.pc = 0

    def label(self, name: str) -> None:
        self._labels[name] = self.pc

    def _emit(self, size: int, encode: Callable[[dict[str, int]], int]) -> None:
        self._items.append((self.pc, size, encode))
        self.pc += size

    def word(self, value: int) -> None:
        self._emit(4, lambda _: value & 0xFFFF_FFFF)

    def half(self, value: int) -> None:
        self._emit(2, lambda _: value & 0xFFFF)

    def _target(self, target: int | str, pc: int, labels: dict[str, int]) -> int:
        return labels[target] - pc if isinstance(target, str) else target

    def assemble(self) -> bytes:
        image = bytearray(self.pc)
        for address, size, encode in self._items:
            image[address : address + size] = encode(self._labels).to_bytes(size, "little")
        return bytes(image)

    # --- RV32I ----------------------------------------------------------------------

    def lui(self, rd: int, imm20: int) -> None:
        self._emit(4, lambda _: u_type(imm20, rd, 0x37))

    def auipc(self, rd: int, imm20: int) -> None:
        self._emit(4, lambda _: u_type(imm20, rd, 0x17))

    def jal(self, rd: int, target: int | str) -> None:
        pc = self.pc
        self._emit(4, lambda labels: j_type(self._target(target, pc, labels), rd))

    def jalr(self, rd: int, rs1: int, imm: int = 0) -> None:
        self._emit(4, lambda _: i_type(imm, rs1, 0, rd, 0x67))

    def branch(self, name: str, rs1: int, rs2: int, target: int | str) -> None:
        pc = self.pc
        funct3 = BRANCH[name]
        self._emit(4, lambda labels: b_type(self._target(target, pc, labels), rs2, rs1, funct3))

    def load(self, name: str, rd: int, rs1: int, imm: int = 0) -> None:
        self._emit(4, lambda _: i_type(imm, rs1, LOAD[name], rd, 0x03))

    def store(self, name: str, rs2: int, rs1: int, imm: int = 0) -> None:
        self._emit(4, lambda _: s_type(imm, rs2, rs1, STORE[name]))

    def op_imm(self, name: str, rd: int, rs1: int, imm: int) -> None:
        funct3 = ALU[name]
        if name in ("sll", "srl"):
            imm = _check(imm, 5, signed=False)
        self._emit(4, lambda _: i_type(imm, rs1, funct3, rd, 0x13))

    def op(self, name: str, rd: int, rs1: int, rs2: int) -> None:
        if name in ("sub", "sra"):
            funct7, funct3 = 0x20, ALU["add" if name == "sub" else "srl"]
        else:
            funct7, funct3 = 0, ALU[name]
        self._emit(4, lambda _: r_type(funct7, rs2, rs1, funct3, rd, 0x33))

    def srai(self, rd: int, rs1: int, shamt: int) -> None:
        self._emit(4, lambda _: i_type(0x400 | _check(shamt, 5, False), rs1, 5, rd, 0x13))

    def fence(self) -> None:
        self.word(0x0FF0_000F)

    def ecall(self) -> None:
        self.word(0x0000_0073)

    def ebreak(self) -> None:
        self.word(0x0010_0073)

    def __getattr__(self, name: str) -> Callable[..., None]:
        """addi, slli, add, sub, beq, lw, sw, ... by name"""
        if name in BRANCH:
            return lambda rs1, rs2, target: self.branch(name, rs1, rs2, target)
        if name in LOAD:
            return lambda rd, rs1, imm=0: self.load(name, rd, rs1, imm)
        if name in STORE:
            return lambda rs2, rs1, imm=0: self.store(name, rs2, rs1, imm)
        if name == "sltiu":
            return lambda rd, rs1, imm: self.op_imm("sltu", rd, rs1, imm)
        if name.endswith("i") and name[:-1] in ALU:
            return lambda rd, rs1, imm: self.op_imm(name[:-1], rd, rs1, imm)
        if name.rstrip("_") in ALU or name in ("sub", "sra"):
            return lambda rd, rs1, rs2: self.op(name.rstrip("_"), rd, rs1, rs2)
        raise AttributeError(name)

    # --- Pseudo instructions ----------------------------------------------------------

    def li(self, rd: int, value: int) -> None:
        """Any 32-bit value, always lui + addi (8 bytes)"""
        value &= 0xFFFF_FFFF
        low = value & 0xFFF
        low = low - 0x1000 if low & 0x800 else low
        self.lui(rd, ((value - low) >> 12) & 0xFFFFF)
        self.op_imm("add", rd, rd, low)

    def mv(self, rd: int, rs1: int) -> None:
        self.op_imm("add", rd, rs1, 0)

    def j(self, target: int | str) -> None:
        self.jal(0, target)

    def putc(self, char: str, tmp: int = 15) -> None:
        """Print a character on the console (uses x14 and tmp)"""
        self.li(14, CONSOLE_TX)
        self.op_imm("add", tmp, 0, ord(char))
        self.store("sb", tmp, 14, 0)

    def exit(self, code: int | None = None, reg: int = 10) -> None:
        """Write the exit register, from 'reg' (a0) or a constant (uses x14, x15)"""
        self.li(14, CONSOLE_EXIT)
        if code is not None:
            self.li(15, code)
            reg = 15
        self.store("sw", reg, 14, 0)
        self.label(f"_halt_{self.pc}")
        self.jal(0, 0)
