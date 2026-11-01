// Two-entry reservation station holding tags only. See "Reservation stations" in
// docs/architecture.md.
//
// Issue looks only at the stored ready bits, so a dependent instruction issues two
// cycles after its producer and never reads a latch while it is open. The ready
// bits given at allocation must already include the wakeup of that same cycle, or
// it is missed. prf provides this through chk_ready.
`default_nettype none

module issue_queue (
    input  logic        clk,
    input  logic        rst_n,

    // Insert one instruction. Fires when alloc_valid && alloc_ready.
    input  logic        alloc_valid,
    output logic        alloc_ready,
    input  logic [2:0]  alloc_class,  // low bits of uop_class, only classes that issue
    input  logic [3:0]  alloc_alu_op,
    input  logic [2:0]  alloc_mem_op,
    input  logic        alloc_b_is_imm,
    input  logic [11:0] alloc_imm,
    input  logic [4:0]  alloc_pdst,
    input  logic [1:0]  alloc_rob_tag,
    input  logic [4:0]  alloc_src1,
    input  logic        alloc_src1_ready,
    input  logic [4:0]  alloc_src2,
    input  logic        alloc_src2_ready,

    // Write-back from prf.
    input  logic        wakeup_valid,
    input  logic [4:0]  wakeup_tag,

    // The oldest cannot starve, as a full ROB stops new instructions.
    input  logic        issue_hold,   // the LSU needs the write port this cycle
    output logic        issue_valid,
    output logic [2:0]  issue_class,
    output logic [3:0]  issue_alu_op,
    output logic [2:0]  issue_mem_op,
    output logic        issue_b_is_imm,
    output logic [11:0] issue_imm,
    output logic [4:0]  issue_pdst,
    output logic [1:0]  issue_rob_tag,
    output logic [4:0]  issue_src1,
    output logic [4:0]  issue_src2
);

    logic [1:0]       valid;
    logic [1:0][2:0]  uop_class;
    logic [1:0][3:0]  alu_op;
    logic [1:0][2:0]  mem_op;
    logic [1:0]       b_is_imm;
    logic [1:0][11:0] imm;
    logic [1:0][4:0]  pdst;
    logic [1:0][1:0]  rob_tag;
    logic [1:0][4:0]  src1;
    logic [1:0]       src1_ready;
    logic [1:0][4:0]  src2;
    logic [1:0]       src2_ready;

    logic [1:0] can_issue;
    logic       alloc_fire;
    logic       alloc_slot;
    logic       issue_slot;

    // Ignores a same-cycle issue, so nothing runs from issue_hold to dispatch.
    assign alloc_ready = valid != 2'b11;
    assign alloc_fire  = alloc_valid && alloc_ready;
    assign alloc_slot  = valid[0];

    assign can_issue   = valid & src1_ready & src2_ready;
    assign issue_slot  = !can_issue[0];
    assign issue_valid = (can_issue != 2'b00) && !issue_hold;

    assign issue_class    = uop_class[issue_slot];
    assign issue_alu_op   = alu_op[issue_slot];
    assign issue_mem_op   = mem_op[issue_slot];
    assign issue_b_is_imm = b_is_imm[issue_slot];
    assign issue_imm      = imm[issue_slot];
    assign issue_pdst     = pdst[issue_slot];
    assign issue_rob_tag  = rob_tag[issue_slot];
    assign issue_src1     = src1[issue_slot];
    assign issue_src2     = src2[issue_slot];

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            valid <= '0;
        end else begin
            if (issue_valid) valid[issue_slot] <= 1'b0;
            if (alloc_fire)  valid[alloc_slot] <= 1'b1;
        end
    end

    for (genvar i = 0; i < 2; i++) begin : g_entry
        logic load;

        assign load = alloc_fire && (alloc_slot == 1'(i));

        always_ff @(posedge clk) begin
            if (wakeup_valid && (wakeup_tag == src1[i])) src1_ready[i] <= 1'b1;
            if (wakeup_valid && (wakeup_tag == src2[i])) src2_ready[i] <= 1'b1;
            if (load) begin
                uop_class[i]  <= alloc_class;
                alu_op[i]     <= alloc_alu_op;
                mem_op[i]     <= alloc_mem_op;
                b_is_imm[i]   <= alloc_b_is_imm;
                imm[i]        <= alloc_imm;
                pdst[i]       <= alloc_pdst;
                rob_tag[i]    <= alloc_rob_tag;
                src1[i]       <= alloc_src1;
                src1_ready[i] <= alloc_src1_ready;
                src2[i]       <= alloc_src2;
                src2_ready[i] <= alloc_src2_ready;
            end
        end
    end

endmodule

`default_nettype wire
