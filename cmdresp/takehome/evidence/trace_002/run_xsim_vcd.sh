#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
/eda/xilinx/2026.1/Vivado/bin/xsim -testplusarg "UVM_VERBOSITY=UVM_NONE" -testplusarg "UVM_TESTNAME=maxpool_test_lib" -testplusarg "UVM_TIMEOUT=20000000000000" --noieeewarnings maxpool -tclbatch maxpool_vcd.tcl -view maxpool_dataflow_ana.wcfg -protoinst maxpool.protoinst
