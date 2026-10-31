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
MODULES = ["rename_rob.sv", "prf.sv"]


def simulate(name, source, build_dir, extra_env=None, parameters=None):
    runner = get_runner("verilator")
    runner.build(
        sources=[source],
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
    subprocess.run(["verilator", "--lint-only", "-Wall", "--sv", str(RTL / module)], check=True)


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
        ["yosys", "-q", "-p", f"read_verilog -sv {RTL / module}; synth -top {top}"],
        check=True,
    )


def test_rename_rob():
    simulate("rename_rob", RTL / "rename_rob.sv", BUILD / "rename_rob")


@pytest.mark.parametrize("latches", [1, 0], ids=["latch", "flop"])
def test_prf(latches):
    simulate("prf", RTL / "prf.sv", BUILD / f"prf_{latches}", parameters={"USE_LATCHES": latches})


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
