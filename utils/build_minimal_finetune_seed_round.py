#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


def read_csv_rows(csv_path: Path) -> List[Dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(csv_path: Path, rows: Sequence[Dict[str, object]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        if not rows:
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def natural_key(text: str) -> Tuple[str, ...]:
    return tuple(text.split("_"))


def run_step(command: List[str]) -> None:
    pretty = " ".join(f'"{part}"' if " " in part else part for part in command)
    print(f"Running: {pretty}")
    subprocess.run(command, check=True)


def select_issue1_residuals(
    hidden_rows: Sequence[Dict[str, str]],
    rerun_rows: Sequence[Dict[str, str]],
    max_events: int,
    max_per_dataset: int,
) -> List[Dict[str, object]]:
    hidden_lookup = {
        (row["group_name"], row["dataset_name"], row["frame_name"], row["event_type"]): row for row in hidden_rows
    }
    candidates = []
    for row in rerun_rows:
        retry_used = int(row["retry_used"])
        changed_ratio = float(row["changed_ratio"])
        if retry_used == 1 and changed_ratio >= 0.01:
            continue
        key = (row["group_name"], row["dataset_name"], row["frame_name"], "issue1_candidate")
        source = hidden_lookup.get(key)
        if source is None:
            continue
        seed_reason = "rerun_not_adopted" if retry_used == 0 else "rerun_small_change"
        candidates.append(
            (
                -float(row["severity_score"]),
                -float(row["bucket_margin"]),
                row["group_name"],
                row["dataset_name"],
                row["frame_name"],
                source,
                seed_reason,
            )
        )

    selected: List[Dict[str, object]] = []
    per_dataset: Counter[Tuple[str, str]] = Counter()
    for _, _, group_name, dataset_name, _, source, seed_reason in sorted(candidates):
        dataset_key = (group_name, dataset_name)
        if per_dataset[dataset_key] >= max_per_dataset:
            continue
        payload = dict(source)
        payload["seed_reason"] = seed_reason
        payload["seed_priority"] = "issue1_residual"
        selected.append(payload)
        per_dataset[dataset_key] += 1
        if len(selected) >= max_events:
            break
    return selected


def select_issue2_boundaries(
    hidden_rows: Sequence[Dict[str, str]],
    max_events: int,
    max_per_dataset: int,
) -> List[Dict[str, object]]:
    candidates = []
    for row in hidden_rows:
        if row["event_type"] != "issue2_boundary_false_positive_candidate":
            continue
        if row.get("human_locked", "").strip() == "1":
            continue
        candidates.append(
            (
                -float(row["severity_score"] or 0.0),
                row["group_name"],
                row["dataset_name"],
                row["frame_name"],
                row,
            )
        )

    selected: List[Dict[str, object]] = []
    per_dataset: Counter[Tuple[str, str]] = Counter()
    for _, group_name, dataset_name, _, row in sorted(candidates):
        dataset_key = (group_name, dataset_name)
        if per_dataset[dataset_key] >= max_per_dataset:
            continue
        payload = dict(row)
        payload["seed_reason"] = "boundary_hard_negative"
        payload["seed_priority"] = "issue2_boundary"
        selected.append(payload)
        per_dataset[dataset_key] += 1
        if len(selected) >= max_events:
            break
    return selected


def write_report(
    report_path: Path,
    summary: Dict[str, object],
    selected_rows: Sequence[Dict[str, object]],
) -> None:
    priority_counts = Counter(row["seed_priority"] for row in selected_rows)
    lines = [
        "# Minimal Finetune Seed Round 1",
        "",
        "## Why This Pack Exists",
        "- First use conservative auto rerun to rescue easy Issue-1 frames.",
        "- Then label only the residual hard cases plus strong boundary false positives.",
        "- Keep the first finetune round small to save annotation time.",
        "",
        "## Selection Summary",
        f"- Source hidden scan: `{summary['hidden_scan_csv']}`",
        f"- Source rerun results: `{summary['rerun_csv']}`",
        f"- Selected events: `{summary['selected_event_count']}`",
        f"- Selected datasets: `{summary['selected_dataset_count']}`",
        f"- Issue1 residual seeds: `{priority_counts.get('issue1_residual', 0)}`",
        f"- Issue2 boundary seeds: `{priority_counts.get('issue2_boundary', 0)}`",
        "",
        "## Pack Roots",
        f"- Audit subset: `{summary['audit_dir']}`",
        f"- Label pack: `{summary['pack_dir']}`",
        "",
        "## Suggested Use",
        "1. Do not relabel everything. Start from this small seed pack.",
        "2. Prioritize center-frame masks for the selected events.",
        "3. Save manual edits into `-mask_new` so later automation treats them as locked.",
        "4. After this first finetune round, rerun only the problematic datasets again.",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a small first-round finetune seed pack from hidden scan + rerun residuals.")
    parser.add_argument(
        "--root",
        default=r"D:\jvlei_project_all\new_xz_data\for binary_fromxz",
        help="Root directory containing dataset / dataset-mask pairs.",
    )
    parser.add_argument(
        "--hidden-events-csv",
        default=r"D:\jvlei_project_all\new_xz_data\for binary_fromxz\_seg_audit_report\hidden_bug_scan_round1\suspicious_events.csv",
        help="Hidden-bug scan suspicious_events.csv.",
    )
    parser.add_argument(
        "--rerun-results-csv",
        default=r"D:\jvlei_project_all\new_xz_data\for binary_fromxz\_seg_audit_report\hidden_issue1_highconf_rerun_round1\frame_rerun_results.csv",
        help="Frame-level rerun results from hidden issue1 high-confidence rerun.",
    )
    parser.add_argument(
        "--audit-output",
        default=r"D:\jvlei_project_all\new_xz_data\for binary_fromxz\_seg_audit_report\minimal_finetune_seed_round1",
        help="Output directory for the reduced suspicious_events subset.",
    )
    parser.add_argument(
        "--pack-output",
        default=r"D:\jvlei_project_all\new_xz_data\for binary_fromxz\_seg_audit_report\minimal_finetune_seed_pack_round1",
        help="Output directory for the label pack.",
    )
    parser.add_argument("--issue1-count", type=int, default=36, help="How many residual Issue-1 seed events to keep.")
    parser.add_argument("--issue2-count", type=int, default=24, help="How many boundary false-positive seed events to keep.")
    parser.add_argument("--issue1-max-per-dataset", type=int, default=4, help="Cap Issue-1 residual seeds per dataset.")
    parser.add_argument("--issue2-max-per-dataset", type=int, default=3, help="Cap Issue-2 boundary seeds per dataset.")
    parser.add_argument("--triage-context-radius", type=int, default=30, help="Storyboard context radius for the seed pack.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    hidden_events_csv = Path(args.hidden_events_csv).resolve()
    rerun_results_csv = Path(args.rerun_results_csv).resolve()
    audit_output = Path(args.audit_output).resolve()
    pack_output = Path(args.pack_output).resolve()
    audit_output.mkdir(parents=True, exist_ok=True)

    hidden_rows = read_csv_rows(hidden_events_csv)
    rerun_rows = read_csv_rows(rerun_results_csv)
    issue1_rows = select_issue1_residuals(
        hidden_rows,
        rerun_rows,
        max_events=args.issue1_count,
        max_per_dataset=args.issue1_max_per_dataset,
    )
    issue2_rows = select_issue2_boundaries(
        hidden_rows,
        max_events=args.issue2_count,
        max_per_dataset=args.issue2_max_per_dataset,
    )

    combined_map: Dict[Tuple[str, str, str, str], Dict[str, object]] = {}
    for row in issue1_rows + issue2_rows:
        key = (row["group_name"], row["dataset_name"], row["frame_name"], row["event_type"])
        combined_map[key] = row
    combined_rows = sorted(
        combined_map.values(),
        key=lambda row: (
            str(row["seed_priority"]),
            -float(row["severity_score"] or 0.0),
            row["group_name"],
            row["dataset_name"],
            row["frame_name"],
        ),
    )
    if not combined_rows:
        raise SystemExit("No minimal finetune seed events were selected.")

    write_csv_rows(audit_output / "suspicious_events.csv", combined_rows)
    summary = {
        "hidden_scan_csv": str(hidden_events_csv),
        "rerun_csv": str(rerun_results_csv),
        "selected_event_count": len(combined_rows),
        "selected_dataset_count": len({(row['group_name'], row['dataset_name']) for row in combined_rows}),
        "audit_dir": str(audit_output),
        "pack_dir": str(pack_output),
        "priority_counts": dict(Counter(row["seed_priority"] for row in combined_rows)),
        "event_type_counts": dict(Counter(row["event_type"] for row in combined_rows)),
    }
    (audit_output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(audit_output / "minimal_finetune_seed_round1_zh.md", summary, combined_rows)

    script_dir = Path(__file__).resolve().parent
    python_exe = sys.executable
    event_types = ["issue1_candidate", "issue2_boundary_false_positive_candidate"]
    run_step(
        [
            python_exe,
            str(script_dir / "build_suspicious_label_pack.py"),
            "--root",
            str(root),
            "--audit-dir",
            str(audit_output),
            "--output",
            str(pack_output),
            "--max-events",
            str(len(combined_rows)),
            "--max-events-per-dataset",
            str(args.issue1_max_per_dataset + args.issue2_max_per_dataset),
            "--event-types",
            *event_types,
        ]
    )
    run_step(
        [
            python_exe,
            str(script_dir / "build_triage_contact_sheets.py"),
            "--pack-root",
            str(pack_output),
            "--context-radius",
            str(args.triage_context_radius),
        ]
    )
    run_step([python_exe, str(script_dir / "build_triage_fill_table.py"), "--pack-root", str(pack_output)])


if __name__ == "__main__":
    main()
