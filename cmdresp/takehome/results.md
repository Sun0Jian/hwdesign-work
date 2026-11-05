# Interface

All retained implementation runs used the accepted Version 1 specification
at commit `e07d94b069719939eaa5ea4b364461b8fec6f941`.
[prompt.md](./prompt.md) remains byte-for-byte identical to that version.
The historical host diagnostics and Git outputs are retained in
[environment_checks.txt](./evidence/environment_checks.txt); their branch-head
observations describe that earlier point in time. This final documentation
review adds reporting detail without changing the tested implementation or
relabelling its runs. Its separate provenance and submission checks are in
[submission_audit.json](./evidence/submission_review/submission_audit.json).

Both AXI4-Stream ports carry 32-bit words. Each payload beat contains exactly
one signed 16-bit two's-complement sample in bits `[15:0]`. Input bits `[31:16]`
are ignored; the host normally writes zero, and verification also supplies
nonzero padding. Output bits `[31:16]` are always zero, including for negative
samples. Input and output TKEEP and TSTRB are all ones. There are no TUSER, TID,
or TDEST fields. Samples have zero fractional bits and range from -32768 to
32767. Their comparison is signed; their transmission preserves the low
16-bit representation exactly.

Every command uses the following fixed four-beat header. TLAST must be zero on
the first three beats and one on the fourth beat, including for END.

| Header beat | Contents |
| --- | --- |
| 0 | Complete unsigned 32-bit `tx_id` |
| 1 | Complete unsigned 32-bit opcode: END = 0, COMPUTE = 1 |
| 2 | Unsigned 16-bit H in `[15:0]`; unsigned 16-bit W in `[31:16]` |
| 3 | Complete unsigned 32-bit K |

COMPUTE is followed by exactly `H*W` payload beats in row-major order, with
TLAST asserted only on the last beat. A successful response consists of a
two-beat response-header burst followed by a separate result-data burst:

| Response-header beat | Contents | TLAST |
| --- | --- | --- |
| 0 | Echoed complete unsigned 32-bit `tx_id` | 0 |
| 1 | Unsigned output height `H/K` in `[15:0]`; unsigned output width `W/K` in `[31:16]` | 1 |

The result burst contains exactly `(H/K)*(W/K)` beats, in row-major order, with
TLAST on its final beat. A single-sample result is a single beat with TLAST.
END has no payload, produces no response, and returns normally. It ignores
H, W, and K but still validates every header framing bit.

This packing gives a largest image of 4096 input payload beats and a largest
result of 1024 payload beats. The performance activation has 4104 input beats:
four COMPUTE-header beats, 4096 samples, and four END-header beats. It produces
1026 output beats: two response-header beats and 1024 result beats. Padding
bits add no samples, and there are no unused sample lanes or partially filled
payload beats. Wire storage is 32 bits per sample; the complete-image buffer
stores only the signed 16-bit values.

The unsigned parameter fields represent every required invalid test class:
H and W can encode 0, 1, 65, and 65535; K can encode unsupported small values,
values exceeding either dimension, and values as large as `0xffffffff`.
The host encoder rejects values outside each field's representable range
instead of truncating them. Negative parameters are outside this unsigned
wire encoding and are rejected by that encoder. The kernel checks the full
encoded opcode and K, so values such as opcode `0x10001` or K `0x10002` do not
become valid by losing their high bits. These choices are shared by
[maxpool_model.py](./maxpool_model.py),
[verify_python.py](./verify_python.py),
[maxpool_body_impl.tpp](./maxpool_body_impl.tpp), and the vectors read by
[maxpool_tb.cpp](./maxpool_tb.cpp).

AXI-Lite is used only for activation control and status, through the generated
`control` bundle. The control interface exposes start/completion and the
read-only status outputs `halted` (one bit), `error` (32 bits), and
`error_tx_id` (32 bits). No computation parameter is carried by AXI-Lite.
Each activation clears all status outputs before processing commands; normal
END leaves them zero. An error sets `halted=1` and records the offending
command's complete `tx_id`.

The synthesized AXI-Lite data-register offsets are control `0x00`, `halted`
`0x10`, `error` `0x20`, and `error_tx_id` `0x30`. Control bit 0 starts the
activation; bit 1 reports completion. The status data registers are read-only;
their associated valid flags are at `0x14`, `0x24`, and `0x34`. These offsets
come from the retained synthesized
[control module](./evidence/cosim_002/hls/sim/verilog/maxpool_control_s_axi.v).

| Error code | Meaning | Detection and consumption boundary |
| --- | --- | --- |
| 0 | No error | Normal END |
| 1 | Header framing | Stop on the early TLAST beat or final header beat lacking TLAST |
| 2 | Unknown command | After the complete, correctly framed header |
| 3 | Invalid parameters | After the header, before reading any payload |
| 4 | Early payload TLAST | Stop on the offending payload beat |
| 5 | Missing payload TLAST | Stop on the final expected payload beat |

Checks follow that table's precedence: header framing, opcode, COMPUTE
parameters, then payload framing while reading. The complete transaction ID
is available even if the very first header beat asserts TLAST. The kernel
does not drain input after an error or seek a later TLAST. Input AXIS register
mode is explicitly off to avoid a boundary register prefetching queued input.
After an error, the host must reset the stream path; every recovery test uses
fresh streams. A sender that supplies no next beat is a stall. There is no
timeout watchdog and no error response burst.

# Design

[maxpool_hw.py](./maxpool_hw.py) declares the Waveflow `HostActivated`
streaming boundary and status register map. Waveflow's `HlsCodegenStep`
generates the top-level wrapper and `StreamUtilsStep` supplies the course
AXI-stream helpers. This follows the `stream_inband` reference's external
C++ body pattern. The generated wrapper calls the handwritten implementation
in [maxpool_body_impl.tpp](./maxpool_body_impl.tpp). The build applies the
documented input register-mode setting to the generated wrapper without
changing the command protocol.

