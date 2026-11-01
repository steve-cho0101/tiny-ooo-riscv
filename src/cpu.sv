// Out-of-order RV32E core. See docs/architecture.md.
//
// This file holds the blocks together, along with dispatch and control flow. An
// instruction leaves the fetch queue when it dispatches, except that branches and
// JALR stay at the head until they resolve, and HALT stays there for good.
`default_nettype none

module cpu (
    input  logic       clk,
    input  logic       rst_n,

    input  logic [7:0] i_data,
    input  logic       i_valid,
    output logic       i_ready,
    output logic [7:0] o_data,
    output logic       o_valid,
    input  logic [3:0] d_data,
    input  logic       d_valid
);

    // Reserved tag that reads as zero and is always ready.
    localparam logic [4:0] PTAG_ZERO = 5'd31;

    // Fetch and decode.
    logic        instr_valid;
    logic [31:0] instr;
    logic [15:0] pc;
    logic [15:0] pc_next;
    logic        advance;
    logic        redirect_start;
    logic [15:0] redirect_target;
    logic        redirect_valid;
    logic        redirect_done;
    logic        redirect_ack;

    logic [3:0]  uop_class;
    logic [3:0]  decode_alu_op;
    logic        decode_b_is_imm;
    logic [3:0]  rd;
    logic [3:0]  rs1;
    logic [3:0]  rs2;
    logic [31:0] imm;
    logic [2:0]  decode_mem_op;
    logic        decode_done;
    logic        decode_halt;
    logic [1:0]  halt_reason;

    // Rename and ROB.
    logic        rob_alloc_ready;
    logic [1:0]  alloc_tag;
    logic [4:0]  alloc_pdst;
    logic [4:0]  alloc_psrc1;
    logic [4:0]  alloc_psrc2;
    logic        complete_valid;
    logic [1:0]  complete_tag;
    logic        retire_valid;
    logic        retire_halt;
    logic [1:0]  head_tag;
    logic        rob_empty;

    // Register file.
    logic        wr_en;
    logic [4:0]  wr_tag;
    logic [31:0] wr_data;
    logic        wb_valid;
    logic [4:0]  wb_tag;
    logic [31:0] rd_data1;
    logic [31:0] rd_data2;
    logic        chk_ready1;
    logic        chk_ready2;

    // Issue.
    logic        iq_alloc_ready;
    logic        issue_valid;
    logic [2:0]  issue_class;
    logic [3:0]  issue_alu_op;
    logic [2:0]  issue_mem_op;
    logic        issue_b_is_imm;
    logic [11:0] issue_imm;
    logic [4:0]  issue_pdst;
    logic [1:0]  issue_rob_tag;
    logic [4:0]  issue_src1;
    logic [4:0]  issue_src2;

    // ALU and memory.
    logic [31:0] alu_y;
    logic        branch_taken;
    logic        lsu_result_valid;
    logic [4:0]  lsu_result_tag;
    logic [31:0] lsu_result_data;
    logic [1:0]  lsu_result_rob_tag;
    logic        req_valid;
    logic        req_is_store;
    logic [1:0]  req_size;
    logic [15:0] req_addr;
    logic        req_done;
    logic [7:0]  store_byte;
    logic        store_byte_taken;
    logic        load_nibble_valid;
    logic [3:0]  load_nibble;
    logic        load_done;
    logic        halt_done;

    // Dispatch.
    logic        control_wait;  // a branch or JALR at the head has not resolved
    logic        mem_busy;      // a load or store is in flight
    logic        stopped;       // a HALT has dispatched
    logic        is_alu;
    logic        is_mem;
    logic        is_branch;
    logic        is_jalr;
    logic        is_jal;
    logic        is_auipc;
    logic        is_lui;
    logic        to_issue;
    logic        dispatch_write;
    logic        port_free;
    logic        can_dispatch;
    logic        dispatch_fire;

    assign is_alu    = uop_class == uop_pkg::UOP_ALU;
    assign is_mem    = (uop_class == uop_pkg::UOP_LOAD) || (uop_class == uop_pkg::UOP_STORE);
    assign is_branch = uop_class == uop_pkg::UOP_BRANCH;
    assign is_jalr   = uop_class == uop_pkg::UOP_JALR;
    assign is_jal    = uop_class == uop_pkg::UOP_JAL;
    assign is_auipc  = uop_class == uop_pkg::UOP_AUIPC;
    assign is_lui    = uop_class == uop_pkg::UOP_LUI;

    assign to_issue       = is_alu || is_mem || is_branch || is_jalr;
    assign dispatch_write = is_lui || is_auipc || is_jal || is_jalr;

    // The LSU and ALU come first on the write port, and an issue may need it.
    assign port_free = !lsu_result_valid && !issue_valid;

    assign can_dispatch = instr_valid && !control_wait && !stopped
                       && (!to_issue || iq_alloc_ready)
                       && (!is_mem || !mem_busy)
                       && (!dispatch_write || port_free);

    assign dispatch_fire = can_dispatch && rob_alloc_ready;

    // Control flow. The head still shows the branch, so pc_target is its target.
    logic [31:0] pc_target;
    logic        issue_is_branch;
    logic        issue_is_jalr;
    logic        issue_is_mem;
    logic        branch_taken_now;

    assign pc_target = {16'd0, pc} + imm;

    assign issue_is_branch  = issue_valid && (issue_class == uop_pkg::UOP_BRANCH[2:0]);
    assign issue_is_jalr    = issue_valid && (issue_class == uop_pkg::UOP_JALR[2:0]);
    assign issue_is_mem     = issue_valid && ((issue_class == uop_pkg::UOP_LOAD[2:0])
                                           || (issue_class == uop_pkg::UOP_STORE[2:0]));
    assign branch_taken_now = issue_is_branch && branch_taken;

    assign redirect_start  = (dispatch_fire && is_jal) || branch_taken_now || issue_is_jalr;
    assign redirect_target = issue_is_jalr ? alu_y[15:0] : pc_target[15:0];

    assign advance = (dispatch_fire && !is_branch && !is_jalr && !decode_halt)
                  || (issue_is_branch && !branch_taken);

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            control_wait <= 1'b0;
            mem_busy     <= 1'b0;
            stopped      <= 1'b0;
        end else begin
            if (dispatch_fire && (is_branch || is_jalr)) control_wait <= 1'b1;
            if (issue_is_branch || issue_is_jalr) control_wait <= 1'b0;
            if (dispatch_fire && is_mem) mem_busy <= 1'b1;
            if (lsu_result_valid) mem_busy <= 1'b0;
            if (dispatch_fire && decode_halt) stopped <= 1'b1;
        end
    end

    // Result bus. Branches and JALR have nothing to write, so they send the zero
    // tag and use the bus only to complete in the ROB.
    logic        alu_result;
    logic [31:0] dispatch_data;

    assign alu_result = issue_valid && !issue_is_mem;

    assign dispatch_data = is_lui   ? imm
                         : is_auipc ? pc_target
                         :            {16'd0, pc_next};

    always_comb begin
        wr_en   = 1'b1;
        wr_tag  = alloc_pdst;
        wr_data = dispatch_data;
        if (lsu_result_valid) begin
            wr_tag  = lsu_result_tag;
            wr_data = lsu_result_data;
        end else if (alu_result) begin
            wr_tag  = (issue_class == uop_pkg::UOP_ALU[2:0]) ? issue_pdst : PTAG_ZERO;
            wr_data = alu_y;
        end else if (!(dispatch_fire && dispatch_write)) begin
            wr_en   = 1'b0;
        end
    end

    // The ROB marks an instruction done in W, along with its wakeup.
    always_ff @(posedge clk) begin
        complete_valid <= rst_n && (lsu_result_valid || alu_result);
        complete_tag   <= lsu_result_valid ? lsu_result_rob_tag : issue_rob_tag;
    end

    fetch u_fetch (
        .clk,
        .rst_n,
        .i_data,
        .i_valid,
        .i_ready,
        .instr_valid,
        .instr,
        .pc,
        .pc_next,
        .advance,
        .redirect_start,
        .redirect_target,
        .redirect_valid,
        .redirect_done,
        .redirect_ack
    );

    decode u_decode (
        .instr,
        .uop_class,
        .alu_op     (decode_alu_op),
        .b_is_imm   (decode_b_is_imm),
        .rd,
        .rs1,
        .rs2,
        .imm,
        .mem_op     (decode_mem_op),
        .done       (decode_done),
        .halt       (decode_halt),
        .halt_reason
    );

    rename_rob u_rename_rob (
        .clk,
        .rst_n,
        .alloc_valid (can_dispatch),
        .alloc_ready (rob_alloc_ready),
        .alloc_rd    (rd),
        .alloc_rs1   (rs1),
        .alloc_rs2   (rs2),
        .alloc_done  (decode_done),
        .alloc_halt  (decode_halt),
        .alloc_tag,
        .alloc_pdst,
        .alloc_psrc1,
        .alloc_psrc2,
        .complete_valid,
        .complete_tag,
        .retire_valid,
        .retire_ready(!retire_halt || halt_done),
        .retire_halt,
        .head_tag,
        .rob_empty
    );

    prf u_prf (
        .clk,
        .rst_n,
        .wr_en,
        .wr_tag,
        .wr_data,
        .wb_valid,
        .wb_tag,
        .rd_tag1    (issue_src1),
        .rd_data1,
        .rd_tag2    (issue_src2),
        .rd_data2,
        .alloc_valid(dispatch_fire),
        .alloc_tag  (alloc_pdst),
        .chk_tag1   (alloc_psrc1),
        .chk_ready1,
        .chk_tag2   (alloc_psrc2),
        .chk_ready2
    );

    issue_queue u_issue_queue (
        .clk,
        .rst_n,
        .alloc_valid     (dispatch_fire && to_issue),
        .alloc_ready     (iq_alloc_ready),
        .alloc_class     (uop_class[2:0]),
        .alloc_alu_op    (decode_alu_op),
        .alloc_mem_op    (decode_mem_op),
        .alloc_b_is_imm  (decode_b_is_imm),
        .alloc_imm       (imm[11:0]),
        .alloc_pdst,
        .alloc_rob_tag   (alloc_tag),
        .alloc_src1      (alloc_psrc1),
        .alloc_src1_ready(chk_ready1),
        .alloc_src2      (alloc_psrc2),
        .alloc_src2_ready(chk_ready2),
        .wakeup_valid    (wb_valid),
        .wakeup_tag      (wb_tag),
        .issue_hold      (lsu_result_valid),
        .issue_valid,
        .issue_class,
        .issue_alu_op,
        .issue_mem_op,
        .issue_b_is_imm,
        .issue_imm,
        .issue_pdst,
        .issue_rob_tag,
        .issue_src1,
        .issue_src2
    );

    alu u_alu (
        .op(issue_alu_op),
        .a (rd_data1),
        .b (issue_b_is_imm ? {{20{issue_imm[11]}}, issue_imm} : rd_data2),
        .y (alu_y),
        .branch_taken
    );

    lsu u_lsu (
        .clk,
        .rst_n,
        .start_valid   (issue_is_mem),
        .start_is_store(issue_class == uop_pkg::UOP_STORE[2:0]),
        .start_mem_op  (issue_mem_op),
        .start_addr    (alu_y[15:0]),
        .start_data    (rd_data2),
        .start_pdst    (issue_pdst),
        .start_rob_tag (issue_rob_tag),
        .head_tag,
        .req_valid,
        .req_is_store,
        .req_size,
        .req_addr,
        .req_done,
        .store_byte,
        .store_byte_taken,
        .load_nibble_valid,
        .load_nibble,
        .load_done,
        .result_valid  (lsu_result_valid),
        .result_tag    (lsu_result_tag),
        .result_data   (lsu_result_data),
        .result_rob_tag(lsu_result_rob_tag)
    );

    bus_if u_bus_if (
        .clk,
        .rst_n,
        .o_data,
        .o_valid,
        .d_data,
        .d_valid,
        .req_valid,
        .req_is_store,
        .req_size,
        .req_addr,
        .req_done,
        .store_byte,
        .store_byte_taken,
        .load_nibble_valid,
        .load_nibble,
        .load_done,
        .redirect_valid,
        .redirect_addr(pc),
        .redirect_done,
        .redirect_ack,
        .halt_valid   (retire_valid && retire_halt),
        .halt_reason,
        .halt_done
    );

    logic unused;
    assign unused = &{alu_y[31:16], pc_target[31:16], rob_empty, 1'b0};

endmodule

`default_nettype wire
