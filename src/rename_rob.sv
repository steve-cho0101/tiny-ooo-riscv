// Register rename map and reorder buffer, using the ROB-slot swap.
// See "Rename: the ROB-slot swap" in docs/architecture.md.
//
// Each ROB slot owns one physical register. Allocating an instruction with a
// destination swaps that register with the RAT entry for rd, so the slot then
// holds the old mapping until it retires. Retirement touches no register state.
`default_nettype none

module rename_rob (
    input  logic       clk,
    input  logic       rst_n,

    // Allocate one instruction. Fires when alloc_valid && alloc_ready.
    input  logic       alloc_valid,
    output logic       alloc_ready,
    input  logic [3:0] alloc_rd,
    input  logic [3:0] alloc_rs1,
    input  logic [3:0] alloc_rs2,
    input  logic       alloc_done,   // already complete, e.g. a dispatch write
    input  logic       alloc_halt,   // halt when this instruction retires
    output logic [1:0] alloc_tag,
    output logic [4:0] alloc_pdst,   // PTAG_ZERO when rd is x0
    output logic [4:0] alloc_psrc1,  // PTAG_ZERO when rs1 is x0
    output logic [4:0] alloc_psrc2,  // PTAG_ZERO when rs2 is x0

    // Mark an allocated instruction as finished.
    input  logic       complete_valid,
    input  logic [1:0] complete_tag,

    // Retire the head. Fires when retire_valid && retire_ready.
    output logic       retire_valid,
    input  logic       retire_ready,
    output logic       retire_halt,

    output logic [1:0] head_tag,     // the LSU compares this to start a store
    output logic       rob_empty
);

    // Reserved tag that reads as zero and is always ready.
    localparam logic [4:0] PTAG_ZERO = 5'd31;

    logic [15:1][4:0] rat;     // x1..x15 to physical register
    logic [3:0][4:0]  slot_p;  // physical register owned by each ROB slot
    logic [3:0]       done;
    logic [3:0]       halt;
    logic [1:0]       head;
    logic [1:0]       tail;
    logic [2:0]       count;

    logic alloc_fire;
    logic retire_fire;

    assign rob_empty   = count == 3'd0;
    assign alloc_ready = count != 3'd4;
    assign alloc_fire  = alloc_valid && alloc_ready;

    assign alloc_tag   = tail;
    assign alloc_pdst  = (alloc_rd  == 4'd0) ? PTAG_ZERO : slot_p[tail];
    assign alloc_psrc1 = (alloc_rs1 == 4'd0) ? PTAG_ZERO : rat[alloc_rs1];
    assign alloc_psrc2 = (alloc_rs2 == 4'd0) ? PTAG_ZERO : rat[alloc_rs2];

    assign head_tag     = head;
    assign retire_valid = !rob_empty && done[head];
    assign retire_halt  = halt[head];
    assign retire_fire  = retire_valid && retire_ready;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            for (int i = 1; i <= 15; i++) rat[i] <= 5'(i - 1);
            for (int i = 0; i < 4; i++) slot_p[i] <= 5'(15 + i);
            done  <= '0;
            halt  <= '0;
            head  <= '0;
            tail  <= '0;
            count <= '0;
        end else begin
            if (complete_valid) done[complete_tag] <= 1'b1;

            if (alloc_fire) begin
                if (alloc_rd != 4'd0) begin
                    slot_p[tail] <= rat[alloc_rd];
                    rat[alloc_rd] <= slot_p[tail];
                end
                done[tail] <= alloc_done;
                halt[tail] <= alloc_halt;
                tail <= tail + 2'd1;
            end

            if (retire_fire) head <= head + 2'd1;

            if (alloc_fire && !retire_fire) count <= count + 3'd1;
            else if (retire_fire && !alloc_fire) count <= count - 3'd1;
        end
    end

endmodule

`default_nettype wire
