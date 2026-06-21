#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from utils.cv_image_io import load_grayscale


VALID_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
ISSUE1_BUCKETS = ("low_contrast_or_washed_out", "dark_background", "dark_particle")


@dataclass
class DatasetPair:
    group_dir: Path
    dataset_name: str
    origin_dir: Path
    mask_dir: Path
    mask_new_dir: Optional[Path]
    hrtem_dir: Optional[Path]
    lrtem_dir: Optional[Path]


def natural_sort_key(value: str) -> List[object]:
    return [int(token) if token.isdigit() else token.lower() for token in re.split(r"(\d+)", str(value))]


def iter_image_names(directory: Path) -> List[str]:
    return sorted(
        [path.name for path in directory.iterdir() if path.is_file() and path.suffix.lower() in VALID_EXTENSIONS],
        key=natural_sort_key,
    )


def discover_dataset_pairs(root: Path) -> Dict[Tuple[str, str], DatasetPair]:
    pairs: Dict[Tuple[str, str], DatasetPair] = {}
    for group_dir in sorted([path for path in root.iterdir() if path.is_dir()], key=lambda p: natural_sort_key(p.name)):
        child_dirs = {path.name: path for path in group_dir.iterdir() if path.is_dir()}
        for dataset_name, origin_dir in sorted(child_dirs.items(), key=lambda item: natural_sort_key(item[0])):
            if dataset_name.endswith(("-mask", "-mask_new", "-hrtem", "-lrtem")):
                continue
            mask_dir = child_dirs.get(f"{dataset_name}-mask")
            if mask_dir is None:
                continue
            pairs[(group_dir.name, dataset_name)] = DatasetPair(
                group_dir=group_dir,
                dataset_name=dataset_name,
                origin_dir=origin_dir,
                mask_dir=mask_dir,
                mask_new_dir=child_dirs.get(f"{dataset_name}-mask_new"),
                hrtem_dir=child_dirs.get(f"{dataset_name}-hrtem"),
                lrtem_dir=child_dirs.get(f"{dataset_name}-lrtem"),
            )
    return pairs


def load_gray(path: Path) -> np.ndarray:
    image = load_grayscale(path)
    if image is None:
        raise FileNotFoundError(f"Failed to read image: {path}")
    return image


def collect_image_statistics(image: np.ndarray) -> Dict[str, float]:
    arr = image.astype(np.float32)
    return {
        "mean": float(arr.mean()),
        "std": float(arr.std()),
        "p5": float(np.percentile(arr, 5)),
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "dyn95_5": float(np.percentile(arr, 95) - np.percentile(arr, 5)),
        "lap_var": float(cv2.Laplacian(image, cv2.CV_32F).var()),
    }


def compute_mask_geometry(mask_binary: np.ndarray) -> Dict[str, float]:
    h, w = mask_binary.shape[:2]
    total = max(1, h * w)
    mask_uint8 = (mask_binary > 0).astype(np.uint8)
    component_count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask_uint8, connectivity=4)
    if component_count <= 1:
        return {
            "mask_ratio": 0.0,
            "largest_component_ratio": 0.0,
            "component_count": 0.0,
            "largest_width_ratio": 0.0,
            "largest_height_ratio": 0.0,
            "largest_aspect_ratio": 0.0,
            "largest_center_y_ratio": 0.5,
            "touch_left": 0.0,
            "touch_right": 0.0,
            "touch_top": 0.0,
            "touch_bottom": 0.0,
        }

    component_sizes = stats[1:, cv2.CC_STAT_AREA]
    comp_idx = int(np.argmax(component_sizes)) + 1
    x = int(stats[comp_idx, cv2.CC_STAT_LEFT])
    y = int(stats[comp_idx, cv2.CC_STAT_TOP])
    bw = int(stats[comp_idx, cv2.CC_STAT_WIDTH])
    bh = int(stats[comp_idx, cv2.CC_STAT_HEIGHT])
    area = int(stats[comp_idx, cv2.CC_STAT_AREA])
    center_y = float(centroids[comp_idx][1])

    return {
        "mask_ratio": float(mask_uint8.sum() / total),
        "largest_component_ratio": float(area / total),
        "component_count": float(component_count - 1),
        "largest_width_ratio": float(bw / max(1, w)),
        "largest_height_ratio": float(bh / max(1, h)),
        "largest_aspect_ratio": float(bw / max(1, bh)),
        "largest_center_y_ratio": float(center_y / max(1, h)),
        "touch_left": float(x <= 1),
        "touch_right": float(x + bw >= w - 1),
        "touch_top": float(y <= 1),
        "touch_bottom": float(y + bh >= h - 1),
    }


