# Simulator comparison: selftest

Machine: x86_64, Python 3.15.0. Icarus Verilog version 14.0 (devel) (s20221226-554-g25a84d5cf), Verilator 5.032 2025-01-01 rev (Debian 5.032-1), ferrooxide 0.1.0 (49a31d6).
Build: synthesis/compilation and loading, from the cache for digsim if the RTL didn't
change. Every simulator retired the same instructions with the same results as
the first digsim run when 'same trace' is yes.

| ISA | Simulator | Build (s) | Run (s) | Cycles | Cycles/s | PASS | Same trace |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| rv32e | digsim native (functional) | 0.04 | 1.64 | 86750 | 52,777 | yes | yes |
| rv32e | digsim native (gates) | 0.17 | 3.43 | 86750 | 25,264 | yes | yes |
| rv32e | Icarus Verilog (RTL) | 0.01 | 2.08 | 86750 | 41,713 | yes | yes |
| rv32e | ferrooxide (RTL) | 0.09 | 0.32 | 86750 | 268,576 | yes | yes |
| rv32e | Verilator (RTL) | 0.05 | 0.08 | 86750 | 1,021,729 | yes | yes |
