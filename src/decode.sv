// Combinational RV32E decoder. See docs/isa.md.
//
// A register field the instruction does not use reads as x0. Rename then gives
// it the always-ready zero tag, so stray bits such as a LUI immediate in the rs1
// position can neither stall the instruction nor rename a register.
`default_nettype none

module decode (
    input  logic [31:0] instr,

    output logic [3:0]  uop_class,
    output logic [3:0]  alu_op,
    output logic        b_is_imm,     // ALU operand B is imm, not rs2
    output logic [3:0]  rd,           // x0 when unused
    output logic [3:0]  rs1,          // x0 when unused
    output logic [3:0]  rs2,          // x0 when unused
    output logic [31:0] imm,
    output logic [2:0]  mem_op,       // funct3 of a load or store
    output logic        done,         // complete at allocation
    output logic        halt,         // halt when this instruction retires
    output logic [1:0]  halt_reason
);

    logic [6:0] opcode;
    logic [2:0] funct3;
    logic [6:0] funct7;

    assign opcode = instr[6:0];
    assign funct3 = instr[14:12];
    assign funct7 = instr[31:25];

    assign mem_op = funct3;

    logic [31:0] imm_i, imm_s, imm_b, imm_u, imm_j;

    assign imm_i = {{21{instr[31]}}, instr[30:20]};
    assign imm_s = {{21{instr[31]}}, instr[30:25], instr[11:7]};
    assign imm_b = {{20{instr[31]}}, instr[7], instr[30:25], instr[11:8], 1'b0};
    assign imm_u = {instr[31:12], 12'd0};
    assign imm_j = {{12{instr[31]}}, instr[19:12], instr[20], instr[30:21], 1'b0};

    // Operation selected by funct3, shared by the register and immediate forms.
    logic [3:0] funct3_op;

    always_comb begin
        unique case (funct3)
            3'b000:  funct3_op = uop_pkg::ALU_ADD;
            3'b001:  funct3_op = uop_pkg::ALU_SLL;
            3'b010:  funct3_op = uop_pkg::ALU_SLT;
            3'b011:  funct3_op = uop_pkg::ALU_SLTU;
            3'b100:  funct3_op = uop_pkg::ALU_XOR;
            3'b101:  funct3_op = instr[30] ? uop_pkg::ALU_SRA : uop_pkg::ALU_SRL;
            3'b110:  funct3_op = uop_pkg::ALU_OR;
            default: funct3_op = uop_pkg::ALU_AND;
        endcase
    end

    // SRA, SRAI and SUB are the only uses of funct7 0100000.
    logic shift_funct7_ok;

    assign shift_funct7_ok = (funct7 == 7'b0000000) || (funct7 == 7'b0100000);

    logic       is_ecall;
    logic       is_ebreak;
    logic       recognised;
    logic       uses_rd;
    logic       uses_rs1;
    logic       uses_rs2;
    logic [3:0] class_raw;

    assign is_ecall  = instr == 32'h0000_0073;
    assign is_ebreak = instr == 32'h0010_0073;

    always_comb begin
        recognised = 1'b0;
        uses_rd    = 1'b0;
        uses_rs1   = 1'b0;
        uses_rs2   = 1'b0;
        class_raw  = uop_pkg::UOP_HALT;
        alu_op     = uop_pkg::ALU_ADD;
        b_is_imm   = 1'b1;
        imm        = imm_i;

        unique case (opcode)
            7'b0110111: begin  // LUI
                recognised = 1'b1;
                uses_rd    = 1'b1;
                class_raw  = uop_pkg::UOP_LUI;
                imm        = imm_u;
            end
            7'b0010111: begin  // AUIPC
                recognised = 1'b1;
                uses_rd    = 1'b1;
                class_raw  = uop_pkg::UOP_AUIPC;
                imm        = imm_u;
            end
            7'b1101111: begin  // JAL
                recognised = 1'b1;
                uses_rd    = 1'b1;
                class_raw  = uop_pkg::UOP_JAL;
                imm        = imm_j;
            end
            7'b1100111: begin  // JALR
                recognised = funct3 == 3'b000;
                uses_rd    = 1'b1;
                uses_rs1   = 1'b1;
                class_raw  = uop_pkg::UOP_JALR;
            end
            7'b1100011: begin  // Branches
                recognised = (funct3 != 3'b010) && (funct3 != 3'b011);
                uses_rs1   = 1'b1;
                uses_rs2   = 1'b1;
                class_raw  = uop_pkg::UOP_BRANCH;
                b_is_imm   = 1'b0;
                imm        = imm_b;
                unique case (funct3)
                    3'b000:  alu_op = uop_pkg::ALU_BEQ;
                    3'b001:  alu_op = uop_pkg::ALU_BNE;
                    3'b100:  alu_op = uop_pkg::ALU_BLT;
                    3'b101:  alu_op = uop_pkg::ALU_BGE;
                    3'b110:  alu_op = uop_pkg::ALU_BLTU;
                    default: alu_op = uop_pkg::ALU_BGEU;
                endcase
            end
            7'b0000011: begin  // Loads
                recognised = (funct3 != 3'b011) && (funct3 != 3'b110) && (funct3 != 3'b111);
                uses_rd    = 1'b1;
                uses_rs1   = 1'b1;
                class_raw  = uop_pkg::UOP_LOAD;
            end
            7'b0100011: begin  // Stores
                recognised = funct3 <= 3'b010;
                uses_rs1   = 1'b1;
                uses_rs2   = 1'b1;
                class_raw  = uop_pkg::UOP_STORE;
                imm        = imm_s;
            end
            7'b0010011: begin  // Immediate ALU. ADDI must not become SUB from imm[10].
                unique case (funct3)
                    3'b001:  recognised = funct7 == 7'b0000000;
                    3'b101:  recognised = shift_funct7_ok;
                    default: recognised = 1'b1;
                endcase
                uses_rd   = 1'b1;
                uses_rs1  = 1'b1;
                class_raw = uop_pkg::UOP_ALU;
                alu_op    = funct3_op;
            end
            7'b0110011: begin  // Register ALU
                unique case (funct3)
                    3'b000, 3'b101: recognised = shift_funct7_ok;
                    default:        recognised = funct7 == 7'b0000000;
                endcase
                uses_rd   = 1'b1;
                uses_rs1  = 1'b1;
                uses_rs2  = 1'b1;
                class_raw = uop_pkg::UOP_ALU;
                alu_op    = (funct3 == 3'b000) ? (instr[30] ? uop_pkg::ALU_SUB : uop_pkg::ALU_ADD) : funct3_op;
                b_is_imm  = 1'b0;
            end
            7'b0001111: begin  // FENCE, a no-op that uses no registers
                recognised = funct3 == 3'b000;
                class_raw  = uop_pkg::UOP_NOP;
            end
            7'b1110011: begin  // ECALL, EBREAK
                recognised = is_ecall || is_ebreak;
            end
            default: ;
        endcase
    end

    // RV32E has 16 registers, so bit 4 of a used register field is illegal.
    logic illegal;

    assign illegal = !recognised
                  || (uses_rd  && instr[11])
                  || (uses_rs1 && instr[19])
                  || (uses_rs2 && instr[24]);

    assign uop_class = illegal ? uop_pkg::UOP_HALT : class_raw;

    assign rd  = (uses_rd  && !illegal) ? instr[10:7]  : 4'd0;
    assign rs1 = (uses_rs1 && !illegal) ? instr[18:15] : 4'd0;
    assign rs2 = (uses_rs2 && !illegal) ? instr[23:20] : 4'd0;

    assign done = (uop_class == uop_pkg::UOP_JAL)  || (uop_class == uop_pkg::UOP_LUI)
               || (uop_class == uop_pkg::UOP_AUIPC) || (uop_class == uop_pkg::UOP_NOP)
               || (uop_class == uop_pkg::UOP_HALT);

    assign halt = uop_class == uop_pkg::UOP_HALT;

    assign halt_reason = illegal   ? uop_pkg::HALT_ILLEGAL
                       : is_ebreak ? uop_pkg::HALT_EBREAK
                       :             uop_pkg::HALT_ECALL;

endmodule

`default_nettype wire
