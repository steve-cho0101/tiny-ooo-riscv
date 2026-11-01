// Tiny Tapeout top level: the pin mapping from "External bus" in docs/architecture.md.
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

    logic i_ready;
    logic o_valid;

    cpu u_cpu (
        .clk,
        .rst_n,
        .i_data (ui_in),
        .i_valid(uio_in[4]),
        .i_ready,
        .o_data (uo_out),
        .o_valid,
        .d_data (uio_in[3:0]),
        .d_valid(uio_in[5])
    );

    assign uio_out = {i_ready, o_valid, 6'd0};
    assign uio_oe  = 8'b1100_0000;

    logic unused;
    assign unused = &{ena, uio_in[7:6], 1'b0};

endmodule

`default_nettype wire