Each valid COMPUTE fills an `ap_int<16> image[64][64]` buffer. Its logical
capacity is `64*64*2 = 8192` bytes; this is the stored image size, not a measured
BRAM resource count. Cyclic partitioning by four along both dimensions gives
sixteen memory banks for parallel access to a pooling window. The input loop
checks TLAST at every read and validates the final input beat before emitting
any response. Therefore malformed COMPUTE payloads produce neither a
response header nor a partial result. Responses emitted for earlier valid
commands remain complete and TLAST-terminated.

For each output position, the implementation reads the relevant window,
uses signed 16-bit maximum comparisons, and writes the maximum's exact bit
pattern into the low half of an output word. The reduction covers a 4-by-4
window; for K=2, unused comparison positions are set to -32768. No addition,
rounding, saturation, or lossy type conversion changes a sample. The output
positions advance in row-major order with stride K.

No configuration or computational state is intentionally retained across
commands or activations. Every valid image location needed for a result is
overwritten before it is read, and statuses are initialized on every
activation. [maxpool_model.py](./maxpool_model.py) implements the same contract
with ordinary signed scalar loops and explicitly tracks consumed and queued
beats. It contains no timing model.

The final kernel writes the entry status clears through volatile aliases to
the output references. This makes those writes externally observable before
the first stream read. An earlier version used ordinary reference assignments;
HLS delayed the observable status updates until completion, which the initial
completion-only tests did not expose. The strengthened RTL entry test observed
stale error status after starting recovery. The final correction preserves the
entry writes without changing the arithmetic or protocol; its failing baseline
and successful retest are retained in
[rtl_stream_002](./evidence/rtl_stream_002/rtl_checks.json) and
[rtl_stream_003](./evidence/rtl_stream_003/rtl_checks.json).

# Targets

The configured FPGA is `xc7z020clg484-1` and the requested clock period is
10 ns, using the reference's default without an override. The inspected
reference settings are retained in
[reference_config.txt](./evidence/reference_config.txt); final synthesis
records the actual settings in
[maxpool_csynth.xml](./evidence/synth_002/hls/syn/report/maxpool_csynth.xml)
and the retained [Tcl configuration](./evidence/synth_002/sources/run.tcl).

| Item | Requirement | Measured result and status | Evidence |
| --- | --- | --- | --- |
| Synthesis estimated clock | Strictly less than 10 ns | PASS: 9.258 ns | [maxpool_csynth.xml](./evidence/synth_002/hls/syn/report/maxpool_csynth.xml), [maxpool_csynth.rpt](./evidence/synth_002/hls/syn/report/maxpool_csynth.rpt); threshold: [prompt.md](./prompt.md) |
| Application latency | At most 20,000 cycles for COMPUTE H=64, W=64, K=2 followed by END | PASS: 5162 cycles, individual transaction 0 | [result.transaction.rpt](./evidence/cosim_002/hls/sim/report/verilog/result.transaction.rpt), [cosim_trace_checks.json](./evidence/cosim_trace_checks.json); threshold: [prompt.md](./prompt.md) |
| Effective input throughput | Report scalar input samples per clock | `4096 / 5162 = 0.7934908950019373` samples/cycle | Numerator: [scenarios.json](./data/scenarios.json); measured denominator: [result.transaction.rpt](./evidence/cosim_002/hls/sim/report/verilog/result.transaction.rpt); calculation: [cosim_trace_checks.json](./evidence/cosim_trace_checks.json) |
| LUT, FF, DSP, BRAM | Report measured use; no numerical resource limits | LUT 5373; FF 1555; DSP 2; BRAM_18K 16 | [maxpool_csynth.xml](./evidence/synth_002/hls/syn/report/maxpool_csynth.xml), [maxpool_csynth.rpt](./evidence/synth_002/hls/syn/report/maxpool_csynth.rpt) |

Achieved loop initiation intervals are taken directly from the final
`synth_002` loop-detail rows, corroborated by each XML `PipelineII` field:

| Loop name | Pipelined | Achieved II (cycles) | Reported target II | Evidence |
| --- | --- | --- | --- | --- |
| `read_header` | yes | 1 | N/A | [loop RPT](./evidence/synth_002/hls/syn/report/maxpool_Pipeline_read_header_csynth.rpt), [loop XML](./evidence/synth_002/hls/syn/report/maxpool_Pipeline_read_header_csynth.xml) |
| `buffer_image` | yes | 1 | 1 | [loop RPT](./evidence/synth_002/hls/syn/report/maxpool_Pipeline_buffer_image_csynth.rpt), [loop XML](./evidence/synth_002/hls/syn/report/maxpool_Pipeline_buffer_image_csynth.xml) |
| `emit_windows` | yes | 1 | 1 | [loop RPT](./evidence/synth_002/hls/syn/report/maxpool_Pipeline_emit_windows_csynth.rpt), [loop XML](./evidence/synth_002/hls/syn/report/maxpool_Pipeline_emit_windows_csynth.xml) |
| Outer command loop `VITIS_LOOP_46_1` | no | No numeric II reported (`-`) | `-` | [top-level loop RPT](./evidence/synth_002/hls/syn/report/maxpool_csynth.rpt), [top-level XML](./evidence/synth_002/hls/syn/report/maxpool_csynth.xml) |

These are achieved loop IIs, not effective application throughput or the
top-level transaction interval. In particular, the `read_header` helper's
module summary reports pipeline type `no`, while its loop-detail row explicitly
reports `read_header` as pipelined with achieved II 1; the table uses the
loop-detail result, not the helper's module interval. See its
[synthesis report](./evidence/synth_002/hls/syn/report/maxpool_Pipeline_read_header_csynth.rpt).
No loop-II value is inferred for the unpipelined outer command loop.

The reported latency is the vendor simulator's top-level transaction latency
for `performance_64x64_k2`, index 0, in the single final `cosim_002` run. It
includes both command headers, the complete image, the response/result, and
END processing. Its report entry is latency 5162 and interval 5176; the
interval is not substituted for latency, and no aggregate extremum is used.
See [result.transaction.rpt](./evidence/cosim_002/hls/sim/report/verilog/result.transaction.rpt)
and the transaction mapping in [scenarios.json](./data/scenarios.json).

