// Outgoing frames and the data response path. See "External bus" in
// docs/architecture.md.
//
// A frame is a header, two address bytes, and data bytes for a store. At most one
// load or redirect is outstanding, so the core always knows what the next D_VALID
// means. Stores get no response, so they can go at any time.
`default_nettype none

module bus_if (
    input  logic        clk,
    input  logic        rst_n,

    // Pins.
    output logic [7:0]  o_data,
    output logic        o_valid,
    input  logic [3:0]  d_data,
    input  logic        d_valid,

    // From lsu. Each request stays asserted until its done pulse.
    input  logic        req_valid,
    input  logic        req_is_store,
    input  logic [1:0]  req_size,
    input  logic [15:0] req_addr,
    output logic        req_done,
    input  logic [7:0]  store_byte,
    output logic        store_byte_taken,
    output logic        load_nibble_valid,
    output logic [3:0]  load_nibble,
    input  logic        load_done,

    // From fetch.
    input  logic        redirect_valid,
    input  logic [15:0] redirect_addr,
    output logic        redirect_done,
    output logic        redirect_ack,

    // From retirement.
    input  logic        halt_valid,
    input  logic [1:0]  halt_reason,
    output logic        halt_done
);

    localparam logic [1:0] SEL_LSU      = 2'd0;
    localparam logic [1:0] SEL_REDIRECT = 2'd1;
    localparam logic [1:0] SEL_HALT     = 2'd2;

    logic       active;
    logic [1:0] sel;
    logic [2:0] index;
    logic       wait_load;
    logic       wait_ack;

    logic       busy;
    logic       start_lsu;
    logic       start_redirect;
    logic       start;
    logic [2:0] last_index;
    logic       last_byte;

    assign busy           = wait_load || wait_ack;
    assign start_lsu      = req_valid && (req_is_store || !busy);
    assign start_redirect = redirect_valid && !busy;
    assign start          = !active && (halt_valid || start_lsu || start_redirect);

    assign last_index = ((sel == SEL_LSU) && req_is_store) ? 3'd2 + (3'd1 << req_size) : 3'd2;
    assign last_byte  = active && (index == last_index);

    assign req_done         = last_byte && (sel == SEL_LSU);
    assign redirect_done    = last_byte && (sel == SEL_REDIRECT);
    assign halt_done        = last_byte && (sel == SEL_HALT);
    assign store_byte_taken = active && (index >= 3'd3);  // only stores get this far

    assign load_nibble_valid = d_valid && wait_load;
    assign load_nibble       = d_data;
    assign redirect_ack      = d_valid && wait_ack;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            active    <= 1'b0;
            wait_load <= 1'b0;
            wait_ack  <= 1'b0;
        end else begin
            if (start) active <= 1'b1;
            else if (last_byte) active <= 1'b0;

            // A store can start while a response is outstanding, and must not
            // disturb it, so these only ever set and clear their own bit.
            if (load_done) wait_load <= 1'b0;
            if (redirect_ack) wait_ack <= 1'b0;
            if (start && !halt_valid && start_lsu && !req_is_store) wait_load <= 1'b1;
            if (start && !halt_valid && !start_lsu) wait_ack <= 1'b1;
        end
    end

    always_ff @(posedge clk) begin
        if (start) begin
            sel   <= halt_valid ? SEL_HALT : start_lsu ? SEL_LSU : SEL_REDIRECT;
            index <= 3'd0;
        end else begin
            index <= index + 3'd1;
        end
    end

    logic [7:0]  header;
    logic [15:0] addr;

    always_comb begin
        unique case (sel)
            SEL_LSU: begin
                header = req_is_store ? {2'b10, req_size, 4'd0} : 8'h40;
                addr   = req_addr;
            end
            SEL_REDIRECT: begin
                header = 8'h00;
                addr   = redirect_addr;
            end
            default: begin
                header = {4'b1100, 2'b00, halt_reason};
                addr   = 16'd0;
            end
        endcase
    end

    always_comb begin
        unique case (index)
            3'd0:    o_data = header;
            3'd1:    o_data = addr[7:0];
            3'd2:    o_data = addr[15:8];
            default: o_data = store_byte;
        endcase
    end

    assign o_valid = active;

endmodule

`default_nettype wire
