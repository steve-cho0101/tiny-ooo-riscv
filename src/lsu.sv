// Load and store unit with one slot. See "Memory ordering" in docs/architecture.md.
//
// One 32-bit register shifts store bytes out and load nibbles in. A finished load
// or store takes the result bus for one cycle, which holds issue, so loads get the
// write port and the ROB complete port is never contested. A store has nothing to
// write, so it sends the zero tag.
`default_nettype none

module lsu (
    input  logic        clk,
    input  logic        rst_n,

    // Pulses as a memory instruction issues. Dispatch allows only one in flight.
    input  logic        start_valid,
    input  logic        start_is_store,
    input  logic [2:0]  start_mem_op,   // funct3
    input  logic [15:0] start_addr,     // from the ALU
    input  logic [31:0] start_data,     // rs2, for stores
    input  logic [4:0]  start_pdst,
    input  logic [1:0]  start_rob_tag,

    input  logic [1:0]  head_tag,       // stores wait until they are at the ROB head

    // Request to bus_if. Held until req_done, when the whole frame has been sent.
    output logic        req_valid,
    output logic        req_is_store,
    output logic [1:0]  req_size,
    output logic [15:0] req_addr,
    input  logic        req_done,

    output logic [7:0]  store_byte,     // next data byte of a store frame
    input  logic        store_byte_taken,

    // Word from the MCU, least significant nibble first.
    input  logic        load_nibble_valid,
    input  logic [3:0]  load_nibble,
    output logic        load_done,      // pulses with the last nibble

    // Result bus. result_valid has priority over the ALU, so it also holds issue.
    output logic        result_valid,
    output logic [4:0]  result_tag,
    output logic [31:0] result_data,
    output logic [1:0]  result_rob_tag
);

    // Reserved tag that reads as zero and is always ready.
    localparam logic [4:0] PTAG_ZERO = 5'd31;

    localparam logic [1:0] S_IDLE      = 2'd0;
    localparam logic [1:0] S_REQUEST   = 2'd1;
    localparam logic [1:0] S_WAIT_LOAD = 2'd2;
    localparam logic [1:0] S_RESULT    = 2'd3;

    logic [1:0]  state;
    logic [2:0]  nibble_count;
    logic        is_store;
    logic [2:0]  mem_op;
    logic [15:0] addr;
    logic [31:0] data;
    logic [4:0]  pdst;
    logic [1:0]  rob_tag;

    logic start_fire;
    logic load_fire;

    assign start_fire = (state == S_IDLE) && start_valid;
    assign load_fire  = (state == S_WAIT_LOAD) && load_nibble_valid;
    assign load_done  = load_fire && (nibble_count == 3'd7);

    assign req_valid    = (state == S_REQUEST) && (!is_store || (rob_tag == head_tag));
    assign req_is_store = is_store;
    assign req_size     = mem_op[1:0];
    assign req_addr     = addr;
    assign store_byte   = data[7:0];

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state        <= S_IDLE;
            nibble_count <= 3'd0;
        end else begin
            unique case (state)
                S_IDLE:      if (start_valid) state <= S_REQUEST;
                S_REQUEST:   if (req_valid && req_done) state <= is_store ? S_RESULT : S_WAIT_LOAD;
                S_WAIT_LOAD: if (load_done) state <= S_RESULT;
                default:     state <= S_IDLE;
            endcase
            if (load_fire) nibble_count <= nibble_count + 3'd1;
        end
    end

    always_ff @(posedge clk) begin
        if (start_fire) begin
            is_store <= start_is_store;
            mem_op   <= start_mem_op;
            addr     <= start_addr;
            data     <= start_data;
            pdst     <= start_pdst;
            rob_tag  <= start_rob_tag;
        end else if (store_byte_taken) begin
            data <= {8'd0, data[31:8]};
        end else if (load_fire) begin
            data <= {load_nibble, data[31:4]};
        end
    end

    // The MCU sends the aligned word. Misaligned accesses are undefined, so a
    // halfword looks only at addr[1].
    logic [15:0] half;
    logic [7:0]  low_byte;
    logic        fill;

    assign half     = addr[1] ? data[31:16] : data[15:0];
    assign low_byte = addr[0] ? half[15:8] : half[7:0];
    assign fill     = !mem_op[2] && (mem_op[0] ? half[15] : low_byte[7]);

    assign result_valid   = state == S_RESULT;
    assign result_tag     = is_store ? PTAG_ZERO : pdst;
    assign result_rob_tag = rob_tag;
    assign result_data    = mem_op[1] ? data
                          : mem_op[0] ? {{16{fill}}, half}
                          :             {{24{fill}}, low_byte};

endmodule

`default_nettype wire