The independent VCD audit samples port values immediately before each rising
clock edge, grouping all updates at a timestamp before advancing the stored
state. Start is the sampled rise of `ap_start` while inactive; completion is
sampled `ap_done`. The performance start is at 165000 ps and completion at
51765000 ps, separated by 5160 clock intervals or 5161 inclusive sampled
edges. The vendor convention adds 2 cycles relative to those intervals, and
that offset is consistent across all 99 transactions. The required measured
value remains the vendor's 5162 cycles. This observed convention, exact
timestamps, and correlation are retained in
[cosim_trace_checks.json](./evidence/cosim_trace_checks.json) and
[cosim.vcd](./evidence/trace_003/cosim.vcd).

The performance waveform has zero input-valid gaps before or after its first
offer through the final accepted input beat, zero input starvation, and zero
output-ready-low cycles throughout the activation. Thus the required
continuously-available input and always-ready output conditions are met;
the measured throughput uses the stated 4096 scalar input samples and full
activation latency. These conditions and counts are recorded in
[cosim_trace_checks.json](./evidence/cosim_trace_checks.json).

The synthesis report uses a 2.70 ns uncertainty margin with the configured
10.00 ns clock. The 9.258 ns estimate exceeds the resulting 7.30 ns internal
margin budget, so HLS reports a timing violation, while the specification's
strictly-less-than-10-ns estimated-clock target is PASS. These are distinct
criteria; this is not a place-and-route timing-closure claim. All clock values
and the timing-violation flag are retained in
[maxpool_csynth.xml](./evidence/synth_002/hls/syn/report/maxpool_csynth.xml) and
[maxpool_csynth.rpt](./evidence/synth_002/hls/syn/report/maxpool_csynth.rpt);
the applicable target is in [prompt.md](./prompt.md). Any measured application
target failure will be reported without redefining its threshold or replacing
hardware measurements with a Python estimate.

# Verification

The independent oracle in [verify_python.py](./verify_python.py) validates
sample ranges before NumPy conversion, reshapes each matrix into independent
pooling windows, and applies `max(axis=(1, 3))`. Its expected headers, payload
words, statuses, and consumption boundaries are constructed independently of
the scalar model's pooling and protocol implementations. Verification compares
complete 32-bit words and TLAST, including zeroed output padding, rather than
only comparing decoded numerical samples.

| Check | Observed result | Evidence |
| --- | --- | --- |
| Hand-computed examples | PASS: both 2 examples match the scalar and independent NumPy implementations; example A yields `[5, 7, -1, 11]`, example B yields `[-7]` | [python_checks.json](./evidence/python_checks.json), [verify_python.py](./verify_python.py) |
| Every legal shape | PASS: 1280 valid `(H,W,K)` combinations checked against NumPy | [python_checks.json](./evidence/python_checks.json) |
| Random independent checks | PASS: 96 additional signed-input comparisons | [python_checks.json](./evidence/python_checks.json) |
| Encoder and reference bounds | PASS: 24 rejection checks; incomplete transmission is classified as a stall | [python_checks.json](./evidence/python_checks.json) |
| Shared Python protocol scenarios | PASS: 99 activations with exact output, TLAST, status, consumed count, and remaining input contents | [python_checks.json](./evidence/python_checks.json), [scenarios.json](./data/scenarios.json) |
| Fresh-stream recovery | PASS: all 43 error activations are immediately followed by successful recoveries; supplemental RTL confirms status clears before their first input without resetting the DUT between activations | [python_checks.json](./evidence/python_checks.json), [tb_csim.json](./evidence/csim_003/tb_csim.json), [rtl_checks.json](./evidence/rtl_stream_003/rtl_checks.json) |
| C simulation against the same independent vectors | PASS: all 99 activations, zero failures; complete output words/TLAST/sidebands, status, and exact unconsumed suffix match | [tb_csim.json](./evidence/csim_003/tb_csim.json), [run_csim.log](./evidence/csim_003/run_csim.log) |
| RTL co-simulation bit-exact checks | PASS: all 99 activations in final single run `cosim_002`, with exact outputs, TLAST, and error/status results | [tb_cosim.json](./evidence/cosim_002/tb_cosim.json), [maxpool_cosim.rpt](./evidence/cosim_002/hls/sim/report/maxpool_cosim.rpt), [cosim_trace_checks.json](./evidence/cosim_trace_checks.json) |
| RTL queued-input non-consumption | PASS: all 44 queued-suffix cases retain the exact suffix; pending TVALID is observed at done and held for at least 17 cycles afterward, with zero extra input acceptances | [rtl_checks.json](./evidence/rtl_stream_003/rtl_checks.json), [cosim_adapter_audit.json](./evidence/cosim_adapter_audit.json) |
| Observable activation-entry status | PASS: all 99 entry-status checks are zero; all 43 recovery activations are checked before their first input while the DUT remains busy, using only one initial DUT reset | [rtl_checks.json](./evidence/rtl_stream_003/rtl_checks.json), [cosim_adapter_audit.json](./evidence/cosim_adapter_audit.json) |

The exhaustive shape and random numerical comparisons above are Python-only
checks. The common C/RTL protocol set is the 99 activations identified in
[scenarios.json](./data/scenarios.json), with Python comparison evidence in
[python_checks.json](./evidence/python_checks.json). The same
[scenarios.txt](./data/scenarios.txt) is read by the C/RTL testbench.

