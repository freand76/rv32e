# rv32: design decisions

A RISC-V processor written from "The RISC-V Instruction Set Manual, Volume I:
Unprivileged ISA", in one Verilog file (`rtl/rv32.v`), synthesized with digsim's Yosys
(YoWASP) and simulated with digsim. The test bench, the tests and a reference model are
in Python. No existing core was used as a starting point: the decoder and the datapath
follow the spec's tables and encoding figures.

## Scope

| | |
| --- | --- |
| ISA | RV32E: the RV32I instructions with 16 registers, x0 to x15 |
| Also | FENCE and FENCE.I (Zifencei) as no-ops |
| Not | M, C, F/D (no floating point), A, Zicsr (no CSRs), privileged modes, interrupts |
| Traps | ECALL, EBREAK, illegal instruction (also x16 to x31), misaligned load/store/jump, a fetch outside the ILM: the processor halts with the exception code |
| Memories | An instruction local memory (ILM) and a data local memory (DLM), with stalls: a busy memory makes the processor wait |

An earlier version was RV32I with M and C as parameters. It was cut down to RV32E: the
smallest base ISA, half the register file, and one configuration to test instead of
four.

## The processor

### Single-cycle

Every clock cycle fetches, decodes, executes and writes back one instruction. The
alternatives were a multi-cycle state machine or a pipeline.

- A single-cycle design is the shortest path from the spec to working RTL, with no
  hazards, forwarding or stalls to get right.
- One instruction per cycle makes the lockstep comparison with the reference model
  simple: the test bench samples the write-back port once per cycle.
- The cost is a long combinational path (fetch, decode, register read, ALU, load,
  write-back). In real hardware that sets a low clock frequency. In
  digsim the bench runs each half cycle until all events are done (see the test bench),
  so the path length costs simulation events, not correctness.

### Memories: combinational read, write on the clock edge

The processor has an instruction port and a data port (`imem_*`, `dmem_*`). Both read
combinationally (the data follows the address in the same cycle) and write on the
rising edge with byte strobes, which a single-cycle core needs.

- Every instruction is a 32-bit aligned word, so the instruction port returns the aligned
  word at the pc, like the data port.
- The data port returns the aligned word, and the core picks out and extends the bytes
  (LB/LH/LBU/LHU), and replicates them with strobes for SB/SH. That is what a real
  32-bit bus does.

### The local memories: ILM and DLM

The bench has two memories, like a small embedded core with tightly coupled memories:

| Address | Memory | What |
| --- | --- | --- |
| `0x0000_0000` | ILM, 2^`ilm_address_width` bytes | Code, read-only data, the load image of `.data` |
| `0x1000_0000` | Console | Character output, the exit register at `+4` |
| `0x2000_0000` | DLM, 2^`dlm_address_width` bytes | `.data`, `.bss` and the stack |

- **The ILM has two ports:** the instruction port, and a read-only port on the data side,
  so a load reads the program's constants where the linker put them, next to the code.
  A store to the ILM is an error. The core doesn't know the map: the memory system
  decodes the data address, and the core's data port stays 32 bits wide.
- **The processor's fetch port is as wide as the ILM:** `ILM_ADDR_WIDTH` (16 by
  default) is a parameter of the RTL, and a pc outside the ILM traps as an instruction
  access fault (code 1) without a fetch. The DLM's width is a parameter of the memories
  and the linker script (`--defsym`), not of the core.
- **`.data` is copied at startup.** `crt0.S` copies it from its load image in the ILM to
  the DLM, then clears `.bss`, as a program in flash does.

### Stalls

Both ports have a ready input (`imem_ready`, `dmem_ready`), for a memory that another
master (a DMA, a debugger) is using in a cycle. In a single-cycle core a stall is one
more term in the condition that a cycle counts:

- A cycle goes ahead when the instruction is fetched (`imem_ready`) and, for a load or a
  store, the data port is ready too. A fetch fault needs neither.
- While it waits, the core keeps its request on the port (the address, `dmem_re` and the
  strobes) and changes nothing: the pc, the registers and `halted` stay, and `retire` is
  0. A store is written at the edge of the cycle with `dmem_ready`, once.
- The bench can make both ports busy in random cycles (`Bench.run(stall=...)`, seeded),
  and the lockstep comparison leaves the stalled cycles out: the same instructions must
  retire with the same results, in more cycles.

