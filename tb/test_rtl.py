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
MODULES = ["rename_rob.sv", "prf.sv", "decode.sv", "alu.sv", "issue_queue.sv", "lsu.sv", "bus_if.sv", "fetch.sv"]
CORE = [RTL / m for m in MODULES]
SW = TB.parent / "sw"
PKG = RTL / "uop_pkg.sv"


def simulate(name, source, build_dir, extra_env=None, parameters=None, others=()):
    runner = get_runner("verilator")
    runner.build(
        sources=[PKG, source, *others],
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


def test_cpu_lint():
    subprocess.run(
        ["verilator", "--lint-only", "-Wall", "--sv", "--top-module", "cpu",
         str(PKG), str(RTL / "cpu.sv"), *map(str, CORE)],
        check=True,
    )


def test_cpu_synthesis_read():
    files = " ".join(map(str, [PKG, RTL / "cpu.sv", *CORE]))
    subprocess.run(["yosys", "-q", "-p", f"read_verilog -sv {files}; synth -top cpu"], check=True)


def test_top_level_lint():
    subprocess.run(
        ["verilator", "--lint-only", "-Wall", "-Wno-DECLFILENAME", "--sv",
         "--top-module", "tt_um_steve_cho0101_ooo", str(PKG), str(RTL / "project.sv"),
         str(RTL / "cpu.sv"), *map(str, CORE)],
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


def test_issue_queue():
    simulate("issue_queue", RTL / "issue_queue.sv", BUILD / "issue_queue")


def test_lsu():
    simulate("lsu", RTL / "lsu.sv", BUILD / "lsu")


def test_bus_if():
    simulate("bus_if", RTL / "bus_if.sv", BUILD / "bus_if")


def test_fetch():
    simulate("fetch", RTL / "fetch.sv", BUILD / "fetch")


def gcc_tool(name):
    found = shutil.which(f"riscv-none-elf-{name}")
    if found:
        return found
    tools = sorted(Path.home().glob(f"opt/xpack-riscv-none-elf-gcc-*/bin/riscv-none-elf-{name}"))
    if not tools:
        pytest.fail("riscv-none-elf toolchain not found, see docs/isa.md")
    return str(tools[-1])


@pytest.fixture(scope="session")
def images(tmp_path_factory):
    """Compile sw/ with the command in docs/isa.md, plus the linker script."""
    out = tmp_path_factory.mktemp("images")
    for program in sorted(SW.glob("*.c")):
        if program.stem == "runtime":
            continue
        elf = out / f"{program.stem}.elf"
        subprocess.run(
            [gcc_tool("gcc"), "-march=rv32e", "-mabi=ilp32e", "-O1", "-ffreestanding", "-nostdlib",
             "-T", SW / "link.ld", "-o", elf, SW / "startup.S", program, SW / "runtime.c", "-lgcc"],
            check=True,
        )
        subprocess.run([gcc_tool("objcopy"), "-O", "binary", elf, out / f"{program.stem}.bin"], check=True)
    return out


def test_cpu(images):
    simulate("cpu", RTL / "cpu.sv", BUILD / "cpu", {"CPU_IMAGES": str(images)}, others=CORE)


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


ISSUE_QUEUE_MUTANTS = {
    "alloc_ready_sees_issue": ("assign alloc_ready = valid != 2'b11;", "assign alloc_ready = (valid != 2'b11) || issue_valid;"),
    "alloc_ignores_full": ("assign alloc_fire  = alloc_valid && alloc_ready;", "assign alloc_fire  = alloc_valid;"),
    "alloc_always_slot_0": ("assign alloc_slot  = valid[0];", "assign alloc_slot  = 1'b0;"),
    "alloc_always_slot_1": ("assign alloc_slot  = valid[0];", "assign alloc_slot  = 1'b1;"),
    "issue_ignores_src1": ("valid & src1_ready & src2_ready", "valid & src2_ready"),
    "issue_ignores_src2": ("valid & src1_ready & src2_ready", "valid & src1_ready"),
    "issue_ignores_valid": ("valid & src1_ready & src2_ready", "src1_ready & src2_ready"),
    "issue_slot_flipped": ("assign issue_slot  = !can_issue[0];", "assign issue_slot  = can_issue[1];"),
    "issue_ignores_hold": ("(can_issue != 2'b00) && !issue_hold", "(can_issue != 2'b00)"),
    "issue_during_wakeup": ("assign can_issue   = valid & src1_ready & src2_ready;",
        "assign can_issue   = valid & (src1_ready | {2{wakeup_valid}}) & src2_ready;"),
    "entry_not_cleared": ("if (issue_valid) valid[issue_slot] <= 1'b0;", ""),
    "hold_clears_entry": ("if (issue_valid) valid[issue_slot]", "if (can_issue != 2'b00) valid[issue_slot]"),
    "wakeup_ignores_valid_1": ("if (wakeup_valid && (wakeup_tag == src1[i]))", "if (wakeup_tag == src1[i])"),
    "wakeup_ignores_valid_2": ("if (wakeup_valid && (wakeup_tag == src2[i]))", "if (wakeup_tag == src2[i])"),
    "wakeup_wrong_source": ("(wakeup_tag == src2[i])) src2_ready", "(wakeup_tag == src1[i])) src2_ready"),
    "wakeup_any_tag": ("(wakeup_tag == src1[i])) src1_ready", "1'b1) src1_ready"),
    "no_wakeup_src1": ("if (wakeup_valid && (wakeup_tag == src1[i])) src1_ready[i] <= 1'b1;", ""),
    "wakeup_blocked_by_hold": ("if (wakeup_valid && (wakeup_tag == src2[i]))", "if (!issue_hold && wakeup_valid && (wakeup_tag == src2[i]))"),
    "alloc_ignores_ready1": ("src1_ready[i] <= alloc_src1_ready;", "src1_ready[i] <= 1'b0;"),
    "alloc_assumes_ready2": ("src2_ready[i] <= alloc_src2_ready;", "src2_ready[i] <= 1'b1;"),
    "class_not_stored": ("uop_class[i]  <= alloc_class;", ""),
    "imm_not_stored": ("imm[i]        <= alloc_imm;", ""),
    "load_all_entries": ("assign load = alloc_fire && (alloc_slot == 1'(i));", "assign load = alloc_fire;"),
    "load_without_fire": ("assign load = alloc_fire && (alloc_slot == 1'(i));", "assign load = alloc_slot == 1'(i);"),
    "pdst_from_slot_0": ("assign issue_pdst     = pdst[issue_slot];", "assign issue_pdst     = pdst[0];"),
    "rob_tag_from_slot_0": ("assign issue_rob_tag  = rob_tag[issue_slot];", "assign issue_rob_tag  = rob_tag[0];"),
    "reset_keeps_valid": ("valid <= '0;", ""),
}


LSU_MUTANTS = {
    "store_ignores_head": ("(!is_store || (rob_tag == head_tag))", "1'b1"),
    "load_waits_for_head": ("(!is_store || (rob_tag == head_tag))", "(rob_tag == head_tag)"),
    "req_ignores_done": ("if (req_valid && req_done) state", "if (req_valid) state"),
    "req_done_while_blocked": ("if (req_valid && req_done) state", "if (req_done) state"),
    "store_waits_for_load_data": ("is_store ? S_RESULT : S_WAIT_LOAD", "S_WAIT_LOAD"),
    "load_skips_data": ("is_store ? S_RESULT : S_WAIT_LOAD", "S_RESULT"),
    "seven_nibbles": ("nibble_count == 3'd7", "nibble_count == 3'd6"),
    "count_not_reset": ("nibble_count <= 3'd0;", ""),
    "result_two_cycles": ("default:     state <= S_IDLE;", "default:     state <= start_valid ? S_REQUEST : S_RESULT;"),
    "start_overwrites_slot": ("assign start_fire = (state == S_IDLE) && start_valid;", "assign start_fire = start_valid;"),
    "nibble_without_valid": ("assign load_fire  = (state == S_WAIT_LOAD) && load_nibble_valid;", "assign load_fire  = state == S_WAIT_LOAD;"),
    "nibbles_high_first": ("data <= {load_nibble, data[31:4]};", "data <= {data[27:0], load_nibble};"),
    "store_shift_wrong_way": ("data <= {8'd0, data[31:8]};", "data <= {data[23:0], 8'd0};"),
    "store_never_shifts": ("data <= {8'd0, data[31:8]};", ""),
    "addr_not_captured": ("addr     <= start_addr;", ""),
    "data_not_captured": ("data     <= start_data;", ""),
    "mem_op_not_captured": ("mem_op   <= start_mem_op;", ""),
    "pdst_not_captured": ("pdst     <= start_pdst;", ""),
    "rob_tag_not_captured": ("rob_tag  <= start_rob_tag;", ""),
    "half_ignores_addr": ("assign half     = addr[1] ? data[31:16] : data[15:0];", "assign half     = data[15:0];"),
    "byte_ignores_addr": ("assign low_byte = addr[0] ? half[15:8] : half[7:0];", "assign low_byte = half[7:0];"),
    "unsigned_sign_extends": ("assign fill     = !mem_op[2] && ", "assign fill     = "),
    "signed_zero_extends": ("assign fill     = !mem_op[2] && (mem_op[0] ? half[15] : low_byte[7]);", "assign fill     = 1'b0;"),
    "byte_sign_from_half": ("(mem_op[0] ? half[15] : low_byte[7])", "half[15]"),
    "half_sign_from_byte": ("(mem_op[0] ? half[15] : low_byte[7])", "low_byte[7]"),
    "store_writes_register": ("assign result_tag     = is_store ? PTAG_ZERO : pdst;", "assign result_tag     = pdst;"),
    "lw_extracts_byte": ("assign result_data    = mem_op[1] ? data", "assign result_data    = mem_op[1] ? {16'd0, half}"),
    "size_wrong": ("assign req_size     = mem_op[1:0];", "assign req_size     = 2'd2;"),
    "req_addr_truncated": ("assign req_addr     = addr;", "assign req_addr     = {addr[15:2], 2'd0};"),
    "reset_keeps_state": ("state        <= S_IDLE;", ""),
}


BUS_IF_MUTANTS = {
    "store_blocked_by_busy": ("req_valid && (req_is_store || !busy)", "req_valid && !busy"),
    "load_ignores_busy": ("req_valid && (req_is_store || !busy)", "req_valid"),
    "redirect_ignores_busy": ("redirect_valid && !busy", "redirect_valid"),
    "busy_ignores_ack": ("assign busy           = wait_load || wait_ack;", "assign busy           = wait_load;"),
    "busy_ignores_load": ("assign busy           = wait_load || wait_ack;", "assign busy           = wait_ack;"),
    "store_clears_wait_load": ("if (start && !halt_valid && start_lsu && !req_is_store) wait_load <= 1'b1;", "if (start) wait_load <= !halt_valid && start_lsu && !req_is_store;"),
    "store_clears_wait_ack": ("if (start && !halt_valid && !start_lsu) wait_ack <= 1'b1;", "if (start) wait_ack <= !halt_valid && !start_lsu;"),
    "store_sets_wait_load": ("start_lsu && !req_is_store) wait_load", "start_lsu) wait_load"),
    "halt_sets_wait_ack": ("if (start && !halt_valid && !start_lsu) wait_ack", "if (start && !start_lsu) wait_ack"),
    "store_length_fixed": ("3'd2 + (3'd1 << req_size)", "3'd6"),
    "store_length_off_by_one": ("3'd2 + (3'd1 << req_size)", "3'd3 + (3'd1 << req_size)"),
    "load_sends_store_bytes": ("((sel == SEL_LSU) && req_is_store)", "(sel == SEL_LSU)"),
    "byte_taken_early": ("(index >= 3'd3);", "(index >= 3'd2);"),
    "nibble_without_load": ("assign load_nibble_valid = d_valid && wait_load;", "assign load_nibble_valid = d_valid;"),
    "ack_without_redirect": ("assign redirect_ack      = d_valid && wait_ack;", "assign redirect_ack      = d_valid;"),
    "wrong_store_header": ("{2'b10, req_size, 4'd0}", "{2'b01, req_size, 4'd0}"),
    "wrong_load_header": ("8'h40", "8'h00"),
    "wrong_halt_header": ("{4'b1100, 2'b00, halt_reason}", "{4'b1000, 2'b00, halt_reason}"),
    "halt_drops_reason": ("{4'b1100, 2'b00, halt_reason}", "8'hC0"),
    "addr_bytes_swapped": ("3'd1:    o_data = addr[7:0];", "3'd1:    o_data = addr[15:8];"),
    "redirect_uses_lsu_addr": ("addr   = redirect_addr;", "addr   = req_addr;"),
    "lsu_first_then_halt": ("sel   <= halt_valid ? SEL_HALT : start_lsu ? SEL_LSU : SEL_REDIRECT;", "sel   <= start_lsu ? SEL_LSU : halt_valid ? SEL_HALT : SEL_REDIRECT;"),
    "frame_never_ends": ("else if (last_byte) active <= 1'b0;", ""),
    "load_done_ignored": ("if (load_done) wait_load <= 1'b0;", ""),
    "ack_ignored": ("if (redirect_ack) wait_ack <= 1'b0;", ""),
    "reset_keeps_wait": ("wait_load <= 1'b0;\n            wait_ack  <= 1'b0;\n        end else begin\n            if (start)", "wait_ack  <= 1'b0;\n        end else begin\n            if (start)"),
    "o_valid_always": ("assign o_valid = active;", "assign o_valid = 1'b1;"),
    "done_every_byte": ("assign req_done         = last_byte && (sel == SEL_LSU);", "assign req_done         = active && (sel == SEL_LSU);"),
}

FETCH_MUTANTS = {
    "ready_ignores_redirect": ("assign i_ready   = !redirecting && (!fill_full || !head_valid);", "assign i_ready   = !fill_full || !head_valid;"),
    "ready_ignores_full": ("assign i_ready   = !redirecting && (!fill_full || !head_valid);", "assign i_ready   = !redirecting;"),
    "ready_stalls_with_head_free": ("(!fill_full || !head_valid)", "!fill_full"),
    "byte_ignores_ready": ("assign byte_fire = i_valid && i_ready;", "assign byte_fire = i_valid;"),
    "head_ignores_advance": ("assign head_load = fill_full && (!head_valid || advance);", "assign head_load = fill_full && !head_valid;"),
    "head_overwritten": ("assign head_load = fill_full && (!head_valid || advance);", "assign head_load = fill_full;"),
    "instr_shows_during_redirect": ("assign instr_valid = head_valid && !redirecting;", "assign instr_valid = head_valid;"),
    "pc_next_plus_two": ("pc + 16'd4", "pc + 16'd2"),
    "ack_keeps_count": ("byte_count <= 2'd0;\n            fill_full  <= 1'b0;", "if (!rst_n) byte_count <= 2'd0;\n            fill_full  <= 1'b0;"),
    "ack_keeps_fill": ("fill_full  <= 1'b0;\n            head_valid <= 1'b0;\n        end else", "if (!rst_n) fill_full  <= 1'b0;\n            head_valid <= 1'b0;\n        end else"),
    "ack_keeps_head": ("fill_full  <= 1'b0;\n            head_valid <= 1'b0;\n        end else", "fill_full  <= 1'b0;\n            if (!rst_n) head_valid <= 1'b0;\n        end else"),
    "full_one_byte_early": ("if (byte_count == 2'd3)", "if (byte_count == 2'd2)"),
    "bytes_high_first": ("fill <= {i_data, fill[31:8]};", "fill <= {fill[23:0], i_data};"),
    "advance_ignored": ("else if (advance) head_valid <= 1'b0;", ""),
    "pc_stuck": ("pc <= pc_next;", ""),
    "advance_wins_over_redirect": ("if (redirect_start) begin\n                pc             <= redirect_target;", "if (redirect_start) begin\n                pc             <= advance ? pc_next : redirect_target;"),
    "target_ignored": ("pc             <= redirect_target;", "pc             <= pc_next;"),
    "redirecting_not_set": ("redirecting    <= 1'b1;", ""),
    "redirect_valid_not_set": ("redirect_valid <= 1'b1;", ""),
    "redirect_valid_stuck": ("if (redirect_done) redirect_valid <= 1'b0;", ""),
    "ready_back_at_frame_end": ("if (redirect_ack) redirecting <= 1'b0;", "if (redirect_done) redirecting <= 1'b0;"),
    "reset_keeps_redirecting": ("redirecting    <= 1'b0;\n            redirect_valid <= 1'b0;", "redirect_valid <= 1'b0;"),
    "reset_keeps_pc": ("pc             <= 16'd0;", ""),
}


# These need the blocks working together, so they run on the whole core.
CPU_MUTANTS = {
    "lost_wakeup_port1": ("prf", "|| (wb_valid && (wb_tag == chk_tag1))", ""),
    "lost_wakeup_port2": ("prf", "|| (wb_valid && (wb_tag == chk_tag2))", ""),
    "two_memory_ops": ("cpu", "                       && (!is_mem || !mem_busy)\n", ""),
    "dispatch_write_collides": ("cpu", "                       && (!dispatch_write || port_free);", ";"),
    "lsu_result_collides": ("cpu", ".issue_hold      (lsu_result_valid),", ".issue_hold      (1'b0),"),
    "no_control_wait": ("cpu", "if (dispatch_fire && (is_branch || is_jalr)) control_wait <= 1'b1;", ""),
    "branch_leaves_head": ("cpu", "dispatch_fire && !is_branch && !is_jalr", "dispatch_fire && !is_jalr"),
    "not_taken_stays": ("cpu", "                  || (issue_is_branch && !branch_taken);", ";"),
    "taken_ignored": ("cpu", "|| branch_taken_now || issue_is_jalr", "|| issue_is_jalr"),
    "jalr_uses_pc_target": ("cpu", "issue_is_jalr ? alu_y[15:0] : pc_target[15:0]", "pc_target[15:0]"),
    "auipc_drops_pc": ("cpu", ": is_auipc ? pc_target", ": is_auipc ? imm"),
    "link_is_pc": ("cpu", ":            {16'd0, pc_next};", ":            {16'd0, pc};"),
    "imm_not_sign_extended": ("cpu", "{{20{issue_imm[11]}}, issue_imm}", "{20'd0, issue_imm}"),
    "store_data_from_rs1": ("cpu", ".start_data    (rd_data2),", ".start_data    (rd_data1),"),
    "branch_writes_pdst": ("cpu", "(issue_class == uop_pkg::UOP_ALU[2:0]) ? issue_pdst : PTAG_ZERO", "issue_pdst"),
    "complete_tag_mixed_up": ("cpu", "lsu_result_valid ? lsu_result_rob_tag : issue_rob_tag", "issue_rob_tag"),
    "dispatch_after_halt": ("cpu", "if (dispatch_fire && decode_halt) stopped <= 1'b1;", ""),
    "prf_ready_not_cleared": ("cpu", ".alloc_valid(dispatch_fire),\n        .alloc_tag  (alloc_pdst),", ".alloc_valid(1'b0),\n        .alloc_tag  (alloc_pdst),"),
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


@pytest.mark.parametrize("mutant", ISSUE_QUEUE_MUTANTS)
def test_issue_queue_mutant_is_caught(mutant, tmp_path):
    run_mutant(tmp_path, "issue_queue", *ISSUE_QUEUE_MUTANTS[mutant], {"IQ_CYCLES": "3000"})


@pytest.mark.parametrize("mutant", LSU_MUTANTS)
def test_lsu_mutant_is_caught(mutant, tmp_path):
    run_mutant(tmp_path, "lsu", *LSU_MUTANTS[mutant], {"LSU_OPS": "150"})


@pytest.mark.parametrize("mutant", BUS_IF_MUTANTS)
def test_bus_if_mutant_is_caught(mutant, tmp_path):
    run_mutant(tmp_path, "bus_if", *BUS_IF_MUTANTS[mutant], {"BUS_OPS": "300"})


@pytest.mark.parametrize("mutant", FETCH_MUTANTS)
def test_fetch_mutant_is_caught(mutant, tmp_path):
    run_mutant(tmp_path, "fetch", *FETCH_MUTANTS[mutant], {"FETCH_INSTRS": "500"})


@pytest.mark.parametrize("mutant", CPU_MUTANTS)
def test_cpu_mutant_is_caught(mutant, tmp_path, images):
    module, find, replace = CPU_MUTANTS[mutant]
    path = RTL / f"{module}.sv"
    text = path.read_text()
    assert text.count(find) == 1, f"mutant pattern no longer matches the RTL: {find}"
    source = tmp_path / path.name
    source.write_text(text.replace(find, replace))
    others = [f for f in [RTL / "cpu.sv", *CORE] if f.name != path.name]
    env = {"CPU_IMAGES": str(images), "CPU_PROGRAMS": "8"}
    with pytest.raises(SystemExit):
        simulate("cpu", source, tmp_path / "build", env, others=others)
    shutil.rmtree(tmp_path / "build", ignore_errors=True)
