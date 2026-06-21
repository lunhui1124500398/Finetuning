from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple


DEFAULT_PRIORITY_CSV = (
    r"D:\jvlei_project_all\20260408_10000test\analysis_runs\comparison_reports_20260409\priority_manual_review_groups.csv"
)
DEFAULT_ROOT_DIR = r"D:\jvlei_project_all\new_xz_data\for binary_fromxz"
DEFAULT_SESSION_DIR = r"D:\jvlei_project_all\new_xz_data\for binary_fromxz\_finetuning_batch_sessions"


def read_csv_rows(csv_path: Path) -> List[Dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize_float(value: str, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def normalize_int(value: str, fallback: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def dedupe_priority_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    unique_rows: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for row in rows:
        key = (str(row.get("Dataset_Name", "")).strip(), str(row.get("Source_Group", "")).strip())
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    return unique_rows


def build_manifest_rows(rows: List[Dict[str, str]]) -> List[Dict[str, object]]:
    manifest_rows: List[Dict[str, object]] = []
    for rank, row in enumerate(rows, start=1):
        dataset_name = str(row["Dataset_Name"]).strip()
        source_group = str(row["Source_Group"]).strip()
        selection_entry = f"{dataset_name}/{source_group}"
        manifest_rows.append(
            {
                "review_rank": rank,
                "selection_entry": selection_entry,
                "group_name": dataset_name,
                "dataset_name": source_group,
                "analysis_source": str(row.get("Analysis", "")).strip(),
                "n_rows": normalize_int(row.get("N", 0)),
                "cluster_ii": normalize_int(row.get("ClusterII", 0)),
                "cluster_iii": normalize_int(row.get("ClusterIII", 0)),
                "rod_complex_balance": normalize_float(row.get("RodComplexBalance", 0.0)),
                "mask_new_frac": normalize_float(row.get("MaskNewFrac", 0.0)),
            }
        )
    return manifest_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a Finetuning Binary queue session for datasets that most likely drag K=3."
    )
    parser.add_argument("--priority-csv", default=DEFAULT_PRIORITY_CSV, help="priority_manual_review_groups.csv path.")
    parser.add_argument("--root-dir", default=DEFAULT_ROOT_DIR, help="for binary_fromxz root directory.")
    parser.add_argument("--session-dir", default=DEFAULT_SESSION_DIR, help="Output directory for Binary queue session JSON.")
    parser.add_argument("--session-name", default="", help="Optional session JSON file name.")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on number of unique dataset pairs.")
    parser.add_argument("--save-suffix", default="-mask_new", help="Editable suffix used by Finetuning.")
    parser.add_argument(
        "--manifest-prefix",
        default="K3_DRAGGER_REVIEW_MANIFEST",
        help="Prefix for the companion CSV/JSON manifest files.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))
    from core.binary_queue_core import BinaryQueueCore

    priority_csv = Path(args.priority_csv).resolve()
    if not priority_csv.exists():
        raise FileNotFoundError(f"Priority CSV not found: {priority_csv}")

    rows = dedupe_priority_rows(read_csv_rows(priority_csv))
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]
    if not rows:
        raise RuntimeError("No unique dataset pairs were found in the priority CSV.")

    manifest_rows = build_manifest_rows(rows)
    selection_entries = [row["selection_entry"] for row in manifest_rows]

    timestamp = datetime.now().strftime("%Y%m%d")
    session_name = args.session_name.strip()
    if not session_name:
        session_name = f"K3_DRAGGER_BINARY_QUEUE_SESSION__FOR_BINARY_FROMXZ__{len(selection_entries)}_DATASETS__{timestamp}.json"

    session_dir = Path(args.session_dir).resolve()
    session_dir.mkdir(parents=True, exist_ok=True)
    session_path = BinaryQueueCore.create_session(
        args.root_dir,
        save_suffix=args.save_suffix,
        session_dir=str(session_dir),
        selection_entries=selection_entries,
        session_name=session_name,
    )
    session = BinaryQueueCore.read_session(session_path)
    progress = BinaryQueueCore.summarize_progress(session)

    manifest_prefix = f"{args.manifest_prefix}__{len(selection_entries)}_DATASETS__{timestamp}"
    csv_path = session_dir / f"{manifest_prefix}.csv"
    json_path = session_dir / f"{manifest_prefix}.json"
    summary_path = session_dir / f"{manifest_prefix}__SUMMARY.json"

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest_rows[0].keys()))
        writer.writeheader()
        writer.writerows(manifest_rows)

    json_path.write_text(json.dumps(manifest_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "priority_csv": str(priority_csv),
        "root_dir": str(Path(args.root_dir).resolve()),
        "session_path": str(Path(session_path).resolve()),
        "dataset_count": len(selection_entries),
        "progress": progress,
        "selection_entries": selection_entries,
        "manifest_csv": str(csv_path.resolve()),
        "manifest_json": str(json_path.resolve()),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
