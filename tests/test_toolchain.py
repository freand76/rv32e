# Copyright (c) Fredrik Andersson, 2026
# All rights reserved

"""
Checks against the GNU toolchain (skipped without riscv64-unknown-elf-as): the Python
assembler encodes the same bits as GNU as for rv32e, which also rejects the registers
x16..x31 (the processor traps on them, see test_traps.py).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from rv32sim import ISA
from rv32sim.asm import Program


AS = "riscv64-unknown-elf-as"
OBJCOPY = "riscv64-unknown-elf-objcopy"

pytestmark = pytest.mark.skipif(shutil.which(AS) is None, reason="no RISC-V toolchain")


def gnu_as(source: str, folder: Path) -> bytes:
    asm, obj, binary = folder / "t.S", folder / "t.o", folder / "t.bin"
    asm.write_text(".option norelax\n" + source + "\n")
    subprocess.run([AS, f"-march={ISA}", "-mabi=ilp32e", "-o", obj, asm], check=True)
    subprocess.run([OBJCOPY, "-O", "binary", "-j", ".text", obj, binary], check=True)
    return binary.read_bytes()


ENCODINGS = [
    ("add x5, x6, x7", lambda p: p.add(5, 6, 7)),
    ("sub x15, x1, x2", lambda p: p.sub(15, 1, 2)),
    ("sra x3, x4, x5", lambda p: p.sra(3, 4, 5)),
    ("sltu x10, x11, x12", lambda p: p.sltu(10, 11, 12)),
    ("and x1, x2, x3", lambda p: p.and_(1, 2, 3)),
    ("addi x5, x6, -2048", lambda p: p.addi(5, 6, -2048)),
    ("sltiu x5, x6, -1", lambda p: p.sltiu(5, 6, -1)),
    ("xori x5, x6, 2047", lambda p: p.xori(5, 6, 2047)),
    ("slli x5, x6, 31", lambda p: p.slli(5, 6, 31)),
    ("srai x5, x6, 7", lambda p: p.srai(5, 6, 7)),
    ("lui x5, 0xfffff", lambda p: p.lui(5, 0xFFFFF)),
    ("auipc x5, 0x12345", lambda p: p.auipc(5, 0x12345)),
    ("lb x5, -1(x6)", lambda p: p.lb(5, 6, -1)),
    ("lhu x5, 2046(x6)", lambda p: p.lhu(5, 6, 2046)),
    ("sw x7, -2048(x8)", lambda p: p.sw(7, 8, -2048)),
    ("sb x7, 5(x8)", lambda p: p.sb(7, 8, 5)),
    ("jalr x1, 12(x5)", lambda p: p.jalr(1, 5, 12)),
    ("jal x1, .+2048", lambda p: p.jal(1, 2048)),
    ("jal x0, .-1048576", lambda p: p.jal(0, -1048576)),
    ("beq x5, x6, .-4096", lambda p: p.beq(5, 6, -4096)),
    ("bgeu x14, x15, .+4094", lambda p: p.bgeu(14, 15, 4094)),
    ("ecall", lambda p: p.ecall()),
    ("ebreak", lambda p: p.ebreak()),
    ("fence", lambda p: p.fence()),
]


@pytest.mark.parametrize("source, build", ENCODINGS, ids=[e[0] for e in ENCODINGS])
def test_encoding(tmp_path: Path, source: str, build) -> None:
    p = Program()
    build(p)
    assert p.assemble().hex() == gnu_as(source, tmp_path).hex()


@pytest.mark.parametrize("source", ["add x16, x1, x2", "lw x5, 0(x31)", "mul x1, x2, x3"])
def test_not_rv32e(tmp_path: Path, source: str) -> None:
    """GNU as rejects what RV32E doesn't have"""
    with pytest.raises(subprocess.CalledProcessError):
        gnu_as(source, tmp_path)
