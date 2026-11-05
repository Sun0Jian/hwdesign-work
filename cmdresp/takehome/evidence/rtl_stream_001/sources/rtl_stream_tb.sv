`timescale 1ns/1ps

// Supplementary RTL verification of complete queued inputs. Unlike Vitis's
// golden-C input recorder, this source offers every beat in scenarios.txt.
module rtl_stream_tb;
  reg ap_clk = 0;
  always #5 ap_clk = ~ap_clk;
  reg ap_rst_n = 0;
  reg [31:0] s_in_TDATA = 0;
  reg s_in_TVALID = 0;
  wire s_in_TREADY;
  reg [3:0] s_in_TKEEP = 15, s_in_TSTRB = 15;
  reg s_in_TLAST = 0;
  wire [31:0] m_out_TDATA;
  wire m_out_TVALID;
  wire m_out_TREADY = 1'b1;
  wire [3:0] m_out_TKEEP, m_out_TSTRB;
  wire m_out_TLAST;

  reg s_axi_control_AWVALID = 0;
  wire s_axi_control_AWREADY;
  reg [5:0] s_axi_control_AWADDR = 0;
  reg s_axi_control_WVALID = 0;
  wire s_axi_control_WREADY;
  reg [31:0] s_axi_control_WDATA = 0;
  reg [3:0] s_axi_control_WSTRB = 15;
  reg s_axi_control_ARVALID = 0;
  wire s_axi_control_ARREADY;
  reg [5:0] s_axi_control_ARADDR = 0;
  wire s_axi_control_RVALID;
  wire s_axi_control_RREADY = 1'b1;
  wire [31:0] s_axi_control_RDATA;
  wire [1:0] s_axi_control_RRESP;
  wire s_axi_control_BVALID;
  wire s_axi_control_BREADY = 1'b1;
  wire [1:0] s_axi_control_BRESP;
  wire interrupt;

  maxpool dut(.*);

  reg [31:0] input_data [0:65535];
  reg input_last [0:65535];
  reg [31:0] output_data [0:65535];
  reg output_last [0:65535];
  integer nin, nout, expected_consumed, expected_halted, expected_error;
  reg [31:0] expected_tx;
  integer accepted = 0, emitted = 0, post_done_accepts = 0;
  integer current_failures = 0, all_failures = 0;
  integer cycles = 0, start_cycle = 0, done_cycle = 0;
  integer pending_post_done_cycles = 0;
  reg active = 0, done_seen = 0, start_seen = 0, pending_at_done = 0;
  reg input_match = 1, output_match = 1;

  // Data changes only on falling edges. Consecutive accepted beats remain
  // continuously valid, including the queued suffix after an offending beat.
  always @(negedge ap_clk) begin
    if (active && accepted < nin) begin
      s_in_TDATA = input_data[accepted];
      s_in_TLAST = input_last[accepted];
      s_in_TVALID = 1;
    end else begin
      s_in_TVALID = 0;
    end
  end

  // Sample handshakes on rising edges, before any nonblocking DUT updates.
  always @(posedge ap_clk) begin
    cycles = cycles + 1;
    if (active) begin
      if (!start_seen && dut.ap_start && dut.ap_CS_fsm_state1) begin
        start_seen = 1;
        start_cycle = cycles;
      end
      if (s_in_TVALID && s_in_TREADY) begin
        if (done_seen) post_done_accepts = post_done_accepts + 1;
        if (accepted >= nin || s_in_TDATA !== input_data[accepted]
            || s_in_TLAST !== input_last[accepted]
            || s_in_TKEEP !== 4'hf || s_in_TSTRB !== 4'hf) begin
          input_match = 0;
          current_failures = current_failures + 1;
        end
        accepted = accepted + 1;
      end
      if (m_out_TVALID && m_out_TREADY) begin
        if (emitted >= nout || m_out_TDATA !== output_data[emitted]
            || m_out_TLAST !== output_last[emitted]
            || m_out_TKEEP !== 4'hf || m_out_TSTRB !== 4'hf) begin
          output_match = 0;
          current_failures = current_failures + 1;
          $display("OUTPUT_MISMATCH beat=%0d data=%08x last=%0d", emitted,
                   m_out_TDATA, m_out_TLAST);
        end
        emitted = emitted + 1;
      end
      if (!done_seen && dut.ap_done) begin
        done_seen = 1;
        done_cycle = cycles;
        pending_at_done = accepted < nin && s_in_TVALID
                          && s_in_TDATA === input_data[accepted]
                          && s_in_TLAST === input_last[accepted];
      end
      if (done_seen && s_in_TVALID && accepted < nin)
        pending_post_done_cycles = pending_post_done_cycles + 1;
    end
  end

  task automatic axi_write(input [5:0] address, input [31:0] value);
    begin
      @(negedge ap_clk);
      s_axi_control_AWADDR = address;
      s_axi_control_AWVALID = 1;
      do @(posedge ap_clk); while (s_axi_control_AWREADY !== 1'b1);
      @(negedge ap_clk);
      s_axi_control_AWVALID = 0;
      s_axi_control_WDATA = value;
      s_axi_control_WVALID = 1;
      do @(posedge ap_clk); while (s_axi_control_WREADY !== 1'b1);
      @(negedge ap_clk);
      s_axi_control_WVALID = 0;
      do @(posedge ap_clk); while (s_axi_control_BVALID !== 1'b1);
      if (s_axi_control_BRESP !== 0) $fatal(1, "AXI-Lite write failed");
    end
  endtask

  task automatic axi_read(input [5:0] address, output [31:0] value);
    begin
      @(negedge ap_clk);
      s_axi_control_ARADDR = address;
      s_axi_control_ARVALID = 1;
      do @(posedge ap_clk); while (s_axi_control_ARREADY !== 1'b1);
      @(negedge ap_clk);
      s_axi_control_ARVALID = 0;
      do @(posedge ap_clk); while (s_axi_control_RVALID !== 1'b1);
      value = s_axi_control_RDATA;
      if (s_axi_control_RRESP !== 0) $fatal(1, "AXI-Lite read failed");
    end
  endtask

  string scenario_path, result_path, scenario_name;
  integer source, report, count, index, beat, fields, last_field, wait_cycles;
  reg [31:0] observed_halted, observed_error, observed_tx;
  reg status_match, suffix_match, passed;
  initial begin
    if (!$value$plusargs("SCENARIOS=%s", scenario_path)
        || !$value$plusargs("RESULT=%s", result_path))
      $fatal(1, "Supply +SCENARIOS=... and +RESULT=...");
    source = $fopen(scenario_path, "r");
    report = $fopen(result_path, "w");
    if (!source || !report) $fatal(1, "Cannot open scenario/result file");
    fields = $fscanf(source, "%d", count);
    if (fields != 1) $fatal(1, "Missing scenario count");
    $fwrite(report, "{\n  \"method\":\"full-queue RTL AXI-stream and AXI-Lite verification\",\n");
    $fwrite(report, "  \"dut_reset_count\":1,\n  \"activations\":[\n");

    repeat (10) @(posedge ap_clk);
    @(negedge ap_clk); ap_rst_n = 1;
    repeat (4) @(posedge ap_clk);
    for (index = 0; index < count; index = index + 1) begin
      // No DUT reset here. Only the external stream queue is fresh.
      @(negedge ap_clk); #1;
      active = 0;
      s_in_TVALID = 0;
      fields = $fscanf(source, "%s %d %d %d %d %d %d", scenario_name,
                       nin, nout, expected_consumed, expected_halted,
                       expected_error, expected_tx);
      if (fields != 7 || nin > 65536 || nout > 65536)
        $fatal(1, "Invalid scenario metadata at %0d", index);
      for (beat = 0; beat < nin; beat = beat + 1) begin
        fields = $fscanf(source, "%h %d", input_data[beat], last_field);
        if (fields != 2) $fatal(1, "Invalid input beat");
        input_last[beat] = last_field != 0;
      end
      for (beat = 0; beat < nout; beat = beat + 1) begin
        fields = $fscanf(source, "%h %d", output_data[beat], last_field);
        if (fields != 2) $fatal(1, "Invalid expected output beat");
        output_last[beat] = last_field != 0;
      end
      accepted = 0; emitted = 0; post_done_accepts = 0;
      done_seen = 0; start_seen = 0; pending_at_done = 0;
      pending_post_done_cycles = 0; current_failures = 0;
      input_match = 1; output_match = 1;
      active = 1;
      axi_write(6'h00, 32'h00000001);
      wait_cycles = 0;
      while (!done_seen) begin
        @(negedge ap_clk); #1;
        wait_cycles = wait_cycles + 1;
        if (wait_cycles > 250000) $fatal(1, "Activation timeout %0d", index);
      end
      axi_read(6'h10, observed_halted);
      axi_read(6'h20, observed_error);
      axi_read(6'h30, observed_tx);
      // Continue to present the pending tail while status is read, then for
      // ten additional clocks. A returned body must accept no more input.
      repeat (10) @(negedge ap_clk);
      #1;
      status_match = observed_halted === expected_halted
                     && observed_error === expected_error
                     && observed_tx === expected_tx;
      suffix_match = accepted == expected_consumed && post_done_accepts == 0;
      if (nin > expected_consumed)
        suffix_match = suffix_match && pending_at_done
                       && pending_post_done_cycles >= 10;
      output_match = output_match && emitted == nout;
      passed = current_failures == 0 && status_match && suffix_match
               && input_match && output_match;
      if (!passed) all_failures = all_failures + 1;
      $display("RTL_ACTIVATION %0d %s %s accepted=%0d/%0d output=%0d/%0d status=%0d,%0d,%0d pending_at_done=%0d post_done_accepts=%0d",
               index, scenario_name, passed ? "PASS" : "FAIL", accepted,
               expected_consumed, emitted, nout, observed_halted,
               observed_error, observed_tx, pending_at_done, post_done_accepts);
      if (index) $fwrite(report, ",\n");
      $fwrite(report, "    {\"index\":%0d,\"name\":\"%s\",\"pass\":%s,", index,
              scenario_name, passed ? "true" : "false");
      $fwrite(report, "\"input_match\":%s,\"output_match\":%s,\"status_match\":%s,\"remaining_suffix_match\":%s,",
              input_match ? "true" : "false", output_match ? "true" : "false",
              status_match ? "true" : "false", suffix_match ? "true" : "false");
      $fwrite(report, "\"input_beats\":%0d,\"consumed_beats\":%0d,\"remaining_beats\":%0d,\"output_beats\":%0d,",
              nin, accepted, nin-accepted, emitted);
      $fwrite(report, "\"halted\":%0d,\"error\":%0d,\"error_tx_id\":%0d,", observed_halted, observed_error, observed_tx);
      $fwrite(report, "\"pending_valid_at_done\":%s,\"pending_post_done_cycles\":%0d,\"post_done_accepts\":%0d,\"observed_start_to_done_cycles\":%0d}",
              pending_at_done ? "true" : "false", pending_post_done_cycles,
              post_done_accepts, done_cycle-start_cycle);
      active = 0;
      s_in_TVALID = 0;
      // Flush only the host's stream path by discarding its unaccepted suffix.
      repeat (2) @(negedge ap_clk);
    end
    $fwrite(report, "\n  ],\n  \"scenario_count\":%0d,\n  \"failures\":%0d\n}\n", count, all_failures);
    $fclose(source);
    $fclose(report);
    $display("RTL_ALL_ACTIVATIONS %0d FAILURES %0d", count, all_failures);
    if (all_failures) $fatal(1, "RTL stream verification failed");
    $finish;
  end

  initial begin
    #100000000;
    $fatal(1, "Global simulation timeout");
  end
endmodule
