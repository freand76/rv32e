# Copyright (c) Fredrik Andersson, 2026
# All rights reserved

"""
The C test program (programs/selftest.c, built by programs/build_programs.py for rv32e),
in lockstep with the reference model. It must print PASS and exit 0.

On the functional netlist by default, the gates with --slow. There is no M, the program
calls libgcc's software multiplication and division.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rv32sim import ISA


PROGRAMS = Path(__file__).resolve().parent.parent / "programs" / "bin"


def test_selftest(run, mode: str, request: pytest.FixtureRequest) -> None:
    if mode == "gates" and not request.config.getoption("--slow"):
        pytest.skip("a long test, run with --slow")
    image = (PROGRAMS / f"selftest_{ISA}.bin").read_bytes()
    result = run(image, max_cycles=150_000)
    assert result.text.endswith("PASS\n"), result.text
    assert " 0 failures" in result.text
    assert result.exit_code == 0
    print(f"{ISA} {mode}: {result.cycles} cycles in {result.seconds:.1f} s")
