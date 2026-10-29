# Simulator comparison: selftest

Machine: x86_64, Python 3.14.0. Icarus Verilog version 13.0 (devel) (s20221226-554-g25a84d5cf), Verilator 5.032 2025-01-01 rev (Debian 5.032-1).
Build: synthesis/compilation and loading, from the cache for digsim if the RTL didn't
change. Every simulator retired the same instructions with the same results as
the first digsim run when 'same trace' is yes.

| ISA | Simulator | Build (s) | Run (s) | Cycles | Cycles/s | PASS | Same trace |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| rv32e | digsim python (functional) | 0.03 | 81.22 | 86750 | 1,068 | yes | yes |
| rv32e | digsim native (functional) | 0.04 | 6.88 | 86750 | 12,616 | yes | yes |
| rv32e | digsim python (gates) | 0.17 | 426.50 | 86750 | 203 | yes | yes |
| rv32e | digsim native (gates) | 0.23 | 33.20 | 86750 | 2,613 | yes | yes |
| rv32e | Icarus Verilog (RTL) | 0.01 | 2.20 | 86750 | 39,432 | yes | yes |
| rv32e | Verilator (RTL) | 6.72 | 0.10 | 86750 | 911,904 | yes | yes |
