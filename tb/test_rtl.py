"""pytest entry point for RTL simulation. Run with: pytest tb

test_mutant_is_caught injects known bugs into a copy of the RTL and requires the
testbench to fail, which shows that the tests can detect each bug.
"""
import shutil
import subprocess
from pathlib import Path

import pytest
from cocotb_tools.runner import get_runner

TB = Path(__file__).resolve().parent
RTL = TB.parent / "rtl"
BUILD = TB / "sim_build"


def simulate(name, source, build_dir, extra_env=None):
    runner = get_runner("verilator")
    runner.build(
        sources=[source],
        hdl_toplevel=name,
        build_dir=build_dir,
        build_args=["--public-flat-rw"],
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


def test_lint():
    subprocess.run(
        ["verilator", "--lint-only", "-Wall", "--sv", str(RTL / "rename_rob.sv")],
        check=True,
    )


def test_synthesis_read():
    """Yosys must accept the source, since it is the path to silicon."""
    subprocess.run(
        ["yosys", "-q", "-p", f"read_verilog -sv {RTL / 'rename_rob.sv'}; synth -top rename_rob"],
        check=True,
    )


def test_rename_rob():
    simulate("rename_rob", RTL / "rename_rob.sv", BUILD / "rename_rob")


MUTANTS = {
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


@pytest.mark.parametrize("mutant", MUTANTS)
def test_mutant_is_caught(mutant, tmp_path):
    find, replace = MUTANTS[mutant]
    text = (RTL / "rename_rob.sv").read_text()
    assert text.count(find) == 1, f"mutant {mutant} no longer matches the RTL"
    source = tmp_path / "rename_rob.sv"
    source.write_text(text.replace(find, replace))
    with pytest.raises(SystemExit):
        simulate("rename_rob", source, tmp_path / "build", {"RR_INSTRUCTIONS": "300"})
    shutil.rmtree(tmp_path / "build", ignore_errors=True)