A core that loads read-only data from a single-ported ILM would need more than a stall:
the port is fetching the load itself in the same cycle, so the instruction would have
to be kept in a register for a second cycle. The ILM's second port avoids that.

### Decoding

- Every legal instruction is recognized exactly, including the funct7 bits of the
  shifts and the funct3 values of loads, stores, branches and JALR. Everything else
  (M, compressed and CSR instructions, the reserved encodings, all zeros) is an illegal
  instruction, so a test can check that the processor does not execute what it doesn't
  implement.
- Immediates are built with the bit layouts of the spec's I, S, B, U and J formats.

### RV32E: 16 registers

RV32E is RV32I with x16 to x31 taken away, for small cores where the register file is a
large part of the area. The instructions and their encodings are the same, and the
register fields keep their 5 bits: the spec reserves the encodings that name x16 to x31.

- The core uses the low 4 bits of the fields, and an instruction whose format uses a
  field with the fifth bit set is illegal: rd for R, I, U and J, rs1 for R, I, S and B,
  rs2 for R, S and B. The bits of a field the format doesn't use (an immediate in the rs2
  field of an I-type, in the rd field of an S-type) can be anything.
- Trapping on them is the spec's choice for a core without them, and it makes a program
  built for RV32I fail at its first such instruction instead of running on with a wrong
  register.
- The ABI is ilp32e: GCC passes arguments in a0 to a5 and keeps the stack 4-byte
  aligned. Without M it calls libgcc for the multiplications and divisions.
- Without C a jump or taken branch to an address that is not 32-bit aligned traps as
  instruction address misaligned, on the jump.

### The register file

A 512-bit vector, `regfile[rd*32 +: 32]`, with x0 as the bottom 32 bits that are never
written. Yosys makes it one wide register and two shifters for the read ports, which the
functional netlist simulates as a few word operations, where an array would become a
memory or 15 registers and wide multiplexers.

It is reset to 0. The spec doesn't require that, but digsim simulates X: a register
read before it is written would make X results, and a branch on X makes the pc X.
Resetting it keeps every simulation defined and repeatable.

### Traps without CSRs

There is no Zicsr, so there is no mtvec to jump to. A trap halts the processor at the
trapping instruction (it doesn't retire) with the machine mode exception code in
`trap_cause` (0, 1, 2, 3, 4, 6, 11), which the tests check. Misaligned loads and stores
trap, as the spec allows.

### Observing the processor

The write-back port (`pc_out`, `retire`, `wb_we`, `wb_rd`, `wb_data`) shows what every
instruction did, a small version of RVFI. `pc_out` is the whole pc, where the fetch port
only has the ILM's bits. It is what makes the lockstep comparison possible without
reading the internal signals of the netlist, which digsim can do (`signals=True`) but
which slows the simulation down.

### One file

The RTL is one module in one file. `rv32sim/build.py` synthesizes it and caches the
netlist in `build/`, by a hash of the RTL and the mode, so changing the RTL rebuilds only
what changed.

When the core still had M and C as parameters, the first version had to write a copy of
the RTL with the parameter defaults changed for each configuration, because digsim's
synthesis couldn't set parameters. This project is why it can now: `Synthesis`,
`YosysComponent` and `python -m digsim.synth -p` take them.

## The test bench

- **A digsim circuit.** `Bench` builds a `Circuit` with the processor as a
  `YosysComponent` (from the functional or the gates netlist), the `LocalMemories` and a
  `Console`. `LocalMemories` (the ILM and the DLM, the instruction port and the decoded
  data port) and the `Console` (character output and an exit register) are new digsim
  components, small Python classes like digsim's own.
- **The clock is driven by the bench**, like the Fibonacci synthesis example drives its
  ports: it sets `clk` and runs the circuit for a half period. It sets the ready inputs
  in the low half, so the circuit has settled with them when the next cycle is sampled. A half period is 20 µs of
  simulated time, more than any path, and the bench checks that no events are left. The
  simulated time costs nothing, digsim jumps over it.
- **Writes see the values from before the edge.** The memories write in their update at
  the rising edge, before the processor's registers change (their outputs change one delta
  cycle later).
- **A reference model.** `rv32sim/iss.py` is an instruction set simulator from the spec,
  written apart from the RTL. It finds the format of an instruction first and checks its
  register fields against the 16 registers, where the RTL checks the fifth bit of each
  field it uses. In lockstep, every retired instruction (pc, instruction, register
  write), the traps, the console output and at the end both memories must be the same.

