// Codes shared by decode, alu and the blocks that will carry a decoded instruction.
// verilator lint_off UNUSEDPARAM
package uop_pkg;

    // Instruction classes.
    localparam logic [3:0] UOP_ALU    = 4'd0;  // issues, result goes to rd
    localparam logic [3:0] UOP_LOAD   = 4'd1;
    localparam logic [3:0] UOP_STORE  = 4'd2;
    localparam logic [3:0] UOP_BRANCH = 4'd3;
    localparam logic [3:0] UOP_JALR   = 4'd4;  // link is a dispatch write, ALU gives the target
    localparam logic [3:0] UOP_JAL    = 4'd5;  // dispatch write only
    localparam logic [3:0] UOP_LUI    = 4'd6;  // dispatch write only
    localparam logic [3:0] UOP_AUIPC  = 4'd7;  // dispatch write only
    localparam logic [3:0] UOP_NOP    = 4'd8;  // FENCE
    localparam logic [3:0] UOP_HALT   = 4'd9;  // ECALL, EBREAK or illegal

    // ALU operations. Branch operations only drive branch_taken.
    localparam logic [3:0] ALU_ADD  = 4'd0;
    localparam logic [3:0] ALU_SUB  = 4'd1;
    localparam logic [3:0] ALU_SLL  = 4'd2;
    localparam logic [3:0] ALU_SLT  = 4'd3;
    localparam logic [3:0] ALU_SLTU = 4'd4;
    localparam logic [3:0] ALU_XOR  = 4'd5;
    localparam logic [3:0] ALU_SRL  = 4'd6;
    localparam logic [3:0] ALU_SRA  = 4'd7;
    localparam logic [3:0] ALU_OR   = 4'd8;
    localparam logic [3:0] ALU_AND  = 4'd9;
    localparam logic [3:0] ALU_BEQ  = 4'd10;
    localparam logic [3:0] ALU_BNE  = 4'd11;
    localparam logic [3:0] ALU_BLT  = 4'd12;
    localparam logic [3:0] ALU_BGE  = 4'd13;
    localparam logic [3:0] ALU_BLTU = 4'd14;
    localparam logic [3:0] ALU_BGEU = 4'd15;

    // Halt reasons, as sent in the HALT frame.
    localparam logic [1:0] HALT_ECALL   = 2'd0;
    localparam logic [1:0] HALT_EBREAK  = 2'd1;
    localparam logic [1:0] HALT_ILLEGAL = 2'd2;

endpackage
// verilator lint_on UNUSEDPARAM
