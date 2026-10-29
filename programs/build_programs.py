# Copyright (c) Fredrik Andersson, 2026
# All rights reserved

"""
Build the test programs with the RISC-V GCC (riscv64-unknown-elf-gcc) for rv32e (the
ilp32e ABI, with libgcc's multiplication and division), into bin/<program>_rv32e.bin
(and a disassembly, .lst). The binaries are kept, so the tests run without the
toolchain.

    python build_programs.py
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
BIN = HERE / "bin"
GCC = "riscv64-unknown-elf-gcc"
# The address bits of the local memories, as in rv32sim/devices.py
ILM_ADDRESS_WIDTH = 16
DLM_ADDRESS_WIDTH = 16
PROGRAMS = ["selftest"]
ISAS = ["rv32e"]


def have_toolchain() -> bool:
    return shutil.which(GCC) is not None


def build(program: str, isa: str) -> Path:
    BIN.mkdir(exist_ok=True)
    elf = BIN / f"{program}_{isa}.elf"
    binary = elf.with_suffix(".bin")
    # Zicsr/Zifencei are in the default ISA string of newer GCCs, not needed here
    subprocess.run(
        [
            GCC,
            f"-march={isa}",
            "-mabi=ilp32e",
            "-O2",
            "-ffreestanding",
            "-nostdlib",
            "-nostartfiles",
            "-Wall",
            "-Wno-div-by-zero",
            # The division checks that are left out (by 0, INT32_MIN / -1) are dead code
            "-Wno-overflow",
            "-Wl,--no-warn-rwx-segments",
            f"-Wl,--defsym=ILM_ADDRESS_WIDTH={ILM_ADDRESS_WIDTH}",
            f"-Wl,--defsym=DLM_ADDRESS_WIDTH={DLM_ADDRESS_WIDTH}",
            "-T",
            str(HERE / "link.ld"),
            str(HERE / "crt0.S"),
            str(HERE / f"{program}.c"),
            "-lgcc",
            "-o",
            str(elf),
        ],
        check=True,
    )
    objcopy = GCC.replace("gcc", "objcopy")
    objdump = GCC.replace("gcc", "objdump")
    subprocess.run([objcopy, "-O", "binary", str(elf), str(binary)], check=True)
    listing = subprocess.run([objdump, "-d", str(elf)], check=True, capture_output=True, text=True)
    elf.with_suffix(".lst").write_text(listing.stdout)
    elf.unlink()
    return binary


def main() -> None:
    for program in PROGRAMS:
        for isa in ISAS:
            binary = build(program, isa)
            print(f"{binary.relative_to(HERE)}: {binary.stat().st_size} bytes")


if __name__ == "__main__":
    main()
