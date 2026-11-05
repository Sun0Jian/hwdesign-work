"""Replay the existing all-scenario HLS simulation snapshot to export port VCD.

No synthesis or stimulus changes occur. The original co-simulation report and
its individual transaction measurements remain in evidence/cosim_001/.
"""
from contextlib import redirect_stdout, redirect_stderr
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import traceback

from waveflow.scripts.xsim_vcd import run_xsim_vcd
from maxpool_build import Tee, new_attempt

ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cosim-run", default="cosim_001")
    args = parser.parse_args()
    report = ROOT / "evidence" / args.cosim_run / "hls/sim/report/verilog/result.transaction.rpt"
    if not report.is_file():
        raise RuntimeError(f"Missing preserved transaction report: {report}")
    attempt = new_attempt("trace")
    meta = {"started_utc": datetime.now(timezone.utc).isoformat(),
            "purpose": f"VCD replay of unchanged {args.cosim_run} all-99-activation snapshot",
            "original_report": str(report.relative_to(ROOT))}
    code = 0
    with (attempt / "export.log").open("w") as log:
        with redirect_stdout(Tee(sys.stdout, log)), redirect_stderr(Tee(sys.stderr, log)):
            try:
                scope = "/apatb_maxpool_top/AESL_inst_maxpool/"
                names = ["ap_clk", "ap_rst_n", "ap_start", "ap_done", "ap_idle", "ap_ready"]
                names += [p + s for p in ("s_in_", "m_out_")
                          for s in ("TDATA", "TLAST", "TKEEP", "TSTRB", "TVALID", "TREADY")]
                # Explicit scalar/vector signals avoid exporting internal memories
                # and unsupported objects through an unrestricted hierarchy wildcard.
                targets = "[get_objects {" + " ".join(scope + n for n in names) + "}]"
                path = run_xsim_vcd(top="maxpool", comp="maxpool_prj",
                                    out=f"{attempt.name}.vcd",
                                    trace_level=targets,
                                    workdir=ROOT)
                path = Path(path)
                target = attempt / "cosim.vcd"
                shutil.copy2(path, target)
                meta["vcd"] = str(target.relative_to(ROOT))
                meta["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
                sim_log = ROOT / "maxpool_prj/solution1/sim/verilog/xsim.log"
                log_text = sim_log.read_text()
                if "ERROR:" in log_text or "unexpected exception" in log_text:
                    raise RuntimeError("XSIM reported an error despite returning exit status zero; see xsim.log")
                with target.open() as trace:
                    if not any(line.startswith("#") and line.strip() != "#0" for line in trace):
                        raise RuntimeError("VCD has no nonzero simulation timestamps")
                print(f"Retained trace: {target}")
            except Exception:
                traceback.print_exc()
                code = 1
            finally:
                for name in ("xsim.log", "maxpool_vcd.tcl", "run_xsim_vcd.sh"):
                    source = ROOT / "maxpool_prj/solution1/sim/verilog" / name
                    if source.exists():
                        shutil.copy2(source, attempt / name)
    meta.update(finished_utc=datetime.now(timezone.utc).isoformat(), exit_status=code)
    (attempt / "run.json").write_text(json.dumps(meta, indent=2) + "\n")
    return code

if __name__ == "__main__":
    raise SystemExit(main())
