# Copyright (c) Fredrik Andersson, 2026
# All rights reserved

"""
Random instruction streams, run in lockstep with the reference model: every retired
instruction, the traps, the console and the RAM at the end must be the same. Also random
register fields, where x16..x31 (reserved in RV32E) make an instruction illegal.
"""

from __future__ import annotations

import random

import pytest

from rv32sim import DLM_BASE
from rv32sim.asm import ALU, LOAD, Program, b_type, i_type, j_type, r_type, s_type, u_type


DATA = DLM_BASE
BASE = 8  # x8 holds DATA, it isn't written
REGS = [reg for reg in range(1, 16) if reg != BASE]  # The destinations
VALUES = [0, 1, 2, 31, 32, -1, -2, 0x7FFF_FFFF, -0x8000_0000, 0x5555_5555, 0xAAAA_AAAA]


def random_value(rng: random.Random) -> int:
    return rng.choice(VALUES) if rng.random() < 0.4 else rng.getrandbits(32)


def random_program(seed: int, length: int) -> bytes:
    rng = random.Random(seed)
    p = Program()
    p.li(BASE, DATA)
    for reg in REGS:
        p.li(reg, random_value(rng))
    kinds = ["op", "op_imm", "shift", "lui", "load", "store", "branch"]

    def reg() -> int:
        return rng.choice(REGS)

    for index in range(length):
        p.label(f"L{index}")
        kind = rng.choice(kinds)
        if kind == "op":
            name = rng.choice([*ALU, "sub", "sra"])
            p.op(name, reg(), reg(), reg())
        elif kind == "op_imm":
            name = rng.choice(["add", "slt", "sltu", "xor", "or", "and"])
            p.op_imm(name, reg(), reg(), rng.randrange(-2048, 2048))
        elif kind == "shift":
            name = rng.choice(["slli", "srli", "srai"])
            rd, rs1, shamt = reg(), reg(), rng.randrange(32)
            p.srai(rd, rs1, shamt) if name == "srai" else p.op_imm(name[:3], rd, rs1, shamt)
        elif kind == "lui":
            (p.lui if rng.random() < 0.5 else p.auipc)(reg(), rng.getrandbits(20))
        elif kind == "load":
            name = rng.choice(list(LOAD))
            size = {"lb": 1, "lbu": 1, "lh": 2, "lhu": 2, "lw": 4}[name]
            p.load(name, reg(), BASE, rng.randrange(0, 256, size))
        elif kind == "store":
            name = rng.choice(["sb", "sh", "sw"])
            size = {"sb": 1, "sh": 2, "sw": 4}[name]
            p.store(name, reg(), BASE, rng.randrange(0, 256, size))
        else:
            # Forward, over 1 to 3 instructions
            target = f"L{min(index + rng.randint(1, 4), length)}"
            name = rng.choice(["beq", "bne", "blt", "bge", "bltu", "bgeu"])
            p.branch(name, reg(), reg(), target)
    p.label(f"L{length}")
    # The checksum of the registers is the exit code, the model checks the RAM
    p.li(10, 0)
    for reg_ in REGS:
        p.xor(10, 10, reg_)
    p.exit()
    return p.assemble()


def random_field_word(rng: random.Random) -> int:
    """
    An instruction with random register fields, a quarter of them x16..x31. Only
    instructions that can't reach outside the RAM: the loads and stores use x8 (or x24,
    reserved), the jumps and branches go 8 bytes forward.
    """

    def field() -> int:
        return rng.randrange(16, 32) if rng.random() < 0.25 else rng.randrange(16)

    def rd() -> int:
        """Not x8, the base of the loads and stores"""
        return rng.randrange(16, 32) if rng.random() < 0.25 else rng.choice([0, *REGS])

    def base() -> int:
        return BASE + 16 if rng.random() < 0.25 else BASE

    kind = rng.randrange(8)
    if kind == 0:  # OP
        funct3 = rng.randrange(8)
        funct7 = 0x20 if funct3 in (0, 5) and rng.random() < 0.5 else 0
        return r_type(funct7, field(), field(), funct3, rd(), 0x33)
    if kind == 1:  # OP-IMM
        funct3 = rng.choice([0, 2, 3, 4, 6, 7])
        return i_type(rng.randrange(-2048, 2048), field(), funct3, rd(), 0x13)
    if kind == 2:
        return u_type(rng.getrandbits(20), rd(), rng.choice([0x37, 0x17]))
    if kind == 3:
        return b_type(8, field(), field(), rng.choice([0, 1, 4, 5, 6, 7]))
    if kind == 4:
        return j_type(8, rd())
    if kind == 5:  # A load from x8 + 0..252
        return i_type(rng.randrange(0, 256, 4), base(), 2, rd(), 0x03)
    if kind == 6:  # A store to x8 + 0..252
        return s_type(rng.randrange(0, 256, 4), field(), base(), 2)
    # JALR to the next instruction but one, from x13 (set to it below)
    return i_type(0, 13 + 16 * (rng.random() < 0.25), 0, rd(), 0x67)


def random_field_program(seed: int, length: int) -> bytes:
    rng = random.Random(seed)
    p = Program()
    p.li(BASE, DATA)
    for reg in REGS:
        p.li(reg, random_value(rng))
    for _ in range(length):
        word = random_field_word(rng)
        if word & 0x7F == 0x67:
            # x13 = the instruction after the JALR
            p.auipc(13, 0)
            p.addi(13, 13, 12)
        p.word(word)
        p.word(0x0000_0013)  # nop, where the jumps and branches go
    p.exit(0)
    return p.assemble()


@pytest.mark.parametrize("seed", range(8))
def test_random(run, mode: str, seed: int) -> None:
    if mode == "gates" and seed >= 2:
        pytest.skip("two seeds on gates, the rest with --slow")
    result = run(random_program(seed, 120), max_cycles=1000)
    assert result.exit_code is not None


@pytest.mark.parametrize("seed", range(24))
def test_random_register_fields(run, mode: str, seed: int) -> None:
    """Each program runs until its first instruction with a reserved register, if any"""
    if mode == "gates" and seed >= 4:
        pytest.skip("four seeds on gates")
    result = run(random_field_program(seed, 12), max_cycles=1000)
    assert result.exit_code is not None or (result.halted and result.cause == 2)


@pytest.mark.slow
@pytest.mark.parametrize("seed", range(2, 8))
def test_random_gates(run, mode: str, seed: int) -> None:
    if mode != "gates":
        pytest.skip("only on gates")
    result = run(random_program(seed, 120), max_cycles=1000)
    assert result.exit_code is not None


@pytest.mark.slow
@pytest.mark.parametrize("seed", range(100, 140))
def test_random_long(run, mode: str, seed: int) -> None:
    if mode != "functional":
        pytest.skip("only on functional")
    result = run(random_program(seed, 500), max_cycles=3000)
    assert result.exit_code is not None
