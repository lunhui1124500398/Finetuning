#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from utils.cv_image_io import cv_imwrite, load_grayscale


VALID_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


@dataclass
class DatasetPair:
    group_dir: Path
    dataset_name: str
    origin_dir: Path
    mask_dir: Path
    hrtem_dir: Optional[Path]
    lrtem_dir: Optional[Path]


def natural_sort_key(value: str) -> List[object]:
    return [int(token) if token.isdigit() else token.lower() for token in re.split(r"(\d+)", str(value))]


def iter_image_names(directory: Path) -> List[str]:
    return sorted(
        [path.name for path in directory.iterdir() if path.is_file() and path.suffix.lower() in VALID_EXTENSIONS],
        key=natural_sort_key,
    )


def discover_dataset_pairs(root: Path) -> List[DatasetPair]:
    pairs: List[DatasetPair] = []
    for group_dir in sorted([path for path in root.iterdir() if path.is_dir()], key=lambda p: natural_sort_key(p.name)):
        child_dirs = {path.name: path for path in group_dir.iterdir() if path.is_dir()}
        for dataset_name, origin_dir in sorted(child_dirs.items(), key=lambda item: natural_sort_key(item[0])):
            if dataset_name.endswith(("-mask", "-mask_new", "-hrtem", "-lrtem")):
                continue
            mask_dir = child_dirs.get(f"{dataset_name}-mask")
            if mask_dir is None:
                continue
            pairs.append(
                DatasetPair(
                    group_dir=group_dir,
                    dataset_name=dataset_name,
                    origin_dir=origin_dir,
                    mask_dir=mask_dir,
                    hrtem_dir=child_dirs.get(f"{dataset_name}-hrtem"),
                    lrtem_dir=child_dirs.get(f"{dataset_name}-lrtem"),
                )
            )
    return pairs


def count_nonzero_ratio(mask_path: Path) -> float:
    mask = load_grayscale(mask_path)
    if mask is None:
        raise FileNotFoundError(f"Failed to read mask: {mask_path}")
    return float(cv2.countNonZero(mask) / float(mask.shape[0] * mask.shape[1]))


def compute_image_stats(image_path: Path) -> Dict[str, float]:
    image = load_grayscale(image_path)
    if image is None:
        raise FileNotFoundError(f"Failed to read image: {image_path}")
    arr = image.astype(np.float32)
    return {
        "mean": float(arr.mean()),
        "std": float(arr.std()),
        "dyn95_5": float(np.percentile(arr, 95) - np.percentile(arr, 5)),
        "lap_var": float(cv2.Laplacian(image, cv2.CV_32F).var()),
    }


