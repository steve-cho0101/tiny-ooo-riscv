// Instruction fetch. See "Control flow" and "External bus" in docs/architecture.md.
//
// The queue is the instruction at the head plus the word being assembled from
// bytes. A branch stays at the head until it resolves, which keeps its PC and
// immediate. The PC also holds a redirect target until the frame has been sent.
`default_nettype none

module fetch (
    input  logic        clk,
    input  logic        rst_n,

    // Pins.
    input  logic [7:0]  i_data,
    input  logic        i_valid,
    output logic        i_ready,

    // Head of the queue, for decode.
    output logic        instr_valid,
    output logic [31:0] instr,
    output logic [15:0] pc,
    output logic [15:0] pc_next,

    input  logic        advance,          // drop the head and move to pc_next
    input  logic        redirect_start,   // pulse, wins over advance
    input  logic [15:0] redirect_target,

    // To bus_if.
    output logic        redirect_valid,
    input  logic        redirect_done,
    input  logic        redirect_ack
);

    logic [31:0] fill;
    logic [1:0]  byte_count;
    logic        fill_full;
    logic        head_valid;
    logic        redirecting;

    logic byte_fire;
    logic head_load;

    // Low from the cycle after the decision until the acknowledge. Anything that
    // arrives before then is stale and is dropped at the acknowledge.
    assign i_ready   = !redirecting && (!fill_full || !head_valid);
    assign byte_fire = i_valid && i_ready;
    assign head_load = fill_full && (!head_valid || advance);

    assign instr_valid = head_valid && !redirecting;
    assign pc_next     = pc + 16'd4;

    always_ff @(posedge clk) begin
        if (!rst_n || redirect_ack) begin
            byte_count <= 2'd0;
            fill_full  <= 1'b0;
            head_valid <= 1'b0;
        end else begin
            if (head_load) fill_full <= 1'b0;
            if (byte_fire) begin
                byte_count <= byte_count + 2'd1;
                if (byte_count == 2'd3) fill_full <= 1'b1;
            end
            if (head_load) head_valid <= 1'b1;
            else if (advance) head_valid <= 1'b0;
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            pc             <= 16'd0;
            redirecting    <= 1'b0;
            redirect_valid <= 1'b0;
        end else begin
            if (redirect_start) begin
                pc             <= redirect_target;
                redirecting    <= 1'b1;
                redirect_valid <= 1'b1;
            end else if (advance) begin
                pc <= pc_next;
            end
            if (redirect_done) redirect_valid <= 1'b0;
            if (redirect_ack) redirecting <= 1'b0;
        end
    end

    always_ff @(posedge clk) begin
        if (byte_fire) fill <= {i_data, fill[31:8]};
        if (head_load) instr <= fill;
    end

endmodule

`default_nettype wire