### Tests

The `mode` fixture (functional, gates) gives every test two variants. A bench per mode is
built once for the session. 224 tests run in about 40 s, 272 with `--slow` in under a
minute and a half.

| Test | Expected values from | Variants |
| --- | --- | --- |
| Instructions (ALU, immediates, loads, stores, branches, jumps) | The spec, worked out by hand | 2 |
| Traps, M and C instructions, x16 to x31 in each format | The spec's exception codes | 2 |
| Random instruction streams | The reference model | 2 (more seeds with --slow) |
| Random register fields, a quarter of them x16 to x31 | The reference model | 2 |
| Read-only data in the ILM, the memory map's errors, small memories | The memory map | 2 |
| Random stalls of both ports (20, 50 and 80 % of the cycles) | The same run without stalls, the reference model | 2 (the self test with --slow) |
| Python assembler, what rv32e doesn't have | GNU as | |
| C self test, 963 checks | GCC (constant folding) | functional, gates with --slow |

Breaking the RTL's check of the register fields on purpose makes 41 of the 44 tests of
reserved registers fail, so the tests reach it.

### Bugs the setup found

- **The processor: SRA and SRAI shifted in zeros.** In
  `funct7[5] ? $signed(a) >>> shamt : a >> shamt` the unsigned operand of `?:` makes the
  whole expression unsigned, so `>>>` is a logical shift. A classic Verilog pitfall. The
  lockstep run of the self test stopped at the first wrong SRAI (cycle 1192 on rv32i,
  before the core was RV32E),
  with the pc, the instruction and both values. The fix is a signed wire of its own.
- **The Icarus/Verilator test bench (compare/), twice.** A store followed by a load from
  the same address read the old word: in Icarus, a continuous assignment that calls a
  function only follows the function's arguments, not the memory array. And Verilator
  didn't see the exit flag, set in the clocked block, in an `initial` block waiting with
  `@(posedge clk)`. The digsim bench had neither problem: its RAM is Python code that
  evaluates its outputs after each write.

## The netlists

| | Functional | Gates |
| --- | --- | --- |
| Cells | 190 (adders, comparators, multiplexers, registers) | 7,770 (MUX, AND, OR, XOR, NOT, 547 flip-flops) |
| Synthesis | 0.5 s | 4.0 s |

RV32I without M had 11,393 gates and 1,060 flip-flops: the 16 registers save a third of
the gates and half the flip-flops. The operand isolation below costs 478 gates (7,292
before it).

## Simulation time: less switching per cycle

An event-driven simulator does work for every signal that changes, and a single-cycle
core computes everything for every instruction: the shifter, the comparators and the
address adder see new operands each cycle even when the result is thrown away, and every
intermediate value (a glitch, as a signal settles) is an event too. The self test was
timed after each change (86,750 cycles, the native engine, no lockstep):

| Change | Functional | Gates |
| --- | ---: | ---: |
| RV32E, one shared RAM (before this) | 10.7 s | 51.1 s |
| ILM and DLM, the stall inputs | 11.9 s | 52.5 s |
| The data port is 0 unless a load or store goes out | 7.9 s | 42.5 s |
| Unused register fields read x0 (undone) | 8.7 s | 53.4 s |
| The shifter only sees the operands of a shift | 8.2 s | 40.1 s |
| The branch comparators only see a branch's operands | 8.0 s | 38.9 s |
| The pc in one register of bits 31:2 | 8.0 s | 38.6 s |
| The memories recompute only the output whose address changed (bench) | 7.7 s | 38.0 s |
| The ALU only sees the operands of OP and OP-IMM | 7.4 s | 37.4 s |
| The address and jump target adders only see their instructions' operands | 6.8 s | 33.0 s |
| `wb_data` is 0 unless a register is written (undone) | 6.9 s | 33.9 s |

In all, 36 % less time functional and 35 % at gate level, and 40 % in the Python engine
(below). What it showed:

- **Isolating the data port was the largest gain.** Before it the memories were woken
  15 times a cycle, by every glitch of `rs1 + imm` for every instruction, also the ones
  that don't load or store. Gated with the decode, the port changes about once a cycle.
- **Isolation pays off for a large unit behind operands that change every cycle**: the
  shifter, the comparators and the adders. It costs where the gate sits behind a decode
  that settles late: gating the register read indices with "uses rs1" made both netlists
  slower, since the multiplexer then switches with every glitch of the decode too.
