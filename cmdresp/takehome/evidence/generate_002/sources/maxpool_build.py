#!/usr/bin/env python3
"""Generate the Waveflow boundary and run independently recorded HLS stages.

Run with the existing course Python environment. Each invocation creates a new
evidence directory, so a failed or repeated run never replaces earlier logs.
"""

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback

from waveflow.build.build import BuildConfig, BuildDag, SourceStep
from waveflow.build.hwcodegen_steps import HlsCodegenStep
from waveflow.build.streamutils import StreamUtilsStep
from waveflow.toolchain import toolchain
import waveflow

from maxpool_hw import MaxPoolAccel

ROOT = Path(__file__).resolve().parent


class Tee:
    def __init__(self, terminal, log):
        self.terminal, self.log = terminal, log

    def write(self, text):
        self.terminal.write(text)
        self.log.write(text)
        self.flush()
        return len(text)

    def flush(self):
        self.terminal.flush()
        self.log.flush()

    def isatty(self):
        return False


def new_attempt(stage):
    evidence = ROOT / "evidence"
    evidence.mkdir(exist_ok=True)
    for number in range(1, 1000000):
        attempt = evidence / f"{stage}_{number:03d}"
        try:
            attempt.mkdir()
            return attempt
        except FileExistsError:
            continue
    raise RuntimeError("No available evidence attempt number")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_sources(attempt):
    sources = {}
    for name in (
        "prompt.md", "maxpool_hw.py", "maxpool_build.py", "run.tcl",
        "maxpool_body_impl.tpp", "maxpool_tb.cpp", "data/scenarios.txt",
        "gen/maxpool.hpp", "gen/maxpool.cpp", "include/streamutils.hpp",
    ):
        source = ROOT / name
        if source.is_file():
            sources[name] = sha256(source)
            target = attempt / "sources" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    package_sources = {}
    for cls in (MaxPoolAccel.__bases__[0], HlsCodegenStep, StreamUtilsStep):
        path = Path(inspect.getfile(cls)).resolve()
        package_sources[str(path)] = sha256(path)
    return {
        "python": sys.executable,
        "waveflow": str(Path(waveflow.__file__).resolve()),
        "source_sha256": sources,
        "waveflow_source_sha256": package_sources,
    }


def require_success(result, action):
    failed = [name for name, step in result.items() if not step.success]
    for name, step in result.items():
        print(f"{action}: {name}: {step}")
    if failed:
        raise RuntimeError(f"{action} failed steps: {failed}")


def generate():
    config = BuildConfig(root_dir=ROOT)
    helpers = BuildDag()
    helpers.add(StreamUtilsStep(output_dir="include"))
    require_success(helpers.run(config), "Waveflow stream helpers")

    dag = BuildDag()
    dag.add(SourceStep(
        name="kernel_sources", artifact="kernel_sources",
        path=ROOT / "maxpool_hw.py",
    ))
    dag.add(HlsCodegenStep(
        name="gen_kernel", comp_class=MaxPoolAccel,
        source_artifact="kernel_sources", output_dir="gen", impl_dir=".",
    ))
    require_success(dag.run(config), "Waveflow HLS boundary")

    # The reference API provides no stream register-mode parameter. Turn off
    # input-side AXIS registers in the generated pragma: a forward register
    # could accept a queued beat after the body has detected an error.
    # This is a narrow, deterministic wrapper setting; all generated interfaces
    # and the body call remain under Waveflow's code generator.
    path = ROOT / "gen" / "maxpool.cpp"
    lines = path.read_text().splitlines(keepends=True)
    matched = 0
    for i, line in enumerate(lines):
        if "#pragma HLS INTERFACE" in line and re.search(r"\baxis\b", line) and re.search(r"\bport\s*=\s*s_in\b", line):
            if re.search(r"\bregister_mode\s*=\s*\w+", line):
                line = re.sub(r"\bregister_mode\s*=\s*\w+", "register_mode=off", line)
            else:
                line = line.rstrip("\n") + " register_mode=off\n"
            lines[i] = line
            matched += 1
    if matched != 1:
        raise RuntimeError(f"Expected one s_in AXIS pragma; found {matched}")
    path.write_text("".join(lines))
    print("Generated Waveflow kernel boundary and stream helpers.")
    print("Applied input AXIS register_mode=off to prevent input prefetch.")
    print(path.read_text())


def run_stage(stage, attempt):
    if not (ROOT / "gen" / "maxpool.cpp").is_file():
        raise RuntimeError("Run --stage generate before an HLS stage")
    try:
        result = toolchain.run_vitis_hls(
            ROOT / "run.tcl", work_dir=ROOT, capture_output=True,
            env={
                "WAVEFLOW_POOL_STAGE": stage,
                "WAVEFLOW_POOL_SCENARIOS": str(ROOT / "data" / "scenarios.txt"),
                "WAVEFLOW_POOL_TB_RESULT": str(attempt / f"tb_{stage}.json"),
            },
        )
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout, end="" if exc.stdout.endswith("\n") else "\n")
        if exc.stderr:
            print(exc.stderr, file=sys.stderr, end="" if exc.stderr.endswith("\n") else "\n")
        print(f"Vitis HLS exit status: {exc.returncode}")
        raise
    if getattr(result, "stdout", None):
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if getattr(result, "stderr", None):
        print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
    code = getattr(result, "returncode", None)
    if code is None:
        raise RuntimeError(f"Unexpected run_vitis_hls result type: {type(result).__name__}: {result}")
    print(f"Vitis HLS exit status: {code}")
    if code:
        raise RuntimeError(f"Vitis HLS {stage} failed with exit status {code}")


def preserve_hls_evidence(stage, attempt):
    """Keep each stage's reports and co-sim handshake/transaction evidence."""
    solution = ROOT / "maxpool_prj" / "solution1"
    roots = {
        "csim": ("csim/report",),
        "synth": ("syn/report",),
        "cosim": ("sim/report", "sim/verilog", "sim/wrapc_pc"),
    }.get(stage, ())
    saved = []
    for relative in roots:
        directory = solution / relative
        if not directory.is_dir():
            continue
        for source in directory.rglob("*"):
            if not source.is_file():
                continue
            if source.suffix.lower() not in {
                ".rpt", ".xml", ".json", ".csv", ".log", ".vcd", ".wdb",
                ".wcfg", ".v", ".cpp", ".h", ".tcl", ".dat", ".tv", ".rb",
            }:
                continue
            relative_path = source.relative_to(solution)
            target = attempt / "hls" / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            saved.append(str(relative_path))
    return saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=("generate", "csim", "synth", "cosim"))
    args = parser.parse_args()
    attempt = new_attempt(args.stage)
    metadata = {
        "stage": args.stage,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(ROOT), "part": "xc7z020clg484-1", "clock_ns": 10,
        "command": sys.argv,
    }
    code = 0
    with (attempt / f"run_{args.stage}.log").open("w") as log:
        with redirect_stdout(Tee(sys.stdout, log)), redirect_stderr(Tee(sys.stderr, log)):
            print(f"Evidence directory: {attempt}")
            try:
                if args.stage == "generate":
                    generate()
                else:
                    run_stage(args.stage, attempt)
            except Exception:
                traceback.print_exc()
                code = 1
            finally:
                metadata.update(record_sources(attempt))
                metadata["hls_evidence"] = preserve_hls_evidence(args.stage, attempt)
                metadata["finished_utc"] = datetime.now(timezone.utc).isoformat()
                metadata["exit_status"] = code
                (attempt / "run.json").write_text(json.dumps(metadata, indent=2) + "\n")
                print(f"Build runner exit status: {code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
