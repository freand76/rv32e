# Copyright (c) Fredrik Andersson, 2026
# All rights reserved

"""
Instruction tests with known answers from the spec. Each test also runs in lockstep with
the reference model, on both netlists. The registers are x0..x13: x14 and x15 are the
scratch registers of p.exit() and p.putc().
"""

from __future__ import annotations

import pytest

from rv32sim import DLM_BASE, Bench
from rv32sim.asm import Program


MASK = 0xFFFF_FFFF
DATA = DLM_BASE  # A data area, in the DLM
BASE = 8  # x8 holds DATA
INT_MIN = 0x8000_0000


def s32(value: int) -> int:
    value &= MASK
    return value - (1 << 32) if value & INT_MIN else value


def vector_program(vectors: list[tuple[str, int, int]]) -> Program:
    """For each (op, a, b): x7 = op(x5 = a, x6 = b), stored at DATA + 4 * index"""
    p = Program()
    p.li(BASE, DATA)
    for index, (op, a, b) in enumerate(vectors):
        p.li(5, a)
        p.li(6, b)
        getattr(p, op)(7, 5, 6)
        p.sw(7, BASE, 4 * index)
    p.exit(0)
    return p


def check_vectors(run, bench: Bench, vectors: list[tuple[str, int, int, int]]) -> None:
    result = run(vector_program([v[:3] for v in vectors]).assemble())
    assert result.exit_code == 0 and not result.halted
    for index, (op, a, b, expected) in enumerate(vectors):
        got = bench.ram.word(DATA + 4 * index)
        assert got == expected & MASK, f"{op}(0x{a & MASK:08x}, 0x{b & MASK:08x})"


def test_alu(run, bench: Bench) -> None:
    check_vectors(
        run,
        bench,
        [
            ("add", 0x7FFF_FFFF, 1, INT_MIN),
            ("add", MASK, 1, 0),
            ("sub", 0, 1, MASK),
            ("sub", INT_MIN, 1, 0x7FFF_FFFF),
            ("sll", 1, 31, INT_MIN),
            ("sll", 1, 33, 2),  # only the low 5 bits of rs2
            ("srl", INT_MIN, 31, 1),
            ("srl", MASK, 4, 0x0FFF_FFFF),
            ("sra", INT_MIN, 31, MASK),
            ("sra", INT_MIN, 4, 0xF800_0000),
            ("sra", 0x7FFF_FFFF, 30, 1),
            ("slt", -1, 1, 1),
            ("slt", 1, -1, 0),
            ("slt", INT_MIN, 0x7FFF_FFFF, 1),
            ("sltu", 1, MASK, 1),
            ("sltu", MASK, 1, 0),
            ("xor", 0xFF00_FF00, 0x0FF0_0FF0, 0xF0F0_F0F0),
            ("or_", 0xFF00_FF00, 0x0FF0_0FF0, 0xFFF0_FFF0),
            ("and_", 0xFF00_FF00, 0x0FF0_0FF0, 0x0F00_0F00),
        ],
    )


def test_immediates(run, bench: Bench) -> None:
    p = Program()
    p.li(1, 0x1234_5678)
    p.addi(2, 1, -1)
    p.slti(3, 1, -1)
    p.sltiu(4, 1, -1)  # -1 is 0xffffffff unsigned: 1
    p.xori(5, 1, -1)  # NOT
    p.ori(6, 0, -2048)
    p.andi(7, 1, 0x7FF)
    p.slli(8, 1, 4)
    p.srli(9, 5, 28)
    p.srai(10, 5, 28)
    p.lui(11, 0xFFFFF)
    p.label("here")
    p.auipc(12, 0x00001)
    p.addi(0, 1, 1)  # x0 stays 0
    p.add(13, 0, 0)
    p.fence()
    p.exit(0)
    result = run(p.assemble())
    assert result.exit_code == 0
    x = bench.x
    assert x[2] == 0x1234_5677
    assert x[3] == 0
    assert x[4] == 1
    assert x[5] == 0xEDCB_A987
    assert x[6] == 0xFFFF_F800
    assert x[7] == 0x678
    assert x[8] == 0x2345_6780
    assert x[9] == 0xE
    assert x[10] == 0xFFFF_FFFE
    assert x[11] == 0xFFFF_F000
    assert x[12] == 48 + 0x1000  # auipc is at 48 (li is two instructions)
    assert x[13] == 0


