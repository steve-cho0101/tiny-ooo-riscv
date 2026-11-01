"""pytest entry point for RTL simulation. Run with: pytest tb

The mutant tests inject known bugs into a copy of the RTL and require the
testbench to fail, which shows that the tests can detect each bug.
"""
import shutil
import subprocess
from pathlib import Path

import pytest
from cocotb_tools.runner import get_runner

TB = Path(__file__).resolve().parent
RTL = TB.parent / "src"
BUILD = TB / "sim_build"
MODULES = ["rename_rob.sv", "prf.sv", "decode.sv", "alu.sv"]
PKG = RTL / "uop_pkg.sv"


def simulate(name, source, build_dir, extra_env=None, parameters=None):
    runner = get_runner("verilator")
    runner.build(
        sources=[PKG, source],
        hdl_toplevel=name,
        build_dir=build_dir,
        build_args=["--public-flat-rw"],
        parameters=parameters or {},
        timescale=("1ns", "1ps"),
        always=True,
    )
    runner.test(
        hdl_toplevel=name,
        test_module=f"tb_{name}",
        test_dir=TB,
        build_dir=build_dir,
        extra_env={"PYTHONPATH": str(TB), **(extra_env or {})},
    )


@pytest.mark.parametrize("module", MODULES)
def test_lint(module):
    subprocess.run(
        ["verilator", "--lint-only", "-Wall", "--sv", "--top-module", module.removesuffix(".sv"),
         str(PKG), str(RTL / module)],
        check=True,
    )


def test_top_level_lint():
    subprocess.run(
        ["verilator", "--lint-only", "-Wall", "-Wno-DECLFILENAME", "--sv",
         "--top-module", "tt_um_steve_cho0101_ooo", str(RTL / "project.sv"), str(RTL / "prf.sv")],
        check=True,
    )


@pytest.mark.parametrize("module", MODULES)
def test_synthesis_read(module):
    """Yosys must accept the source, since it is the path to silicon."""
    top = module.removesuffix(".sv")
    subprocess.run(
        ["yosys", "-q", "-p", f"read_verilog -sv {PKG} {RTL / module}; synth -top {top}"],
        check=True,
    )


def test_rename_rob():
    simulate("rename_rob", RTL / "rename_rob.sv", BUILD / "rename_rob")


@pytest.mark.parametrize("latches", [1, 0], ids=["latch", "flop"])
def test_prf(latches):
    simulate("prf", RTL / "prf.sv", BUILD / f"prf_{latches}", parameters={"USE_LATCHES": latches})


def test_decode():
    simulate("decode", RTL / "decode.sv", BUILD / "decode")


def test_alu():
    simulate("alu", RTL / "alu.sv", BUILD / "alu")


RENAME_ROB_MUTANTS = {
    "no_slot_update": ("slot_p[tail] <= rat[alloc_rd];", ""),
    "no_rat_update": ("rat[alloc_rd] <= slot_p[tail];", ""),
    "x0_gets_renamed": ("if (alloc_rd != 4'd0) begin", "begin"),
    "x0_source_uses_rat": (
        "(alloc_rs1 == 4'd0) ? PTAG_ZERO : rat[alloc_rs1]", "rat[alloc_rs1]"),
    "source_reads_after_swap": (
        "(alloc_rs2 == 4'd0) ? PTAG_ZERO : rat[alloc_rs2]",
        "(alloc_rs2 == 4'd0) ? PTAG_ZERO : (alloc_rs2 == alloc_rd) ? slot_p[tail] : rat[alloc_rs2]"),
    "retire_ignores_done": ("!rob_empty && done[head]", "!rob_empty"),
    "alloc_ignores_full": ("count != 3'd4", "1'b1"),
    "done_not_cleared": ("done[tail] <= alloc_done;", "done[tail] <= done[tail] | alloc_done;"),
    "complete_marks_head": ("done[complete_tag] <= 1'b1", "done[head] <= 1'b1"),
    "retire_ignores_ready": ("retire_fire  = retire_valid && retire_ready", "retire_fire  = retire_valid"),
    "count_wrong_on_both": (
        "if (alloc_fire && !retire_fire) count", "if (alloc_fire) count"),
    "reset_duplicates_register": ("5'(15 + i)", "5'(14 + i)"),
    "halt_flag_dropped": ("halt[tail] <= alloc_halt;", ""),
}

