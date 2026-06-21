from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import cv2
import numpy as np


DEFAULT_SMALL_COMPONENT_AREA = 50


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-run coarse binary cleanup steps over a Finetuning Binary queue session."
    )
    parser.add_argument("--session-path", required=True, help="Binary queue session JSON path.")
    parser.add_argument(
        "--coarse-status-csv",
        default="",
        help="Optional coarse status CSV path. Defaults next to the session JSON.",
    )
    parser.add_argument(
        "--initialize-missing",
        action="store_true",
        help="Copy missing save masks from mask_dir into save_dir.",
    )
    parser.add_argument(
        "--overwrite-initialization",
        action="store_true",
        help="When initializing, overwrite existing save masks instead of skipping them.",
    )
    parser.add_argument(
        "--remove-small-area",
        type=int,
        default=None,
        help="Remove connected components whose area is <= this threshold.",
    )
    parser.add_argument(
        "--keep-largest",
        action="store_true",
        help="Keep only the largest connected component for each frame.",
    )
    parser.add_argument(
        "--include-done",
        action="store_true",
        help="Also process datasets currently marked done in the queue session.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional cap on number of datasets to process.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print what would be processed. No files will be modified.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print machine-readable summary JSON at the end.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=10,
        help="Print a coarse progress line after every N datasets.",
    )
    parser.add_argument(
        "--skip-session-refresh",
        action="store_true",
        help="Use the session JSON as-is instead of recomputing counts via BinaryQueueCore.refresh_session.",
    )
    return parser.parse_args()


def natural_sort_key(value: str) -> List[object]:
    import re

    return [int(token) if token.isdigit() else token.lower() for token in re.split(r"(\d+)", str(value))]


def list_image_files(directory: Path) -> List[Path]:
    valid = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
    if not directory.is_dir():
        return []
    return sorted(
        [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in valid and not path.name.startswith(".")],
        key=lambda path: natural_sort_key(path.name),
    )