| Required coverage | Named scenarios or groups | Evidence |
| --- | --- | --- |
| Smallest/largest legal inputs, both K values, rectangles | `hand_b_smallest_negative_tied`, `performance_64x64_k2`, `largest_k4`, `rectangular_k2`, `rectangular_k4` | [scenarios.json](./data/scenarios.json), [tb_csim.json](./evidence/csim_003/tb_csim.json) |
| Negative/equal/tied/extreme samples, ignored padding, signed comparisons | `hand_b_smallest_negative_tied`, `all_negative_k4`, `all_equal_minimum`, `all_equal_maximum`, `signed_extremes_poisoned_padding` | [scenarios.json](./data/scenarios.json), [tb_csim.json](./evidence/csim_003/tb_csim.json) |
| Several COMPUTEs with changed fields and transaction IDs | `multiple_compute_changed_every_field` | [scenarios.json](./data/scenarios.json), [tb_csim.json](./evidence/csim_003/tb_csim.json) |
| END ignores invalid COMPUTE fields and leaves later input queued | `end_only_ignored_invalid_fields`, `end_only_leaves_queued_input` | [scenarios.json](./data/scenarios.json), [tb_csim.json](./evidence/csim_003/tb_csim.json) |
| Early header TLAST at every position; absent final header TLAST; END framing | `header_early_*`, `header_missing_final_tlast`, `end_header_*` | [scenarios.json](./data/scenarios.json), [tb_csim.json](./evidence/csim_003/tb_csim.json) |
| Unknown opcodes and preservation of high opcode bits | `unknown_opcode_*` | [scenarios.json](./data/scenarios.json), [tb_csim.json](./evidence/csim_003/tb_csim.json) |
| Every invalid parameter restriction, including overlapping restrictions and high K bits | `invalid_h_*`, `invalid_w_*`, `invalid_k_*` | [scenarios.json](./data/scenarios.json), [tb_csim.json](./evidence/csim_003/tb_csim.json) |
| Early/absent payload TLAST and error precedence | `payload_early_*`, `payload_missing_final_tlast`, `precedence_*` | [scenarios.json](./data/scenarios.json), [tb_csim.json](./evidence/csim_003/tb_csim.json) |
| Earlier complete responses retained, failed COMPUTE emits nothing | `after_success_*` and ordinary error scenarios | [scenarios.json](./data/scenarios.json), [tb_csim.json](./evidence/csim_003/tb_csim.json) |
| Immediate recovery with independent streams and cleared status | `recovery_after_*` | [scenarios.json](./data/scenarios.json), [tb_csim.json](./evidence/csim_003/tb_csim.json) |

For every error, vectors include additional queued beats beyond the exact
detection boundary, including payload after an invalid COMPUTE header and
beats after malformed framing. Python and C simulation compare the complete
remaining suffix, including both data and TLAST. C simulation confirms this
property in [tb_csim.json](./evidence/csim_003/tb_csim.json).

The generated Vitis adapter was inspected rather than assuming that its
host-side stream state proves RTL non-consumption. It serializes only the
C-consumed input prefix and removes that recorded count during post-check;
all 44 queued-suffix cases therefore omit their suffix from the original RTL
stimulus. This limitation is confirmed in
[cosim_adapter_audit.json](./evidence/cosim_adapter_audit.json) and the retained
[adapter source](./evidence/cosim_002/hls/sim/wrapc/apatb_maxpool.cpp).
The primary co-simulation and VCD audit establish exact consumed-prefix and
output behavior; they do not alone establish rejection of offered successors.

The supplemental SystemVerilog testbench in
[rtl_stream_tb.sv](./rtl_stream_tb.sv) drives the unchanged final synthesized
RTL with each complete input queue. It advances its source only on actual
input handshakes, checks each output handshake against the independent
expected word/TLAST/sidebands, and reads status through AXI-Lite. For every
queued-suffix case the next beat remains valid through completion, the status
reads, and ten further clocks. All 44 suffix cases retain their expected
pending word and exact queue position; the minimum observed pending interval
after done is 17 cycles and no extra input handshake occurs. This is PASS
based on [rtl_checks.json](./evidence/rtl_stream_003/rtl_checks.json) and the
summarized evidence in
[cosim_adapter_audit.json](./evidence/cosim_adapter_audit.json).

For the nonperformance activations, that supplemental test withholds the first
input beat, waits eight clocks after writing start, then reads all status
registers and verifies zero status while the accelerator is busy. Only then
does it release the input queue. The performance activation is fed
continuously and is not delayed for this check. The DUT is reset once at the
beginning; fresh source/sink queues, rather than another DUT reset, separate
activations. All 43 immediate recoveries consequently prove observable status
clearing before any new header is accepted. These checks are PASS in
[rtl_checks.json](./evidence/rtl_stream_003/rtl_checks.json); its
`entry_checked_before_first_input` and
`source_withheld_for_entry_check` fields explicitly distinguish the
performance case from the other activations.

Strengthening the entry check exposed a real defect in the earlier kernel:
all 43 recovery entries retained the preceding error status despite
completion-only tests passing. The failing result is preserved in
[rtl_stream_002/rtl_checks.json](./evidence/rtl_stream_002/rtl_checks.json).
Volatile entry-clear writes corrected that behavior, and the final
[rtl_stream_003/rtl_checks.json](./evidence/rtl_stream_003/rtl_checks.json)
records the successful retest. Final C simulation, synthesis, and the entire
co-simulation suite were rerun after that kernel change.

The final primary co-simulation is one run, `cosim_002`, containing all 99
activations in manifest order, with a separate kernel invocation and fresh
streams for each activation. All 43 recoveries immediately follow their
errors, and performance transaction 0 is part of that same run. See
[tb_cosim.json](./evidence/cosim_002/tb_cosim.json),
[run_cosim.log](./evidence/cosim_002/run_cosim.log), and
[result.transaction.rpt](./evidence/cosim_002/hls/sim/report/verilog/result.transaction.rpt).
The supplemental all-scenario run supplies the additional physical queue and
activation-entry evidence; it does not replace that required co-simulation.

The following individual scenario matrix accounts for all 99 recorded
activations, in the manifest's zero-based order. Each scenario name links to
its manifest entry's file; the result links identify the corresponding
`scenarios[index]` record in the Python report and `activations[index]` record
in each C/RTL report. Names and indices agree in all four files.