PRF_MUTANTS = {
    "no_wakeup_bypass_port1": ("|| (wb_valid && (wb_tag == chk_tag1))", ""),
    "no_wakeup_bypass_port2": ("|| (wb_valid && (wb_tag == chk_tag2))", ""),
    "zero_tag_not_zero": ("(rd_tag1 == PTAG_ZERO) ? '0 : mem[rd_tag1]", "mem[rd_tag1 % 5'd19]"),
    "zero_tag_not_ready": ("(chk_tag1 == PTAG_ZERO) || ready[chk_tag1]", "ready[chk_tag1 % 5'd19]"),
    "ready_never_cleared": ("ready[i] <= 1'b0", "ready[i] <= 1'b1"),
    "ready_never_set": ("else if (wb_hit[i]) ready[i] <= 1'b1;", ""),
    "reset_not_ready": ("if (!rst_n) ready[i] <= 1'b1;", "if (!rst_n) ready[i] <= 1'b0;"),
    "reset_keeps_write": ("wb_valid <= rst_n && wr_en;", "wb_valid <= wr_en;"),
    "port2_reads_port1": (
        "(rd_tag2 == PTAG_ZERO) ? '0 : mem[rd_tag2]", "(rd_tag1 == PTAG_ZERO) ? '0 : mem[rd_tag1]"),
    "latch_opens_on_any_write": ("assign gate = !clk && wb_hit[i];", "assign gate = !clk && wb_valid;"),
    "hit_ignores_valid": (
        "assign wb_hit[i] = wb_valid && (wb_tag == 5'(i));", "assign wb_hit[i] = wb_tag == 5'(i);"),
}


DECODE_MUTANTS = {
    "imm_b_bit_11_wrong": ("instr[7], instr[30:25], instr[11:8], 1'b0}", "instr[31], instr[30:25], instr[11:8], 1'b0}"),
    "imm_j_bit_11_wrong": ("instr[19:12], instr[20], instr[30:21]", "instr[19:12], instr[31], instr[30:21]"),
    "imm_s_uses_i": ("imm        = imm_s;", ""),
    "imm_u_low_bits": ("assign imm_u = {instr[31:12], 12'd0};", "assign imm_u = instr;"),
    "addi_becomes_sub": ("alu_op    = funct3_op;", "alu_op    = (funct3 == 3'b000 && instr[30]) ? uop_pkg::ALU_SUB : funct3_op;"),
    "sub_becomes_add": ("(instr[30] ? uop_pkg::ALU_SUB : uop_pkg::ALU_ADD)", "uop_pkg::ALU_ADD"),
    "sra_becomes_srl": ("instr[30] ? uop_pkg::ALU_SRA : uop_pkg::ALU_SRL", "uop_pkg::ALU_SRL"),
    "slli_allows_funct7": ("3'b001:  recognised = funct7 == 7'b0000000;", "3'b001:  recognised = 1'b1;"),
    "srli_allows_funct7": ("3'b101:  recognised = shift_funct7_ok;", "3'b101:  recognised = 1'b1;"),
    "reg_allows_funct7": ("default:        recognised = funct7 == 7'b0000000;", "default:        recognised = 1'b1;"),
    "add_allows_funct7": ("3'b000, 3'b101: recognised = shift_funct7_ok;", "3'b000, 3'b101: recognised = 1'b1;"),
    "shamt_is_a_register": ("(uses_rs2 && instr[24])", "(instr[24] && (uses_rs2 || opcode == 7'b0010011))"),
    "rd_bit_4_allowed": ("(uses_rd  && instr[11])", "1'b0"),
    "rs1_bit_4_allowed": ("(uses_rs1 && instr[19])", "1'b0"),
    "rs2_bit_4_allowed": ("(uses_rs2 && instr[24])", "1'b0"),
    "rs1_not_masked": ("(uses_rs1 && !illegal) ? instr[18:15] : 4'd0", "instr[18:15]"),
    "rs2_not_masked": ("(uses_rs2 && !illegal) ? instr[23:20] : 4'd0", "instr[23:20]"),
    "rd_not_masked": ("(uses_rd  && !illegal) ? instr[10:7]  : 4'd0", "instr[10:7]"),
    "store_writes_rd": ("recognised = funct3 <= 3'b010;\n                uses_rs1   = 1'b1;", "recognised = funct3 <= 3'b010;\n                uses_rd    = 1'b1;\n                uses_rs1   = 1'b1;"),
    "ecall_loose_match": ("assign is_ecall  = instr == 32'h0000_0073;", "assign is_ecall  = opcode == 7'b1110011;"),
    "ebreak_reason_wrong": ("illegal   ? uop_pkg::HALT_ILLEGAL\n                       : is_ebreak ? uop_pkg::HALT_EBREAK", "illegal   ? uop_pkg::HALT_ILLEGAL\n                       : is_ebreak ? uop_pkg::HALT_ECALL"),
    "load_funct3_gap": ("(funct3 != 3'b011) && (funct3 != 3'b110) && (funct3 != 3'b111)", "1'b1"),
    "store_funct3_gap": ("funct3 <= 3'b010", "1'b1"),
    "branch_funct3_gap": ("(funct3 != 3'b010) && (funct3 != 3'b011)", "1'b1"),
    "jalr_funct3_ignored": ("recognised = funct3 == 3'b000;\n                uses_rd", "recognised = 1'b1;\n                uses_rd"),
    "fence_i_accepted": ("recognised = funct3 == 3'b000;\n                class_raw  = uop_pkg::UOP_NOP;", "recognised = 1'b1;\n                class_raw  = uop_pkg::UOP_NOP;"),
    "branch_uses_imm": ("                b_is_imm   = 1'b0;\n                imm        = imm_b;", "                imm        = imm_b;"),
    "jal_not_done": ("assign done = (uop_class == uop_pkg::UOP_JAL)  || ", "assign done = "),
    "alu_done_at_alloc": ("(uop_class == uop_pkg::UOP_LUI)\n", "(uop_class == uop_pkg::UOP_LUI) || (uop_class == uop_pkg::UOP_ALU)\n"),
}