def read_csv_rows(csv_path: Path) -> List[Dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(csv_path: Path, rows: List[Dict[str, object]], fieldnames: List[str]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def default_coarse_status_path(session_path: Path) -> Path:
    return session_path.with_name(f"{session_path.stem}__coarse_status.csv")


def build_status_rows(session: Dict) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for dataset in session.get("datasets", []):
        rows.append(
            {
                "group_name": dataset["group_name"],
                "dataset_name": dataset["dataset_name"],
                "dataset_key": f"{dataset['group_name']}::{dataset['dataset_name']}",
                "queue_status": dataset.get("status", ""),
                "origin_count": dataset.get("origin_count", 0),
                "mask_count": dataset.get("mask_count", 0),
                "save_count_snapshot": dataset.get("save_count", 0),
                "origin_dir": dataset.get("origin_dir", ""),
                "mask_dir": dataset.get("mask_dir", ""),
                "save_dir": dataset.get("save_dir", ""),
                "coarse_initialized": "",
                "coarse_initialized_at": "",
                "region_rule": "",
                "clear_after_frame": "",
                "small_components_removed": "",
                "small_components_removed_at": "",
                "small_component_area_threshold": "",
                "largest_only_applied": "",
                "largest_only_applied_at": "",
                "qc_report_generated": "",
                "qc_report_generated_at": "",
                "promote_to_mask_new": "",
                "manual_notes": "",
                "last_batch_operation": "",
                "last_batch_operation_at": "",
            }
        )
    return rows


def load_or_initialize_status(csv_path: Path, session: Dict) -> List[Dict[str, object]]:
    existing_rows = read_csv_rows(csv_path)
    if not existing_rows:
        return build_status_rows(session)

    by_key = {str(row.get("dataset_key", "")).strip(): dict(row) for row in existing_rows}
    merged_rows: List[Dict[str, object]] = []
    for default_row in build_status_rows(session):
        key = str(default_row["dataset_key"])
        row = by_key.get(key, {})
        merged = dict(default_row)
        merged.update({k: v for k, v in row.items() if k in merged and v not in (None, "")})
        merged_rows.append(merged)
    return merged_rows


def keep_largest_component(mask: np.ndarray) -> np.ndarray:
    binary = (mask > 0).astype(np.uint8)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if num_labels <= 1:
        return binary
    largest_label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    output = np.zeros_like(binary)
    output[labels == largest_label] = 1
    return output


def dataset_frames(dataset: Dict) -> List[object]:
    from core.semi_auto_mask_tools import build_frame_paths

    original_files = [str(path) for path in list_image_files(Path(dataset["origin_dir"]))]
    mask_files = [str(path) for path in list_image_files(Path(dataset["mask_dir"]))]
    return build_frame_paths(original_files, mask_files, dataset["save_dir"])


def process_dataset(
    dataset: Dict,
    args: argparse.Namespace,
) -> Dict[str, object]:
    from core.semi_auto_mask_tools import (
        _load_binary_mask,
        _save_binary_mask,
        initialize_saved_masks_from_sources,
        mark_auto_generated_mask,
        remove_small_connected_components,
    )

    frames = dataset_frames(dataset)
    if not frames:
        return {
            "dataset_key": f"{dataset['group_name']}::{dataset['dataset_name']}",
            "processed_frames": 0,
            "init_copied": 0,
            "init_skipped": 0,
            "missing_source": 0,
            "small_removed_components": 0,
            "small_removed_pixels": 0,
            "largest_written_frames": 0,
        }

    init_copied = 0
    init_skipped = 0
    missing_source = 0
    if args.initialize_missing:
        if args.dry_run:
            for frame in frames:
                if frame.mask_path is None or not frame.mask_path.exists():
                    missing_source += 1
                elif frame.save_path.exists() and not args.overwrite_initialization:
                    init_skipped += 1
                else:
                    init_copied += 1
        else:
            result = initialize_saved_masks_from_sources(
                frames=frames,
                overwrite_existing=args.overwrite_initialization,
                progress_callback=None,
            )
            init_copied = int(result.copied_frames)
            init_skipped = int(result.skipped_existing_frames)
            missing_source = int(result.missing_source_frames)

    small_removed_components = 0
    small_removed_pixels = 0
    largest_written_frames = 0
    processed_frames = 0

    for frame in frames:
        input_path = frame.save_path if frame.save_path.exists() else frame.mask_path
        if input_path is None or not Path(input_path).exists():
            continue

        base_mask = _load_binary_mask(Path(input_path))
        if base_mask is None:
            continue

        updated_mask = base_mask.copy()
        changed = False

        if args.remove_small_area is not None:
            updated_mask, removed_components, removed_pixels = remove_small_connected_components(
                updated_mask,
                max_component_area=args.remove_small_area,
            )
            small_removed_components += int(removed_components)
            small_removed_pixels += int(removed_pixels)
            changed = True

        if args.keep_largest:
            updated_mask = keep_largest_component(updated_mask)
            largest_written_frames += 1
            changed = True

        if changed:
            processed_frames += 1
            if not args.dry_run:
                _save_binary_mask(frame.save_path, updated_mask)
                method_parts: List[str] = []
                if args.remove_small_area is not None:
                    method_parts.append(f"remove_small_le_{args.remove_small_area}")
                if args.keep_largest:
                    method_parts.append("keep_largest")
                mark_auto_generated_mask(frame.save_path, method="coarse_" + "_".join(method_parts))

    return {
        "dataset_key": f"{dataset['group_name']}::{dataset['dataset_name']}",
        "processed_frames": processed_frames,
        "init_copied": init_copied,
        "init_skipped": init_skipped,
        "missing_source": missing_source,
        "small_removed_components": small_removed_components,
        "small_removed_pixels": small_removed_pixels,
        "largest_written_frames": largest_written_frames,
    }


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))

    from core.binary_queue_core import BinaryQueueCore

    session_path = Path(args.session_path).resolve()
    if not session_path.exists():
        raise FileNotFoundError(f"Session JSON not found: {session_path}")

    if args.skip_session_refresh:
        session = json.loads(session_path.read_text(encoding="utf-8"))
    else:
        session = BinaryQueueCore.refresh_session(str(session_path))
    coarse_status_path = Path(args.coarse_status_csv).resolve() if args.coarse_status_csv else default_coarse_status_path(session_path)
    status_rows = load_or_initialize_status(coarse_status_path, session)
    status_by_key = {str(row["dataset_key"]): row for row in status_rows}

    datasets = list(session.get("datasets", []))
    if not args.include_done:
        datasets = [dataset for dataset in datasets if dataset.get("status") != "done"]
    if args.limit and args.limit > 0:
        datasets = datasets[: args.limit]

    summary_rows: List[Dict[str, object]] = []
    operations = []
    if args.initialize_missing:
        operations.append("initialize_missing")
    if args.remove_small_area is not None:
        operations.append(f"remove_small_le_{args.remove_small_area}")
    if args.keep_largest:
        operations.append("keep_largest")
    operation_name = "+".join(operations) if operations else "status_only"

    for dataset in datasets:
        dataset_index = len(summary_rows) + 1
        dataset_key = f"{dataset['group_name']}::{dataset['dataset_name']}"
        print(f"START [{dataset_index}/{len(datasets)}] {dataset_key}", flush=True)
        started = time.perf_counter()
        result = process_dataset(dataset, args)
        elapsed = time.perf_counter() - started
        summary_rows.append(result)

        row = status_by_key.get(dataset_key)
        if row is None:
            continue
        row["queue_status"] = dataset.get("status", "")
        row["save_count_snapshot"] = dataset.get("save_count", 0)
        if args.initialize_missing:
            row["coarse_initialized"] = "yes"
            row["coarse_initialized_at"] = now_text()
        if args.remove_small_area is not None:
            row["small_components_removed"] = "yes"
            row["small_components_removed_at"] = now_text()
            row["small_component_area_threshold"] = str(args.remove_small_area)
        if args.keep_largest:
            row["largest_only_applied"] = "yes"
            row["largest_only_applied_at"] = now_text()
        row["last_batch_operation"] = operation_name
        row["last_batch_operation_at"] = now_text()
        progress_every = max(1, int(args.progress_every))
        if dataset_index == 1 or dataset_index == len(datasets) or dataset_index % progress_every == 0:
            print(
                f"[{dataset_index}/{len(datasets)}] {dataset_key} | "
                f"frames={result['processed_frames']} init_copied={result['init_copied']} "
                f"small_removed={result['small_removed_components']} "
                f"largest_written={result['largest_written_frames']} "
                f"elapsed={elapsed:.1f}s",
                flush=True,
            )

    fieldnames = list(status_rows[0].keys()) if status_rows else []
    if fieldnames:
        write_csv_rows(coarse_status_path, status_rows, fieldnames)

    summary = {
        "session_path": str(session_path),
        "coarse_status_csv": str(coarse_status_path),
        "processed_dataset_count": len(datasets),
        "operation": operation_name,
        "dry_run": bool(args.dry_run),
        "datasets": summary_rows,
    }

    if args.print_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"Coarse status CSV: {coarse_status_path}")
        print(f"Processed datasets: {len(datasets)}")
        print(f"Operation: {operation_name}")
        if args.dry_run:
            print("Dry run: no files were modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