def test_loads(run, bench: Bench) -> None:
    p = Program()
    p.li(1, DATA)
    p.li(2, 0x8BAD_F00D)
    p.sw(2, 1, 0)
    p.lb(3, 1, 0)
    p.lbu(4, 1, 0)
    p.lb(5, 1, 3)
    p.lbu(6, 1, 3)
    p.lh(7, 1, 2)
    p.lhu(8, 1, 2)
    p.lh(9, 1, 0)
    p.lw(10, 1, 0)
    p.exit(0)
    result = run(p.assemble())
    assert result.exit_code == 0
    x = bench.x
    assert x[3] == 0x0000_000D
    assert x[4] == 0x0D
    assert x[5] == 0xFFFF_FF8B
    assert x[6] == 0x8B
    assert x[7] == 0xFFFF_8BAD
    assert x[8] == 0x8BAD
    assert x[9] == 0xFFFF_F00D
    assert x[10] == 0x8BAD_F00D


def test_stores(run, bench: Bench) -> None:
    p = Program()
    p.li(1, DATA)
    p.li(2, 0x8BAD_F00D)
    p.sw(2, 1, 0)
    p.li(3, 0x1234_56A5)
    p.sb(3, 1, 1)  # Only byte 1
    p.sh(3, 1, 6)  # The upper half of the next word
    p.lw(4, 1, 0)
    p.lw(5, 1, 4)
    p.addi(6, 1, 8)
    p.sw(2, 6, -4)  # A negative offset
    p.lw(7, 1, 4)
    p.exit(0)
    result = run(p.assemble())
    assert result.exit_code == 0
    x = bench.x
    assert x[4] == 0x8BAD_A50D
    assert x[5] == 0x56A5_0000
    assert x[7] == 0x8BAD_F00D


@pytest.mark.parametrize(
    "branch, a, b, taken",
    [
        ("beq", 5, 5, True),
        ("beq", 5, 6, False),
        ("bne", 5, 6, True),
        ("blt", -1, 1, True),
        ("blt", 1, -1, False),
        ("bge", -1, -1, True),
        ("bge", -2, -1, False),
        ("bltu", 1, -1, True),
        ("bltu", -1, 1, False),
        ("bgeu", -1, 1, True),
        ("bgeu", 1, -1, False),
    ],
)
def test_branches(run, bench: Bench, branch: str, a: int, b: int, taken: bool) -> None:
    p = Program()
    p.li(5, a)
    p.li(6, b)
    p.li(10, 1)
    getattr(p, branch)(5, 6, "skip")
    p.li(10, 2)
    p.label("skip")
    p.exit()
    result = run(p.assemble())
    assert result.exit_code == (1 if taken else 2)


def test_jumps(run, bench: Bench) -> None:
    p = Program()
    p.jal(1, "function")  # pc 0, x1 = 4
    p.j("after")  # pc 4
    p.label("function")
    p.mv(10, 1)  # pc 8
    p.jalr(0, 1, 0)  # back to 4
    p.label("after")
    p.li(5, 37)  # pc 16 (li is 8 bytes), an odd target: JALR clears bit 0 (37 -> 36)
    p.jalr(11, 5, 0)  # pc 24, x11 = 28
    p.li(12, 99)  # pc 28, jumped over
    p.label("target")
    p.li(13, 7)  # pc 36
    p.exit(0)
    result = run(p.assemble())
    assert result.exit_code == 0
    assert bench.x[10] == 4
    assert bench.x[11] == 28
    assert bench.x[12] == 0
    assert bench.x[13] == 7


def test_loop(run, bench: Bench) -> None:
    p = Program()
    p.li(5, 10)
    p.li(10, 0)
    p.label("loop")
    p.add(10, 10, 5)
    p.addi(5, 5, -1)
    p.bne(5, 0, "loop")
    p.putc("o")
    p.putc("k")
    p.exit()
    result = run(p.assemble())
    assert result.exit_code == 55
    assert result.text == "ok"