def percentile_or_default(values: np.ndarray, q: float, default: float) -> float:
    if values.size == 0:
        return default
    return float(np.percentile(values, q))


def choose_bucket_from_note(note_fields: Dict[str, str]) -> Optional[str]:
    if note_fields.get("issue2_frames") or note_fields.get("issue4_frames") or note_fields.get("issue5_frames"):
        return None
    note_lower = note_fields.get("note", "").lower()
    if "dark_background" in note_lower:
        return "dark_background"
    if "dark_particle" in note_lower:
        return "dark_particle"
    return "low_contrast_or_washed_out"


def parse_notes(notes_path: Path) -> Dict[str, Dict[str, str]]:
    blocks: Dict[str, Dict[str, str]] = {}
    current_key: Optional[str] = None
    current_fields: Dict[str, str] = {}
    for raw_line in notes_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            if current_key is not None:
                blocks[current_key] = current_fields
            current_key = line[1:-1]
            current_fields = {}
            continue
        if current_key is None or "=" not in line:
            continue
        key, value = line.split("=", 1)
        current_fields[key.strip()] = value.strip()
    if current_key is not None:
        blocks[current_key] = current_fields
    return blocks


def read_csv_rows(csv_path: Path) -> List[Dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def feature_vector(stats: Dict[str, float], mask_geom: Dict[str, float]) -> np.ndarray:
    return np.asarray(
        [
            stats["mean"],
            stats["std"],
            stats["dyn95_5"],
            stats["p5"],
            stats["p95"],
            mask_geom["mask_ratio"],
            mask_geom["largest_component_ratio"],
        ],
        dtype=np.float32,
    )


def build_issue1_bucket_model(
    dataset_lookup: Dict[Tuple[str, str], DatasetPair],
    reviewed_meta_dir: Path,
) -> Dict[str, object]:
    notes = parse_notes(reviewed_meta_dir / "triage_segment_notes.txt")
    segments = read_csv_rows(reviewed_meta_dir / "triage_segments.csv")

    training_rows: List[Tuple[str, np.ndarray]] = []
    for row in segments:
        bucket = choose_bucket_from_note(notes.get(row["segment_key"], {}))
        if bucket is None:
            continue
        dataset = dataset_lookup.get((row["group_name"], row["dataset_name"]))
        if dataset is None:
            continue
        for frame_name in [name.strip() for name in row["issue_frame_names"].split("|") if name.strip()]:
            origin_path = dataset.origin_dir / frame_name
            mask_path = dataset.mask_dir / frame_name
            if not (origin_path.exists() and mask_path.exists()):
                continue
            origin = load_gray(origin_path)
            mask = load_gray(mask_path) > 127
            training_rows.append((bucket, feature_vector(collect_image_statistics(origin), compute_mask_geometry(mask))))

    if not training_rows:
        return {
            "feature_mean": np.zeros(7, dtype=np.float32),
            "feature_std": np.ones(7, dtype=np.float32),
            "centroids": {bucket: np.zeros(7, dtype=np.float32) for bucket in ISSUE1_BUCKETS},
            "distance_thresholds": {bucket: 999.0 for bucket in ISSUE1_BUCKETS},
            "training_counts": {bucket: 0 for bucket in ISSUE1_BUCKETS},
        }

    all_features = np.stack([item[1] for item in training_rows], axis=0)
    feat_mean = all_features.mean(axis=0)
    feat_std = all_features.std(axis=0)
    feat_std = np.where(feat_std < 1e-6, 1.0, feat_std)

    centroids: Dict[str, np.ndarray] = {}
    thresholds: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    for bucket in ISSUE1_BUCKETS:
        bucket_features = np.stack([feature for label, feature in training_rows if label == bucket], axis=0)
        bucket_norm = (bucket_features - feat_mean) / feat_std
        centroid = bucket_norm.mean(axis=0)
        distances = np.linalg.norm(bucket_norm - centroid[None, :], axis=1)
        centroids[bucket] = centroid.astype(np.float32)
        thresholds[bucket] = float(np.percentile(distances, 90)) if distances.size else 999.0
        counts[bucket] = int(bucket_features.shape[0])

    return {
        "feature_mean": feat_mean.astype(np.float32),
        "feature_std": feat_std.astype(np.float32),
        "centroids": centroids,
        "distance_thresholds": thresholds,
        "training_counts": counts,
    }


def classify_issue1_bucket(
    model: Dict[str, object],
    stats: Dict[str, float],
    mask_geom: Dict[str, float],
) -> Tuple[str, float, float]:
    feat = feature_vector(stats, mask_geom)
    feat_mean = np.asarray(model["feature_mean"], dtype=np.float32)
    feat_std = np.asarray(model["feature_std"], dtype=np.float32)
    norm = (feat - feat_mean) / feat_std

    distances = {
        bucket: float(np.linalg.norm(norm - np.asarray(centroid, dtype=np.float32)))
        for bucket, centroid in dict(model["centroids"]).items()
    }
    ranked = sorted(distances.items(), key=lambda item: item[1])
    best_bucket, best_distance = ranked[0]
    second_distance = ranked[1][1] if len(ranked) > 1 else best_distance + 1.0
    threshold = float(dict(model["distance_thresholds"]).get(best_bucket, 999.0))

    if best_distance > threshold * 1.35 or (second_distance - best_distance) < 0.08:
        return "uncertain_review", best_distance, second_distance - best_distance
    return best_bucket, best_distance, second_distance - best_distance


def trailing_empty_run(mask_ratios: Sequence[float], tiny_floor: float) -> int:
    count = 0
    for value in reversed(mask_ratios):
        if value <= tiny_floor:
            count += 1
        else:
            break
    return count


def write_csv(csv_path: Path, rows: Sequence[Dict[str, object]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        if not rows:
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan the full binary dataset root for hidden issue candidates and auto-bucket them.")
    parser.add_argument("--root", required=True, help="Root directory containing dataset / dataset-mask folders.")
    parser.add_argument("--output-dir", required=True, help="Output directory for suspicious_events.csv and summaries.")
    parser.add_argument(
        "--reviewed-meta-dir",
        default=r"D:\jvlei_project_all\new_xz_data\for binary_fromxz\_seg_audit_report\suspicious_label_pack_top180\_label_pack_meta",
        help="Reviewed triage metadata used to learn rough Issue-1 bucket prototypes.",
    )
    parser.add_argument("--context-radius", type=int, default=3, help="Context radius when building event rows.")
    parser.add_argument("--boundary-score-threshold", type=float, default=4.0, help="Threshold for boundary false-positive candidates.")
    parser.add_argument("--weak-score-threshold", type=float, default=2.5, help="Threshold for Issue-1 weak-response candidates.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset_lookup = discover_dataset_pairs(root)
    if not dataset_lookup:
        raise RuntimeError(f"No dataset pairs found under {root}")

    bucket_model = build_issue1_bucket_model(dataset_lookup, Path(args.reviewed_meta_dir).resolve())

    event_rows: List[Dict[str, object]] = []
    dataset_rows: List[Dict[str, object]] = []
    summary = {
        "root": str(root),
        "dataset_count": len(dataset_lookup),
        "training_counts": dict(bucket_model["training_counts"]),
    }
    global_counts = Counter()

    for dataset_key, dataset in sorted(dataset_lookup.items(), key=lambda item: natural_sort_key(f"{item[0][0]}::{item[0][1]}")):
        origin_names = iter_image_names(dataset.origin_dir)
        mask_names = set(iter_image_names(dataset.mask_dir))
        common_names = [name for name in origin_names if name in mask_names]
        if not common_names:
            continue

        locked_names = set()
        if dataset.mask_new_dir is not None and dataset.mask_new_dir.exists():
            locked_names = set(iter_image_names(dataset.mask_new_dir))

        origin_stats_by_name: Dict[str, Dict[str, float]] = {}
        mask_geom_by_name: Dict[str, Dict[str, float]] = {}
        mask_ratios: List[float] = []
        means: List[float] = []
        stds: List[float] = []
        dyns: List[float] = []

        for name in common_names:
            origin = load_gray(dataset.origin_dir / name)
            mask_binary = load_gray(dataset.mask_dir / name) > 127
            stats = collect_image_statistics(origin)
            geom = compute_mask_geometry(mask_binary)
            origin_stats_by_name[name] = stats
            mask_geom_by_name[name] = geom
            mask_ratios.append(float(geom["mask_ratio"]))
            means.append(stats["mean"])
            stds.append(stats["std"])
            dyns.append(stats["dyn95_5"])

        mask_array = np.asarray(mask_ratios, dtype=np.float32)
        positive = mask_array[mask_array > 0]
        healthy_floor = max(0.01, percentile_or_default(positive, 35, 0.01) * 0.6) if positive.size else 0.01
        tiny_floor = max(0.001, healthy_floor * 0.12)
        mean_q15 = percentile_or_default(np.asarray(means, dtype=np.float32), 15, float(np.mean(means)))
        std_q20 = percentile_or_default(np.asarray(stds, dtype=np.float32), 20, float(np.mean(stds)))
        dyn_q20 = percentile_or_default(np.asarray(dyns, dtype=np.float32), 20, float(np.mean(dyns)))
        tail_run = trailing_empty_run(mask_ratios, tiny_floor)

        dataset_event_counts = Counter()
        locked_count = 0

        for idx, frame_name in enumerate(common_names):
            if frame_name in locked_names:
                locked_count += 1
                continue

            stats = origin_stats_by_name[frame_name]
            geom = mask_geom_by_name[frame_name]
            mask_ratio = float(geom["mask_ratio"])
            left = max(0, idx - args.context_radius)
            right = min(len(common_names), idx + args.context_radius + 1)
            prev_max = float(np.max(mask_array[left:idx])) if idx > left else 0.0
            next_max = float(np.max(mask_array[idx + 1:right])) if idx + 1 < right else 0.0
            neighbor_peak = max(prev_max, next_max)
            neighbor_min = min(prev_max, next_max)
            temporal_drop = max(0.0, neighbor_min - mask_ratio)
            temporal_jump = max(abs(mask_ratio - prev_max), abs(mask_ratio - next_max))

            boundary_score = 0.0
            if geom["largest_width_ratio"] >= 0.65:
                boundary_score += 1.5
            if geom["largest_aspect_ratio"] >= 4.0:
                boundary_score += 1.5
            if geom["largest_height_ratio"] <= 0.28:
                boundary_score += 1.0
            if geom["touch_left"] or geom["touch_right"]:
                boundary_score += 1.0
            if mask_ratio >= max(0.003, tiny_floor * 2.0):
                boundary_score += 0.5
            if geom["largest_center_y_ratio"] <= 0.42 or geom["largest_center_y_ratio"] >= 0.58:
                boundary_score += 0.5

            weak_score = 0.0
            weak_reasons: List[str] = []
            if mask_ratio <= 0.0:
                weak_score += 2.5
                weak_reasons.append("empty_mask")
            elif mask_ratio <= tiny_floor:
                weak_score += 2.0
                weak_reasons.append("tiny_mask")
            elif mask_ratio <= max(tiny_floor * 2.0, healthy_floor * 0.25):
                weak_score += 1.0
                weak_reasons.append("small_mask")

            if neighbor_peak >= healthy_floor and mask_ratio <= max(tiny_floor, neighbor_min * 0.12):
                weak_score += 2.0
                weak_reasons.append("internal_gap_like")
            elif neighbor_peak >= healthy_floor and mask_ratio <= neighbor_peak * 0.35:
                weak_score += 1.0
                weak_reasons.append("abrupt_drop_like")

            if stats["std"] <= std_q20 and stats["dyn95_5"] <= dyn_q20:
                weak_score += 1.0
                weak_reasons.append("flat_origin")
            elif stats["std"] <= std_q20 or stats["dyn95_5"] <= dyn_q20:
                weak_score += 0.5
                weak_reasons.append("partially_flat_origin")

            if stats["mean"] <= mean_q15:
                weak_score += 0.5
                weak_reasons.append("dark_origin")

            is_tail_empty = tail_run >= 3 and idx >= len(common_names) - tail_run and mask_ratio <= tiny_floor
            context_names = [name for name in common_names[left:right] if name not in locked_names]

            event_type = ""
            suggested_bucket = ""
            severity_score = 0.0
            bucket_distance = 0.0
            bucket_margin = 0.0
            reasons: List[str] = []

            if boundary_score >= args.boundary_score_threshold:
                event_type = "issue2_boundary_false_positive_candidate"
                severity_score = boundary_score + geom["largest_width_ratio"] + geom["largest_aspect_ratio"] * 0.1
                reasons = [
                    "wide_component",
                    "thin_component",
                    "edge_touch",
                ]
            elif is_tail_empty:
                event_type = "issue4_tail_empty_normal_candidate"
                severity_score = 0.5 + tail_run * 0.02
                reasons = ["tail_empty_run"]
            elif weak_score >= args.weak_score_threshold:
                event_type = "issue1_candidate"
                suggested_bucket, bucket_distance, bucket_margin = classify_issue1_bucket(bucket_model, stats, geom)
                severity_score = weak_score + temporal_drop * 4.0 + max(0.0, healthy_floor - mask_ratio) * 8.0
                reasons = weak_reasons[:]
                reasons.append(f"suggested_bucket={suggested_bucket}")
            else:
                continue

            dataset_event_counts[event_type] += 1
            global_counts[event_type] += 1
            event_rows.append(
                {
                    "group_name": dataset.group_dir.name,
                    "dataset_name": dataset.dataset_name,
                    "event_type": event_type,
                    "frame_name": frame_name,
                    "frame_index": idx + 1,
                    "mask_ratio": mask_ratio,
                    "prev_context_max": prev_max,
                    "next_context_max": next_max,
                    "severity_score": severity_score,
                    "reasons": "|".join(reasons),
                    "context_names": "|".join(context_names),
                    "origin_mean": stats["mean"],
                    "origin_std": stats["std"],
                    "origin_dyn95_5": stats["dyn95_5"],
                    "origin_lap_var": stats["lap_var"],
                    "largest_component_ratio": geom["largest_component_ratio"],
                    "largest_width_ratio": geom["largest_width_ratio"],
                    "largest_height_ratio": geom["largest_height_ratio"],
                    "largest_aspect_ratio": geom["largest_aspect_ratio"],
                    "largest_center_y_ratio": geom["largest_center_y_ratio"],
                    "boundary_score": boundary_score,
                    "weak_score": weak_score,
                    "temporal_drop": temporal_drop,
                    "temporal_jump": temporal_jump,
                    "healthy_floor": healthy_floor,
                    "tiny_floor": tiny_floor,
                    "suggested_bucket": suggested_bucket,
                    "bucket_distance": bucket_distance,
                    "bucket_margin": bucket_margin,
                    "source_origin": str(dataset.origin_dir / frame_name),
                    "source_mask": str(dataset.mask_dir / frame_name),
                    "source_mask_new": str(dataset.mask_new_dir / frame_name) if dataset.mask_new_dir is not None else "",
                    "human_locked": 0,
                }
            )

        primary_issue = "none"
        if dataset_event_counts:
            primary_issue = dataset_event_counts.most_common(1)[0][0]
        dataset_rows.append(
            {
                "group_name": dataset.group_dir.name,
                "dataset_name": dataset.dataset_name,
                "frame_count": len(common_names),
                "locked_frame_count": locked_count,
                "issue1_candidate_count": dataset_event_counts["issue1_candidate"],
                "issue2_candidate_count": dataset_event_counts["issue2_boundary_false_positive_candidate"],
                "issue4_candidate_count": dataset_event_counts["issue4_tail_empty_normal_candidate"],
                "tail_empty_run": tail_run,
                "healthy_floor": healthy_floor,
                "tiny_floor": tiny_floor,
                "mean_origin_mean": float(np.mean(means)),
                "mean_origin_std": float(np.mean(stds)),
                "mean_origin_dyn95_5": float(np.mean(dyns)),
                "suggested_primary_issue": primary_issue,
            }
        )

    event_rows = sorted(
        event_rows,
        key=lambda row: (-float(row["severity_score"]), row["group_name"], row["dataset_name"], row["frame_name"]),
    )
    dataset_rows = sorted(
        dataset_rows,
        key=lambda row: (
            -int(row["issue1_candidate_count"]),
            -int(row["issue2_candidate_count"]),
            row["group_name"],
            row["dataset_name"],
        ),
    )

    write_csv(output_dir / "suspicious_events.csv", event_rows)
    write_csv(output_dir / "dataset_summary.csv", dataset_rows)

    summary.update(
        {
            "event_count": len(event_rows),
            "event_type_counts": dict(global_counts),
            "dataset_with_any_candidates": int(sum(1 for row in dataset_rows if (int(row["issue1_candidate_count"]) + int(row["issue2_candidate_count"]) + int(row["issue4_candidate_count"])) > 0)),
        }
    )
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
