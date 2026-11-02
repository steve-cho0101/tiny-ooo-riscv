`default_nettype none

module fetch #(
    parameter int INDEX_BITS = 4
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic [7:0]  i_data,
    input  logic        i_valid,
    output logic        i_ready,
    output logic        instr_valid,
    output logic [31:0] instr,
    output logic [15:0] pc,
    output logic [15:0] pc_next,
    input  logic        advance,
    input  logic        redirect_start,
    input  logic [15:0] redirect_target,
    output logic        redirect_valid,
    input  logic        redirect_done,
    input  logic        redirect_ack
);

    localparam int WORDS    = 1 << INDEX_BITS;
    localparam int TAG_BITS = 14 - INDEX_BITS;

    logic [31:0] fill;
    logic [1:0]  byte_count;
    logic        fill_full;
    logic        head_valid;
    logic        redirecting;
    logic [13:0] stream;       // word address of the word being assembled

    logic [31:0]         data [WORDS];
    logic [TAG_BITS-1:0] tag  [WORDS];
    logic [WORDS-1:0]    valid;
    logic                write_pending;

    logic [15:0]           lookup;
    logic [INDEX_BITS-1:0] lookup_index;
    logic [TAG_BITS-1:0]   lookup_tag;
    logic [INDEX_BITS-1:0] pc_index;
    logic                  hit;
    logic                  fill_match;
    logic                  want_head;
    logic                  head_load;
    logic                  fill_take;
    logic                  need_redirect;
    logic                  byte_fire;

    assign pc_next      = pc + 16'd4;
    assign lookup       = advance ? pc_next : pc;
    assign lookup_index = lookup[2 + INDEX_BITS - 1:2];
    assign lookup_tag   = lookup[15:2 + INDEX_BITS];
    assign pc_index     = pc[2 + INDEX_BITS - 1:2];
    assign hit          = valid[lookup_index] && (tag[lookup_index] == lookup_tag);
    assign fill_match   = fill_full && (stream == lookup[15:2]);

    assign want_head = !head_valid || advance;
    assign head_load = want_head && !redirect_start && !redirecting && (hit || fill_match);
    assign fill_take = head_load && fill_match;

    assign need_redirect = !head_valid && !redirecting && !redirect_start && !hit
                        && (stream != pc[15:2]);

    assign i_ready   = !redirecting && (!fill_full || (!head_valid && (stream == pc[15:2])));
    assign byte_fire = i_valid && i_ready;

    assign instr_valid = head_valid && !redirecting;

    always_ff @(posedge clk) begin
        if (!rst_n || redirect_ack) begin
            byte_count <= 2'd0;
            fill_full  <= 1'b0;
        end else begin
            if (fill_take) fill_full <= 1'b0;
            if (byte_fire) begin
                byte_count <= byte_count + 2'd1;
                if (byte_count == 2'd3) fill_full <= 1'b1;
            end
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            pc             <= 16'd0;
            stream         <= 14'd0;
            head_valid     <= 1'b0;
            redirecting    <= 1'b0;
            redirect_valid <= 1'b0;
            write_pending  <= 1'b0;
        end else begin
            write_pending <= head_load && !hit;
            if (redirect_start) begin
                pc         <= redirect_target;
                head_valid <= 1'b0;
            end else begin
                if (advance) pc <= pc_next;
                if (head_load) head_valid <= 1'b1;
                else if (advance) head_valid <= 1'b0;
            end
            if (need_redirect) begin
                redirecting    <= 1'b1;
                redirect_valid <= 1'b1;
            end
            if (redirect_done) redirect_valid <= 1'b0;
            if (redirect_ack) begin
                redirecting <= 1'b0;
                stream      <= pc[15:2];
            end else if (fill_take) begin
                stream <= stream + 14'd1;
            end
        end
    end

    always_ff @(posedge clk) begin
        if (byte_fire) fill <= {i_data, fill[31:8]};
        if (head_load) instr <= hit ? data[lookup_index] : fill;
    end

    // A word from the bus is written the cycle after it reaches the head, so the
    // head register and PC are the stable write data, as with the PRF write-back.
    for (genvar i = 0; i < WORDS; i++) begin : g_line
        logic write_hit;
        logic gate;
        assign write_hit = write_pending && (pc_index == INDEX_BITS'(i));
        assign gate      = !clk && write_hit;
        always_latch if (gate) data[i] = instr;
        always_latch if (gate) tag[i]  = pc[15:2 + INDEX_BITS];
        always_ff @(posedge clk) begin
            if (!rst_n) valid[i] <= 1'b0;
            else if (write_hit) valid[i] <= 1'b1;
        end
    end

endmodule

`default_nettype wire
