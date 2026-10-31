// Physical register file with the write-back register and ready bits.
// See "Pipeline timing" and "Reservation stations" in docs/architecture.md.
//
// A write presented in cycle E is captured in the write-back register, drives
// wakeup in cycle W, and is readable from cycle E+2. Reading a register during
// its own W cycle is not allowed, because the ready bit is not yet set.
//
// USE_LATCHES selects the latch array or the flop fallback, with the same timing.
// Latches open in the low phase of W, when the write-back register is stable.
`default_nettype none

module prf #(
    parameter bit USE_LATCHES = 1'b1
) (
    input  logic        clk,
    input  logic        rst_n,

    // Write from the result bus, in cycle E.
    input  logic        wr_en,
    input  logic [4:0]  wr_tag,
    input  logic [31:0] wr_data,

    // Wakeup, in cycle W.
    output logic        wb_valid,
    output logic [4:0]  wb_tag,

    // Operand reads. PTAG_ZERO reads as zero.
    input  logic [4:0]  rd_tag1,
    output logic [31:0] rd_data1,
    input  logic [4:0]  rd_tag2,
    output logic [31:0] rd_data2,

    // A renamed destination stops being ready until it is written.
    input  logic        alloc_valid,
    input  logic [4:0]  alloc_tag,

    // Ready check at rename, including a write-back in the same cycle, so an
    // instruction renamed while its producer is in W cannot miss the wakeup.
    input  logic [4:0]  chk_tag1,
    output logic        chk_ready1,
    input  logic [4:0]  chk_tag2,
    output logic        chk_ready2
);

    localparam int         NPHYS     = 19;
    localparam logic [4:0] PTAG_ZERO = 5'd31;

    logic [31:0]      wb_data;
    logic [31:0]      mem [NPHYS];
    logic [NPHYS-1:0] ready;
    logic [NPHYS-1:0] wb_hit;

    always_ff @(posedge clk) begin
        wb_valid <= rst_n && wr_en;
        wb_tag   <= wr_tag;
        wb_data  <= wr_data;
    end

    for (genvar i = 0; i < NPHYS; i++) begin : g_reg
        assign wb_hit[i] = wb_valid && (wb_tag == 5'(i));

        if (USE_LATCHES) begin : g_latch
            logic gate;
            // Hit changes only just after a rising edge, while !clk masks it.
            assign gate = !clk && wb_hit[i];
            always_latch if (gate) mem[i] = wb_data;
        end else begin : g_flop
            always_ff @(posedge clk) if (wb_hit[i]) mem[i] <= wb_data;
        end

        always_ff @(posedge clk) begin
            if (!rst_n) ready[i] <= 1'b1;
            else if (wb_hit[i]) ready[i] <= 1'b1;
            else if (alloc_valid && (alloc_tag == 5'(i))) ready[i] <= 1'b0;
        end
    end

    assign rd_data1 = (rd_tag1 == PTAG_ZERO) ? '0 : mem[rd_tag1];
    assign rd_data2 = (rd_tag2 == PTAG_ZERO) ? '0 : mem[rd_tag2];

    assign chk_ready1 = (chk_tag1 == PTAG_ZERO) || ready[chk_tag1]
                        || (wb_valid && (wb_tag == chk_tag1));
    assign chk_ready2 = (chk_tag2 == PTAG_ZERO) || ready[chk_tag2]
                        || (wb_valid && (wb_tag == chk_tag2));

endmodule

`default_nettype wire