- **The pc was three flip-flops** in the functional netlist (bits 31:2, 1 and 0), which
  changed in separate events. As one 30-bit register the low bits are constant zeros
  (the pc is always 32-bit aligned) and two flip-flops go.
- **digsim updates a component once per changed bit of a bus** that comes from a
  netlist, so the ILM sees an address pass through intermediate values at each edge. Its
  outputs have a 1 ns delay, and an event replaced by a later one for the same port is
  skipped, so the processor only sees the last word: the cost is the Python calls, which
  the memories now keep short.

The functional netlist simulates whole words per cell, the gates netlist one bit per
gate, with a 1 ns delay per gate. Both run the same tests, and the functional one is
used for the long runs.

## Comparison with Icarus Verilog and Verilator

`compare/` runs the same RTL and the same self test on Icarus Verilog 13.0 (devel) and
Verilator 5.032, with a Verilog test bench (`tb_rv32.v`) that has the same memory map and
writes the same trace (pc, instruction, register write). `run_compare.py` builds and
runs everything and writes `compare/results.md`, digsim in the engines of `--engines`.
On one x86-64 machine, with nothing else running and no lockstep model, Python 3.14:

| Simulator | rv32e self test (86,750 cycles) | Build |
| --- | ---: | --- |
| digsim native, functional netlist | 6.9 s, 12,600 cycles/s | synthesis 0.5 s (cached) |
| digsim native, gates netlist | 33 s, 2,600 cycles/s | synthesis 4.0 s (cached) |
| digsim Python, functional netlist | 81 s, 1,070 cycles/s | synthesis 0.5 s (cached) |
| digsim Python, gates netlist | 427 s, 200 cycles/s | synthesis 4.0 s (cached) |
| Icarus Verilog, RTL | 2.2 s, 39,000 cycles/s | < 0.1 s |
| Verilator, RTL | 0.10 s, 910,000 cycles/s | 7 s (C++ compile) |

All six runs pass with exactly the same trace. The operand isolation (above) also made
Icarus a fifth faster, which is event-driven too. Verilator, which evaluates its logic
every cycle, didn't change.

- **The RTL is portable.** It ran unchanged on three simulators with three different
  front ends (Yosys, Icarus, Verilator), and every one retired the same 86,750
  instructions with the same results. Nothing in it depended on digsim.
- **Verilator is about 70 times faster than digsim's functional netlist** in the native
  engine, and Icarus 3 times (850 and 37 times in the Python engine). The tests also run
  the lockstep reference model, in Python too, which slows digsim down further. The C
  self test takes 7 s in digsim's native engine (81 s in Python) and a tenth of a second
  in Verilator.
- **The native engine is 12 to 13 times faster than the Python engine**, at gate level
  and functional. At gate level it simulates every gate in Rust, the Python engine does
  one Python call per gate, and with 7,800 gates and their glitches the event count
  dominates.
- **Icarus first ran the gate netlist at under 4 cycles/s**, much slower than digsim.
  Yosys writes the register file's read shifters as wide wires, and when one bit of a
  vector changes Icarus wakes every reader of the whole vector. `splitnets` (a wire per
  bit) made it 200 times faster. digsim never had the problem, its netlist is per bit.
- **The test bench was the weak point of the Verilog flows**: both test bench bugs
  (above) were in `tb_rv32.v`, in the simulator semantics of `initial` blocks and of
  functions in continuous assignments. The Python bench had none, and debugging it is
  ordinary Python.

## Conclusion

This was a small project, a single-cycle core with about 280 lines of RTL and about 2,000
lines of Python, but it went the whole way: RTL from the spec, a synthesized netlist,
unit tests, random tests in lockstep with a model, a C program, and gate-level
simulation. digsim carried all of it, and the comparison
puts numbers on what that costs.

### Compared with the open source Verilog flows

The usual open source flow is Icarus Verilog or Verilator for simulation, cocotb for a
Python test bench, Yosys for synthesis, SymbiYosys for formal checks, and GTKWave for
waveforms. GHDL and NVC do the same for VHDL.

Pros of digsim:

- **One install, pure Python.** `pip install` brings the simulator and Yosys (as
  WebAssembly), on Linux, Windows and macOS. No C++ compiler (Verilator), no native
  builds, no version matching between cocotb and a simulator.