`PASS*` is the Python outcome derived from the retained report's complete-run
`status: "PASS"` and the indexed scenario record. The Python JSON does not
store a separate per-case pass Boolean. In the hash-matched
[verify_python.py](./verify_python.py), `export_and_check` asserts every
case's exact output, status, consumed count, and remaining input contents
before the report can be written; assertions cannot be disabled for that
reporting path. C-simulation and co-simulation `PASS` values below come
directly from each retained record's `pass: true`. This is a documentation
extraction of recorded outcomes, with no new implementation execution.

The status column is `(halted, error, error_tx_id)` in decimal. Each tuple
matches the C/RTL actual status fields and the Python status values checked
by those assertions. An error row explicitly names its immediately following
fresh-stream recovery, gives all three recovery outcomes, and confirms its
zero status; that recovery also has its own row. All 43 errors have these
successful immediate recoveries. Source hashes, exact JSON record pointers,
and the extracted status/recovery mapping are retained in
[scenario_matrix.json](./evidence/submission_review/scenario_matrix.json).
The co-simulation adapter limitation and supplemental physical queue checks
described above still apply to these co-simulation outcomes.

| Index / scenario | Python model | C simulation | RTL co-simulation | Matched status (Python / C / RTL) | Immediately following fresh recovery |
| --- | --- | --- | --- | --- | --- |
| 0 / [performance_64x64_k2](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 1 / [hand_a](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 2 / [hand_b_smallest_negative_tied](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 3 / [largest_k4](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 4 / [rectangular_k2](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 5 / [rectangular_k4](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 6 / [all_negative_k4](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 7 / [all_equal_minimum](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 8 / [all_equal_maximum](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 9 / [signed_extremes_poisoned_padding](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 10 / [multiple_compute_changed_every_field](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 11 / [end_only_ignored_invalid_fields](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 12 / [end_only_leaves_queued_input](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 13 / [header_early_beat0](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 1, 2415919104)` | 14 / `recovery_after_header_early_beat0`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 14 / [recovery_after_header_early_beat0](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 15 / [header_early_beat1](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 1, 2415919105)` | 16 / `recovery_after_header_early_beat1`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 16 / [recovery_after_header_early_beat1](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 17 / [header_early_beat2](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 1, 2415919106)` | 18 / `recovery_after_header_early_beat2`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 18 / [recovery_after_header_early_beat2](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 19 / [header_missing_final_tlast](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 1, 2415919107)` | 20 / `recovery_after_header_missing_final_tlast`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 20 / [recovery_after_header_missing_final_tlast](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 21 / [end_header_early](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 1, 2415919108)` | 22 / `recovery_after_end_header_early`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 22 / [recovery_after_end_header_early](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 23 / [end_header_missing](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 1, 2415919109)` | 24 / `recovery_after_end_header_missing`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 24 / [recovery_after_end_header_missing](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 25 / [unknown_opcode_2](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 2, 2432696326)` | 26 / `recovery_after_unknown_opcode_2`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 26 / [recovery_after_unknown_opcode_2](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 27 / [unknown_opcode_ffffffff](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 2, 2432696327)` | 28 / `recovery_after_unknown_opcode_ffffffff`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 28 / [recovery_after_unknown_opcode_ffffffff](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 29 / [unknown_opcode_10001](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 2, 2432696328)` | 30 / `recovery_after_unknown_opcode_10001`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 30 / [recovery_after_unknown_opcode_10001](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 31 / [invalid_h_zero](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473536)` | 32 / `recovery_after_invalid_h_zero`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 32 / [recovery_after_invalid_h_zero](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 33 / [invalid_h_one](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473537)` | 34 / `recovery_after_invalid_h_one`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 34 / [recovery_after_invalid_h_one](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 35 / [invalid_h_65](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473538)` | 36 / `recovery_after_invalid_h_65`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 36 / [recovery_after_invalid_h_65](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 37 / [invalid_h_max_u16](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473539)` | 38 / `recovery_after_invalid_h_max_u16`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 38 / [recovery_after_invalid_h_max_u16](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 39 / [invalid_w_zero](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473540)` | 40 / `recovery_after_invalid_w_zero`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 40 / [recovery_after_invalid_w_zero](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 41 / [invalid_w_one](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473541)` | 42 / `recovery_after_invalid_w_one`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 42 / [recovery_after_invalid_w_one](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 43 / [invalid_w_65](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473542)` | 44 / `recovery_after_invalid_w_65`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 44 / [recovery_after_invalid_w_65](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 45 / [invalid_w_max_u16](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473543)` | 46 / `recovery_after_invalid_w_max_u16`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 46 / [recovery_after_invalid_w_max_u16](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 47 / [invalid_k_zero](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473544)` | 48 / `recovery_after_invalid_k_zero`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 48 / [recovery_after_invalid_k_zero](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 49 / [invalid_k_one](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473545)` | 50 / `recovery_after_invalid_k_one`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 50 / [recovery_after_invalid_k_one](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 51 / [invalid_k_three](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473546)` | 52 / `recovery_after_invalid_k_three`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 52 / [recovery_after_invalid_k_three](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 53 / [invalid_k_five](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473547)` | 54 / `recovery_after_invalid_k_five`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 54 / [recovery_after_invalid_k_five](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 55 / [invalid_k_max_u32](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473548)` | 56 / `recovery_after_invalid_k_max_u32`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 56 / [recovery_after_invalid_k_max_u32](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 57 / [invalid_k_large_low_bits_valid](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473549)` | 58 / `recovery_after_invalid_k_large_low_bits_valid`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 58 / [recovery_after_invalid_k_large_low_bits_valid](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 59 / [invalid_k_exceeds_h](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473550)` | 60 / `recovery_after_invalid_k_exceeds_h`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 60 / [recovery_after_invalid_k_exceeds_h](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 61 / [invalid_k_exceeds_w](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473551)` | 62 / `recovery_after_invalid_k_exceeds_w`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 62 / [recovery_after_invalid_k_exceeds_w](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 63 / [invalid_h_not_divisible_k4](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473552)` | 64 / `recovery_after_invalid_h_not_divisible_k4`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 64 / [recovery_after_invalid_h_not_divisible_k4](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 65 / [invalid_w_not_divisible_k4](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473553)` | 66 / `recovery_after_invalid_w_not_divisible_k4`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 66 / [recovery_after_invalid_w_not_divisible_k4](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 67 / [invalid_h_not_divisible_k2](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473554)` | 68 / `recovery_after_invalid_h_not_divisible_k2`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 68 / [recovery_after_invalid_h_not_divisible_k2](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 69 / [invalid_w_not_divisible_k2](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473555)` | 70 / `recovery_after_invalid_w_not_divisible_k2`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 70 / [recovery_after_invalid_w_not_divisible_k2](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 71 / [payload_early_beat0](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 4, 2466250752)` | 72 / `recovery_after_payload_early_beat0`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 72 / [recovery_after_payload_early_beat0](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 73 / [payload_early_beat7](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 4, 2466250759)` | 74 / `recovery_after_payload_early_beat7`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 74 / [recovery_after_payload_early_beat7](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 75 / [payload_early_beat14](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 4, 2466250766)` | 76 / `recovery_after_payload_early_beat14`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 76 / [recovery_after_payload_early_beat14](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 77 / [payload_missing_final_tlast](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 5, 2466250768)` | 78 / `recovery_after_payload_missing_final_tlast`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 78 / [recovery_after_payload_missing_final_tlast](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 79 / [precedence_early_header_over_unknown_invalid](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 1, 2483027968)` | 80 / `recovery_after_precedence_early_header_over_unknown_invalid`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 80 / [recovery_after_precedence_early_header_over_unknown_invalid](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 81 / [precedence_missing_header_over_unknown_invalid](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 1, 2483027969)` | 82 / `recovery_after_precedence_missing_header_over_unknown_invalid`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 82 / [recovery_after_precedence_missing_header_over_unknown_invalid](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 83 / [precedence_unknown_over_invalid](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 2, 2483027970)` | 84 / `recovery_after_precedence_unknown_over_invalid`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 84 / [recovery_after_precedence_unknown_over_invalid](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 85 / [precedence_invalid_over_early_payload](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2483027971)` | 86 / `recovery_after_precedence_invalid_over_early_payload`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 86 / [recovery_after_precedence_invalid_over_early_payload](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 87 / [precedence_early_payload_over_missing_final](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 4, 2483027972)` | 88 / `recovery_after_precedence_early_payload_over_missing_final`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 88 / [recovery_after_precedence_early_payload_over_missing_final](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 89 / [after_success_header_early_beat0](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 1, 2415919104)` | 90 / `recovery_after_after_success_header_early_beat0`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 90 / [recovery_after_after_success_header_early_beat0](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 91 / [after_success_unknown_opcode_2](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 2, 2432696326)` | 92 / `recovery_after_after_success_unknown_opcode_2`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 92 / [recovery_after_after_success_unknown_opcode_2](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 93 / [after_success_invalid_h_zero](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 3, 2449473536)` | 94 / `recovery_after_after_success_invalid_h_zero`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 94 / [recovery_after_after_success_invalid_h_zero](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 95 / [after_success_payload_early_beat0](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 4, 2466250752)` | 96 / `recovery_after_after_success_payload_early_beat0`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 96 / [recovery_after_after_success_payload_early_beat0](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |
| 97 / [after_success_payload_missing_final_tlast](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(1, 5, 2466250768)` | 98 / `recovery_after_after_success_payload_missing_final_tlast`: Python PASS*, C PASS, RTL PASS; `(0, 0, 0)` |
| 98 / [recovery_after_after_success_payload_missing_final_tlast](./data/scenarios.json) | [PASS*](./evidence/python_checks.json) | [PASS](./evidence/csim_003/tb_csim.json) | [PASS](./evidence/cosim_002/tb_cosim.json) | `(0, 0, 0)` | Not an error activation |

# Assumptions

The stream width, field layout, opcode values, error codes, and padding rules
in Interface are settled implementation choices. A single sample per beat
keeps every payload framing boundary identical to a sample boundary and
allows the complete transaction ID to occupy the first header beat. The
unused upper payload half is deliberate wire padding; it does not relax
matrix divisibility or create padding samples.

Supported input transfers use complete 32-bit words with TKEEP and TSTRB
both set to `0xF` (all ones). Other byte-enable patterns are outside the
supported input contract. The kernel ignores upper input sample bits and
uses the low signed sample; all output byte-valid sidebands are set.
This resolves Version 1's delegated stream-width, sample-packing, and
padding-bit choices in [Header and Encoding Requirements](./prompt.md#header-and-encoding-requirements)
and its requirement to document resolved host-protocol assumptions in
[Assumptions](./prompt.md#assumptions). Version 1 does not require partial-byte
input transfers or define a byte-enable error category. No existing sample,
TLAST, error-precedence, or recovery requirement is relaxed. The already
implemented and tested full-word choice is now explicit here; no specification
revision or implementation change is necessary.

The host resets the stream path after an error and begins recovery with fresh
streams. It does not ask the kernel to drain or resynchronize malformed input.
The no-timeout behavior is intentional: lack of a next input beat stalls a
blocking read, whereas missing TLAST is detected when the expected final beat
actually arrives.

Performance reporting uses the RTL simulator's individual top-level
transaction latency, including command/END overhead. Effective throughput is
scalar input samples per cycle, not payload beats per cycle or a loop's
initiation interval. Targets documents the observed vendor-versus-waveform
counting convention and the retained ready/available evidence. The supplemental
entry-status check deliberately delays nonperformance inputs; those delayed
activations are not used for throughput or latency reporting. No functional
Python result is used as a timing prediction.

The accepted specification's introductory note about the unavailable official
Part 3 template is preserved. This implementation does not silently rewrite
the accepted document or treat integration fixes as changes to its contract.

# Open Items

None remain for the specified Part 4 implementation and validation. The
original co-simulation adapter's queued-input limitation is resolved by the
supplemental RTL evidence, and the activation-entry status defect was corrected
and revalidated. No consequential protocol, output, error, or measurement
decision is deferred.

The clock and resource figures are HLS synthesis estimates; physical
place-and-route timing closure was not requested and is not claimed. The
accepted document's historical Part 3 template note remains unchanged.
Failed integration and verification attempts remain available below rather
than being removed from the evidence.

# Run History

The approved diagnostics established access to the existing course Python
environment and Waveflow checkout and verified the accepted specification's
committed and pushed state; see
[environment_checks.txt](./evidence/environment_checks.txt). No packages were
installed, no specification edit or Git commit/push was made, and the sandbox
configuration was not changed by those diagnostics.

| Actual run | Prompt version | Configuration and observed outcome | Evidence |
| --- | --- | --- | --- |
| Python verification | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Existing course Python and NumPy; hand examples, exhaustive shapes, random checks, and all shared protocol scenarios passed | [python_checks.json](./evidence/python_checks.json) |
| `generate_001` | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Failed before kernel generation: `BuildDag.run` returned a dictionary, while the runner expected a single object's `.success` | [run_generate.log](./evidence/generate_001/run_generate.log), [run.json](./evidence/generate_001/run.json) |
| `generate_002` | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Stream helper generation succeeded; kernel generation rejected `cpp_body='body'` because the component lacked the required Python `body` hook | [run_generate.log](./evidence/generate_002/run_generate.log), [run.json](./evidence/generate_002/run.json) |
| `generate_003` | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Waveflow stream helpers and HLS boundary generated successfully; input register mode set to off; runner exit status zero | [run_generate.log](./evidence/generate_003/run_generate.log), [run.json](./evidence/generate_003/run.json) |
| `csim_001` | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Vitis was not launched: Waveflow installation-path discovery failed before tool execution | [run_csim.log](./evidence/csim_001/run_csim.log), [run.json](./evidence/csim_001/run.json) |
| `csim_002` | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Existing Vitis 2026.1 discovered from host PATH; original kernel passed all 99 completion/output/leftover checks. This run did not observe status during activation entry | [run_csim.log](./evidence/csim_002/run_csim.log), [tb_csim.json](./evidence/csim_002/tb_csim.json) |
| `synth_001` | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Original kernel synthesized: estimated clock 9.258 ns, LUT 5331, FF 1555, DSP 2, BRAM_18K 16; documented uncertainty-margin warning | [run_synth.log](./evidence/synth_001/run_synth.log), [maxpool_csynth.xml](./evidence/synth_001/hls/syn/report/maxpool_csynth.xml) |
| `cosim_001` | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Original kernel passed the single 99-activation co-simulation, with transaction 0 latency 5162 cycles. These completion checks did not establish observable entry clearing | [tb_cosim.json](./evidence/cosim_001/tb_cosim.json), [run_cosim.log](./evidence/cosim_001/run_cosim.log), [result.transaction.rpt](./evidence/cosim_001/hls/sim/report/verilog/result.transaction.rpt) |
| `trace_001` | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Broad wildcard VCD logging raised `ERROR: unexpected exception when evaluating tcl command` despite process exit 0. The initial-values-only VCD was rejected as evidence | [xsim.log](./evidence/trace_001/xsim.log), [run.json](./evidence/trace_001/run.json) |
| `trace_002` and first audit | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Explicit signal export successfully replayed the original snapshot. The first parser audit failed because its start predicate found no activations and it omitted the final transaction whose interval is `x`; these were audit defects, not RTL output failures | [xsim.log](./evidence/trace_002/xsim.log), [audit_attempt_001.json](./evidence/trace_002/audit_attempt_001.json) |
| Corrected `trace_002` audit | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | With sampled `ap_start` rise detection and support for a final unavailable interval, all 99 waveform transactions matched and correlated with their individual vendor latencies | [audit_final.json](./evidence/trace_002/audit_final.json) |
| `rtl_stream_001` | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Supplemental full-queue RTL run passed all 99 activations and queued-suffix checks. Its entry observation was not yet strong enough to establish clearing before input | [rtl_checks.json](./evidence/rtl_stream_001/rtl_checks.json), [run_rtl_stream.log](./evidence/rtl_stream_001/run_rtl_stream.log) |
| `rtl_stream_002` | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Strengthened pre-input status reads exposed 43 recovery-entry failures in the original kernel; final numerical outputs and completed status alone had hidden this defect | [rtl_checks.json](./evidence/rtl_stream_002/rtl_checks.json), [run_rtl_stream.log](./evidence/rtl_stream_002/run_rtl_stream.log) |
| `csim_003` | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Corrected kernel with volatile entry-clear writes passed all 99 C-simulation activations | [tb_csim.json](./evidence/csim_003/tb_csim.json), [run_csim.log](./evidence/csim_003/run_csim.log) |
| `synth_002` | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Final corrected kernel synthesized; measured clock/resources are the values reported in Targets | [run_synth.log](./evidence/synth_002/run_synth.log), [maxpool_csynth.xml](./evidence/synth_002/hls/syn/report/maxpool_csynth.xml) |
| `cosim_002` | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Final corrected kernel passed all 99 activations in one co-simulation run; individual performance transaction latency is 5162 cycles | [tb_cosim.json](./evidence/cosim_002/tb_cosim.json), [run_cosim.log](./evidence/cosim_002/run_cosim.log), [result.transaction.rpt](./evidence/cosim_002/hls/sim/report/verilog/result.transaction.rpt) |
| `rtl_stream_003` | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Final full-queue and entry-status RTL verification passed all 99 activations, including 43 recoveries before first input and 44 queued-suffix cases, without resetting the DUT between activations | [rtl_checks.json](./evidence/rtl_stream_003/rtl_checks.json), [run_rtl_stream.log](./evidence/rtl_stream_003/run_rtl_stream.log), [run.json](./evidence/rtl_stream_003/run.json) |
| `trace_003` and final audit | V1 (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Replayed the unchanged final `cosim_002` snapshot; all 99 waveform comparisons passed. Performance source/sink conditions and the vendor counting offset were verified | [run.json](./evidence/trace_003/run.json), [xsim.log](./evidence/trace_003/xsim.log), [cosim_trace_checks.json](./evidence/cosim_trace_checks.json), [cosim.vcd](./evidence/trace_003/cosim.vcd) |
| Final submission documentation review | V1 unchanged (`e07d94b069719939eaa5ea4b364461b8fec6f941`) | Read retained final loop reports; added achieved II, all 99 individual scenario rows, prompt-version attribution, and explicit delegated byte-enable contract. No implementation change, synthesis, co-simulation, or functional rerun. | [submission_audit.json](./evidence/submission_review/submission_audit.json), [scenario_matrix.json](./evidence/submission_review/scenario_matrix.json) |

Revision history for implementation changes motivated by actual runs:

| Revision | Observed run and reason | Change | Supporting evidence |
| --- | --- | --- | --- |
| Integration 1 | `generate_001` raised `AttributeError` while interpreting build results | Iterate over the returned result mapping and validate each build step | [run_generate.log](./evidence/generate_001/run_generate.log), [subsequent source snapshot](./evidence/generate_002/sources/maxpool_build.py) |
| Integration 2 | `generate_002` raised `SynthesisError` for a missing Python body hook | Declare the component's Python body hook for external C++ body generation; functional verification remains in the independent scalar model | [run_generate.log](./evidence/generate_002/run_generate.log), [subsequent source snapshot](./evidence/generate_003/sources/maxpool_hw.py) |
| Integration 3 | `csim_001` could not locate Vitis before executing it | Discover existing tool installations from host PATH and set process-local Waveflow installation paths | [run_csim.log](./evidence/csim_001/run_csim.log), [successful subsequent run](./evidence/csim_002/run_csim.log) |
| Evidence export | `trace_001` raised a simulator exception for wildcard logging and produced no time-progress evidence | Export the explicit top-level clock/control and stream signal list; retain both the failed attempt and subsequent complete trace | [failed export](./evidence/trace_001/xsim.log), [corrected export script](./evidence/trace_002/maxpool_vcd.tcl), [successful replay](./evidence/trace_002/xsim.log) |
| Trace audit | First `trace_002` audit detected no activations and parsed only 98 vendor records | Detect sampled `ap_start` rises because `ap_idle` deasserts combinatorially on start; accept final interval `x` while still requiring numeric latency. Preserve every word/TLAST comparison | [failed audit](./evidence/trace_002/audit_attempt_001.json), [corrected audit](./evidence/trace_002/audit_final.json), [audit_cosim_trace.py](./audit_cosim_trace.py) |
| Verification scope | Adapter inspection showed that the co-simulator omits all queued suffixes; initial supplemental entry observation did not prove pre-input clearing | Add full-queue RTL driving, then withhold nonperformance input while checking AXI-Lite status after start; preserve the performance feed conditions | [adapter audit](./evidence/cosim_adapter_audit.json), [initial supplemental evidence](./evidence/rtl_stream_001/rtl_checks.json), [strengthened test snapshot](./evidence/rtl_stream_002/sources/rtl_stream_tb.sv) |
| Kernel correctness | `rtl_stream_002` observed stale prior error status at all 43 recovery entries before accepting any new input | Make the three initial clear writes observable through volatile output-reference aliases; rerun C simulation, synthesis, co-simulation, and supplemental RTL verification | [failing baseline](./evidence/rtl_stream_002/rtl_checks.json), [final kernel snapshot](./evidence/cosim_002/sources/maxpool_body_impl.tpp), [successful entry/queue retest](./evidence/rtl_stream_003/rtl_checks.json) |

The Version 1 history in [prompt.md](./prompt.md) concerns the supplied
requirements and actual Part 3 feedback. It is not an implementation run, and
it is not rewritten by the integration revision history above. Every HLS
attempt preserves its source hashes, tool configuration, logs, and available
reports in its own evidence directory.

Reproduction uses the existing course environment from the workspace:

```bash
cd /home/js12359/hwdesign-work/cmdresp/takehome
COURSE_PY=/home/js12359/hwdesign-work/.venv/bin/python
"$COURSE_PY" -B verify_python.py
"$COURSE_PY" -B maxpool_build.py --stage generate
"$COURSE_PY" -B maxpool_build.py --stage csim
"$COURSE_PY" -B maxpool_build.py --stage synth
"$COURSE_PY" -B maxpool_build.py --stage cosim
"$COURSE_PY" -B verify_rtl_stream.py
"$COURSE_PY" -B audit_cosim_trace.py evidence/trace_003/cosim.vcd \
  --transactions evidence/cosim_002/hls/sim/report/verilog/result.transaction.rpt \
  --output evidence/cosim_trace_checks.json
```

The build and supplemental RTL runners allocate new numbered attempt
directories; repeating those commands therefore creates later run numbers.
The last command re-audits the retained final waveform against its matching
retained vendor report. To export a newly generated co-simulation snapshot,
use [export_cosim_trace.py](./export_cosim_trace.py) with that run's actual
directory name. For example, the following command was used for the final
retained co-simulation; use a later run number after rebuilding:

```bash
"$COURSE_PY" -B export_cosim_trace.py --cosim-run cosim_002
```

The exporter prints and preserves a new numbered trace directory. Keep that
waveform and its matching individual transaction report together, then pass
their paths explicitly to
[audit_cosim_trace.py](./audit_cosim_trace.py). Inspect the simulator log for
errors and require advancing trace timestamps; a process exit of zero alone
was insufficient in the failed export recorded above. Host-side tool execution
uses the supported approval mechanism when the existing sandbox requires it.
