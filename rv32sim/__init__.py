# Copyright (c) Fredrik Andersson, 2026
# All rights reserved

"""A framework for designing and testing an RV32E processor with digsim"""

from .bench import Bench, Mismatch, Result
from .build import ISA, REGISTERS, netlist
from .devices import (
    CONSOLE_EXIT,
    CONSOLE_TX,
    DLM_ADDRESS_WIDTH,
    DLM_BASE,
    ILM_ADDRESS_WIDTH,
    ILM_BASE,
    Console,
    LocalMemories,
)
from .iss import Iss, Retired
