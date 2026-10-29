# Copyright (c) Fredrik Andersson, 2026
# All rights reserved

"""
Synthesize the processor RTL with digsim's Yosys (YoWASP).

The RTL is one file, rtl/rv32.v, an RV32E processor, with the ILM's address width as a
parameter. The netlists are cached in build/, by a hash of the RTL, the width and the
synthesis mode.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from digsim.synth import Synthesis

from .devices import ILM_ADDRESS_WIDTH


ROOT = Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl" / "rv32.v"
# In the project, not in /tmp: YoWASP can't read the real /tmp
BUILD = ROOT / "build"
TOP = "rv32"
# The ISA of the processor, for GCC (-march) and the names of the programs
ISA = "rv32e"
# x0..x15
REGISTERS = 16


def netlist(functional: bool, ilm_address_width: int = ILM_ADDRESS_WIDTH) -> Path:
    """
    The Yosys JSON netlist of the processor, synthesized into functional blocks
    (functional=True) or into gates, from the cache if the RTL didn't change
    """
    BUILD.mkdir(exist_ok=True)
    mode = "functional" if functional else "gates"
    parameters = {"ILM_ADDR_WIDTH": ilm_address_width}
    key = f"{mode}\n{parameters}\n{RTL.read_text(encoding='utf-8')}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:12]
    name = f"{TOP}_{ISA}_ilm{ilm_address_width}_{mode}"
    json_path = BUILD / f"{name}_{digest}.json"
    if not json_path.exists():
        partial = json_path.with_suffix(".partial")
        synthesis = Synthesis(RTL, TOP, functional=functional, parameters=parameters)
        synthesis.synth_to_json_file(partial, silent=True)
        partial.replace(json_path)
        # Old netlists of this width and mode, and the ones from before the width
        for old in [*BUILD.glob(f"{name}_*.json"), *BUILD.glob(f"{TOP}_{ISA}_{mode}_*.json")]:
            if old != json_path:
                old.unlink()
    return json_path
