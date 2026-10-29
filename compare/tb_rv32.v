// A Verilog test bench for rv32.v (RV32E), for Icarus Verilog and Verilator, with the same
// memory map and memory behavior as the digsim test bench (rv32sim/devices.py): the ILM
// at 0 (64 KiB, the program, read by both ports), the DLM at 0x20000000 (64 KiB, written
// on the rising clock edge with byte strobes), the console at 0x10000000 and the exit
// register at 0x10000004. The memories are always ready.
//
//   +program=<file.hex>   the program, one byte per line ($readmemh)
//   +trace=<file>         write every retired instruction: pc insn [rd value]
//   +max_cycles=<n>       stop after n cycles (default 1000000)

`timescale 1ns / 1ps


module tb_rv32;
    localparam ILM_ADDR_WIDTH = 16;
    localparam ILM_SIZE = 1 << ILM_ADDR_WIDTH;
    localparam DLM_BASE = 32'h2000_0000;
    localparam DLM_SIZE = 65536;

    reg clk = 0;
    reg rst = 1;
    reg [7:0] ilm[0:ILM_SIZE-1];
    reg [7:0] dlm[0:DLM_SIZE-1];

    wire [ILM_ADDR_WIDTH-1:0] imem_addr;
    wire [31:0] pc, dmem_addr, dmem_wdata, wb_data;
    wire [3:0] dmem_wstrb, trap_cause;
    wire dmem_re, retire, wb_we, halted;
    wire [3:0] wb_rd;

    // Counts the writes: an argument of word_at(), so the reads below are evaluated again
    // after a write (a continuous assignment only follows its arguments, not the array)
    reg [31:0] writes = 0;

    // The aligned word at an address in the ILM or the DLM, 0 outside them
    function [31:0] word_at(input [31:0] addr, input [31:0] version);
        if (addr < ILM_SIZE)
            word_at = {ilm[addr+3], ilm[addr+2], ilm[addr+1], ilm[addr]};
        else if (addr >= DLM_BASE && addr - DLM_BASE < DLM_SIZE)
            word_at = {dlm[addr-DLM_BASE+3], dlm[addr-DLM_BASE+2], dlm[addr-DLM_BASE+1],
                       dlm[addr-DLM_BASE]};
        else
            word_at = 32'd0;
    endfunction

    wire [31:0] imem_rdata = word_at({imem_addr[ILM_ADDR_WIDTH-1:2], 2'b00}, writes);
    wire [31:0] dmem_rdata = word_at(dmem_addr & ~32'd3, writes);

    rv32 #(.ILM_ADDR_WIDTH(ILM_ADDR_WIDTH)) dut (
        .clk(clk),
        .rst(rst),
        .imem_addr(imem_addr),
        .imem_rdata(imem_rdata),
        .imem_ready(1'b1),
        .dmem_addr(dmem_addr),
        .dmem_re(dmem_re),
        .dmem_wdata(dmem_wdata),
        .dmem_wstrb(dmem_wstrb),
        .dmem_rdata(dmem_rdata),
        .dmem_ready(1'b1),
        .pc_out(pc),
        .retire(retire),
        .wb_we(wb_we),
        .wb_rd(wb_rd),
        .wb_data(wb_data),
        .halted(halted),
        .trap_cause(trap_cause)
    );

    integer i, trace_file, cycles, max_cycles;
    reg [1023:0] program_file, trace_name;
    reg [31:0] base;

    always #5 clk = !clk;

    // The end of the simulation, called from the clocked block (where the exit register
    // and halted are seen): Verilator doesn't see a variable set there change in an
    // initial block waiting with @(posedge clk)
    task finish(input integer exit_code);
        begin
            if (halted) $display("\nHALTED cause=%0d pc=%08x", trap_cause, pc);
            $display("\nEXIT code=%0d cycles=%0d", exit_code, cycles);
            if (trace_file != 0) $fclose(trace_file);
            $finish;
        end
    endtask

    always @(posedge clk) begin
        if (!rst) begin
            if (halted) finish(-1);
            if (trace_file != 0 && retire) begin
                if (wb_we)
                    $fwrite(trace_file, "%08x %08x %0d %08x\n", pc, imem_rdata, wb_rd, wb_data);
                else
                    $fwrite(trace_file, "%08x %08x\n", pc, imem_rdata);
            end
            cycles = cycles + 1;
            if (dmem_wstrb != 0) begin
                if (dmem_addr == 32'h1000_0004) begin
                    finish(dmem_wdata);
                end else if ((dmem_addr & ~32'd3) == 32'h1000_0000) begin
                    $write("%c", dmem_wdata[8*dmem_addr[1:0]+:8]);
                end else if (dmem_addr >= DLM_BASE && dmem_addr - DLM_BASE < DLM_SIZE) begin
                    base = (dmem_addr - DLM_BASE) & ~32'd3;
                    for (i = 0; i < 4; i = i + 1)
                        if (dmem_wstrb[i]) dlm[base+i] <= dmem_wdata[8*i+:8];
                    writes <= writes + 1;
                end else begin
                    $display("\nERROR store to %08x outside the DLM", dmem_addr);
                    finish(-1);
                end
            end
            if (cycles >= max_cycles) finish(-1);
        end
    end

    initial begin
        for (i = 0; i < ILM_SIZE; i = i + 1) ilm[i] = 8'd0;
        for (i = 0; i < DLM_SIZE; i = i + 1) dlm[i] = 8'd0;
        if (!$value$plusargs("program=%s", program_file)) begin
            $display("Give the program with +program=<file.hex>");
            $finish;
        end
        $readmemh(program_file, ilm);
        trace_file = 0;
        if ($value$plusargs("trace=%s", trace_name)) trace_file = $fopen(trace_name, "w");
        if (!$value$plusargs("max_cycles=%d", max_cycles)) max_cycles = 1000000;
        cycles = 0;
        repeat (2) @(posedge clk);
        #1 rst = 0;
    end
endmodule
