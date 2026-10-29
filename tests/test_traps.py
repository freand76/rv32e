# Copyright (c) Fredrik Andersson, 2026
# All rights reserved

"""
Traps: the processor halts at the instruction with the exception code in trap_cause.
RV32E has no M and no C, and the registers x16..x31 are reserved: instructions that use
them are illegal.
"""

from __future__ import annotations

import pytest

from rv32sim import DLM_BASE, ILM_ADDRESS_WIDTH
from rv32sim.asm import Program, i_type, r_type, s_type


DATA = DLM_BASE
BASE = 8


def trap_program(body) -> tuple[bytes, int]:
    """A program that sets x8 = DATA, then runs body(p). Returns it and body's pc"""
    p = Program()
    p.li(BASE, DATA)
    pc = p.pc
    body(p)
    p.exit(0)
    return p.assemble(), pc


@pytest.mark.parametrize(
    "name, body, cause",
    [
        ("ecall", lambda p: p.ecall(), 11),
        ("ebreak", lambda p: p.ebreak(), 3),
        ("all zeros", lambda p: p.word(0), 2),
        ("all ones", lambda p: p.word(0xFFFF_FFFF), 2),
        ("csrrw (no Zicsr)", lambda p: p.word(0x3401_1073), 2),
        ("slli with bit 25", lambda p: p.word(0x0200_9293), 2),
        ("sub-like add", lambda p: p.word(0x0400_02B3), 2),  # funct7 0000010
        ("jalr funct3 1", lambda p: p.word(0x0000_10E7), 2),
        ("branch funct3 2", lambda p: p.word(0x0000_2063), 2),
        ("load funct3 3", lambda p: p.word(0x0000_3283), 2),
        ("store funct3 3", lambda p: p.word(0x0000_3023), 2),
        ("lw misaligned", lambda p: p.lw(5, BASE, 1), 4),
        ("lh misaligned", lambda p: p.lh(5, BASE, 3), 4),
        ("sw misaligned", lambda p: p.sw(5, BASE, 2), 6),
        ("sh misaligned", lambda p: p.sh(5, BASE, 1), 6),
        # No M
        ("mul", lambda p: p.word(r_type(1, 6, 5, 0, 7, 0x33)), 2),
        ("div", lambda p: p.word(r_type(1, 6, 5, 4, 7, 0x33)), 2),
        # No C: c.li x10, 3 followed by c.nop
        ("compressed", lambda p: p.word(0x0001_450D), 2),
    ],
)
def test_trap(run, name: str, body, cause: int) -> None:
    image, pc = trap_program(body)
    result = run(image)
    assert result.halted
    assert result.cause == cause, result.cause_text
    assert result.pc == pc
    assert result.exit_code is None


@pytest.mark.parametrize(
    "name, body",
    [
        ("add rd x16", lambda p: p.add(16, 1, 2)),
        ("add rs1 x17", lambda p: p.add(1, 17, 2)),
        ("sub rs2 x31", lambda p: p.sub(1, 2, 31)),
        ("addi rd x20", lambda p: p.addi(20, 1, 1)),
        ("addi rs1 x16", lambda p: p.addi(1, 16, 1)),
        ("srai rs1 x24", lambda p: p.srai(1, 24, 3)),
        ("lw rd x18", lambda p: p.lw(18, BASE, 0)),
        ("lw rs1 x18", lambda p: p.lw(1, 18, 0)),
        ("sw rs2 x16", lambda p: p.sw(16, BASE, 0)),
        ("sw rs1 x30", lambda p: p.sw(1, 30, 0)),
        ("beq rs1 x16", lambda p: p.beq(16, 0, 8)),
        ("bne rs2 x19", lambda p: p.bne(0, 19, 8)),
        ("lui rd x16", lambda p: p.lui(16, 1)),
        ("auipc rd x31", lambda p: p.auipc(31, 1)),
        ("jal rd x16", lambda p: p.jal(16, 8)),
        ("jalr rs1 x16", lambda p: p.jalr(1, 16, 0)),
        ("jalr rd x16", lambda p: p.jalr(16, 1, 0)),
    ],
)
def test_reserved_register(run, name: str, body) -> None:
    """RV32E: x16..x31 in a register field that the instruction uses is illegal"""
    image, pc = trap_program(body)
    result = run(image)
    assert result.halted and result.cause == 2 and result.pc == pc


@pytest.mark.parametrize(
    "name, word",
    [
        # The rs2 field of an I-type instruction holds immediate bits: addi x1, x0, 0x7ff
        ("addi with a large immediate", i_type(0x7FF, 0, 0, 1, 0x13)),
        # lui x1 with bits that would be rs1 and rs2 in other formats
        ("lui with any immediate", 0xFFFF_F0B7),
        # The rd field of a store holds immediate bits, 16 here: sw x1, 16(x8)
        ("sw with offset 16", s_type(16, 1, BASE, 2)),
    ],
)
def test_unused_register_fields_are_fine(run, name: str, word: int) -> None:
    """The fields of the format that aren't registers can hold any value"""
    image, _ = trap_program(lambda p: p.word(word))
    result = run(image)
    assert not result.halted and result.exit_code == 0


def test_unaligned_lb_and_lbu_are_fine(run) -> None:
    image, _ = trap_program(lambda p: (p.lb(5, BASE, 3), p.lbu(6, BASE, 1), p.sb(5, BASE, 3)))
    result = run(image)
    assert not result.halted and result.exit_code == 0


def test_jump_to_16_bit_boundary(run) -> None:
    """There is no C: a jump to pc + 2 traps, on the jump"""
    p = Program()
    p.li(10, 5)
    p.jal(0, 10)  # pc 8 -> 18
    p.word(0)
    p.word(0)
    p.exit()
    result = run(p.assemble())
    assert result.halted and result.cause == 0 and result.pc == 8


def test_taken_branch_to_16_bit_boundary(run) -> None:
    p = Program()
    p.li(10, 5)
    p.beq(0, 0, 10)  # pc 8 -> 18
    p.word(0)
    p.word(0)
    p.exit()
    result = run(p.assemble())
    assert result.halted and result.cause == 0 and result.pc == 8


def test_jalr_to_16_bit_boundary(run) -> None:
    p = Program()
    p.li(5, 22)
    p.jalr(0, 5, 0)  # pc 8 -> 22
    p.exit(0)
    result = run(p.assemble())
    assert result.halted and result.cause == 0 and result.pc == 8


def test_branch_not_taken_to_16_bit_boundary(run) -> None:
    """Only a taken branch can trap"""
    p = Program()
    p.li(10, 5)
    p.bne(0, 0, 10)
    p.exit()
    result = run(p.assemble())
    assert result.exit_code == 5


@pytest.mark.parametrize("target", [1 << ILM_ADDRESS_WIDTH, DLM_BASE, 0xFFFF_FFFC])
def test_fetch_outside_the_ilm(run, target: int) -> None:
    """Above the ILM there is nothing to fetch: an instruction access fault at the target"""
    p = Program()
    p.li(5, target)
    p.jalr(0, 5, 0)
    result = run(p.assemble())
    assert result.halted and result.cause == 1 and result.pc == target


def test_fetch_of_zeros_in_the_ilm(run) -> None:
    """The ILM past the program is zeros, an illegal instruction"""
    p = Program()
    p.li(5, 0x1000)
    p.jalr(0, 5, 0)
    result = run(p.assemble())
    assert result.halted and result.cause == 2 and result.pc == 0x1000