def median_or_zero(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return float(np.median(np.asarray(values, dtype=np.float32)))


def classify_frame_reasons(
    center_name: str,
    dataset: DatasetPair,
    context_names: Sequence[str],
) -> Tuple[List[str], Dict[str, float]]:
    reasons: List[str] = []
    debug_stats: Dict[str, float] = {}

    for prefix, directory in (
        ("origin", dataset.origin_dir),
        ("hrtem", dataset.hrtem_dir),
        ("lrtem", dataset.lrtem_dir),
    ):
        if directory is None or not directory.is_dir():
            continue

        center_stats = compute_image_stats(directory / center_name)
        neighbor_stats = [
            compute_image_stats(directory / name)
            for name in context_names
            if name != center_name and (directory / name).exists()
        ]
        if not neighbor_stats:
            continue

        mean_neighbor_std = median_or_zero([stats["std"] for stats in neighbor_stats])
        mean_neighbor_dyn = median_or_zero([stats["dyn95_5"] for stats in neighbor_stats])
        mean_neighbor_lap = median_or_zero([stats["lap_var"] for stats in neighbor_stats])

        debug_stats[f"{prefix}_std"] = center_stats["std"]
        debug_stats[f"{prefix}_dyn95_5"] = center_stats["dyn95_5"]
        debug_stats[f"{prefix}_lap_var"] = center_stats["lap_var"]

        if mean_neighbor_std > 0 and mean_neighbor_dyn > 0:
            if center_stats["std"] < mean_neighbor_std * 0.72 and center_stats["dyn95_5"] < mean_neighbor_dyn * 0.72:
                reasons.append(f"low_contrast_{prefix}")
        if mean_neighbor_lap > 0 and center_stats["lap_var"] < mean_neighbor_lap * 0.55:
            reasons.append(f"blurred_{prefix}")

    if not reasons:
        reasons.append("temporal_inconsistency_or_threshold")
    return reasons, debug_stats


def make_preview(
    dataset: DatasetPair,
    window_names: Sequence[str],
    area_by_name: Dict[str, float],
    event_name: str,
    preview_path: Path,
) -> None:
    top_row = []
    bottom_row = []

    for name in window_names:
        origin = load_grayscale(dataset.origin_dir / name)
        mask = load_grayscale(dataset.mask_dir / name)
        if origin is None or mask is None:
            continue

        origin_show = cv2.cvtColor(cv2.resize(origin, (160, 160), interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)
        mask_show = cv2.cvtColor(cv2.resize(mask, (160, 160), interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)

        color = (0, 0, 255) if name == event_name else (0, 255, 255)
        cv2.putText(origin_show, name, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1)
        cv2.putText(mask_show, f"{area_by_name.get(name, 0.0):.4f}", (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1)

        top_row.append(origin_show)
        bottom_row.append(mask_show)

    if top_row and bottom_row:
        preview = cv2.vconcat([cv2.hconcat(top_row), cv2.hconcat(bottom_row)])
        if not cv_imwrite(preview_path, preview):
            raise OSError(f"Failed to write preview: {preview_path}")


def find_suspicious_events(
    dataset: DatasetPair,
    *,
    context_radius: int,
    tiny_abs_threshold: float,
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    origin_names = iter_image_names(dataset.origin_dir)
    mask_names = set(iter_image_names(dataset.mask_dir))
    names = [name for name in origin_names if name in mask_names]
    if not names:
        return [], {}

    areas = np.asarray([count_nonzero_ratio(dataset.mask_dir / name) for name in names], dtype=np.float32)
    positive = areas[areas > 0]
    healthy_floor = max(0.01, float(np.percentile(positive, 35)) * 0.6) if positive.size else 0.01
    tiny_floor = max(tiny_abs_threshold, healthy_floor * 0.12)

    suspicious: List[Dict[str, object]] = []

    def local_max(left: int, right: int) -> float:
        if left >= right:
            return 0.0
        return float(np.max(areas[left:right]))

    for idx, name in enumerate(names):
        area = float(areas[idx])
        left = max(0, idx - context_radius)
        right = min(len(names), idx + context_radius + 1)
        prev_max = local_max(left, idx)
        next_max = local_max(idx + 1, right)
        local_context = names[left:right]

        if idx >= context_radius and idx + context_radius < len(names):
            if prev_max >= healthy_floor and next_max >= healthy_floor:
                if area <= max(tiny_floor, min(prev_max, next_max) * 0.12):
                    suspicious.append(
                        {
                            "event_type": "internal_gap",
                            "frame_name": name,
                            "frame_index": idx,
                            "mask_ratio": area,
                            "prev_context_max": prev_max,
                            "next_context_max": next_max,
                            "context_names": local_context,
                        }
                    )
                    continue
                if area <= min(prev_max, next_max) * 0.35 and min(prev_max, next_max) >= healthy_floor * 1.2:
                    suspicious.append(
                        {
                            "event_type": "abrupt_drop",
                            "frame_name": name,
                            "frame_index": idx,
                            "mask_ratio": area,
                            "prev_context_max": prev_max,
                            "next_context_max": next_max,
                            "context_names": local_context,
                        }
                    )

    trailing_empty = 0
    for value in areas[::-1]:
        if float(value) <= tiny_floor:
            trailing_empty += 1
        else:
            break

    summary = {
        "frame_count": len(names),
        "positive_frame_count": int(np.count_nonzero(areas > tiny_floor)),
        "healthy_floor": healthy_floor,
        "tiny_floor": tiny_floor,
        "median_positive_area": float(np.median(positive)) if positive.size else 0.0,
        "trailing_empty_run": trailing_empty,
        "all_names": names,
        "areas": areas.tolist(),
    }
    return suspicious, summary


def write_csv(csv_path: Path, rows: Sequence[Dict[str, object]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        if not rows:
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_template_csv(csv_path: Path, fieldnames: Sequence[str]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()


def with_review_columns(rows: Sequence[Dict[str, object]], extra_fields: Sequence[str]) -> List[Dict[str, object]]:
    annotated: List[Dict[str, object]] = []
    for row in rows:
        enriched = dict(row)
        for field in extra_fields:
            enriched[field] = ""
        annotated.append(enriched)
    return annotated


def write_markdown(report_path: Path, summary_rows: Sequence[Dict[str, object]], event_rows: Sequence[Dict[str, object]], root: Path) -> None:
    top_datasets = sorted(summary_rows, key=lambda row: (-int(row["internal_gap_count"]), -int(row["abrupt_drop_count"])))[:20]
    top_events = sorted(event_rows, key=lambda row: (-float(row["severity_score"]), row["dataset_name"], row["frame_name"]))[:30]

    lines = [
        "# Binary Segmentation Audit Report",
        "",
        f"- Root: `{root}`",
        f"- Dataset pairs scanned: `{len(summary_rows)}`",
        f"- Suspicious events exported: `{len(event_rows)}`",
        "",
        "## What Was Flagged",
        "",
        "- `internal_gap`: middle frames whose mask collapses to empty or tiny area while nearby frames still have clear masks.",
        "- `abrupt_drop`: middle frames whose mask area suddenly drops far below nearby frames, but not necessarily to zero.",
        "- `trailing_empty_run`: ending empty stretches were recorded separately, because the user said they are often normal near sequence tails.",
        "",
        "## Key Interpretation",
        "",
        "- Rerunning the exact same segmentation on the exact same inputs will not usually \"converge\" to a different result. The current pipeline is effectively deterministic.",
        "- The most actionable failure mode is short internal gaps surrounded by healthy masks. Those are better handled by targeted rerun, temporal repair, or manual refinement.",
        "- If no modality looks blurrier or lower-contrast than its neighbors, the likely cause is temporal instability or thresholding, not simple image darkness.",
        "",
        "## Top Problem Datasets",
        "",
        "| Dataset | Frames | Internal gaps | Abrupt drops | Trailing empty run | Healthy floor |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]

    for row in top_datasets:
        lines.append(
            f"| `{row['dataset_name']}` | {row['frame_count']} | {row['internal_gap_count']} | {row['abrupt_drop_count']} | {row['trailing_empty_run']} | {float(row['healthy_floor']):.4f} |"
        )

    lines.extend(
        [
            "",
            "## Top Suspicious Events",
            "",
            "| Dataset | Frame | Type | Mask ratio | Prev max | Next max | Reasons |",
            "| --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )

    for row in top_events:
        lines.append(
            f"| `{row['dataset_name']}` | `{row['frame_name']}` | `{row['event_type']}` | {float(row['mask_ratio']):.4f} | {float(row['prev_context_max']):.4f} | {float(row['next_context_max']):.4f} | `{row['reasons']}` |"
        )

    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit binary segmentation outputs and collect suspicious datasets.")
    parser.add_argument("--root", required=True, help="Root directory containing paired dataset / dataset-mask folders.")
    parser.add_argument("--output", required=True, help="Directory to save CSVs, previews, and markdown report.")
    parser.add_argument("--context-radius", type=int, default=3, help="How many frames to look on each side when checking continuity.")
    parser.add_argument("--tiny-threshold", type=float, default=0.001, help="Minimum absolute mask ratio considered non-empty.")
    parser.add_argument("--max-previews", type=int, default=240, help="Maximum number of suspicious event previews to export.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output = Path(args.output).resolve()
    preview_dir = output / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)

    dataset_pairs = discover_dataset_pairs(root)
    if not dataset_pairs:
        raise RuntimeError(f"No dataset / mask pairs found under {root}")
    dataset_lookup = {(pair.group_dir.name, pair.dataset_name): pair for pair in dataset_pairs}

    summary_rows: List[Dict[str, object]] = []
    event_rows: List[Dict[str, object]] = []

    for pair_index, dataset in enumerate(dataset_pairs, start=1):
        events, summary = find_suspicious_events(
            dataset,
            context_radius=args.context_radius,
            tiny_abs_threshold=args.tiny_threshold,
        )
        if not summary:
            continue

        internal_gap_count = sum(1 for event in events if event["event_type"] == "internal_gap")
        abrupt_drop_count = sum(1 for event in events if event["event_type"] == "abrupt_drop")

        summary_rows.append(
            {
                "group_name": dataset.group_dir.name,
                "dataset_name": dataset.dataset_name,
                "origin_dir": str(dataset.origin_dir),
                "mask_dir": str(dataset.mask_dir),
                "hrtem_dir": str(dataset.hrtem_dir) if dataset.hrtem_dir else "",
                "lrtem_dir": str(dataset.lrtem_dir) if dataset.lrtem_dir else "",
                "frame_count": summary["frame_count"],
                "positive_frame_count": summary["positive_frame_count"],
                "internal_gap_count": internal_gap_count,
                "abrupt_drop_count": abrupt_drop_count,
                "trailing_empty_run": summary["trailing_empty_run"],
                "healthy_floor": summary["healthy_floor"],
                "tiny_floor": summary["tiny_floor"],
                "median_positive_area": summary["median_positive_area"],
            }
        )

        area_by_name = dict(zip(summary["all_names"], summary["areas"]))

        for event in events:
            reasons, debug_stats = classify_frame_reasons(
                center_name=str(event["frame_name"]),
                dataset=dataset,
                context_names=list(event["context_names"]),
            )
            severity_score = (
                float(event["prev_context_max"]) + float(event["next_context_max"]) - float(event["mask_ratio"]) * 2.0
            )

            event_rows.append(
                {
                    "group_name": dataset.group_dir.name,
                    "dataset_name": dataset.dataset_name,
                    "event_type": event["event_type"],
                    "frame_name": event["frame_name"],
                    "frame_index": event["frame_index"],
                    "mask_ratio": event["mask_ratio"],
                    "prev_context_max": event["prev_context_max"],
                    "next_context_max": event["next_context_max"],
                    "severity_score": severity_score,
                    "reasons": "|".join(reasons),
                    "context_names": "|".join(event["context_names"]),
                    **debug_stats,
                }
            )

        if pair_index % 50 == 0:
            print(f"Scanned {pair_index}/{len(dataset_pairs)} datasets...")

    sorted_events = sorted(event_rows, key=lambda row: (-float(row["severity_score"]), row["dataset_name"], row["frame_name"]))
    for index, event in enumerate(sorted_events[: args.max_previews], start=1):
        dataset = dataset_lookup[(str(event["group_name"]), str(event["dataset_name"]))]
        context_names = str(event["context_names"]).split("|")
        area_by_name = {}
        for name in context_names:
            mask_path = dataset.mask_dir / name
            if mask_path.exists():
                area_by_name[name] = count_nonzero_ratio(mask_path)
        preview_name = f"{index:04d}_{event['group_name']}_{event['dataset_name']}_{event['frame_name']}.png"
        make_preview(dataset, context_names, area_by_name, str(event["frame_name"]), preview_dir / preview_name)

    write_csv(output / "dataset_summary.csv", sorted(summary_rows, key=lambda row: (-int(row["internal_gap_count"]), -int(row["abrupt_drop_count"]), row["dataset_name"])))
    write_csv(output / "suspicious_events.csv", sorted_events)
    write_csv(
        output / "dataset_review_template.csv",
        with_review_columns(
            sorted(summary_rows, key=lambda row: (-int(row["internal_gap_count"]), -int(row["abrupt_drop_count"]), row["dataset_name"])),
            ("user_priority", "user_issue_type", "user_need_refine", "user_need_finetune", "user_notes"),
        ),
    )
    write_csv(
        output / "event_review_template.csv",
        with_review_columns(
            sorted_events,
            ("user_keep", "user_issue_type", "user_need_pixel_label", "user_need_rerun", "user_notes"),
        ),
    )
    write_template_csv(
        output / "manual_frame_requests_template.csv",
        (
            "group_name",
            "dataset_name",
            "frame_name",
            "user_issue_type",
            "user_need_pixel_label",
            "user_need_rerun",
            "user_notes",
        ),
    )
    write_markdown(output / "audit_report.md", summary_rows, sorted_events, root)

    summary = {
        "root": str(root),
        "dataset_pairs": len(summary_rows),
        "datasets_with_internal_gaps": int(sum(1 for row in summary_rows if int(row["internal_gap_count"]) > 0)),
        "datasets_with_abrupt_drops": int(sum(1 for row in summary_rows if int(row["abrupt_drop_count"]) > 0)),
        "total_suspicious_events": len(sorted_events),
        "exported_previews": min(args.max_previews, len(sorted_events)),
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved audit report to {output}")


if __name__ == "__main__":
    main()
