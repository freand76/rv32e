# Copyright (c) Fredrik Andersson, 2026
# All rights reserved

"""
The local memories and the stalls: read-only data in the ILM, the errors of the memory
map, the address widths, and memories that are busy in random cycles (the processor
must wait and run the same instructions, in lockstep with the model).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_random import random_program

from rv32sim import DLM_BASE, ISA, Bench
from rv32sim.asm import Program


PROGRAMS = Path(__file__).resolve().parent.parent / "programs" / "bin"


def test_read_only_data_in_the_ilm(run, bench: Bench) -> None:
    """The data port reads the ILM: a table after the code"""
    p = Program()
    p.li(1, 0)  # The address of the table, set below
    p.lw(2, 1, 0)
    p.lbu(3, 1, 5)
    p.lh(4, 1, 6)
    p.lb(5, 1, 7)
    p.exit(0)
    table = p.pc
    p.word(0x1234_5678)
    p.word(0x8001_7F42)
    image = bytearray(p.assemble())
    # li 1, table: lui x1, 0 and addi x1, x1, table
    image[4:8] = (int.from_bytes(image[4:8], "little") | (table << 20)).to_bytes(4, "little")
    result = run(bytes(image))
    assert result.exit_code == 0
    assert bench.x[2] == 0x1234_5678
    assert bench.x[3] == 0x7F
    assert bench.x[4] == 0xFFFF_8001
    assert bench.x[5] == 0xFFFF_FF80


def test_store_to_the_ilm_is_an_error(run) -> None:
    p = Program()
    p.li(1, 0x100)
    p.sw(0, 1, 0)
    p.exit(0)
    with pytest.raises(RuntimeError, match="read-only"):
        run(p.assemble())


@pytest.mark.parametrize("address", [0x1000_0010, DLM_BASE - 4, DLM_BASE + (1 << 16)])
def test_load_outside_the_memories_is_an_error(run, address: int) -> None:
    p = Program()
    p.li(1, address)
    p.lw(2, 1, 0)
    p.exit(0)
    with pytest.raises(RuntimeError, match="outside the memories"):
        run(p.assemble())


_small: dict[str, Bench] = {}


@pytest.fixture
def small(mode: str) -> Bench:
    """A bench with a 4 KiB ILM and a 1 KiB DLM"""
    if mode not in _small:
        _small[mode] = Bench(
            b"", functional=mode == "functional", ilm_address_width=12, dlm_address_width=10
        )
    return _small[mode]


def test_small_memories(small: Bench) -> None:
    p = Program()
    p.li(1, DLM_BASE + 0x3FC)  # The last word of the DLM
    p.li(2, 77)
    p.sw(2, 1, 0)
    p.lw(10, 1, 0)
    p.exit()
    small.load(p.assemble())
    result = small.run(max_cycles=200, lockstep=True)
    assert result.exit_code == 77


def test_fetch_above_a_small_ilm(small: Bench) -> None:
    p = Program()
    p.li(5, 0x1000)  # Just above the 4 KiB ILM
    p.jalr(0, 5, 0)
    small.load(p.assemble())
    result = small.run(max_cycles=200, lockstep=True)
    assert result.halted and result.cause == 1 and result.pc == 0x1000


def test_store_above_a_small_dlm(small: Bench) -> None:
    p = Program()
    p.li(1, DLM_BASE + 0x400)
    p.sw(0, 1, 0)
    p.exit(0)
    small.load(p.assemble())
    with pytest.raises(RuntimeError, match="outside the memories"):
        small.run(max_cycles=200, lockstep=True)


@pytest.mark.parametrize("stall", [0.2, 0.5, 0.8])
@pytest.mark.parametrize("seed", range(3))
def test_stalls(run, mode: str, stall: float, seed: int) -> None:
    """Busy memories: the same instructions and results, in more cycles"""
    if mode == "gates" and seed:
        pytest.skip("one seed on gates")
    image = random_program(seed, 120)
    steady = run(image, max_cycles=1000)
    stalled = run(image, max_cycles=10_000, stall=stall, seed=seed)
    assert stalled.exit_code == steady.exit_code
    assert stalled.stalls > 0
    assert stalled.cycles > steady.cycles


def test_stalled_stores_are_written_once(run) -> None:
    """A store waits for its cycle with dmem_ready, and is written in it once"""
    p = Program()
    for char in "stall":
        p.putc(char)
    p.exit(0)
    result = run(p.assemble(), max_cycles=2000, stall=0.6, seed=7)
    assert result.text == "stall"
    assert result.exit_code == 0


@pytest.mark.slow
def test_selftest_with_stalls(run, mode: str) -> None:
    if mode != "functional":
        pytest.skip("only on functional")
    image = (PROGRAMS / f"selftest_{ISA}.bin").read_bytes()
    result = run(image, max_cycles=400_000, stall=0.3, seed=1)
    assert result.text.endswith("PASS\n") and result.exit_code == 0
