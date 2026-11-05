#!/usr/bin/env python3
"""Run one supplementary all-scenario simulation with complete queued inputs."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parent


def main():
    evidence = ROOT / "evidence"
    evidence.mkdir(exist_ok=True)
    for number in range(1, 1000000):
        attempt = evidence / f"rtl_stream_{number:03d}"
        try:
            attempt.mkdir()
            break
        except FileExistsError:
            continue
    else:
        raise RuntimeError("No available RTL attempt ID")
    metadata = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "method": "supplementary synthesized RTL simulation of every full input queue",
        "python": sys.executable,
        "clock_ns": 10,
        "commands": [],
        "source_sha256": {},
    }
    returncode = 1
    with (attempt / "run_rtl_stream.log").open("w") as log:
        def emit(text):
            print(text, flush=True)
            log.write(text + "\n")
            log.flush()

        try:
            sources = [ROOT / "rtl_stream_tb.sv", ROOT / "verify_rtl_stream.py",
                       ROOT / "data/scenarios.txt", ROOT / "data/scenarios.json"]
            rtl = sorted((ROOT / "maxpool_prj/solution1/syn/verilog").glob("*.v"))
            if not rtl:
                raise RuntimeError("No synthesized Verilog; run synthesis first")
            sources.extend(rtl)
            for source in sources:
                relative = source.relative_to(ROOT)
                destination = attempt / "sources" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                metadata["source_sha256"][str(relative)] = hashlib.sha256(source.read_bytes()).hexdigest()
            tool_paths = {name: shutil.which(name) for name in ("xvlog", "xelab", "xsim")}
            metadata["tools"] = tool_paths
            if not all(tool_paths.values()):
                raise RuntimeError(f"Required host simulator tools not on PATH: {tool_paths}")
            copied_rtl = [str(attempt / "sources" / source.relative_to(ROOT)) for source in rtl]
            copied_tb = attempt / "sources/rtl_stream_tb.sv"
            copied_scenarios = attempt / "sources/data/scenarios.txt"
            commands = [
                [tool_paths["xvlog"], "--sv", "--work", "work", *copied_rtl, str(copied_tb)],
                [tool_paths["xelab"], "work.rtl_stream_tb", "--debug", "typical", "--snapshot", "maxpool_stream_sim"],
                [tool_paths["xsim"], "maxpool_stream_sim", "--runall",
                 "--testplusarg", f"SCENARIOS={copied_scenarios}",
                 "--testplusarg", f"RESULT={attempt / 'rtl_checks.json'}"],
            ]
            emit(f"Evidence directory: {attempt}")
            for command in commands:
                emit("COMMAND " + json.dumps(command))
                completed = subprocess.run(command, cwd=attempt, text=True,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                emit(completed.stdout)
                emit(f"EXIT STATUS {completed.returncode}")
                metadata["commands"].append({"argv": command, "exit_status": completed.returncode})
                if completed.returncode:
                    raise RuntimeError(f"Tool {Path(command[0]).name} failed: {completed.returncode}")
            checks = json.loads((attempt / "rtl_checks.json").read_text())
            scenarios = json.loads((attempt / "sources/data/scenarios.json").read_text())
            if checks["scenario_count"] != scenarios["scenario_count"]:
                raise RuntimeError("RTL scenario count mismatch")
            if checks["failures"] or not all(row["pass"] for row in checks["activations"]):
                raise RuntimeError("RTL scenario assertions failed")
            metadata["scenario_count"] = checks["scenario_count"]
            metadata["failures"] = checks["failures"]
            returncode = 0
        except Exception:
            emit(traceback.format_exc())
        finally:
            metadata["finished_utc"] = datetime.now(timezone.utc).isoformat()
            metadata["exit_status"] = returncode
            (attempt / "run.json").write_text(json.dumps(metadata, indent=2) + "\n")
            emit(f"RTL runner exit status: {returncode}")
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
