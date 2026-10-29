/*
 * The local memories: code, read-only data and the load image of .data in the ILM at
 * address 0, the data and the stack in the DLM at 0x20000000 (see rv32sim/devices.py).
 * The sizes are 2^ILM_ADDRESS_WIDTH and 2^DLM_ADDRESS_WIDTH, set by build_programs.py
 * with --defsym (64 KiB each by default).
 */
OUTPUT_ARCH(riscv)
ENTRY(_start)
ILM_ADDRESS_WIDTH = DEFINED(ILM_ADDRESS_WIDTH) ? ILM_ADDRESS_WIDTH : 16;
DLM_ADDRESS_WIDTH = DEFINED(DLM_ADDRESS_WIDTH) ? DLM_ADDRESS_WIDTH : 16;
MEMORY
{
    ILM (rx) : ORIGIN = 0x00000000, LENGTH = 1 << ILM_ADDRESS_WIDTH
    DLM (rw) : ORIGIN = 0x20000000, LENGTH = 1 << DLM_ADDRESS_WIDTH
}
SECTIONS
{
    .text : { KEEP(*(.text.start)) *(.text .text.*) } > ILM
    .rodata : { *(.rodata .rodata.* .srodata .srodata.*) } > ILM
    /* In the DLM, loaded from the ILM by crt0.S */
    .data : ALIGN(4) {
        __data_start = .;
        *(.data .data.* .sdata .sdata.*)
        . = ALIGN(4);
        __data_end = .;
    } > DLM AT > ILM
    __data_load = LOADADDR(.data);
    .bss (NOLOAD) : ALIGN(4) {
        __bss_start = .;
        *(.bss .bss.* .sbss .sbss.* COMMON)
        . = ALIGN(4);
        __bss_end = .;
    } > DLM
    __stack_top = ORIGIN(DLM) + LENGTH(DLM);
    /DISCARD/ : { *(.comment) *(.riscv.attributes) }
}
