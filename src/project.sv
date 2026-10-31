// Tiny Tapeout top level. For now this is a test harness that exposes prf on the
// pins, so the latch array can be hardened and gate-level tested on its own.
// It will be replaced by the CPU and the bus in docs/architecture.md.
`default_nettype none

module tt_um_steve_cho0101_ooo (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    localparam logic [2:0] CMD_SHIFT = 3'd1;  // shift ui_in into the write data
    localparam logic [2:0] CMD_WRITE = 3'd2;  // write it to tag ui_in[4:0]
    localparam logic [2:0] CMD_TAG1  = 3'd3;  // select tag ui_in[4:0] for port 1
    localparam logic [2:0] CMD_TAG2  = 3'd4;  // select tag ui_in[4:0] for port 2
    localparam logic [2:0] CMD_ALLOC = 3'd5;  // clear ready for tag ui_in[4:0]
    localparam logic [2:0] CMD_SEL   = 3'd6;  // select output ui_in[3:0]

    logic [2:0]  cmd;
    logic [31:0] wdata;
    logic [4:0]  tag1;
    logic [4:0]  tag2;
    logic [3:0]  sel;

    logic        wb_valid;
    logic [4:0]  wb_tag;
    logic [31:0] rd_data1;
    logic [31:0] rd_data2;
    logic        ready1;
    logic        ready2;

    assign cmd = uio_in[2:0];

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            tag1 <= '0;
            tag2 <= '0;
            sel  <= '0;
        end else begin
            if (cmd == CMD_SHIFT) wdata <= {ui_in, wdata[31:8]};
            if (cmd == CMD_TAG1) tag1 <= ui_in[4:0];
            if (cmd == CMD_TAG2) tag2 <= ui_in[4:0];
            if (cmd == CMD_SEL) sel <= ui_in[3:0];
        end
    end

    prf u_prf (
        .clk,
        .rst_n,
        .wr_en      (cmd == CMD_WRITE),
        .wr_tag     (ui_in[4:0]),
        .wr_data    (wdata),
        .wb_valid,
        .wb_tag,
        .rd_tag1    (tag1),
        .rd_data1,
        .rd_tag2    (tag2),
        .rd_data2,
        .alloc_valid(cmd == CMD_ALLOC),
        .alloc_tag  (ui_in[4:0]),
        .chk_tag1   (tag1),
        .chk_ready1 (ready1),
        .chk_tag2   (tag2),
        .chk_ready2 (ready2)
    );

    logic [7:0][7:0] read_bytes;

    assign read_bytes = {rd_data2, rd_data1};

    assign uo_out  = sel[3] ? {ready1, ready2, wb_valid, wb_tag} : read_bytes[sel[2:0]];
    assign uio_out = 8'd0;
    assign uio_oe  = 8'd0;

    logic unused;
    assign unused = &{ena, uio_in[7:3], ui_in[7:5], 1'b0};

endmodule

`default_nettype wire
