// Combinational ALU. One adder serves ADD, SUB, comparisons and branches, and one
// right shifter serves all three shifts, with SLL shifting the reversed operand.
`default_nettype none

module alu (
    input  logic [3:0]  op,
    input  logic [31:0] a,
    input  logic [31:0] b,
    output logic [31:0] y,            // ignored for branch operations
    output logic        branch_taken  // only meaningful for branch operations
);

    logic        subtract;
    logic [32:0] sum;
    logic        equal;
    logic        less_signed;
    logic        less_unsigned;

    assign subtract = op != uop_pkg::ALU_ADD;

    // The top bit of a 33-bit subtraction of zero-extended values is the borrow.
    assign sum = {1'b0, a} + {1'b0, b ^ {32{subtract}}} + 33'(subtract);

    assign equal         = sum[31:0] == 32'd0;
    assign less_unsigned = !sum[32];
    assign less_signed   = (a[31] != b[31]) ? a[31] : sum[31];

    logic        shift_left;
    logic        shift_fill;
    logic [31:0] a_reversed;
    logic [31:0] shift_in;
    logic [31:0] shift_out;
    logic [31:0] shift_out_reversed;

    assign shift_left = op == uop_pkg::ALU_SLL;
    assign shift_fill = (op == uop_pkg::ALU_SRA) && a[31];

    for (genvar i = 0; i < 32; i++) begin : g_reverse
        assign a_reversed[i]         = a[31 - i];
        assign shift_out_reversed[i] = shift_out[31 - i];
    end

    assign shift_in = shift_left ? a_reversed : a;

    logic [62:0] shift_ext;

    assign shift_ext = {{31{shift_fill}}, shift_in} >> b[4:0];
    assign shift_out = shift_ext[31:0];

    always_comb begin
        unique case (op)
            uop_pkg::ALU_SLL:  y = shift_out_reversed;
            uop_pkg::ALU_SRL,
            uop_pkg::ALU_SRA:  y = shift_out;
            uop_pkg::ALU_SLT:  y = {31'd0, less_signed};
            uop_pkg::ALU_SLTU: y = {31'd0, less_unsigned};
            uop_pkg::ALU_XOR:  y = a ^ b;
            uop_pkg::ALU_OR:   y = a | b;
            uop_pkg::ALU_AND:  y = a & b;
            default:  y = sum[31:0];
        endcase
    end

    always_comb begin
        unique case (op)
            uop_pkg::ALU_BEQ:  branch_taken = equal;
            uop_pkg::ALU_BNE:  branch_taken = !equal;
            uop_pkg::ALU_BLT:  branch_taken = less_signed;
            uop_pkg::ALU_BGE:  branch_taken = !less_signed;
            uop_pkg::ALU_BLTU: branch_taken = less_unsigned;
            default:  branch_taken = !less_unsigned;
        endcase
    end

    logic unused;
    assign unused = &{shift_ext[62:32], 1'b0};

endmodule

`default_nettype wire
