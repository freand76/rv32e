# Simulator comparison: selftest

Machine: x86_64, Python 3.15.0. Icarus Verilog version 14.0 (devel) (s20221226-554-g25a84d5cf), Verilator 5.032 2025-01-01 rev (Debian 5.032-1).
Build: synthesis/compilation and loading, from the cache for digsim if the RTL didn't
change. Every simulator retired the same instructions with the same results as
the first digsim run when 'same trace' is yes.

| ISA | Simulator | Build (s) | Run (s) | Cycles | Cycles/s | PASS | Same trace |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| rv32e | digsim python (functional) | 0.05 | 91.32 | 86750 | 950 | yes | yes |
| rv32e | digsim native (functional) | 0.07 | 1.73 | 86750 | 50,184 | yes | yes |
| rv32e | digsim python (gates) | 0.24 | 445.22 | 86750 | 195 | yes | yes |
| rv32e | digsim native (gates) | 0.26 | 3.44 | 86750 | 25,242 | yes | yes |
| rv32e | Icarus Verilog (RTL) | 0.01 | 1.92 | 86750 | 45,109 | yes | yes |
| rv32e | Verilator (RTL) | 0.05 | 0.10 | 86750 | 847,934 | yes | yes |
