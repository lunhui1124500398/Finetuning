#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_step(command: list[str]) -> None:
    pretty = " ".join(f'"{part}"' if " " in part else part for part in command)
    print(f"Running: {pretty}")
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan hidden bug candidates, build a review pack, and render long-context storyboards.")
    parser.add_argument(
        "--root",
        default=r"D:\jvlei_project_all\new_xz_data\for binary_fromxz",
        help="Root directory containing dataset / dataset-mask pairs.",
    )
    parser.add_argument(
        "--audit-output",
        default=r"D:\jvlei_project_all\new_xz_data\for binary_fromxz\_seg_audit_report\hidden_bug_scan_round1",
        help="Output directory for the hidden-bug scan CSVs.",
    )
    parser.add_argument(
        "--pack-output",
        default=r"D:\jvlei_project_all\new_xz_data\for binary_fromxz\_seg_audit_report\hidden_bug_review_pack_round1",
        help="Output directory for the review pack.",
    )
    parser.add_argument("--max-events", type=int, default=240, help="Maximum events to copy into the review pack.")
    parser.add_argument("--max-events-per-dataset", type=int, default=10, help="Cap copied events per dataset.")
    parser.add_argument("--triage-context-radius", type=int, default=50, help="Long-context radius for storyboard sheets.")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    python_exe = sys.executable

    event_types = (
        "issue1_candidate",
        "issue2_boundary_false_positive_candidate",
        "issue4_tail_empty_normal_candidate",
    )

    run_step(
        [
            python_exe,
            str(script_dir / "scan_hidden_bug_candidates.py"),
            "--root",
            args.root,
            "--output-dir",
            args.audit_output,
        ]
    )

    run_step(
        [
            python_exe,
            str(script_dir / "build_suspicious_label_pack.py"),
            "--root",
            args.root,
            "--audit-dir",
            args.audit_output,
            "--output",
            args.pack_output,
            "--max-events",
            str(args.max_events),
            "--max-events-per-dataset",
            str(args.max_events_per_dataset),
            "--event-types",
            *event_types,
        ]
    )

    run_step(
        [
            python_exe,
            str(script_dir / "build_triage_contact_sheets.py"),
            "--pack-root",
            args.pack_output,
            "--context-radius",
            str(args.triage_context_radius),
        ]
    )

    run_step([python_exe, str(script_dir / "build_triage_fill_table.py"), "--pack-root", args.pack_output])


if __name__ == "__main__":
    main()
