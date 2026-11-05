# Signed 16-bit 2-D Non-overlapping Max Pool

> Draft status: this Version 1 records the supplied design requirements. The
> official template at `/home/js12359/hwdesign/labs/cmdresp/partial/prompt.md`
> was unavailable when this draft was written. Its exact fixed instructions and
> revision-history format have not yet been checked or incorporated verbatim.

## Implementation requirements

Implement this accelerator by following the Waveflow `stream_inband` reference
example and the course command-response pattern. Use the reference example's
FPGA part and clock configuration. Preserve the course error-handling contract,
including terminating every output burst that has started with TLAST before
returning.

All implementation, Python modeling, C simulation, RTL co-simulation, synthesis,
and `results.md` generation described below are requirements for the subsequent
implementation stage. The current Part 3 task is to save and display this
specification only.

## 1. Operation

The input is an H-by-W matrix X transmitted in row-major order. Each pooling
window is K-by-K, with stride K in both dimensions and no padding. Windows do not
overlap.

The output Y has dimensions (H/K)-by-(W/K) and is transmitted in row-major order.
Define:

```text
Y[r, c] = max { X[r*K + i, c*K + j] : 0 <= i < K, 0 <= j < K }

0 <= r < H/K
0 <= c < W/K
```

Each COMPUTE command processes one independent image. No computational state
carries from one COMPUTE command to another.

## 2. Data Format and Bounds

Each sample is a signed 16-bit two's-complement integer with zero fractional
bits. Its representable range is [-32768, 32767]. All comparisons use signed
integer semantics.

Each output sample copies the exact 16-bit representation of a maximum input
value from its window. No arithmetic rounding, saturation, or overflow occurs.
Equal maximum values produce the same output value.

Valid parameters satisfy all of the following:

- 2 <= H <= 64.
- 2 <= W <= 64.
- K is either 2 or 4.
- K does not exceed H or W.
- Both H and W are divisible by K.

A COMPUTE command that violates any condition is an invalid-parameter error.
Incomplete windows are rejected rather than padded or discarded.

## 3. Commands and Responses

Support two commands: COMPUTE and END.

### COMPUTE

The command header carries the opcode and the fields tx_id, H, W, and K. It is
followed by one input data burst containing exactly H*W samples.

All parameters used in the computation arrive through the input stream.
AXI-Lite is used only for activation control and status.

A successful COMPUTE command produces, in order:

1. One response-header burst that echoes tx_id and identifies the output
   dimensions H/K and W/K.
2. One result-data burst containing exactly (H/K)*(W/K) samples.

The response-header burst and result-data burst each end with TLAST.

### END

END has no data burst and produces no response. It terminates the current
activation normally and ignores header fields used only by COMPUTE. Its header
must still satisfy the command-header framing rules.

An activation containing only END is valid.

### Header and Encoding Requirements

Use a fixed-length command header, with the same number of header beats for
every command. Place the complete tx_id in the first header beat so that an
early header TLAST can still be associated with a transaction.

During implementation, choose and document:

- Numeric opcode values.
- Header field layouts.
- Stream width.
- Sample packing.
- Padding-bit conventions.
- Numeric error-code values.

Keep these choices consistent across the Python model, kernel, and testbench.
Document them under Interface in `results.md`.

During the first implementation run, settle the stream width and sample packing
before implementing the model, kernel, and testbench. Document their effects on
header and payload beat counts, complete-image buffering, padding, and TLAST
placement so the host and kernel use the same protocol.

The parameter encoding must allow the invalid values needed for verification to
be represented. Do not silently truncate an invalid parameter into a valid one.

Derive the expected input payload beat count consistently from H*W and the
chosen sample-packing format. Derive output beat counts consistently from the
output sample count and that format. Document how unused bits or sample lanes
are represented and handled. Wire padding does not add matrix samples or permit
incomplete pooling windows. TLAST marks the final beat of each header or data
burst, rather than each scalar sample when multiple samples share a beat.

## 4. Error Behavior

At the start of every activation, clear halted, the error code, and the error
tx_id. These error-status fields remain zero after normal completion through
END.

On an error:

- Set halted to 1.
- Set the appropriate error code.
- Record the offending command's tx_id.
- Return without reading or draining any additional input.

For each COMPUTE command, buffer and validate the complete input image before
beginning any response for that command. Consequently:

- A failed COMPUTE produces no response header and no result data.
- Responses from earlier successful commands remain valid and complete.
- Before returning, any output burst that has already started must have been
  terminated with TLAST, as required by the course protocol.

