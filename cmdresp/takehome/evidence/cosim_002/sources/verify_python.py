#!/usr/bin/env python3
"""Independent NumPy oracle, protocol cases, and common C/RTL test vectors.

Run from any directory. Outputs are rooted beside this script. This script
performs functional checks only; it does not estimate hardware timing.
"""

import hashlib
import json
from pathlib import Path
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

import maxpool_model as model


ROOT = Path(__file__).resolve().parent
SEED = 0x4D415850
Beat = model.Beat


@dataclass
class Scenario:
    name: str
    input: list[Beat]
    output: list[Beat]
    consumed: int
    halted: int = 0
    error: int = 0
    error_tx_id: int = 0
    coverage: tuple[str, ...] = ()


def checked_array(values, h, w):
    # Validate before dtype conversion so out-of-range samples cannot wrap.
    flat = list(values)
    if len(flat) != h * w:
        raise ValueError("independent reference: wrong sample count")
    if any(not isinstance(v, (int, np.integer)) or isinstance(v, bool)
           or not -32768 <= int(v) <= 32767 for v in flat):
        raise ValueError("independent reference: invalid signed 16-bit sample")
    return np.array(flat, dtype=np.int16).reshape(h, w)


def numpy_pool(values, h, w, k):
    array = checked_array(values, h, w)
    return array.reshape(h // k, k, w // k, k).max(axis=(1, 3)).ravel().tolist()


def header(tx, op, h, w, k):
    # Oracle wire construction intentionally does not call the model encoder.
    return [Beat(tx), Beat(op), Beat(h + 65536 * w), Beat(k, True)]


def payload(values, padding=0):
    return [Beat((int(v) % 65536) + 65536 * padding, i == len(values) - 1)
            for i, v in enumerate(values)]


def compute(tx, h, w, k, values, padding=0):
    expected = numpy_pool(values, h, w, k)
    inputs = header(tx, 1, h, w, k) + payload(values, padding)
    outputs = [Beat(tx), Beat(h // k + 65536 * (w // k), True)] + payload(expected)
    return inputs, outputs


def end(tx=0, h=0, w=0, k=0):
    return header(tx, 0, h, w, k)


def replace_last(beats, index, last):
    result = list(beats)
    result[index] = Beat(result[index].data, last)
    return result


def pattern(h, w, salt=0):
    return [((r * 503 + c * 1877 + salt * 32749) % 65536) - 32768
            for r in range(h) for c in range(w)]


def make_scenarios():
    scenarios = []

    def success(name, commands, coverage=(), tail=()):
        inputs, outputs = [], []
        for tx, h, w, k, values, padding in commands:
            command_input, command_output = compute(tx, h, w, k, values, padding)
            inputs.extend(command_input)
            outputs.extend(command_output)
        inputs.extend(end())
        consumed = len(inputs)
        inputs.extend(tail)
        scenarios.append(Scenario(name, inputs, outputs, consumed, coverage=coverage))

    # Index zero remains stable: this is the specified performance activation.
    success("performance_64x64_k2", [(0x80000001, 64, 64, 2, pattern(64, 64), 0)],
            ("performance", "largest", "K2", "signed_extremes", "high_tx_id"))
    a = [1, 5, 2, 4, 3, 0, 7, 6, -1, -2, 8, 9, -3, -4, 10, 11]
    b = [-32768, -7, -7, -8]
    success("hand_a", [(1, 4, 4, 2, a, 0)], ("hand_a", "row_major"))
    success("hand_b_smallest_negative_tied", [(0xFFFFFFFF, 2, 2, 2, b, 0)],
            ("hand_b", "smallest", "negative", "repeated_max", "minimum_sample"))
    success("largest_k4", [(3, 64, 64, 4, pattern(64, 64, 3), 0)], ("largest", "K4"))
    success("rectangular_k2", [(4, 6, 10, 2, pattern(6, 10, 1), 0)], ("rectangular", "K2"))
    success("rectangular_k4", [(5, 4, 12, 4, pattern(4, 12, 2), 0)], ("rectangular", "K4"))
    success("all_negative_k4", [(6, 8, 4, 4, [-1000 + i for i in range(32)], 0)],
            ("negative", "rectangular", "K4"))
    success("all_equal_minimum", [(7, 4, 8, 2, [-32768] * 32, 0)],
            ("all_equal", "minimum_sample", "repeated_max"))
    success("all_equal_maximum", [(8, 4, 4, 4, [32767] * 16, 0)],
            ("all_equal", "maximum_sample", "repeated_max"))
    extremes = [-32768, 32767, 32767, -1, 0, -32768, -2, 32767] * 2
    success("signed_extremes_poisoned_padding", [(0, 4, 4, 2, extremes, 0xA55A)],
            ("signed_extremes", "input_padding_ignored", "zero_tx_id"))
    success("multiple_compute_changed_every_field", [
        (0x12345678, 4, 4, 2, a, 0),
        (0xFEDCBA98, 8, 12, 4, pattern(8, 12, 7), 0xFFFF),
        (0x80000000, 2, 2, 2, b, 0)],
        ("multiple_compute", "state_isolation", "row_major", "high_tx_id"))
    sentinel = [Beat(0xCAFE1234), Beat(0xDEAD5678, True)] + end(0xABCD0001)
    scenarios.append(Scenario("end_only_ignored_invalid_fields", end(0xFFFFFFFF, 0, 65535, 0xFFFFFFFF),
                              [], 4, coverage=("end_only", "ignored_parameters", "zero_status")))
    scenarios.append(Scenario("end_only_leaves_queued_input", end() + sentinel,
                              [], 4, coverage=("end_only", "nonconsumption")))

    error_cases = []

    def error(name, inputs, consumed, code, tx, coverage=()):
        error_cases.append(Scenario(name, inputs, [], consumed, 1, code, tx,
                                    ("error", "nonconsumption") + tuple(coverage)))

    for beat in range(3):
        tx = 0x90000000 + beat
        error(f"header_early_beat{beat}", replace_last(header(tx, 1, 4, 4, 2), beat, True) + sentinel,
              beat + 1, 1, tx, ("header_early", "error_tx_id"))
    tx = 0x90000003
    error("header_missing_final_tlast", replace_last(header(tx, 1, 4, 4, 2), 3, False) + sentinel,
          4, 1, tx, ("header_missing",))
    error("end_header_early", replace_last(end(0x90000004), 1, True) + sentinel,
          2, 1, 0x90000004, ("end_framing",))
    error("end_header_missing", replace_last(end(0x90000005), 3, False) + sentinel,
          4, 1, 0x90000005, ("end_framing",))
    for opcode in (2, 0xFFFFFFFF, 0x10001):
        tx = 0x91000000 + len(error_cases)
        error(f"unknown_opcode_{opcode:x}", header(tx, opcode, 4, 4, 2) + sentinel,
              4, 2, tx, ("unknown", "no_opcode_truncation"))

    invalid = [
        ("h_zero", 0, 4, 2), ("h_one", 1, 4, 2), ("h_65", 65, 4, 2), ("h_max_u16", 65535, 4, 2),
        ("w_zero", 4, 0, 2), ("w_one", 4, 1, 2), ("w_65", 4, 65, 2), ("w_max_u16", 4, 65535, 2),
        ("k_zero", 4, 4, 0), ("k_one", 4, 4, 1), ("k_three", 6, 6, 3), ("k_five", 10, 10, 5),
        ("k_max_u32", 4, 4, 0xFFFFFFFF), ("k_large_low_bits_valid", 4, 4, 0x10002),
        ("k_exceeds_h", 2, 4, 4), ("k_exceeds_w", 4, 2, 4),
        ("h_not_divisible_k4", 6, 8, 4), ("w_not_divisible_k4", 8, 6, 4),
        ("h_not_divisible_k2", 3, 4, 2), ("w_not_divisible_k2", 4, 3, 2),
    ]
    queued_payload = payload([123, -456, 789, -32768]) + sentinel
    for index, (name, h, w, k) in enumerate(invalid):
        tx = 0x92000000 + index
        error("invalid_" + name, header(tx, 1, h, w, k) + queued_payload,
              4, 3, tx, ("invalid_parameters", name, "payload_unread"))

    for early in (0, 7, 14):
        tx = 0x93000000 + early
        data = replace_last(payload(a), early, True)
        error(f"payload_early_beat{early}", header(tx, 1, 4, 4, 2) + data + sentinel,
              4 + early + 1, 4, tx, ("payload_early", "no_failed_response"))
    tx = 0x93000010
    error("payload_missing_final_tlast", header(tx, 1, 4, 4, 2)
          + replace_last(payload(a), 15, False) + sentinel,
          20, 5, tx, ("payload_missing", "no_failed_response"))

    tx = 0x94000000
    error("precedence_early_header_over_unknown_invalid", replace_last(header(tx, 99, 0, 0, 0), 1, True) + sentinel,
          2, 1, tx, ("precedence",))
    tx += 1
    error("precedence_missing_header_over_unknown_invalid", replace_last(header(tx, 99, 0, 0, 0), 3, False) + sentinel,
          4, 1, tx, ("precedence",))
    tx += 1
    error("precedence_unknown_over_invalid", header(tx, 99, 0, 0, 0) + sentinel,
          4, 2, tx, ("precedence",))
    tx += 1
    error("precedence_invalid_over_early_payload", header(tx, 1, 1, 4, 2)
          + replace_last(payload(a), 0, True) + sentinel,
          4, 3, tx, ("precedence", "payload_unread"))
    tx += 1
    error("precedence_early_payload_over_missing_final", header(tx, 1, 4, 4, 2)
          + replace_last(replace_last(payload(a), 2, True), 15, False) + sentinel,
          7, 4, tx, ("precedence",))

    # Keep complete earlier responses when each category fails later.
    representative = [next(case for case in error_cases if case.error == code) for code in range(1, 6)]
    prefix_input, prefix_output = compute(0xCAFEBABE, 4, 4, 2, a)
    for case in representative:
        error_cases.append(Scenario("after_success_" + case.name,
                                    prefix_input + case.input, prefix_output + case.output,
                                    len(prefix_input) + case.consumed,
                                    case.halted, case.error, case.error_tx_id,
                                    case.coverage + ("earlier_response_complete", "no_failed_response")))

    # Fresh streams and immediate successful recovery after every error activation.
    for index, case in enumerate(error_cases):
        scenarios.append(case)
        h, w, k = (4, 8, 4) if index % 2 else (2, 2, 2)
        success("recovery_after_" + case.name,
                [(0xA0000000 + index, h, w, k, pattern(h, w, index + 11), 0x55AA)],
                ("recovery", "status_clear", "state_isolation"))
    return scenarios


def expect_value_error(callback):
    try:
        callback()
    except ValueError:
        return
    raise AssertionError("encoder/reference unexpectedly accepted an out-of-range value")


def verify_model():
    a = [1, 5, 2, 4, 3, 0, 7, 6, -1, -2, 8, 9, -3, -4, 10, 11]
    b = [-32768, -7, -7, -8]
    assert model.pool_scalar(a, 4, 4, 2) == [5, 7, -1, 11]
    assert numpy_pool(a, 4, 4, 2) == [5, 7, -1, 11]
    assert model.pool_scalar(b, 2, 2, 2) == [-7]
    assert numpy_pool(b, 2, 2, 2) == [-7]
    shape_count = 0
    scalar_count = 0
    for k in (2, 4):
        for h in range(k, 65, k):
            for w in range(k, 65, k):
                values = pattern(h, w, shape_count)
                assert model.pool_scalar(values, h, w, k) == numpy_pool(values, h, w, k), (h, w, k)
                shape_count += 1
                scalar_count += h * w
    rng = np.random.default_rng(SEED)
    random_count = 96
    for _ in range(random_count):
        k = int(rng.choice([2, 4]))
        h = k * int(rng.integers(1, 64 // k + 1))
        w = k * int(rng.integers(1, 64 // k + 1))
        values = rng.integers(-32768, 32768, size=h * w, dtype=np.int32).tolist()
        assert model.pool_scalar(values, h, w, k) == numpy_pool(values, h, w, k)

    bounds_checks = 0
    for field, bad_values in {
        "tx_id": (-1, 1 << 32), "opcode": (-1, 1 << 32),
        "h": (-1, 1 << 16), "w": (-1, 1 << 16), "k": (-1, 1 << 32),
    }.items():
        for value in bad_values:
            args = dict(tx_id=1, opcode=1, h=4, w=4, k=2)
            args[field] = value
            expect_value_error(lambda args=args: model.command_header(**args))
            bounds_checks += 1
    for sample in (-32769, 32768, 65535, -65536, 1.5, True):
        expect_value_error(lambda sample=sample: model.input_payload([sample]))
        expect_value_error(lambda sample=sample: checked_array([sample] * 4, 2, 2))
        bounds_checks += 2
    for padding in (-1, 65536):
        expect_value_error(lambda padding=padding: model.input_payload([0], padding))
        bounds_checks += 1
    assert model.command_header(0xFFFFFFFF, 0xFFFFFFFF, 65535, 65535, 0xFFFFFFFF) == header(
        0xFFFFFFFF, 0xFFFFFFFF, 65535, 65535, 0xFFFFFFFF)
    assert model.input_payload([-32768, -1, 0, 32767], 0xA55A) == payload([-32768, -1, 0, 32767], 0xA55A)

    # A stalled sender is not a missing-TLAST protocol error or a timeout.
    try:
        model.activate(header(77, 1, 2, 2, 2) + [Beat(12)])
    except model.StreamStall:
        pass
    else:
        raise AssertionError("truncated transmission should be a stall")
    return {"hand_examples": 2, "exhaustive_valid_shape_cases": shape_count,
            "exhaustive_shape_input_samples": scalar_count,
            "random_numpy_comparisons": random_count, "random_seed": SEED,
            "encoder_and_reference_rejection_checks": bounds_checks,
            "incomplete_sender_classified_as_stall": True}


def beat_json(beats):
    return [[beat.data, int(beat.last)] for beat in beats]


def export_and_check(scenarios):
    manifest = []
    lines = [str(len(scenarios))]
    for index, case in enumerate(scenarios):
        result = model.activate(case.input)
        assert result.output == tuple(case.output), (index, case.name, "output mismatch")
        assert (result.halted, result.error, result.error_tx_id) == (case.halted, case.error, case.error_tx_id), case.name
        assert result.consumed == case.consumed, (case.name, "consumption mismatch")
        remaining = case.input[case.consumed:]
        assert result.remaining == tuple(remaining), (case.name, "leftover contents mismatch")
        assert result.consumed + len(result.remaining) == len(case.input)
        if case.error:
            assert remaining, (case.name, "missing queued sentinel input")
            assert scenarios[index + 1].name == "recovery_after_" + case.name
            assert scenarios[index + 1].error == 0
        if case.output:
            assert case.output[-1].last, (case.name, "unterminated earlier output")
        lines.append(f"{case.name} {len(case.input)} {len(case.output)} {case.consumed} "
                     f"{case.halted} {case.error} {case.error_tx_id}")
        lines.extend(f"{beat.data:08x} {int(beat.last)}" for beat in case.input)
        lines.extend(f"{beat.data:08x} {int(beat.last)}" for beat in case.output)
        manifest.append({"index": index, "name": case.name, "coverage": list(case.coverage),
                         "input_count": len(case.input), "output_count": len(case.output),
                         "consumed": case.consumed, "remaining_count": len(remaining),
                         "halted": case.halted, "error": case.error, "error_tx_id": case.error_tx_id,
                         "input": beat_json(case.input), "expected_output": beat_json(case.output),
                         "expected_remaining": beat_json(remaining)})
    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    text = "\n".join(lines) + "\n"
    (data / "scenarios.txt").write_text(text)
    (data / "scenarios.json").write_text(json.dumps({
        "format_version": 1, "performance_transaction_index": 0,
        "numeric_convention": "data words are uint32; TLAST is 0 or 1; JSON numbers are decimal",
        "scenario_count": len(scenarios), "scenarios": manifest,
    }, indent=2) + "\n")
    return manifest, hashlib.sha256(text.encode()).hexdigest()


def main():
    if not __debug__:
        raise RuntimeError("Do not run verification with -O: assertions must remain enabled")
    checks = verify_model()
    scenarios = make_scenarios()
    manifest, vector_hash = export_and_check(scenarios)
    checks.update({
        "status": "PASS", "stage": "Python only; C and RTL validation are separate",
        "utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join([sys.executable, "-B", str(Path(__file__).resolve())]),
        "python": platform.python_version(), "python_executable": sys.executable,
        "numpy": np.__version__, "scenario_count": len(scenarios),
        "error_activations": sum(case.error != 0 for case in scenarios),
        "immediate_fresh_stream_recovery_activations": sum("recovery" in case.coverage for case in scenarios),
        "performance_transaction_index": 0, "performance_scenario": scenarios[0].name,
        "bit_exact_model_vs_independent_numpy_protocol_oracle": True,
        "exact_remaining_input_count_and_content": True,
        "normal_end_status_zero": True, "error_precedence": True,
        "failed_compute_no_output_and_earlier_complete_responses": True,
        "vector_file": "data/scenarios.txt", "vector_sha256": vector_hash,
        "scenario_manifest": "data/scenarios.json",
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in ("maxpool_model.py", "verify_python.py", "prompt.md")},
        "scenarios": [{key: row[key] for key in ("index", "name", "input_count", "output_count",
                                                 "consumed", "remaining_count", "halted", "error", "error_tx_id")}
                      for row in manifest],
    })
    evidence = ROOT / "evidence"
    evidence.mkdir(exist_ok=True)
    destination = evidence / "python_checks.json"
    destination.write_text(json.dumps(checks, indent=2) + "\n")
    print(f"PASS independent hand examples: {checks['hand_examples']}")
    print(f"PASS exhaustive valid shapes: {checks['exhaustive_valid_shape_cases']}")
    print(f"PASS independent random cases: {checks['random_numpy_comparisons']}")
    print(f"PASS protocol activations: {len(scenarios)}; errors and immediate recoveries: {checks['error_activations']}")
    print("PASS exact words, TLAST, status, consumed counts, and remaining-input contents")
    print(f"Performance activation: index 0, {scenarios[0].name}")
    print(f"Evidence: {destination}")


if __name__ == "__main__":
    main()
