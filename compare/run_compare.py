# Copyright (c) Fredrik Andersson, 2026
# All rights reserved

"""
Run the same RTL (rtl/rv32.v) and programs on digsim, Icarus Verilog and Verilator, check
that they retire the same instructions with the same results, and time them.

    uv run python run_compare.py [--digsim-gates] [--engines python native]

The simulators:
- digsim, functional netlist (and gates with --digsim-gates: slow, minutes), with each
  engine of --engines (both by default, "native" only if the package is installed)
- Icarus Verilog on the RTL
- Verilator on the RTL (--binary, the test bench with timing)

Writes results.md and results.json next to this file.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from rv32sim import ISA, Bench
from rv32sim.build import BUILD, RTL


WORK = BUILD / "compare"
PROGRAM = "selftest"


def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kwargs)


def version(cmd: list[str]) -> str:
    return run(cmd).stdout.strip().splitlines()[0]


def write_hex(binary: Path, hex_file: Path) -> None:
    hex_file.write_text("".join(f"{byte:02x}\n" for byte in binary.read_bytes()))


def parse_trace(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def digsim_trace(result) -> list[str]:
    lines = []
    for r in result.trace:
        line = f"{r.pc:08x} {r.insn:08x}"
        if r.rd is not None:
            line += f" {r.rd} {r.value:08x}"
        lines.append(line)
    return lines


def tool_result(name, build_s, run_s, stdout, trace_file, cycles_hint=None) -> dict:
    exit_line = next(line for line in stdout.splitlines() if line.startswith("EXIT"))
    fields = dict(item.split("=") for item in exit_line.split()[1:])
    return {
        "simulator": name,
        "build_s": build_s,
        "run_s": run_s,
        "cycles": int(fields["cycles"]),
        "exit_code": int(fields["code"]),
        "passed": "PASS" in stdout,
        "trace": parse_trace(trace_file.read_text()),
    }


def icarus(dut: Path, hex_file: Path) -> dict:
    exe = WORK / f"tb_{ISA}.vvp"
    trace = WORK / f"trace_{ISA}_icarus.txt"
    start = time.perf_counter()
    run(["iverilog", "-g2012", "-o", str(exe), str(HERE / "tb_rv32.v"), str(dut)])
    build_s = time.perf_counter() - start
    start = time.perf_counter()
    out = run(["vvp", "-n", str(exe), f"+program={hex_file}", f"+trace={trace}"]).stdout
    run_s = time.perf_counter() - start
    return tool_result("Icarus Verilog (RTL)", build_s, run_s, out, trace)


def verilator(dut: Path, hex_file: Path) -> dict:
    obj = WORK / f"verilator_{ISA}"
    trace = WORK / f"trace_{ISA}_verilator.txt"
    start = time.perf_counter()
    run(
        [
            "verilator",
            "--binary",
            "--timing",
            "-O3",
            "-Wno-fatal",
            "-Wno-lint",
            "-Wno-style",
            "--top-module",
            "tb_rv32",
            "-Mdir",
            str(obj),
            str(HERE / "tb_rv32.v"),
            str(dut),
        ]
    )
    build_s = time.perf_counter() - start
    start = time.perf_counter()
    out = run([str(obj / "Vtb_rv32"), f"+program={hex_file}", f"+trace={trace}"]).stdout
    run_s = time.perf_counter() - start
    return tool_result("Verilator (RTL)", build_s, run_s, out, trace)


def digsim(image: bytes, functional: bool, engine: str) -> dict:
    from rv32sim.build import netlist

    # Circuit.init() reads the engine to use
    os.environ["DIGSIM_ENGINE"] = engine
    start = time.perf_counter()
    netlist(functional)  # From the cache if the RTL didn't change
    bench = Bench(image, functional=functional)
    build_s = time.perf_counter() - start
    result = bench.run(max_cycles=1_000_000, trace=True)
    return {
        "simulator": f"digsim {engine} ({'functional' if functional else 'gates'})",
        "build_s": build_s,
        "run_s": result.seconds,
        "cycles": result.cycles,
        "exit_code": result.exit_code,
        "passed": result.text.endswith("PASS\n"),
        "trace": digsim_trace(result),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--digsim-gates", action="store_true")
    parser.add_argument("--engines", nargs="*", default=["python", "native"])
    args = parser.parse_args()
    from digsim.circuit import _native

    if "native" in args.engines and _native.digsim_native is None:
        print("The native engine isn't installed, digsim runs only in Python")
        args.engines.remove("native")
    WORK.mkdir(parents=True, exist_ok=True)

    binary = ROOT / "programs" / "bin" / f"{PROGRAM}_{ISA}.bin"
    hex_file = WORK / f"{PROGRAM}_{ISA}.hex"
    write_hex(binary, hex_file)
    rows = []
    for functional in [True, False] if args.digsim_gates else [True]:
        for engine in args.engines:
            rows.append(digsim(binary.read_bytes(), functional, engine))
    rows.append(icarus(RTL, hex_file))
    rows.append(verilator(RTL, hex_file))

    reference = rows[0]["trace"]
    for result in rows:
        result["same_trace"] = result["trace"] == reference
        result["instructions"] = len(result["trace"])
        del result["trace"]
        result["isa"] = ISA
        print(
            f"{ISA:8s} {result['simulator']:24s} build {result['build_s']:7.2f} s"
            f"  run {result['run_s']:8.2f} s  {result['cycles']} cycles"
            f"  {result['cycles'] / result['run_s']:12.0f} cycles/s"
            f"  pass={result['passed']} same_trace={result['same_trace']}",
            flush=True,
        )

    machine = f"{platform.processor() or platform.machine()}, Python {platform.python_version()}"
    tools = {
        "Icarus Verilog": version(["iverilog", "-V"]),
        "Verilator": version(["verilator", "--version"]),
    }
    (HERE / "results.json").write_text(
        json.dumps({"machine": machine, "tools": tools, "rows": rows}, indent=2)
    )
    lines = [
        f"# Simulator comparison: {PROGRAM}",
        "",
        f"Machine: {machine}. {tools['Icarus Verilog']}, {tools['Verilator']}.",
        "Build: synthesis/compilation and loading, from the cache for digsim if the RTL didn't",
        "change. Every simulator retired the same instructions with the same results as",
        "the first digsim run when 'same trace' is yes.",
        "",
        "| ISA | Simulator | Build (s) | Run (s) | Cycles | Cycles/s | PASS | Same trace |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['isa']} | {r['simulator']} | {r['build_s']:.2f} | {r['run_s']:.2f} | "
            f"{r['cycles']} | {r['cycles'] / r['run_s']:,.0f} | "
            f"{'yes' if r['passed'] else 'no'} | {'yes' if r['same_trace'] else 'no'} |"
        )
    (HERE / "results.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
