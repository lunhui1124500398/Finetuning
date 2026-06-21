#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple


VALID_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def natural_sort_key(value: str) -> List[object]:
    return [int(token) if token.isdigit() else token.lower() for token in re.split(r"(\d+)", str(value))]


def iter_image_names(directory: Path) -> List[str]:
    return sorted(
        [path.name for path in directory.iterdir() if path.is_file() and path.suffix.lower() in VALID_EXTENSIONS],
        key=natural_sort_key,
    )


def read_csv(csv_path: Path) -> List[Dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(csv_path: Path, rows: Sequence[Dict[str, object]], fieldnames: Optional[Sequence[str]] = None) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        if rows:
            keys = list(rows[0].keys())
        else:
            keys = list(fieldnames or [])
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        if rows:
            writer.writerows(rows)


def copy_if_exists(source: Path, target: Path) -> bool:
    if not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a smaller pixel-refinement pack from parsed record.txt triage results.")
    parser.add_argument("--pack-root", required=True, help="Source triage pack root.")
    parser.add_argument("--output", required=True, help="Output root for the smaller refine pack.")
    parser.add_argument("--include-issue-codes", nargs="*", default=("1", "2", "5"), help="Issue codes that should go into the refine pack.")
    parser.add_argument("--context-radius", type=int, default=2, help="How many neighboring frames to keep on each side within the source pack.")
    args = parser.parse_args()

    pack_root = Path(args.pack_root).resolve()
    output_root = Path(args.output).resolve()
    meta_dir = pack_root / "_label_pack_meta"
    triage_index_rows = read_csv(meta_dir / "triage_index.csv")
    refine_rows = read_csv(meta_dir / "refine_candidates.csv")
    include_codes = {str(code).strip() for code in args.include_issue_codes if str(code).strip()}

    dataset_lookup = {(row["group_name"], row["dataset_name"]): row for row in triage_index_rows}
    selected_by_dataset: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    selected_issue_rows: List[Dict[str, object]] = []
    for row in refine_rows:
        if row.get("need_pixel_label") != "yes":
            continue
        if include_codes and row.get("issue_code") not in include_codes:
            continue
        key = (row["group_name"], row["dataset_name"])
        selected_by_dataset[key].add(row["frame_name"])
        selected_issue_rows.append(dict(row))

    if not selected_by_dataset:
        raise RuntimeError("No frames selected for refinement. Check record.txt parsing or include-issue-codes.")

    frame_manifest_rows: List[Dict[str, object]] = []
    for key, center_frames in sorted(selected_by_dataset.items(), key=lambda item: natural_sort_key(f"{item[0][0]}::{item[0][1]}")):
        dataset = dataset_lookup[key]
        origin_dir = Path(dataset["origin_dir"])
        mask_dir = Path(dataset["mask_dir"])
        save_dir = Path(dataset["save_dir"])
        frames = iter_image_names(origin_dir)
        frame_index = {name: idx for idx, name in enumerate(frames)}

        keep_frames: Set[str] = set()
        for center in center_frames:
            center_idx = frame_index.get(center)
            if center_idx is None:
                continue
            start = max(0, center_idx - max(0, args.context_radius))
            end = min(len(frames), center_idx + max(0, args.context_radius) + 1)
            keep_frames.update(frames[start:end])

        pack_group_dir = output_root / key[0]
        pack_origin_dir = pack_group_dir / key[1]
        pack_mask_dir = pack_group_dir / f"{key[1]}-mask"
        pack_save_dir = pack_group_dir / f"{key[1]}-mask_new"
        pack_origin_dir.mkdir(parents=True, exist_ok=True)
        pack_mask_dir.mkdir(parents=True, exist_ok=True)
        pack_save_dir.mkdir(parents=True, exist_ok=True)

        for frame_name in sorted(keep_frames, key=natural_sort_key):
            copied_origin = copy_if_exists(origin_dir / frame_name, pack_origin_dir / frame_name)
            copied_mask = copy_if_exists(mask_dir / frame_name, pack_mask_dir / frame_name)
            if copied_origin:
                frame_manifest_rows.append(
                    {
                        "group_name": key[0],
                        "dataset_name": key[1],
                        "frame_name": frame_name,
                        "frame_role": "center" if frame_name in center_frames else "context",
                        "source_origin": str(origin_dir / frame_name),
                        "source_mask": str(mask_dir / frame_name),
                        "pack_origin": str(pack_origin_dir / frame_name),
                        "pack_mask": str(pack_mask_dir / frame_name),
                        "copied_mask": copied_mask,
                    }
                )

    refine_meta_dir = output_root / "_label_pack_meta"
    write_csv(refine_meta_dir / "selected_for_refine.csv", selected_issue_rows)
    write_csv(refine_meta_dir / "frame_manifest.csv", frame_manifest_rows)

    summary = {
        "source_pack_root": str(pack_root),
        "selected_datasets": len(selected_by_dataset),
        "selected_center_frames": sum(len(value) for value in selected_by_dataset.values()),
        "copied_frames": len(frame_manifest_rows),
        "include_issue_codes": sorted(include_codes),
        "context_radius": args.context_radius,
    }
    (refine_meta_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