Check errors in the following order and use this ordering for error precedence.

### a. Header Framing Error

A header framing error occurs if TLAST is asserted before the final expected
header beat or is not asserted on the final expected header beat.

Stop immediately on the beat where the error is detected. In particular, an
early TLAST must not cause the kernel to read more input to finish the header.
For a missing final header TLAST, do not read another beat to seek TLAST.

### b. Unknown Command

After receiving a complete, correctly framed header, reject any unsupported
opcode.

### c. Invalid Parameters

For COMPUTE, reject any H, W, or K that violates the specified parameter
constraints. Validate all parameters before reading any data beat belonging to
that COMPUTE command.

END ignores the COMPUTE-only parameter fields and does not apply these
parameter checks.

### d. Early Payload TLAST

Report an error if the input data burst asserts TLAST before its final expected
data beat. Determine that beat using H*W and the chosen sample-packing format.
Stop on the beat carrying the early TLAST.

### e. Missing Payload TLAST

Report an error if TLAST is zero on the final expected input data beat. Detect
the error on that beat and return immediately. Do not read further input or wait
for a later TLAST.

### Error Codes, Stalls, and Recovery

Define distinguishable error codes for header framing error, unknown command,
invalid parameters, early payload TLAST, and missing payload TLAST. The no-error
status code is zero.

A missing-TLAST test must supply every expected data beat while leaving TLAST
deasserted on the final expected beat. A sender that stops transmitting
indefinitely is a stream stall. This project does not implement a timeout
watchdog.

After an error, the host is responsible for resetting the stream path before
starting another activation. Recovery tests use fresh streams. No
configuration, error state, or computational state may affect a subsequent
activation.

## 5. Targets

Use the FPGA part and clock configuration from the `stream_inband` reference
example and document the actual configuration used.

### Estimated Clock

The synthesis estimated-clock target is strictly less than 10 ns. A
clock-uncertainty margin warning alone does not constitute failure of this
target.

### Application Latency

For an activation containing exactly the following commands:

1. COMPUTE with H=64, W=64, K=2.
2. END.

the measured RTL co-simulation top-level transaction latency must not exceed
20,000 clock cycles, with input continuously available and output always ready.

Use the simulator's top-level transaction latency for this specific activation
and document its measurement convention. Include the activation's
protocol-processing overhead. Record the measured latency, identify the
corresponding transaction, and cite the evidence file containing it. Do not
substitute aggregate minimum or maximum latency from the entire multi-scenario
test run.

### Effective Input Throughput

Report:

```text
effective_input_throughput = 4096 / measured_activation_latency_in_cycles
```

The unit is scalar input samples per clock cycle. This is not stream beats per
cycle and is not a loop initiation interval. Use the measured latency of the
specific activation above and cite its evidence file.

### Resources and Missed Targets

No numerical resource limits are imposed. Report measured resource usage,
including LUT, FF, DSP, and BRAM usage as reported by the synthesis tools, with
the corresponding evidence files.

If a target is missed, report FAIL honestly and explain the observed limitation.
Do not repeatedly restructure the kernel solely to meet the target. Do not
build a Python timing model.

## 6. Independent Verification

During implementation, create a bit-exact Python model. Check it independently
using hand-computed examples and a separate NumPy reference, for example:

```python
X.reshape(H // K, K, W // K, K).max(axis=(1, 3))
```

Use signed 16-bit sample values. The independent reference must not simply call
the model's pooling implementation.

### Hand-Computed Example A

H=4, W=4, K=2:

```text
X = [
    [ 1,  5,  2,  4],
    [ 3,  0,  7,  6],
    [-1, -2,  8,  9],
    [-3, -4, 10, 11]
]

Expected Y = [
    [ 5,  7],
    [-1, 11]
]
```

### Hand-Computed Example B

H=2, W=2, K=2:

```text
X = [
    [-32768, -7],
    [    -7, -8]
]

Expected Y = [[-7]]
```

### Required Scenarios and Checks

Cover all of the following:

- The smallest legal input, H=2, W=2, K=2.
- The largest legal input, H=64, W=64, including the specified performance
  activation with K=2.
- Rectangular inputs.
- Both K=2 and K=4.
- All-negative inputs.
- All-equal inputs.
- Repeated maximum values.
- The extreme values -32768 and 32767.
- Multiple COMPUTE commands within one activation, changing H, W, K, and tx_id
  between commands.
