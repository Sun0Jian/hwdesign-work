"""Audit documentation and select submission files; never run the implementation.

Run with the existing course Python (which already provides Mistune).
The baseline and every pre-existing evidence file are read-only inputs.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

import mistune

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "evidence/submission_review"
ACCEPTED = "e07d94b069719939eaa5ea4b364461b8fec6f941"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(ROOT.parents[1]), *args],
        check=True, capture_output=True,
    )
    return result.stdout


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.get("children", []))


def plain(node):
    return node.get("raw", "") + "".join(plain(c) for c in node.get("children", []))


def main():
    baseline = json.loads((REVIEW / "baseline.json").read_text())
    changed = []
    for name, original_hash in baseline["files_sha256"].items():
        assert (ROOT / name).is_file(), f"Historical file missing: {name}"
        if digest(ROOT / name) != original_hash:
            changed.append(name)
    assert changed == ["results.md"], f"Unexpected existing-file changes: {changed}"
    assert (ROOT / "prompt.md").read_bytes() == git("show", ACCEPTED + ":cmdresp/takehome/prompt.md")
    git("merge-base", "--is-ancestor", ACCEPTED, "HEAD")
    assert not git("diff", "--cached", "--name-only"), "Review the existing index before staging"

    report = (ROOT / "results.md").read_text()
    parser = mistune.create_markdown(renderer="ast", plugins=["table"])
    nodes = parser(report)
    headings = [plain(n) for n in nodes if n["type"] == "heading"]
    required = ["Interface", "Design", "Targets", "Verification", "Assumptions", "Open Items", "Run History"]
    assert headings == required, headings
    assert report.count("```") % 2 == 0, "Unbalanced fenced code blocks"
    tables = [n for n in nodes if n["type"] == "table"]
    matrix_tables = [n for n in tables if plain(n["children"][0]).startswith("Index / scenario")]
    assert len(matrix_tables) == 1, "Scenario matrix did not parse as a Markdown table"
    matrix_rows = matrix_tables[0]["children"][1]["children"]
    assert len(matrix_rows) == 99
    manifest = json.loads((ROOT / "data/scenarios.json").read_text())["scenarios"]
    python = json.loads((ROOT / "evidence/python_checks.json").read_text())
    c = json.loads((ROOT / "evidence/csim_003/tb_csim.json").read_text())["activations"]
    rtl = json.loads((ROOT / "evidence/cosim_002/tb_cosim.json").read_text())["activations"]
    extracted = json.loads((REVIEW / "scenario_matrix.json").read_text())
    assert python["status"] == "PASS" and len(python["scenarios"]) == len(c) == len(rtl) == 99
    errors = 0
    for index, row in enumerate(matrix_rows):
        cells = row["children"]
        assert len(cells) == 6
        assert plain(cells[0]) == f"{index} / {manifest[index]['name']}"
        records = [python["scenarios"][index], c[index], rtl[index]]
        assert all(r["index"] == index and r["name"] == manifest[index]["name"] for r in records)
        status = tuple(records[0][k] for k in ("halted", "error", "error_tx_id"))
        assert all(tuple(r[k] for k in ("halted", "error", "error_tx_id")) == status for r in records)
        assert plain(cells[4]) == str(status)
        assert c[index]["pass"] and rtl[index]["pass"]
        if status[1]:
            errors += 1
            next_name = "recovery_after_" + manifest[index]["name"]
            assert manifest[index + 1]["name"] == next_name
            assert next_name in plain(cells[5]) and plain(cells[5]).startswith(str(index + 1) + " /")
            assert c[index + 1]["pass"] and rtl[index + 1]["pass"]
            assert all(c[index + 1][k] == rtl[index + 1][k] == 0 for k in ("halted", "error", "error_tx_id"))
    assert errors == 43

    history = next(t for t in tables if plain(t["children"][0]).startswith("Actual run"))
    assert "Prompt version" in plain(history["children"][0])
    history_rows = history["children"][1]["children"]
    assert all(ACCEPTED in plain(row["children"][1]) for row in history_rows)
    assert "Final submission documentation review" in plain(history_rows[-1])

    cited = set()
    link_count = 0
    for node in walk(nodes):
        if node["type"] != "link":
            continue
        url = node["attrs"]["url"]
        parts = urlsplit(url)
        if parts.scheme or not parts.path:
            continue
        target = (ROOT / unquote(parts.path)).resolve()
        assert target.is_relative_to(ROOT), f"Evidence link leaves project: {url}"
        # This audit is written only after its other checks have succeeded.
        assert target.exists() or target == REVIEW / "submission_audit.json", f"Missing link: {url}"
        if parts.fragment and target.suffix == ".md":
            titles = re.findall(r"^#+ (.+)$", target.read_text(), re.M)
            slugs = [re.sub(r"[^\w\- ]", "", t.lower()).replace(" ", "-") for t in titles]
            assert parts.fragment in slugs, f"Missing Markdown heading anchor: {url}"
        cited.add(str(target.relative_to(ROOT)))
        link_count += 1

    loops = []
    for name in ("read_header", "buffer_image", "emit_windows"):
        stem = f"evidence/synth_002/hls/syn/report/maxpool_Pipeline_{name}_csynth"
        tree = ET.parse(ROOT / (stem + ".xml"))
        ii = tree.findtext(f".//SummaryOfLoopLatency/{name}/PipelineII")
        rpt_row = next(line.strip() for line in (ROOT / (stem + ".rpt")).read_text().splitlines() if line.strip().startswith("|- " + name))
        fields = [v.strip() for v in rpt_row.split("|")[1:-1]]
        assert ii == fields[4] == "1" and fields[-1] == "yes"
        loops.append({"name": name, "achieved_ii": int(ii), "pipelined": True,
                      "rpt": stem + ".rpt", "xml": stem + ".xml", "rpt_row": rpt_row})
    outer_rpt = "evidence/synth_002/hls/syn/report/maxpool_csynth.rpt"
    outer_row = next(line for line in (ROOT / outer_rpt).read_text().splitlines() if "|- VITIS_LOOP_46_1" in line)
    outer_fields = [v.strip() for v in outer_row.split("|")[1:-1]]
    assert outer_fields[4] == "-" and outer_fields[-1] == "no"
    loops.append({"name": "VITIS_LOOP_46_1", "achieved_ii": None, "pipelined": False,
                  "reason": "No numeric II in final report; no inference made", "rpt": outer_rpt, "rpt_row": outer_row})

    # Keep lab sources, all historical text evidence, source snapshots and VCDs.
    # Exclude simulator binaries/databases and editor state unless actually cited.
    root_files = [".gitignore", "prompt.md", "results.md", "maxpool_model.py", "verify_python.py",
                  "maxpool_hw.py", "maxpool_build.py", "maxpool_body_impl.tpp", "maxpool_tb.cpp",
                  "run.tcl", "rtl_stream_tb.sv", "verify_rtl_stream.py", "audit_cosim_trace.py",
                  "export_cosim_trace.py"]
    selected = set(root_files)
    excluded_bulk = []
    for folder in ("data", "gen", "include", "evidence"):
        for path in (ROOT / folder).rglob("*"):
            if not path.is_file():
                continue
            name = str(path.relative_to(ROOT))
            preprocessed_vendor_headers = "/hls/sim/wrapc" in name and path.name.endswith("_pre.cpp")
            uncited_simulator_support = "/hls/sim/verilog/" in name and path.suffix not in (".rpt", ".xml", ".rb")
            uncited_csim_support = "/hls/sim/wrapc" in name and path.name != "apatb_maxpool.cpp"
            bulk = ("xsim.dir" in path.parts or ".Xil" in path.parts
                    or path.suffix in (".wdb", ".pb", ".jou") or preprocessed_vendor_headers
                    or uncited_simulator_support or uncited_csim_support)
            if bulk and name not in cited:
                excluded_bulk.append(name)
            else:
                selected.add(name)
    selected.update(("evidence/submission_review/submission_audit.json", "evidence/submission_review/staging_files.txt"))
    assert cited <= selected, f"Cited evidence excluded: {cited - selected}"
    stage_file = REVIEW / "staging_files.txt"
    stage_file.write_text("".join("cmdresp/takehome/" + name + "\n" for name in sorted(selected)))
    branch = git("branch", "--show-current").decode().strip()
    upstream = git("rev-parse", "--abbrev-ref", "@{upstream}").decode().strip()
    remote = git("remote", "get-url", "origin").decode().strip()
    audit = {
        "review_utc": datetime.now(timezone.utc).isoformat(), "status": "PASS",
        "scope": "Documentation extraction and submission preparation only; no implementation or hardware runs",
        "accepted_prompt_version": 1, "accepted_prompt_commit": ACCEPTED,
        "specification_changed": False, "prompt_sha256": digest(ROOT / "prompt.md"),
        "byte_enable_review": {"decision": "Existing Version 1 delegated interface choices cover full-word inputs; no prompt edit",
            "delegation": ["Section 3 Header and Encoding Requirements: Stream width, Sample packing, Padding-bit conventions", "Section 7 Assumptions: resolve and document host protocol choices"],
            "supported_input": "Complete 32-bit words, TKEEP=TSTRB=0xF; other byte-enable patterns outside supported input contract",
            "conflict_found": False, "behavior_change": False},
        "changed_preexisting_files": changed,
        "documentation_changes": ["Achieved loop II from final synth_002 reports", "All 99 individual scenario rows with recorded statuses and 43 next recoveries", "Prompt version column; all historical runs remain Version 1", "Explicit report wording for already chosen full-word byte-enable contract", "Separate documentation review and provenance audit"],
        "results_before_sha256": baseline["results_original_sha256"], "results_after_sha256": digest(ROOT / "results.md"),
        "historical_provenance": {"existing_files_checked": len(baseline["files_sha256"]),
            "all_except_results_unchanged": True, "baseline": "evidence/submission_review/baseline.json",
            "old_report_snapshot": "evidence/submission_review/results_before.txt",
            "final_validation_preserved": True,
            "final_validation_sha256": digest(ROOT / "evidence/final_validation.json"),
            "interpretation": "final_validation.json describes the pre-documentation report and original repository head; it has not been relabelled or rerun"},
        "markdown": {"parser": "mistune", "version": mistune.__version__, "table_plugin": True,
            "required_headings": headings, "parsed_tables": len(tables), "scenario_rows": len(matrix_rows),
            "error_recovery_rows": errors, "historical_and_review_rows": len(history_rows),
            "relative_links_checked": link_count, "unique_cited_paths": sorted(cited)},
        "loop_ii": loops,
        "scenario_outcome_derivation": "Python PASS* derives from recorded whole-run PASS plus indexed checked records; C/RTL pass booleans and statuses are recorded per case. No new outcome is invented.",
        "submission": {"repository_remote": remote, "branch": branch, "upstream": upstream,
            "pre_commit_head": git("rev-parse", "HEAD").decode().strip(),
            "accepted_commit_is_ancestor": True,
            "post_commit_acceptance": "Verify new local HEAD equals remote upstream head and accepted commit remains an ancestor; do not require HEAD to equal original specification commit",
            "staging_file": "evidence/submission_review/staging_files.txt", "selected_file_count": len(selected),
            "selected_bytes_excluding_this_audit": sum((ROOT / name).stat().st_size for name in selected if (ROOT / name).is_file()),
            "excluded_unreferenced_bulk": sorted(excluded_bulk),
            "publication_review": "Automatic approval review rejected publishing the uncited vendor glbl.v library copy. Uncited simulator support and vendor copies are excluded from publication, retained unchanged locally; cited evidence and implementation source snapshots remain included.",
            "excluded_other_locations": [".vscode/", ".waveflow/", "maxpool_prj/", "logs/", "vcd/", "virtual environments"]},
        "cited_file_sha256": {name: digest(ROOT / name) for name in sorted(cited) if (ROOT / name).is_file() and name != "evidence/submission_review/submission_audit.json"},
    }
    assert audit["historical_provenance"]["final_validation_sha256"] == baseline["final_validation_original_sha256"]
    (REVIEW / "submission_audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(f"PASS: {len(matrix_rows)} scenario rows; {errors} error/recovery pairs; {link_count} relative links")
    print(f"PASS: {len(baseline['files_sha256']) - 1} pre-existing files unchanged; only results.md edited")
    print(f"Staging selection: {len(selected)} files, excluding {len(excluded_bulk)} unreferenced bulk files")
    print(f"Remote: {remote}; branch: {branch}; upstream: {upstream}")


if __name__ == "__main__":
    main()
