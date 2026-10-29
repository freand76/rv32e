# rv32: a RISC-V processor designed and tested with digsim

An RV32E processor (the RV32I instructions with 16 registers, x0 to x15), written in one
Verilog file from the RISC-V specification, synthesized by digsim's Yosys (YoWASP) and
simulated by digsim. The test bench, the tests and a reference model are in Python. The
design decisions and a comparison with other Verilog workflows are in
[DESIGN.md](DESIGN.md).

It depends on digsim ([digsim-logic-simulator](https://pypi.org/project/digsim-logic-simulator/)
on PyPI), which `uv` installs with the rest in `.venv`.

```text
rtl/rv32.v              the processor (the only RTL file)
rv32sim/build.py        synthesize the RTL, cached in build/
rv32sim/devices.py      new digsim components: LocalMemories (ILM and DLM), Console
rv32sim/bench.py        the test bench: a digsim Circuit with the processor, the memories, the console
rv32sim/iss.py          the reference model, an instruction set simulator from the spec
rv32sim/asm.py          a small assembler for tests (RV32E, and the reserved encodings)
programs/               startup code, linker script, selftest.c and its binary
tests/                  pytest
compare/                the same RTL and program on Icarus Verilog and Verilator
```

## Running

From this folder:

```sh
uv run pytest                                  # ~40 s
uv run pytest --slow                           # everything (gates, more seeds)
uv run python -m rv32sim programs/bin/selftest_rv32e.bin
uv run python -m rv32sim programs/bin/selftest_rv32e.bin --gates
python3 programs/build_programs.py             # needs riscv64-unknown-elf-gcc
cd compare && uv run python run_compare.py     # needs iverilog and verilator
```

The first run synthesizes the netlists (a few seconds each), later runs take them from
`build/`. `python -m rv32sim` also takes `--stall 0.3` (the memories are busy in 30 % of
the cycles), `--lockstep`, `--vcd`, and `--ilm-width` and `--dlm-width` for the memories'
address bits.

## The memory map

| Address | What |
| --- | --- |
| `0x0000_0000` | ILM, 64 KiB (`ILM_ADDR_WIDTH` = 16): code, read-only data and the load image of `.data`. The data port reads it, a store to it is an error |
| `0x1000_0000` | Console: a store prints its low byte |
| `0x1000_0004` | Exit register: a store ends the simulation with its value |
| `0x2000_0000` | DLM, 64 KiB: `.data` (copied by `crt0.S`), `.bss` and the stack |

The processor fetches from the ILM, with `ILM_ADDR_WIDTH` address bits (a parameter), and
its data port reaches the whole map. Both ports have a ready input: a memory that another
master is using holds it low, and the processor waits.

## The tests

Every test runs on both netlists (functional blocks and gates), with the `mode` fixture,
and in lockstep with the reference model (cycles where a memory stalls the processor are
left out of the comparison). x14 and x15 are the scratch registers of the
assembler's `exit()` and `putc()`.

| File | What |
| --- | --- |
| `test_instructions.py` | Known answers from the spec: ALU, immediates, loads and stores, branches, jumps |
| `test_traps.py` | ECALL, EBREAK, illegal instructions (M, C, x16 to x31 in each format), misaligned loads, stores and jumps, fetches outside the ILM |
| `test_memories.py` | Read-only data in the ILM, the errors of the memory map, small memories, random stalls of both ports |
| `test_random.py` | Random instruction streams, and random register fields with reserved registers, lockstep with the model |
| `test_toolchain.py` | The Python assembler against GNU as for rv32e, and what GNU as rejects for rv32e |
| `test_programs.py` | The C self test (selftest.c, built for rv32e/ilp32e, GCC is the reference) |