ALU_MUTANTS = {
    "add_subtracts": ("assign subtract = op != uop_pkg::ALU_ADD;", "assign subtract = 1'b1;"),
    "no_carry_in": (" + 33'(subtract)", ""),
    "slt_ignores_sign": ("(a[31] != b[31]) ? a[31] : sum[31]", "sum[31]"),
    "slt_sign_flipped": ("(a[31] != b[31]) ? a[31] : sum[31]", "(a[31] != b[31]) ? b[31] : sum[31]"),
    "sltu_inverted": ("assign less_unsigned = !sum[32];", "assign less_unsigned = sum[32];"),
    "sra_fills_zero": ("(op == uop_pkg::ALU_SRA) && a[31]", "1'b0"),
    "srl_fills_sign": ("(op == uop_pkg::ALU_SRA) && a[31]", "a[31]"),
    "sll_not_reversed": ("assign shift_in = shift_left ? a_reversed : a;", "assign shift_in = a;"),
    "shift_uses_six_bits": (">> b[4:0];", ">> b[5:0];"),
    "shift_uses_four_bits": (">> b[4:0];", ">> b[3:0];"),
    "beq_inverted": ("uop_pkg::ALU_BEQ:  branch_taken = equal;", "uop_pkg::ALU_BEQ:  branch_taken = !equal;"),
    "bge_is_strict": ("uop_pkg::ALU_BGE:  branch_taken = !less_signed;", "uop_pkg::ALU_BGE:  branch_taken = !less_signed && !equal;"),
    "blt_unsigned": ("uop_pkg::ALU_BLT:  branch_taken = less_signed;", "uop_pkg::ALU_BLT:  branch_taken = less_unsigned;"),
    "bgeu_signed": ("default:  branch_taken = !less_unsigned;", "default:  branch_taken = !less_signed;"),
    "equal_low_bits_only": ("sum[31:0] == 32'd0", "sum[15:0] == 16'd0"),
    "or_is_xor": ("uop_pkg::ALU_OR:   y = a | b;", "uop_pkg::ALU_OR:   y = a ^ b;"),
    "slt_returns_sign_extended": ("y = {31'd0, less_signed};", "y = {32{less_signed}};"),
}


def run_mutant(tmp_path, module, find, replace, env):
    text = (RTL / f"{module}.sv").read_text()
    assert text.count(find) == 1, f"mutant pattern no longer matches the RTL: {find}"
    source = tmp_path / f"{module}.sv"
    source.write_text(text.replace(find, replace))
    with pytest.raises(SystemExit):
        simulate(module, source, tmp_path / "build", env)
    shutil.rmtree(tmp_path / "build", ignore_errors=True)


@pytest.mark.parametrize("mutant", RENAME_ROB_MUTANTS)
def test_rename_rob_mutant_is_caught(mutant, tmp_path):
    run_mutant(tmp_path, "rename_rob", *RENAME_ROB_MUTANTS[mutant], {"RR_INSTRUCTIONS": "300"})


@pytest.mark.parametrize("mutant", PRF_MUTANTS)
def test_prf_mutant_is_caught(mutant, tmp_path):
    run_mutant(tmp_path, "prf", *PRF_MUTANTS[mutant], {"PRF_OPS": "2000"})


@pytest.mark.parametrize("mutant", DECODE_MUTANTS)
def test_decode_mutant_is_caught(mutant, tmp_path):
    run_mutant(tmp_path, "decode", *DECODE_MUTANTS[mutant], {"DECODE_WORDS": "3000"})


@pytest.mark.parametrize("mutant", ALU_MUTANTS)
def test_alu_mutant_is_caught(mutant, tmp_path):
    run_mutant(tmp_path, "alu", *ALU_MUTANTS[mutant], {"ALU_OPS": "3000"})
