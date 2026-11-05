# Stage selection is supplied by maxpool_build.py through Waveflow's toolchain.
set stage "csim"
if {[info exists ::env(WAVEFLOW_POOL_STAGE)]} {
    set stage $::env(WAVEFLOW_POOL_STAGE)
}
if {$stage ni {csim synth cosim}} {
    error "Unsupported WAVEFLOW_POOL_STAGE: $stage"
}

set root [file normalize [file dirname [info script]]]
cd $root
open_project maxpool_prj
set_top maxpool
set cflags "-std=c++14 -I${root}/include -I${root}/gen -I${root}"
add_files gen/maxpool.cpp -cflags $cflags
add_files include/streamutils.cpp -cflags $cflags
add_files -tb maxpool_tb.cpp -cflags $cflags
open_solution solution1 -flow_target vivado
set_part {xc7z020clg484-1}
create_clock -period 10 -name default

set tb_args [list $::env(WAVEFLOW_POOL_SCENARIOS) $::env(WAVEFLOW_POOL_TB_RESULT)]

if {$stage eq "csim"} {
    csim_design -argv $tb_args
} elseif {$stage eq "synth"} {
    csynth_design
} elseif {$stage eq "cosim"} {
    # One testbench invocation contains every activation and its recovery cases.
    # Port tracing preserves handshakes needed to audit the transaction latency.
    cosim_design -rtl verilog -trace_level port -argv $tb_args
}
exit