- An END-only activation, including ignored COMPUTE-only fields that would be
  invalid for COMPUTE.
- Every error category, including both early and missing command-header TLAST.
- Invalid examples for every parameter restriction: H below 2 and above 64; W
  below 2 and above 64; unsupported K; K exceeding H or W; and H or W not
  divisible by K. Some restrictions necessarily overlap; verify that such
  cases report the invalid-parameter category.
- Error precedence when malformed inputs satisfy more than one error condition.
- A successful activation using fresh streams immediately after each error
  activation, checking that error status clears and no prior state affects it.
- Queued input remaining unconsumed after an error, including data following an
  invalid COMPUTE header and input following the offending framing beat.
- No response for a failed COMPUTE, and valid, complete responses for earlier
  successful COMPUTE commands in the same activation.
- Correct header and data TLAST placement.
- Correct output dimensions, output sample counts, and row-major ordering.
- Correct echoed transaction IDs and error transaction IDs.
- Correct halted and error-code values, including zero status on normal END.

Compare the Python model, C simulation, and RTL co-simulation bit for bit.
Check protocol behavior and error status as well as numerical sample values.

Execute all scenarios in one co-simulation test run, calling the kernel
separately for each activation and using fresh streams for every activation.
Include the dedicated latency-target activation in that same test run and
identify its individual top-level transaction in the evidence. Recovery
activations immediately follow their corresponding error activations; no
separate co-simulation run is needed for each scenario.

## 7. Report Requirements

During the implementation stage, create `results.md` with the following seven
required sections, using these exact names.

Every numerical result and every PASS/FAIL statement in Targets and Verification
must identify its source evidence file. Retain those evidence files so they
remain available for committing with the project. Derived values must identify
their measured inputs and source files. Preserve the evidence identifying the
individual performance activation; aggregate co-simulation extrema alone do not
satisfy that requirement.

### Interface

Document the command and response interface, opcodes, header layouts and beat
counts, tx_id placement, stream width, sample packing, padding conventions,
TLAST behavior, AXI-Lite activation and status fields, error-code values,
precedence, and recovery contract. Explain how invalid test parameters remain
representable without truncation.

### Design

Describe the implementation, complete-image buffering and validation before
response emission, signed maximum comparisons, output ordering, and state
isolation. Explain how the design follows the reference example and the course
command-response pattern.

### Targets

Record the FPGA part and clock configuration, measured synthesis estimated
clock, the identified performance activation's top-level RTL co-simulation
latency and measurement convention, effective scalar input throughput, and
measured resource usage. Give an honest PASS or FAIL for each specified target
and explain any missed target. No numerical resource limit is imposed.

### Verification

Describe the independent model checks and scenario coverage. Record bit-exact
Python, C-simulation, and RTL co-simulation comparisons, protocol and error
checks, fresh-stream recovery, and non-consumption of queued input after errors.
Identify the single co-simulation run containing all activations and the
specific activation used for performance reporting.

### Assumptions

Document assumptions and implementation choices needed to interpret the
interface, verification, and measurements. Do not use assumptions to relax this
specification's requirements.

For the final Part 4 report, state the resolved choices and their rationale,
including stream width and sample packing. No consequential decision about
output behavior, error behavior, throughput measurement, or the host protocol
may remain deferred or implicit.

### Open Items

List unresolved issues, limitations, missing evidence, and failures honestly.
If none remain, state that explicitly.

Resolve consequential design and protocol decisions before final Part 4
submission. If any remain unresolved, identify them explicitly and report the
work as incomplete. A measured target failure must still be reported honestly;
it must not be hidden or treated as permission to redefine the target.

### Run History

Record actual implementation and verification runs, their configuration,
outcomes, and evidence locations. Do not invent runs, measurements, or results.

For each revision motivated by an implementation or verification run, identify
the actual run, its observed result, and the evidence supporting the change.
Record what changed and why in the revision-history table. Distinguish Part 3
grader feedback from implementation-run evidence. Version 1 is the initial
specification; do not invent an implementation run for it or prepopulate future
revision rows.

## Revision history

| Version | Date | Changes | Reason |
| --- | --- | --- | --- |
| 1 | 2026-11-04 | Initial design specification from the supplied Part 3 requirements, with a separate Reason column and clarified Part 4 decision and revision-evidence requirements following grader feedback. | Define the accelerator contract and address the actual Part 3 grader feedback. Exact official-template preservation remains unverified because the template was unavailable; no implementation run or measurement is claimed. |