- **The test bench is Python with no bridge.** cocotb gives Verilog a Python test bench
  too, but through a VPI or VHPI interface, with coroutines and triggers and a separate
  process per simulation. Here the bench, the RAM, the console, the reference model and
  pytest run in one process. A pytest fixture parametrized over the netlist gives every
  test both variants for a few lines of code, and a session cache keeps a netlist loaded
  for all of them.
- **New components are small Python classes.** The RAM and the console are about 100
  lines each, with no VPI, DPI or `$readmemh`, and can raise or record errors (a load
  outside the map) that a Verilog model would print and hope someone reads.
- **It simulates the synthesized netlist.** Every run, functional or gates, is
  post-synthesis. A Verilog construct that simulates one way and synthesizes another
  (a missing sensitivity, a latch, X optimism in an `if`) can't pass the tests here. With
  Icarus or Verilator that needs a separate gate-level run, which this comparison had to
  set up by hand.
- **X and Z are simulated at gate level.** A register read before it is written gives X,
  and the bench stops on it. This is why the
  register file is reset: digsim showed the X, where Verilator's two-state simulation
  would have shown a 0 or a random value.
- **The same circuit opens in the GUI**, with the netlist as a component that can be
  probed, wired to LEDs or 7-segment displays, and clocked by hand. That is for teaching
  and demos, a different job from regression testing.

Cons of digsim:

- **Speed.** About 12,600 cycles/s functional and 2,600 cycles/s at gate level in the
  native engine (a twelfth of that in Python), against 39,000 for Icarus and close to a
  million for Verilator. A processor test that runs an OS boot or a benchmark suite
  (billions of cycles) is out of reach, and the self test takes half a minute on the
  gates netlist. The test suite works around it with small
  programs, and with the long runs on the functional netlist behind `--slow`.
- **Only synthesizable Verilog.** The design has to go through Yosys, so the test bench
  can't be Verilog: no `initial` blocks, `$display`, SystemVerilog assertions, classes,
  constrained random or UVM. Everything that a verification environment does has to be
  written in Python, and an existing Verilog test bench or VIP can't be used.
- **No hierarchy.** The netlist is flattened, and internal signals are reached by Yosys
  names, not through the module hierarchy. (Parameters were missing too, until this
  project added them.)
- **No timing.** Each cell has a 1 ns delay, which is a unit-delay model, not timing. It
  shows glitches and races but not setup or hold violations. Real gate-level timing
  needs SDF back-annotation in a simulator that reads it.
- **No coverage and no formal.** There is no line, toggle or FSM coverage, and nothing
  measures how much of the design the random tests reach. SymbiYosys could prove things like "x0 is
  always 0" or check against riscv-formal, which nothing here does.
- **Debugging is at netlist level.** A VCD is written, but it shows the netlist's
  signals. Icarus and Verilator dump the RTL's own signals and hierarchy.

### Compared with the licensed EDA tools

The commercial flow is a simulator like Siemens Questa (ModelSim), Synopsys VCS, Cadence
Xcelium or Aldec Riviera-PRO (or Vivado's xsim for FPGAs), with UVM, functional and code
coverage, formal tools (Cadence Jasper, Synopsys VC Formal, Siemens Questa Formal), and
emulation (Palladium, ZeBu, Veloce) for the long runs.

- **What they do that digsim can't:** the whole of SystemVerilog and VHDL, with mixed
  languages. Compiled simulation at Verilator-like speed or better, with four-state
  values and full debug. Timing simulation with SDF, power-aware simulation (UPF),
  coverage-driven verification with a verification plan, assertions and formal proofs,
  and waveform debuggers that link waveforms, the source and the schematic (Verdi,
  Visualizer, SimVision). Emulation runs at MHz, enough to boot Linux on a core. For a
  core that goes to silicon, none of this is optional.
- **What digsim has for itself:** it is free, installs in seconds without license
  servers, runs anywhere Python runs (including CI on Windows) and is readable down to
  every event. For a student, a hobby design or a first prototype, the cost and setup of
  the licensed tools (or of a cocotb plus Verilator flow) are larger than the design.

### Verdict

digsim is a good place to design and understand a small processor, and a poor place to
verify a real one. The Python bench made the tests cheap to write and its failure
messages precise (the SRA bug was found at its first instruction, with the operands),
and it simulated the synthesized design from the first run. For the long runs, the
speed is one to two orders of magnitude short of Icarus and Verilator. A practical
mix is the one this project ended up with: the design and the tests in digsim, and
the same RTL checked in Verilator for the long programs, which the identical traces show
is trustworthy.
