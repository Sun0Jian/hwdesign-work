#!/usr/bin/env python3
"""Audit retained RTL port waveforms against the shared independent manifest.

The VCD is sampled immediately before each rising clock edge, before applying
any value changes grouped at that timestamp. The HLS transaction report, not a
guessed waveform counting offset, supplies the reported application latency.
The original HLS adapter offers only C-consumed prefixes: this audit therefore
does not claim that queued successors were presented to the RTL.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent
DEFAULT_SCOPE = "apatb_maxpool_top.AESL_inst_maxpool"
REQUIRED = (
    "ap_clk", "ap_rst_n", "ap_start", "ap_done", "ap_idle", "ap_ready",
    "s_in_TDATA", "s_in_TLAST", "s_in_TVALID", "s_in_TREADY",
    "m_out_TDATA", "m_out_TLAST", "m_out_TKEEP", "m_out_TSTRB",
    "m_out_TVALID", "m_out_TREADY",
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_header(source, requested_scope):
    scopes, signals, widths = [], {}, {}
    statement = []
    timescale = None
    for line in source:
        statement.extend(line.split())
        while "$end" in statement:
            end = statement.index("$end")
            tokens, statement = statement[:end], statement[end + 1:]
            if not tokens:
                continue
            if tokens[0] == "$scope":
                scopes.append(tokens[2].lstrip("\\"))
            elif tokens[0] == "$upscope":
                if not scopes:
                    raise ValueError("Unbalanced VCD scopes")
                scopes.pop()
            elif tokens[0] == "$var":
                full_name = ".".join(scopes + [tokens[4].lstrip("\\")])
                prefix = requested_scope + "."
                if full_name.startswith(prefix) and "." not in full_name[len(prefix):]:
                    name = full_name[len(prefix):]
                    signals[name] = tokens[3]
                    widths[name] = int(tokens[2])
            elif tokens[0] == "$timescale":
                timescale = "".join(tokens[1:])
            elif tokens[0] == "$enddefinitions":
                missing = sorted(set(REQUIRED) - signals.keys())
                if missing:
                    raise ValueError(f"Missing VCD signals in {requested_scope}: {missing}")
                match = re.fullmatch(r"(\d+)(s|ms|us|ns|ps|fs)", timescale or "")
                if not match:
                    raise ValueError(f"Unrecognized VCD timescale: {timescale!r}")
                ns_per_unit = {"s": 1e9, "ms": 1e6, "us": 1e3, "ns": 1,
                               "ps": 1e-3, "fs": 1e-6}[match.group(2)]
                return signals, widths, timescale, int(match.group(1)) * ns_per_unit
    raise ValueError("VCD header ended without $enddefinitions")


def timestamp_groups(source, watched):
    """Yield all changes at one timestamp as a single group, including aliases."""
    timestamp, changes = 0, {}
    ignoring_directive = False
    for line in source:
        line = line.strip()
        if not line:
            continue
        if ignoring_directive:
            if "$end" in line:
                ignoring_directive = False
            continue
        if line.startswith("#"):
            new_time = int(line[1:])
            if new_time < timestamp:
                raise ValueError("VCD timestamps are not monotonic")
            if new_time != timestamp:
                yield timestamp, changes
                timestamp, changes = new_time, {}
            continue
        if line.startswith("$"):
            # Dump directives surround ordinary value-change lines. Comments
            # may span lines and must not be mistaken for such changes.
            if line.startswith("$comment") and "$end" not in line:
                ignoring_directive = True
            continue
        if line[0] in "01xXzZ":
            code, bits = line[1:], line[0].lower()
        elif line[0] in "bB":
            fields = line[1:].split()
            if len(fields) != 2:
                raise ValueError(f"Malformed VCD vector: {line[:100]}")
            bits, code = fields[0].lower(), fields[1]
        else:
            continue  # Real/string values do not describe these digital ports.
        if code in watched:
            changes[code] = None if any(c in bits for c in "xz") else int(bits, 2)
    yield timestamp, changes


def transaction_latencies(path):
    result = {}
    for line in path.read_text().splitlines():
        match = re.match(r"\s*transaction\s+(\d+):\s+(\d+)\s+(\d+|[xX])", line)
        if match:
            index, latency = map(int, match.groups()[:2])
            interval_text = match.group(3)
            interval = None if interval_text.lower() == "x" else int(interval_text)
            if index in result:
                raise ValueError(f"Duplicate HLS transaction {index}")
            result[index] = {"latency_cycles": latency, "interval_cycles": interval}
    if not result:
        raise ValueError("No individual HLS transactions found")
    return result


def first_mismatch(actual, expected):
    for index, (got, want) in enumerate(zip(actual, expected)):
        if got != want:
            return {"beat": index, "actual": got, "expected": want}
    if len(actual) != len(expected):
        return {"beat": min(len(actual), len(expected)), "actual_count": len(actual),
                "expected_count": len(expected)}
    return None


def audit(vcd, manifest_path, transaction_path, scope):
    manifest = json.loads(manifest_path.read_text())
    scenarios = manifest["scenarios"]
    vendor = transaction_latencies(transaction_path)
    errors = []
    transactions, active, state = [], None, {}
    groups = 0
    maximum_time = 0
    rising_edges = 0
    edge_periods = Counter()
    previous_edge = None
    previous_ap_start = 0
    outside_input, outside_output = 0, 0
    reset_interruptions = 0

    with vcd.open() as source:
        signals, widths, timescale, ns_per_tick = parse_header(source, scope)
        watched = set(signals.values())

        def value(name):
            return state.get(signals[name])

        for timestamp, changes in timestamp_groups(source, watched):
            groups += 1
            maximum_time = timestamp
            # Critically, every other signal is read from state BEFORE this
            # timestamp's updates. Clocked logic samples these same old values.
            rising = value("ap_clk") == 0 and changes.get(signals["ap_clk"]) == 1
            if rising:
                rising_edges += 1
                if previous_edge is not None:
                    edge_periods[timestamp - previous_edge] += 1
                previous_edge = timestamp
                if value("ap_rst_n") != 1:
                    if active is not None:
                        reset_interruptions += 1
                        active = None
                else:
                    # This HLS block deasserts ap_idle combinatorially when
                    # ap_start is asserted. Therefore ap_start && ap_idle
                    # cannot identify its accepted start edge. The driver
                    # holds ap_start through the activation; its sampled
                    # low-to-high transition while inactive identifies start.
                    start = value("ap_start") == 1 and previous_ap_start != 1
                    done = value("ap_done") == 1
                    accepted_input = value("s_in_TVALID") == 1 and value("s_in_TREADY") == 1
                    accepted_output = value("m_out_TVALID") == 1 and value("m_out_TREADY") == 1
                    if start and active is None:
                        index = len(transactions)
                        active = {
                            "index": index, "start_time_ticks": timestamp,
                            "start_rising_edge": rising_edges, "input": [], "output": [],
                            "cycles_sampled": 0, "first_input_offer_time_ticks": None,
                            "first_input_handshake_time_ticks": None,
                            "last_input_handshake_time_ticks": None,
                            "input_not_valid_before_first_offer_cycles": 0,
                            "input_ready_without_valid_before_first_offer_cycles": 0,
                            "input_not_valid_after_first_offer_before_complete_cycles": 0,
                            "input_ready_without_valid_after_first_offer_before_complete_cycles": 0,
                            "output_not_ready_cycles": 0, "output_valid_not_ready_cycles": 0,
                            "unknown_control_cycles": 0,
                            "output_auxiliary_bits_ok": True,
                        }
                    elif start and active is not None and not done:
                        errors.append(f"ap_start rose during active activation {active['index']}")

                    if active is None:
                        outside_input += int(accepted_input)
                        outside_output += int(accepted_output)
                    else:
                        active["cycles_sampled"] += 1
                        index = active["index"]
                        expected_consumed = scenarios[index]["consumed"] if index < len(scenarios) else None
                        controls = ("ap_start", "ap_done", "ap_idle", "s_in_TVALID", "s_in_TREADY",
                                    "m_out_TVALID", "m_out_TREADY")
                        if any(value(name) is None for name in controls):
                            active["unknown_control_cycles"] += 1

                        if expected_consumed is None or len(active["input"]) < expected_consumed:
                            if value("s_in_TVALID") == 1 and active["first_input_offer_time_ticks"] is None:
                                active["first_input_offer_time_ticks"] = timestamp
                            if value("s_in_TVALID") != 1:
                                before = active["first_input_offer_time_ticks"] is None
                                phase = "before_first_offer" if before else "after_first_offer_before_complete"
                                active[f"input_not_valid_{phase}_cycles"] += 1
                                if value("s_in_TREADY") == 1:
                                    active[f"input_ready_without_valid_{phase}_cycles"] += 1

                        if value("m_out_TREADY") != 1:
                            active["output_not_ready_cycles"] += 1
                            if value("m_out_TVALID") == 1:
                                active["output_valid_not_ready_cycles"] += 1
                        if accepted_input:
                            active["input"].append([value("s_in_TDATA"), value("s_in_TLAST")])
                            if active["first_input_handshake_time_ticks"] is None:
                                active["first_input_handshake_time_ticks"] = timestamp
                            active["last_input_handshake_time_ticks"] = timestamp
                        if accepted_output:
                            active["output"].append([value("m_out_TDATA"), value("m_out_TLAST")])
                            if value("m_out_TKEEP") != 15 or value("m_out_TSTRB") != 15:
                                active["output_auxiliary_bits_ok"] = False
                        if done:
                            active["done_time_ticks"] = timestamp
                            active["done_rising_edge"] = rising_edges
                            active["elapsed_rising_edge_intervals"] = rising_edges - active["start_rising_edge"]
                            active["inclusive_rising_edge_count"] = rising_edges - active["start_rising_edge"] + 1
                            active["input_valid_at_done"] = value("s_in_TVALID")
                            active["input_ready_at_done"] = value("s_in_TREADY")
                            active["input_word_at_done"] = value("s_in_TDATA")
                            active["input_last_at_done"] = value("s_in_TLAST")
                            transactions.append(active)
                            active = None
                previous_ap_start = value("ap_start") if value("ap_rst_n") == 1 else 0
            state.update(changes)

    if maximum_time <= 0 or groups < 2 or rising_edges == 0:
        errors.append("VCD has no advancing clock/time trace; initial values alone are not evidence")
    if active is not None:
        errors.append(f"Activation {active['index']} started but did not complete")
    if len(transactions) != len(scenarios):
        errors.append(f"Expected {len(scenarios)} completed activations, observed {len(transactions)}")
    if len(vendor) != len(scenarios):
        errors.append(f"HLS transaction count {len(vendor)} differs from manifest count {len(scenarios)}")
    if reset_interruptions:
        errors.append(f"Reset interrupted {reset_interruptions} active transactions")
    if outside_input or outside_output:
        errors.append(f"Handshakes outside activations: input={outside_input}, output={outside_output}")
    if len(edge_periods) != 1:
        errors.append(f"Expected a constant clock period, observed {dict(edge_periods)}")

    audited = []
    offsets = Counter()
    for observed in transactions:
        index = observed["index"]
        if index >= len(scenarios):
            errors.append(f"Unexpected extra activation {index}")
            continue
        expected = scenarios[index]
        inputs = observed.pop("input")
        outputs = observed.pop("output")
        input_mismatch = first_mismatch(inputs, expected["input"][:expected["consumed"]])
        output_mismatch = first_mismatch(outputs, expected["expected_output"])
        status = input_mismatch is None and output_mismatch is None and observed["output_auxiliary_bits_ok"]
        status = status and observed["unknown_control_cycles"] == 0
        vendor_entry = vendor.get(index)
        if vendor_entry is None:
            status = False
            errors.append(f"Missing vendor latency for transaction {index}")
            offset = None
        else:
            offset = vendor_entry["latency_cycles"] - observed["elapsed_rising_edge_intervals"]
            offsets[offset] += 1
        if not status:
            errors.append(f"Activation {index} {expected['name']} waveform comparison failed")
        observed.update({
            "name": expected["name"], "pass": status,
            "expected_input_beats": expected["consumed"], "observed_input_beats": len(inputs),
            "expected_output_beats": expected["output_count"], "observed_output_beats": len(outputs),
            "input_prefix_matches": input_mismatch is None, "output_matches": output_mismatch is None,
            "input_first_mismatch": input_mismatch, "output_first_mismatch": output_mismatch,
            "start_time_ns": observed["start_time_ticks"] * ns_per_tick,
            "done_time_ns": observed["done_time_ticks"] * ns_per_tick,
            "vendor_transaction": vendor_entry,
            "vendor_latency_minus_elapsed_edge_intervals": offset,
            "queued_successors_offered_proven": False,
        })
        audited.append(observed)

    if len(offsets) > 1:
        errors.append(f"Vendor/waveform latency offset is not consistent: {dict(offsets)}")
    period_ticks = next(iter(edge_periods)) if len(edge_periods) == 1 else None
    performance = None
    performance_index = manifest["performance_transaction_index"]
    if performance_index < len(audited) and performance_index in vendor:
        item = audited[performance_index]
        latency = vendor[performance_index]["latency_cycles"]
        startup_starvation = item["input_ready_without_valid_before_first_offer_cycles"]
        gaps = item["input_not_valid_after_first_offer_before_complete_cycles"]
        stalled_output = item["output_valid_not_ready_cycles"]
        performance = {
            "index": performance_index, "name": item["name"],
            "latency_cycles": latency, "latency_source": str(transaction_path),
            "latency_source_record": f"transaction {performance_index}",
            "latency_target_cycles": 20000, "latency_target_pass": latency <= 20000,
            "input_scalar_samples": 4096,
            "effective_input_throughput_samples_per_cycle": 4096 / latency,
            "waveform_elapsed_rising_edge_intervals": item["elapsed_rising_edge_intervals"],
            "waveform_inclusive_rising_edge_count": item["inclusive_rising_edge_count"],
            "vendor_minus_waveform_intervals": item["vendor_latency_minus_elapsed_edge_intervals"],
            "start_time_ticks": item["start_time_ticks"], "done_time_ticks": item["done_time_ticks"],
            "input_startup_not_valid_cycles": item["input_not_valid_before_first_offer_cycles"],
            "input_startup_ready_without_valid_cycles": startup_starvation,
            "input_not_valid_after_first_offer_before_complete_cycles": gaps,
            "input_continuous_after_first_offer_until_last_acceptance": gaps == 0,
            "input_never_starved_a_ready_consumer": startup_starvation == 0 and
                item["input_ready_without_valid_after_first_offer_before_complete_cycles"] == 0,
            "output_not_ready_cycles": item["output_not_ready_cycles"],
            "output_valid_not_ready_cycles": stalled_output,
            "output_ready_on_every_activation_cycle": item["output_not_ready_cycles"] == 0,
            "output_never_backpressured_valid_beat": stalled_output == 0,
            "startup_convention": "Report TVALID startup separately; continuous-availability interval begins with first offered input beat and ends with the final input acceptance.",
        }
        if gaps or startup_starvation or stalled_output:
            errors.append("Performance activation includes input availability gaps/consumer starvation or output backpressure; inspect detailed counts")

    return {
        "status": "PASS" if not errors else "FAIL", "errors": errors,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "audit_script_sha256": sha256(Path(__file__).resolve()),
        "vcd": str(vcd), "vcd_sha256": sha256(vcd), "scope": scope,
        "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path),
        "vendor_transaction_report": str(transaction_path),
        "vendor_transaction_report_sha256": sha256(transaction_path),
        "timescale": timescale, "nanoseconds_per_tick": ns_per_tick,
        "signal_codes": {name: signals[name] for name in REQUIRED},
        "signal_widths": {name: widths[name] for name in REQUIRED},
        "vcd_timestamp_groups": groups, "last_time_ticks": maximum_time,
        "sampled_rising_edges": rising_edges, "clock_period_ticks": period_ticks,
        "clock_period_ns": period_ticks * ns_per_tick if period_ticks is not None else None,
        "expected_activation_count": len(scenarios), "completed_activation_count": len(transactions),
        "outside_activation_input_handshakes": outside_input,
        "outside_activation_output_handshakes": outside_output,
        "latency_correlation": {
            "vendor_minus_preedge_start_to_done_edge_intervals": dict(offsets),
            "consistent_offset": len(offsets) == 1,
            "measurement_rule": "Vendor individual transaction latency is authoritative; waveform edge intervals and inclusive edge counts are recorded independently and their observed offset is reported.",
        },
        "sampling_convention": "At each VCD timestamp containing a low-to-high clock transition, sample all ports from the values before all updates at that timestamp. Group aliases and all delta changes at the same timestamp. Start is the sampled low-to-high transition of ap_start while inactive; completion is sampled ap_done. In this synthesized HLS block ap_idle deasserts combinatorially when ap_start is asserted, so ap_start && ap_idle would miss activations. The driver holds ap_start until completion.",
        "queued_input_limitation": "Original HLS co-simulation adapter truncates input transactions to the golden C-consumed prefixes. Matching those accepted prefixes does not prove that queued successors were presented and rejected. Supplemental RTL stimulus is required for that claim.",
        "performance": performance, "activations": audited,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vcd", type=Path)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/scenarios.json")
    parser.add_argument("--transactions", type=Path,
                        default=ROOT / "evidence/cosim_001/hls/sim/report/verilog/result.transaction.rpt")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/cosim_trace_checks.json")
    parser.add_argument("--scope", default=DEFAULT_SCOPE)
    args = parser.parse_args()
    scope = args.scope.strip("/.").replace("/", ".")
    try:
        result = audit(args.vcd.resolve(), args.manifest.resolve(), args.transactions.resolve(), scope)
    except Exception as exc:
        result = {"status": "FAIL", "vcd": str(args.vcd),
                  "errors": [f"{type(exc).__name__}: {exc}"],
                  "generated_utc": datetime.now(timezone.utc).isoformat()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{result['status']} RTL trace audit: {result.get('completed_activation_count', 0)} activations")
    for error in result["errors"]:
        print(f"  {error}")
    if result.get("performance"):
        performance = result["performance"]
        print(f"Performance transaction {performance['index']}: vendor latency {performance['latency_cycles']} cycles; "
              f"waveform intervals {performance['waveform_elapsed_rising_edge_intervals']}; "
              f"throughput {performance['effective_input_throughput_samples_per_cycle']:.12g} samples/cycle")
    print(f"Evidence: {args.output}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
