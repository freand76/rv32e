# Copyright (c) Fredrik Andersson, 2026
# All rights reserved

"""
Run a program on the processor:

    uv run python -m rv32sim programs/bin/selftest_rv32e.bin
    ... --gates           the gates netlist instead of the functional one
    ... --lockstep        compare every instruction with the reference model
    ... --vcd cpu.vcd     write the waveforms
    ... --stall 0.3       the memories are busy in 30 % of the cycles (each port)
    ... --ilm-width 15    the ILM's address bits (and --dlm-width the DLM's)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import DLM_ADDRESS_WIDTH, ILM_ADDRESS_WIDTH, Bench


def main() -> int:
    parser = argparse.ArgumentParser(prog="rv32sim", description=__doc__.split("\n")[1])
    parser.add_argument("program", type=Path, help="a binary image, loaded at address 0")
    parser.add_argument("--gates", action="store_true", help="simulate the gates netlist")
    parser.add_argument("--lockstep", action="store_true", help="compare with the model")
    parser.add_argument("--vcd", type=Path, help="write the waveforms to a VCD file")
    parser.add_argument("--max-cycles", type=int, default=1_000_000)
    parser.add_argument("--stall", type=float, default=0.0, help="busy memory probability")
    parser.add_argument("--ilm-width", type=int, default=ILM_ADDRESS_WIDTH)
    parser.add_argument("--dlm-width", type=int, default=DLM_ADDRESS_WIDTH)
    args = parser.parse_args()

    bench = Bench(
        args.program.read_bytes(),
        functional=not args.gates,
        ilm_address_width=args.ilm_width,
        dlm_address_width=args.dlm_width,
        vcd=args.vcd,
        echo=True,
    )
    result = bench.run(max_cycles=args.max_cycles, lockstep=args.lockstep, stall=args.stall)
    print(
        f"\n{result.cycles} cycles ({result.stalls} stalled) in {result.seconds:.2f} s"
        f" ({result.cycles / result.seconds:.0f}/s)"
    )
    if result.halted:
        print(f"Halted at 0x{result.pc:08x}: {result.cause_text}")
        return 1
    if result.exit_code is None:
        print("Stopped after --max-cycles")
        return 1
    print(f"Exit code {result.exit_code}")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
