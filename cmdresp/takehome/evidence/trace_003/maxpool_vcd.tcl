
open_vcd
log_vcd [get_objects {/apatb_maxpool_top/AESL_inst_maxpool/ap_clk /apatb_maxpool_top/AESL_inst_maxpool/ap_rst_n /apatb_maxpool_top/AESL_inst_maxpool/ap_start /apatb_maxpool_top/AESL_inst_maxpool/ap_done /apatb_maxpool_top/AESL_inst_maxpool/ap_idle /apatb_maxpool_top/AESL_inst_maxpool/ap_ready /apatb_maxpool_top/AESL_inst_maxpool/s_in_TDATA /apatb_maxpool_top/AESL_inst_maxpool/s_in_TLAST /apatb_maxpool_top/AESL_inst_maxpool/s_in_TKEEP /apatb_maxpool_top/AESL_inst_maxpool/s_in_TSTRB /apatb_maxpool_top/AESL_inst_maxpool/s_in_TVALID /apatb_maxpool_top/AESL_inst_maxpool/s_in_TREADY /apatb_maxpool_top/AESL_inst_maxpool/m_out_TDATA /apatb_maxpool_top/AESL_inst_maxpool/m_out_TLAST /apatb_maxpool_top/AESL_inst_maxpool/m_out_TKEEP /apatb_maxpool_top/AESL_inst_maxpool/m_out_TSTRB /apatb_maxpool_top/AESL_inst_maxpool/m_out_TVALID /apatb_maxpool_top/AESL_inst_maxpool/m_out_TREADY}]
log_wave -r /
set designtopgroup [add_wave_group "Design Top Signals"]
set coutputgroup [add_wave_group "C Outputs" -into $designtopgroup]
set return_group [add_wave_group return(axis) -into $coutputgroup]
add_wave /apatb_maxpool_top/AESL_inst_maxpool/m_out_TLAST -into $return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/m_out_TSTRB -into $return_group -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/m_out_TKEEP -into $return_group -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/m_out_TREADY -into $return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/m_out_TVALID -into $return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/m_out_TDATA -into $return_group -radix hex
set halted__error__error_tx_id__return_group [add_wave_group halted__error__error_tx_id__return(axi_slave) -into $coutputgroup]
add_wave /apatb_maxpool_top/AESL_inst_maxpool/interrupt -into $halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_BRESP -into $halted__error__error_tx_id__return_group -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_BREADY -into $halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_BVALID -into $halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_RRESP -into $halted__error__error_tx_id__return_group -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_RDATA -into $halted__error__error_tx_id__return_group -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_RREADY -into $halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_RVALID -into $halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_ARREADY -into $halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_ARVALID -into $halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_ARADDR -into $halted__error__error_tx_id__return_group -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_WSTRB -into $halted__error__error_tx_id__return_group -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_WDATA -into $halted__error__error_tx_id__return_group -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_WREADY -into $halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_WVALID -into $halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_AWREADY -into $halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_AWVALID -into $halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_axi_control_AWADDR -into $halted__error__error_tx_id__return_group -radix hex
set cinputgroup [add_wave_group "C Inputs" -into $designtopgroup]
set return_group [add_wave_group return(axis) -into $cinputgroup]
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_in_TLAST -into $return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_in_TSTRB -into $return_group -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_in_TKEEP -into $return_group -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_in_TREADY -into $return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_in_TVALID -into $return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/AESL_inst_maxpool/s_in_TDATA -into $return_group -radix hex
set blocksiggroup [add_wave_group "Block-level IO Handshake(internal)" -into $designtopgroup]
add_wave /apatb_maxpool_top/AESL_inst_maxpool/ap_done -into $blocksiggroup
add_wave /apatb_maxpool_top/AESL_inst_maxpool/ap_idle -into $blocksiggroup
add_wave /apatb_maxpool_top/AESL_inst_maxpool/ap_ready -into $blocksiggroup
add_wave /apatb_maxpool_top/AESL_inst_maxpool/ap_start -into $blocksiggroup
set resetgroup [add_wave_group "Reset" -into $designtopgroup]
add_wave /apatb_maxpool_top/AESL_inst_maxpool/ap_rst_n -into $resetgroup
set clockgroup [add_wave_group "Clock" -into $designtopgroup]
add_wave /apatb_maxpool_top/AESL_inst_maxpool/ap_clk -into $clockgroup
set testbenchgroup [add_wave_group "Test Bench Signals"]
set tbinternalsiggroup [add_wave_group "Internal Signals" -into $testbenchgroup]
set tb_simstatus_group [add_wave_group "Simulation Status" -into $tbinternalsiggroup]
set tb_portdepth_group [add_wave_group "Port Depth" -into $tbinternalsiggroup]
add_wave /apatb_maxpool_top/AUTOTB_TRANSACTION_NUM -into $tb_simstatus_group -radix hex
add_wave /apatb_maxpool_top/ready_cnt -into $tb_simstatus_group -radix hex
add_wave /apatb_maxpool_top/done_cnt -into $tb_simstatus_group -radix hex
add_wave /apatb_maxpool_top/LENGTH_error -into $tb_portdepth_group -radix hex
add_wave /apatb_maxpool_top/LENGTH_error_tx_id -into $tb_portdepth_group -radix hex
add_wave /apatb_maxpool_top/LENGTH_halted -into $tb_portdepth_group -radix hex
add_wave /apatb_maxpool_top/LENGTH_m_out_V_data_V -into $tb_portdepth_group -radix hex
add_wave /apatb_maxpool_top/LENGTH_m_out_V_keep_V -into $tb_portdepth_group -radix hex
add_wave /apatb_maxpool_top/LENGTH_m_out_V_last_V -into $tb_portdepth_group -radix hex
add_wave /apatb_maxpool_top/LENGTH_m_out_V_strb_V -into $tb_portdepth_group -radix hex
add_wave /apatb_maxpool_top/LENGTH_s_in_V_data_V -into $tb_portdepth_group -radix hex
add_wave /apatb_maxpool_top/LENGTH_s_in_V_keep_V -into $tb_portdepth_group -radix hex
add_wave /apatb_maxpool_top/LENGTH_s_in_V_last_V -into $tb_portdepth_group -radix hex
add_wave /apatb_maxpool_top/LENGTH_s_in_V_strb_V -into $tb_portdepth_group -radix hex
set tbcoutputgroup [add_wave_group "C Outputs" -into $testbenchgroup]
set tb_return_group [add_wave_group return(axis) -into $tbcoutputgroup]
add_wave /apatb_maxpool_top/m_out_TLAST -into $tb_return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/m_out_TSTRB -into $tb_return_group -radix hex
add_wave /apatb_maxpool_top/m_out_TKEEP -into $tb_return_group -radix hex
add_wave /apatb_maxpool_top/m_out_TREADY -into $tb_return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/m_out_TVALID -into $tb_return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/m_out_TDATA -into $tb_return_group -radix hex
set tb_halted__error__error_tx_id__return_group [add_wave_group halted__error__error_tx_id__return(axi_slave) -into $tbcoutputgroup]
add_wave /apatb_maxpool_top/control_INTERRUPT -into $tb_halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/control_BRESP -into $tb_halted__error__error_tx_id__return_group -radix hex
add_wave /apatb_maxpool_top/control_BREADY -into $tb_halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/control_BVALID -into $tb_halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/control_RRESP -into $tb_halted__error__error_tx_id__return_group -radix hex
add_wave /apatb_maxpool_top/control_RDATA -into $tb_halted__error__error_tx_id__return_group -radix hex
add_wave /apatb_maxpool_top/control_RREADY -into $tb_halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/control_RVALID -into $tb_halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/control_ARREADY -into $tb_halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/control_ARVALID -into $tb_halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/control_ARADDR -into $tb_halted__error__error_tx_id__return_group -radix hex
add_wave /apatb_maxpool_top/control_WSTRB -into $tb_halted__error__error_tx_id__return_group -radix hex
add_wave /apatb_maxpool_top/control_WDATA -into $tb_halted__error__error_tx_id__return_group -radix hex
add_wave /apatb_maxpool_top/control_WREADY -into $tb_halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/control_WVALID -into $tb_halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/control_AWREADY -into $tb_halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/control_AWVALID -into $tb_halted__error__error_tx_id__return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/control_AWADDR -into $tb_halted__error__error_tx_id__return_group -radix hex
set tbcinputgroup [add_wave_group "C Inputs" -into $testbenchgroup]
set tb_return_group [add_wave_group return(axis) -into $tbcinputgroup]
add_wave /apatb_maxpool_top/s_in_TLAST -into $tb_return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/s_in_TSTRB -into $tb_return_group -radix hex
add_wave /apatb_maxpool_top/s_in_TKEEP -into $tb_return_group -radix hex
add_wave /apatb_maxpool_top/s_in_TREADY -into $tb_return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/s_in_TVALID -into $tb_return_group -color #ffff00 -radix hex
add_wave /apatb_maxpool_top/s_in_TDATA -into $tb_return_group -radix hex
save_wave_config maxpool.wcfg
run all
close_vcd
quit

