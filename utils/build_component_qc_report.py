from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import AutoMinorLocator

from utils.cv_image_io import load_grayscale


PLOT_FONT_SIZE = 26
PLOT_COLORS = {
    "blue": "#0072B2",
    "orange": "#D55E00",
    "green": "#009E73",
    "sky": "#56B4E9",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build connected-component QC reports for a Finetuning Binary queue session."
    )
    parser.add_argument("--session-path", required=True, help="Binary queue session JSON path.")
    parser.add_argument(
        "--output-dir",
        default="",
        help="Optional report output directory. Defaults next to the session JSON.",
    )
    parser.add_argument(
        "--small-area-threshold",
        type=int,
        default=50,
        help="Connected components with area <= this threshold are counted as small components.",
    )
    parser.add_argument(
        "--fallback-to-mask-dir",
        action="store_true",
        help="When save_dir is missing a frame, fall back to mask_dir for analysis.",
    )
    parser.add_argument(
        "--include-done",
        action="store_true",
        help="Also analyze datasets currently marked done in the queue session.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional cap on number of datasets to analyze.",
    )
    parser.add_argument(
        "--coarse-status-csv",
        default="",
        help="Optional coarse status CSV path to update with qc_report_generated=yes.",
    )
    return parser.parse_args()


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def natural_sort_key(value: str) -> List[object]:
    return [int(token) if token.isdigit() else token.lower() for token in re.split(r"(\d+)", str(value))]


def list_image_files(directory: Path) -> List[Path]:
    valid = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
    if not directory.is_dir():
        return []
    return sorted(
        [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in valid and not path.name.startswith(".")],
        key=lambda path: natural_sort_key(path.name),
    )


def choose_frame_names(dataset: Dict) -> List[str]:
    origin_names = [path.name for path in list_image_files(Path(dataset["origin_dir"]))]
    if origin_names:
        return origin_names
    mask_names = [path.name for path in list_image_files(Path(dataset["mask_dir"]))]
    if mask_names:
        return mask_names
    return [path.name for path in list_image_files(Path(dataset["save_dir"]))]


def default_output_dir(session_path: Path) -> Path:
    return session_path.with_name(f"{session_path.stem}__component_qc")


def default_coarse_status_path(session_path: Path) -> Path:
    return session_path.with_name(f"{session_path.stem}__coarse_status.csv")


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


def sanitize_filename(value: str, max_len: int = 80) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", str(value)).strip().rstrip(". ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = "unnamed"
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip(" ._")
    return cleaned or "unnamed"


def load_binary_mask(path: Path) -> Optional[np.ndarray]:
    image = load_grayscale(path)
    if image is None:
        return None
    return (image > 127).astype(np.uint8)


def component_sizes(mask: np.ndarray) -> List[int]:
    binary = (mask > 0).astype(np.uint8)
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    sizes = stats[1:, cv2.CC_STAT_AREA].astype(int).tolist() if num_labels > 1 else []
    sizes.sort(reverse=True)
    return sizes


def metrics_from_sizes(sizes: List[int], small_area_threshold: int) -> Dict[str, float]:
    sizes = sorted([int(size) for size in sizes if int(size) > 0], reverse=True)
    total_area = int(sum(sizes))
    largest = int(sizes[0]) if sizes else 0
    second = int(sizes[1]) if len(sizes) > 1 else 0
    small_sizes = [size for size in sizes if size <= small_area_threshold]
    return {
        "component_count": int(len(sizes)),
        "total_foreground_area": total_area,
        "largest_component_area": largest,
        "second_component_area": second,
        "largest_component_fraction": float(largest / total_area) if total_area > 0 else 0.0,
        "small_component_count": int(len(small_sizes)),
        "small_component_pixels": int(sum(small_sizes)),
        "empty_frame": int(total_area == 0),
        "multi_component": int(len(sizes) > 1),
    }


def component_metrics(mask: np.ndarray, small_area_threshold: int) -> Tuple[Dict[str, float], List[int]]:
    sizes = component_sizes(mask)
    return metrics_from_sizes(sizes, small_area_threshold), sizes


def percentile_or_zero(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=float), q))


def median_or_zero(values: List[float]) -> float:
    if not values:
        return 0.0
    return float(np.median(np.asarray(values, dtype=float)))


def dataset_anomaly_score(summary: Dict[str, object]) -> float:
    analyzed = max(int(summary["analyzed_frames"]), 1)
    multi_ratio = float(summary["multi_component_ratio"])
    small_ratio = float(summary["frames_with_small_components"]) / analyzed
    empty_ratio = float(summary["empty_frames"]) / analyzed
    second_ratio = float(summary["frames_with_second_component"]) / analyzed
    return round(multi_ratio * 0.35 + small_ratio * 0.30 + second_ratio * 0.20 + empty_ratio * 0.15, 6)


def apply_plot_defaults() -> None:
    plt.rcParams.update(
        {
            "font.family": "Arial",
            "font.size": PLOT_FONT_SIZE,
            "axes.labelsize": PLOT_FONT_SIZE,
            "axes.titlesize": PLOT_FONT_SIZE,
            "axes.titleweight": "bold",
            "xtick.labelsize": PLOT_FONT_SIZE,
            "ytick.labelsize": PLOT_FONT_SIZE,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
        }
    )


def style_axis(ax, use_minor_x: bool = True, use_minor_y: bool = True) -> None:
    for spine in ax.spines.values():
        spine.set_linewidth(2.0)
    ax.tick_params(
        axis="both",
        which="major",
        direction="out",
        width=1.0,
        length=9,
        top=False,
        right=False,
    )
    ax.tick_params(
        axis="both",
        which="minor",
        direction="out",
        width=0.5,
        length=5,
        top=False,
        right=False,
    )
    if use_minor_x:
        ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    if use_minor_y:
        ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.grid(False)


def save_figure(fig, output_base: Path, save_svg: bool = False, png_dpi: int = 180) -> List[str]:
    output_base.parent.mkdir(parents=True, exist_ok=True)
    png_path = output_base.with_suffix(".png")
    fig.savefig(png_path, dpi=png_dpi, bbox_inches="tight", facecolor="white")
    saved_paths = [str(png_path)]
    if save_svg:
        svg_path = output_base.with_suffix(".svg")
        fig.savefig(svg_path, bbox_inches="tight", facecolor="white")
        saved_paths.append(str(svg_path))
    return saved_paths


def plot_dataset_histograms(dataset_dir: Path, frame_df: pd.DataFrame) -> str:
    apply_plot_defaults()
    fig, axes = plt.subplots(2, 2, figsize=(16.0, 12.0))
    columns = [
        ("component_count", "Component Count"),
        ("largest_component_area", "Largest Component Area (pixels)"),
        ("second_component_area", "Second Component Area (pixels)"),
        ("small_component_count", "Small-component Count"),
    ]
    for ax, (column, xlabel) in zip(axes.flat, columns):
        values = pd.to_numeric(frame_df[column], errors="coerce").fillna(0).to_numpy()
        positive = values[values > 0]
        plot_values = positive if column in {"largest_component_area", "second_component_area"} and len(positive) > 0 else values
        bins = 40 if len(plot_values) >= 40 else max(len(np.unique(plot_values)), 10)
        ax.hist(plot_values, bins=bins, color=PLOT_COLORS["blue"], edgecolor="white")
        ax.set_xlabel(xlabel, fontweight="bold")
        ax.set_ylabel("Frame Count", fontweight="bold")
        style_axis(ax)
    fig.tight_layout()
    saved = save_figure(fig, dataset_dir / "component_histograms", save_svg=False)
    plt.close(fig)
    return saved[0]


def plot_top_datasets(output_dir: Path, summary_df: pd.DataFrame) -> List[str]:
    if summary_df.empty:
        return []
    apply_plot_defaults()
    top = summary_df.sort_values("anomaly_score", ascending=False).head(20).copy()
    labels = [f"{row['group_name']}/{row['dataset_name']}" for _, row in top.iterrows()]
    fig_h = max(8.0, 0.55 * len(top))
    fig, ax = plt.subplots(figsize=(16.0, fig_h))
    ax.barh(np.arange(len(top)), top["anomaly_score"].to_numpy(), color=PLOT_COLORS["orange"])
    ax.set_yticks(np.arange(len(top)))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("Anomaly Score", fontweight="bold")
    ax.set_ylabel("Dataset", fontweight="bold")
    style_axis(ax, use_minor_y=False)
    fig.tight_layout()
    saved = save_figure(fig, output_dir / "top_flagged_datasets", save_svg=True)
    plt.close(fig)
    return saved


def threshold_candidates(max_area: int) -> List[int]:
    base = [1, 2, 3, 4, 5, 8, 10, 15, 20, 30, 40, 50, 60, 75, 100, 150, 200, 300, 500, 750, 1000]
    if max_area <= 0:
        return base
    return [value for value in base if value <= max_area] + ([] if max_area in base else [max_area])


def build_threshold_sweep_table(
    non_largest_counter: Counter[int],
    min_non_largest_per_frame: List[int],
) -> pd.DataFrame:
    if not non_largest_counter:
        return pd.DataFrame(
            columns=[
                "threshold",
                "components_removed_count",
                "components_removed_fraction",
                "non_largest_pixels_removed",
                "non_largest_pixels_removed_fraction",
                "frames_affected_count",
                "frames_affected_fraction",
            ]
        )

    area_values = np.asarray(sorted(non_largest_counter.keys()), dtype=int)
    count_values = np.asarray([non_largest_counter[int(area)] for area in area_values], dtype=float)
    cumulative_counts = np.cumsum(count_values)
    cumulative_pixels = np.cumsum(area_values * count_values)
    total_components = float(cumulative_counts[-1])
    total_pixels = float(cumulative_pixels[-1])
    min_frame_values = np.sort(np.asarray(min_non_largest_per_frame, dtype=int)) if min_non_largest_per_frame else np.asarray([], dtype=int)

    rows: List[Dict[str, float]] = []
    for threshold in threshold_candidates(int(area_values[-1])):
        index = int(np.searchsorted(area_values, threshold, side="right") - 1)
        if index >= 0:
            removed_components = float(cumulative_counts[index])
            removed_pixels = float(cumulative_pixels[index])
        else:
            removed_components = 0.0
            removed_pixels = 0.0

        if len(min_frame_values) > 0:
            affected_frames = int(np.searchsorted(min_frame_values, threshold, side="right"))
        else:
            affected_frames = 0

        rows.append(
            {
                "threshold": int(threshold),
                "components_removed_count": int(round(removed_components)),
                "components_removed_fraction": float(removed_components / total_components) if total_components > 0 else 0.0,
                "non_largest_pixels_removed": int(round(removed_pixels)),
                "non_largest_pixels_removed_fraction": float(removed_pixels / total_pixels) if total_pixels > 0 else 0.0,
                "frames_affected_count": int(affected_frames),
                "frames_affected_fraction": float(affected_frames / len(min_frame_values)) if len(min_frame_values) > 0 else 0.0,
            }
        )
    return pd.DataFrame(rows)


def detect_gap_threshold(non_largest_counter: Counter[int]) -> Optional[Dict[str, float]]:
    if not non_largest_counter or len(non_largest_counter) < 3:
        return None

    areas = np.asarray(sorted(non_largest_counter.keys()), dtype=float)
    counts = np.asarray([non_largest_counter[int(area)] for area in areas], dtype=float)
    cumulative_fraction = np.cumsum(counts) / max(counts.sum(), 1.0)
    log_areas = np.log10(np.maximum(areas, 1.0))
    gaps = np.diff(log_areas)
    valid = (
        (areas[:-1] >= 3)
        & (areas[:-1] <= 300)
        & (cumulative_fraction[:-1] >= 0.20)
        & (cumulative_fraction[:-1] <= 0.90)
    )
    if not np.any(valid):
        return None

    candidate_indices = np.where(valid)[0]
    best_idx = candidate_indices[int(np.argmax(gaps[candidate_indices]))]
    best_gap = float(gaps[best_idx])
    if best_gap < 0.08:
        return None

    lower = float(areas[best_idx])
    upper = float(areas[best_idx + 1])
    threshold = int(round(lower))
    return {
        "gap_threshold": threshold,
        "gap_lower": lower,
        "gap_upper": upper,
        "gap_log10_size": best_gap,
    }


def recommend_threshold_from_sweep(
    threshold_df: pd.DataFrame,
    non_largest_counter: Counter[int],
) -> Dict[str, object]:
    if threshold_df.empty:
        return {
            "recommended_threshold": 0,
            "score_threshold": 0,
            "gap_threshold": None,
            "reason": "No removable non-largest components were detected.",
        }

    sweep = threshold_df.copy()
    sweep["efficiency_score"] = (
        sweep["components_removed_fraction"]
        - sweep["non_largest_pixels_removed_fraction"]
        - 0.20 * sweep["frames_affected_fraction"]
    )
    best_score = float(sweep["efficiency_score"].max())
    near_best = sweep[sweep["efficiency_score"] >= best_score * 0.975].sort_values("threshold")
    score_row = near_best.iloc[0]
    score_threshold = int(score_row["threshold"])

    gap_info = detect_gap_threshold(non_largest_counter)
    recommended_row = score_row
    reason = "Recommended from the best trade-off between removed small components and preserved pixels."

    if gap_info is not None:
        gap_threshold = int(gap_info["gap_threshold"])
        gap_candidates = sweep.iloc[(sweep["threshold"] - gap_threshold).abs().argsort()[:1]]
        if not gap_candidates.empty:
            gap_row = gap_candidates.iloc[0]
            if float(gap_row["efficiency_score"]) >= best_score * 0.92:
                recommended_row = gap_row
                reason = (
                    "Recommended near the first clear gap in the non-largest component-size distribution, "
                    "while keeping the efficiency score close to the optimum."
                )

    return {
        "recommended_threshold": int(recommended_row["threshold"]),
        "score_threshold": score_threshold,
        "gap_threshold": int(gap_info["gap_threshold"]) if gap_info is not None else None,
        "reason": reason,
        "components_removed_fraction": float(recommended_row["components_removed_fraction"]),
        "non_largest_pixels_removed_fraction": float(recommended_row["non_largest_pixels_removed_fraction"]),
        "frames_affected_fraction": float(recommended_row["frames_affected_fraction"]),
        "efficiency_score": float(recommended_row["efficiency_score"]),
    }


def write_component_area_counts_csv(
    output_dir: Path,
    all_component_counter: Counter[int],
    non_largest_component_counter: Counter[int],
) -> str:
    areas = sorted(set(all_component_counter.keys()) | set(non_largest_component_counter.keys()))
    rows = [
        {
            "area": int(area),
            "all_component_count": int(all_component_counter.get(area, 0)),
            "non_largest_component_count": int(non_largest_component_counter.get(area, 0)),
        }
        for area in areas
    ]
    output_path = output_dir / "component_area_counts.csv"
    pd.DataFrame(rows).to_csv(output_path, index=False, encoding="utf-8")
    return str(output_path)


def plot_non_largest_component_distribution(
    output_dir: Path,
    non_largest_counter: Counter[int],
    small_area_threshold: int,
) -> List[str]:
    if not non_largest_counter:
        return []

    apply_plot_defaults()
    area_values = np.asarray(sorted(non_largest_counter.keys()), dtype=float)
    count_values = np.asarray([non_largest_counter[int(area)] for area in area_values], dtype=float)
    max_area = max(float(area_values.max()), 1.0)

    if max_area <= 1.0:
        bins = np.array([0.5, 1.5])
    else:
        bins = np.logspace(np.log10(1.0), np.log10(max_area), 50)

    hist_values, bin_edges = np.histogram(area_values, bins=bins, weights=count_values)
    centers = np.sqrt(bin_edges[:-1] * bin_edges[1:]) if len(bin_edges) > 2 else np.array([1.0])

    fig, ax = plt.subplots(figsize=(14.0, 8.0))
    ax.plot(centers, hist_values, color=PLOT_COLORS["blue"], linewidth=2.8)
    ax.fill_between(centers, hist_values, color=PLOT_COLORS["blue"], alpha=0.18)
    ax.axvline(float(small_area_threshold), color=PLOT_COLORS["orange"], linewidth=2.6, linestyle="--")
    ax.text(
        float(small_area_threshold),
        max(hist_values) * 0.92 if len(hist_values) > 0 else 1.0,
        f"Threshold = {small_area_threshold}",
        rotation=90,
        va="top",
        ha="right",
        color=PLOT_COLORS["orange"],
        fontsize=PLOT_FONT_SIZE * 0.7,
        fontweight="bold",
    )
    ax.set_xscale("log")
    ax.set_xlabel("Non-largest Component Area (pixels)", fontweight="bold")
    ax.set_ylabel("Component Count", fontweight="bold")
    style_axis(ax, use_minor_x=False)
    fig.tight_layout()
    saved = save_figure(fig, output_dir / "non_largest_component_area_distribution", save_svg=True)
    plt.close(fig)
    return saved


def plot_threshold_sweep(
    output_dir: Path,
    threshold_df: pd.DataFrame,
    small_area_threshold: int,
) -> List[str]:
    if threshold_df.empty:
        return []

    apply_plot_defaults()
    thresholds = threshold_df["threshold"].to_numpy(dtype=float)
    component_pct = threshold_df["components_removed_fraction"].to_numpy(dtype=float) * 100.0
    frame_pct = threshold_df["frames_affected_fraction"].to_numpy(dtype=float) * 100.0

    fig, axes = plt.subplots(2, 1, figsize=(14.0, 12.0), sharex=True)

    axes[0].plot(thresholds, component_pct, color=PLOT_COLORS["blue"], linewidth=2.8)
    axes[0].axvline(float(small_area_threshold), color=PLOT_COLORS["orange"], linewidth=2.6, linestyle="--")
    axes[0].set_ylabel("Components <= Threshold (%)", fontweight="bold")
    style_axis(axes[0])

    axes[1].plot(thresholds, frame_pct, color=PLOT_COLORS["green"], linewidth=2.8)
    axes[1].axvline(float(small_area_threshold), color=PLOT_COLORS["orange"], linewidth=2.6, linestyle="--")
    axes[1].set_xlabel("Area Threshold (pixels)", fontweight="bold")
    axes[1].set_ylabel("Frames Affected (%)", fontweight="bold")
    style_axis(axes[1])

    fig.tight_layout()
    saved = save_figure(fig, output_dir / "threshold_sweep", save_svg=True)
    plt.close(fig)
    return saved


def current_dataset_output_dir(save_dir: str, dataset_name: str) -> Path:
    save_path = Path(save_dir)
    parent_dir = save_path.parent if save_path.parent.exists() else save_path
    return parent_dir / f"{sanitize_filename(dataset_name, max_len=48)}__component_qc_current"


def build_current_dataset_component_qc(
    original_dir: str,
    mask_dir: str,
    save_dir: str,
    output_dir: str = "",
    progress_callback: Optional[Callable[[int, int], bool]] = None,
) -> Dict[str, object]:
    original_path = Path(original_dir).resolve()
    mask_path = Path(mask_dir).resolve()
    save_path = Path(save_dir).resolve()

    dataset_name = original_path.name or save_path.name or "current_dataset"
    group_name = original_path.parent.name if original_path.parent else "current_group"
    dataset_label = f"{group_name} / {dataset_name}"
    resolved_output_dir = Path(output_dir).resolve() if output_dir else current_dataset_output_dir(str(save_path), dataset_name)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    dataset = {
        "group_name": group_name,
        "dataset_name": dataset_name,
        "origin_dir": str(original_path),
        "mask_dir": str(mask_path),
        "save_dir": str(save_path),
    }
    frame_names = choose_frame_names(dataset)

    stored_frames: List[Dict[str, object]] = []
    all_component_counter: Counter[int] = Counter()
    non_largest_component_counter: Counter[int] = Counter()
    min_non_largest_per_frame: List[int] = []
    source_usage = Counter()

    frame_total = len(frame_names)
    for frame_index, frame_name in enumerate(frame_names, start=1):
        if progress_callback and not progress_callback(frame_index, frame_total):
            raise RuntimeError("Canceled by user.")

        save_frame_path = save_path / frame_name
        mask_frame_path = mask_path / frame_name
        source_path: Optional[Path] = None
        source_used = "missing"
        if save_frame_path.exists():
            source_path = save_frame_path
            source_used = "save_dir"
        elif mask_frame_path.exists():
            source_path = mask_frame_path
            source_used = "mask_dir_fallback"

        if source_path is None:
            stored_frames.append(
                {
                    "frame_name": frame_name,
                    "source_used": source_used,
                    "sizes": None,
                }
            )
            continue

        mask = load_binary_mask(source_path)
        if mask is None:
            stored_frames.append(
                {
                    "frame_name": frame_name,
                    "source_used": "read_failed",
                    "sizes": None,
                }
            )
            continue

        sizes = component_sizes(mask)
        stored_frames.append(
            {
                "frame_name": frame_name,
                "source_used": source_used,
                "sizes": sizes,
            }
        )
        source_usage[source_used] += 1
        if sizes:
            all_component_counter.update(sizes)
            if len(sizes) > 1:
                non_largest_sizes = sizes[1:]
                non_largest_component_counter.update(non_largest_sizes)
                min_non_largest_per_frame.append(int(min(non_largest_sizes)))

    threshold_df = build_threshold_sweep_table(non_largest_component_counter, min_non_largest_per_frame)
    recommendation = recommend_threshold_from_sweep(threshold_df, non_largest_component_counter)
    recommended_threshold = int(recommendation["recommended_threshold"])

    frame_rows: List[Dict[str, object]] = []
    flagged_rows: List[Dict[str, object]] = []
    for frame in stored_frames:
        if frame["sizes"] is None:
            frame_rows.append(
                {
                    "group_name": group_name,
                    "dataset_name": dataset_name,
                    "frame_name": frame["frame_name"],
                    "source_used": frame["source_used"],
                    "component_count": "",
                    "total_foreground_area": "",
                    "largest_component_area": "",
                    "second_component_area": "",
                    "largest_component_fraction": "",
                    "small_component_count": "",
                    "small_component_pixels": "",
                    "empty_frame": "",
                    "multi_component": "",
                }
            )
            continue

        metrics = metrics_from_sizes(frame["sizes"], recommended_threshold)
        frame_row = {
            "group_name": group_name,
            "dataset_name": dataset_name,
            "frame_name": frame["frame_name"],
            "source_used": frame["source_used"],
            **metrics,
        }
        frame_rows.append(frame_row)

    frame_df = pd.DataFrame(frame_rows)
    valid_frame_df = frame_df[pd.to_numeric(frame_df["component_count"], errors="coerce").notna()].copy()

    analyzed_frames = len(valid_frame_df)
    missing_frames = len(frame_rows) - analyzed_frames
    if analyzed_frames > 0:
        comp_counts = pd.to_numeric(valid_frame_df["component_count"], errors="coerce").fillna(0).tolist()
        largest_areas = pd.to_numeric(valid_frame_df["largest_component_area"], errors="coerce").fillna(0).tolist()
        second_areas = pd.to_numeric(valid_frame_df["second_component_area"], errors="coerce").fillna(0).tolist()
        largest_fracs = pd.to_numeric(valid_frame_df["largest_component_fraction"], errors="coerce").fillna(0).tolist()
        small_counts = pd.to_numeric(valid_frame_df["small_component_count"], errors="coerce").fillna(0).tolist()
        empty_frames = int(pd.to_numeric(valid_frame_df["empty_frame"], errors="coerce").fillna(0).sum())
        multi_frames = int(pd.to_numeric(valid_frame_df["multi_component"], errors="coerce").fillna(0).sum())
        frames_with_small = int(np.sum(np.asarray(small_counts, dtype=float) > 0))
        frames_with_second = int(np.sum(np.asarray(second_areas, dtype=float) > 0))

        valid_frame_df["flag_score"] = (
            pd.to_numeric(valid_frame_df["multi_component"], errors="coerce").fillna(0) * 0.40
            + (pd.to_numeric(valid_frame_df["small_component_count"], errors="coerce").fillna(0) > 0).astype(float) * 0.25
            + (pd.to_numeric(valid_frame_df["second_component_area"], errors="coerce").fillna(0) > recommended_threshold).astype(float) * 0.20
            + pd.to_numeric(valid_frame_df["empty_frame"], errors="coerce").fillna(0) * 0.15
        )
        top_flagged = valid_frame_df.sort_values(
            ["flag_score", "small_component_count", "second_component_area"],
            ascending=[False, False, False],
        ).head(20)
        for _, row in top_flagged.iterrows():
            flagged_rows.append(
                {
                    "group_name": group_name,
                    "dataset_name": dataset_name,
                    "frame_name": row["frame_name"],
                    "source_used": row["source_used"],
                    "flag_score": float(row["flag_score"]),
                    "component_count": int(row["component_count"]),
                    "second_component_area": int(row["second_component_area"]),
                    "small_component_count": int(row["small_component_count"]),
                    "empty_frame": int(row["empty_frame"]),
                }
            )
    else:
        comp_counts = []
        largest_areas = []
        second_areas = []
        largest_fracs = []
        small_counts = []
        empty_frames = 0
        multi_frames = 0
        frames_with_small = 0
        frames_with_second = 0

    dataset_summary = {
        "group_name": group_name,
        "dataset_name": dataset_name,
        "total_frames": len(frame_names),
        "analyzed_frames": analyzed_frames,
        "save_frames": int(source_usage.get("save_dir", 0)),
        "mask_fallback_frames": int(source_usage.get("mask_dir_fallback", 0)),
        "missing_frames": missing_frames,
        "empty_frames": empty_frames,
        "multi_component_frames": multi_frames,
        "multi_component_ratio": round(multi_frames / analyzed_frames, 6) if analyzed_frames else 0.0,
        "frames_with_small_components": frames_with_small,
        "frames_with_second_component": frames_with_second,
        "component_count_median": median_or_zero(comp_counts),
        "component_count_p95": percentile_or_zero(comp_counts, 95),
        "largest_component_area_median": median_or_zero(largest_areas),
        "largest_component_area_p10": percentile_or_zero(largest_areas, 10),
        "second_component_area_p95": percentile_or_zero(second_areas, 95),
        "largest_component_fraction_median": median_or_zero(largest_fracs),
        "small_component_count_median": median_or_zero(small_counts),
        "small_component_count_p95": percentile_or_zero(small_counts, 95),
        "recommended_threshold": recommended_threshold,
        "score_threshold": recommendation["score_threshold"],
        "gap_threshold": recommendation["gap_threshold"],
        "anomaly_score": 0.0,
    }
    dataset_summary["anomaly_score"] = dataset_anomaly_score(dataset_summary)

    frame_metrics_csv = resolved_output_dir / "frame_metrics.csv"
    flagged_frames_csv = resolved_output_dir / "flagged_frames.csv"
    dataset_summary_csv = resolved_output_dir / "dataset_summary.csv"
    threshold_sweep_csv = resolved_output_dir / "threshold_sweep.csv"
    pd.DataFrame(frame_rows).to_csv(frame_metrics_csv, index=False, encoding="utf-8")
    pd.DataFrame(flagged_rows).to_csv(flagged_frames_csv, index=False, encoding="utf-8")
    pd.DataFrame([dataset_summary]).to_csv(dataset_summary_csv, index=False, encoding="utf-8")
    threshold_df.to_csv(threshold_sweep_csv, index=False, encoding="utf-8")

    plot_dataset_histograms(resolved_output_dir, valid_frame_df if not valid_frame_df.empty else pd.DataFrame(columns=["component_count", "largest_component_area", "second_component_area", "small_component_count"]))
    histogram_plot = str((resolved_output_dir / "component_histograms.png"))
    non_largest_plots = plot_non_largest_component_distribution(
        resolved_output_dir,
        non_largest_component_counter,
        small_area_threshold=recommended_threshold,
    )
    threshold_plots = plot_threshold_sweep(
        resolved_output_dir,
        threshold_df,
        small_area_threshold=recommended_threshold,
    )
    component_area_counts_csv = write_component_area_counts_csv(
        resolved_output_dir,
        all_component_counter,
        non_largest_component_counter,
    )

    summary = {
        "group_name": group_name,
        "dataset_name": dataset_name,
        "dataset_label": dataset_label,
        "output_dir": str(resolved_output_dir),
        "recommended_threshold": recommended_threshold,
        "score_threshold": recommendation["score_threshold"],
        "gap_threshold": recommendation["gap_threshold"],
        "recommendation_reason": recommendation["reason"],
        "components_removed_fraction": recommendation.get("components_removed_fraction", 0.0),
        "non_largest_pixels_removed_fraction": recommendation.get("non_largest_pixels_removed_fraction", 0.0),
        "frames_affected_fraction": recommendation.get("frames_affected_fraction", 0.0),
        "dataset_summary_csv": str(dataset_summary_csv),
        "frame_metrics_csv": str(frame_metrics_csv),
        "flagged_frames_csv": str(flagged_frames_csv),
        "threshold_sweep_csv": str(threshold_sweep_csv),
        "component_area_counts_csv": component_area_counts_csv,
        "histogram_plot": histogram_plot,
        "non_largest_component_distribution_plots": non_largest_plots,
        "threshold_sweep_plots": threshold_plots,
        "generated_at": now_text(),
    }
    (resolved_output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def build_component_qc_report(
    session_path: str,
    output_dir: str = "",
    small_area_threshold: int = 50,
    fallback_to_mask_dir: bool = False,
    include_done: bool = False,
    limit: int = 0,
    coarse_status_csv: str = "",
    progress_callback: Optional[Callable[[int, int, int, int, str], bool]] = None,
) -> Dict[str, object]:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from core.binary_queue_core import BinaryQueueCore

    resolved_session_path = Path(session_path).resolve()
    if not resolved_session_path.exists():
        raise FileNotFoundError(f"Session JSON not found: {resolved_session_path}")

    session = BinaryQueueCore.refresh_session(str(resolved_session_path))
    datasets = list(session.get("datasets", []))
    if not include_done:
        datasets = [dataset for dataset in datasets if dataset.get("status") != "done"]
    if limit and limit > 0:
        datasets = datasets[:limit]

    resolved_output_dir = Path(output_dir).resolve() if output_dir else default_output_dir(resolved_session_path)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    per_dataset_dir = resolved_output_dir / "per_dataset"
    per_dataset_dir.mkdir(parents=True, exist_ok=True)

    frame_rows: List[Dict[str, object]] = []
    dataset_rows: List[Dict[str, object]] = []
    flagged_frames: List[Dict[str, object]] = []
    all_component_counter: Counter[int] = Counter()
    non_largest_component_counter: Counter[int] = Counter()
    min_non_largest_per_frame: List[int] = []

    dataset_total = len(datasets)
    for dataset_index, dataset in enumerate(datasets, start=1):
        dataset_label = f"{dataset['group_name']} / {dataset['dataset_name']}"
        frame_names = choose_frame_names(dataset)
        save_dir = Path(dataset["save_dir"])
        mask_dir = Path(dataset["mask_dir"])
        dataset_key = f"{dataset['group_name']}::{dataset['dataset_name']}"
        save_frames = 0
        fallback_frames = 0
        missing_frames = 0
        per_frame: List[Dict[str, object]] = []

        if progress_callback and not progress_callback(dataset_index, dataset_total, 0, len(frame_names), dataset_label):
            raise RuntimeError("Canceled by user.")

        for frame_index, frame_name in enumerate(frame_names, start=1):
            if progress_callback and (frame_index == 1 or frame_index % 100 == 0 or frame_index == len(frame_names)):
                if not progress_callback(dataset_index, dataset_total, frame_index, len(frame_names), dataset_label):
                    raise RuntimeError("Canceled by user.")

            save_path = save_dir / frame_name
            mask_path = mask_dir / frame_name
            source_path: Optional[Path] = None
            source_kind = ""
            if save_path.exists():
                source_path = save_path
                source_kind = "save_dir"
                save_frames += 1
            elif fallback_to_mask_dir and mask_path.exists():
                source_path = mask_path
                source_kind = "mask_dir_fallback"
                fallback_frames += 1
            else:
                missing_frames += 1
                frame_rows.append(
                    {
                        "dataset_key": dataset_key,
                        "group_name": dataset["group_name"],
                        "dataset_name": dataset["dataset_name"],
                        "frame_name": frame_name,
                        "source_used": "missing",
                        "component_count": "",
                        "total_foreground_area": "",
                        "largest_component_area": "",
                        "second_component_area": "",
                        "largest_component_fraction": "",
                        "small_component_count": "",
                        "small_component_pixels": "",
                        "empty_frame": "",
                        "multi_component": "",
                    }
                )
                continue

            mask = load_binary_mask(source_path)
            if mask is None:
                missing_frames += 1
                continue

            metrics, sizes = component_metrics(mask, small_area_threshold)
            if sizes:
                all_component_counter.update(sizes)
                if len(sizes) > 1:
                    non_largest_sizes = sizes[1:]
                    non_largest_component_counter.update(non_largest_sizes)
                    min_non_largest_per_frame.append(int(min(non_largest_sizes)))

            frame_row = {
                "dataset_key": dataset_key,
                "group_name": dataset["group_name"],
                "dataset_name": dataset["dataset_name"],
                "frame_name": frame_name,
                "source_used": source_kind,
                **metrics,
            }
            frame_rows.append(frame_row)
            per_frame.append(frame_row)

        frame_df = pd.DataFrame(per_frame)
        analyzed_frames = len(frame_df)
        if analyzed_frames > 0:
            comp_counts = pd.to_numeric(frame_df["component_count"], errors="coerce").fillna(0).tolist()
            largest_areas = pd.to_numeric(frame_df["largest_component_area"], errors="coerce").fillna(0).tolist()
            second_areas = pd.to_numeric(frame_df["second_component_area"], errors="coerce").fillna(0).tolist()
            largest_fracs = pd.to_numeric(frame_df["largest_component_fraction"], errors="coerce").fillna(0).tolist()
            small_counts = pd.to_numeric(frame_df["small_component_count"], errors="coerce").fillna(0).tolist()
            empty_frames = int(pd.to_numeric(frame_df["empty_frame"], errors="coerce").fillna(0).sum())
            multi_frames = int(pd.to_numeric(frame_df["multi_component"], errors="coerce").fillna(0).sum())
            frames_with_small = int(np.sum(np.asarray(small_counts, dtype=float) > 0))
            frames_with_second = int(np.sum(np.asarray(second_areas, dtype=float) > 0))
        else:
            comp_counts = []
            largest_areas = []
            second_areas = []
            largest_fracs = []
            small_counts = []
            empty_frames = 0
            multi_frames = 0
            frames_with_small = 0
            frames_with_second = 0

        summary = {
            "dataset_key": dataset_key,
            "group_name": dataset["group_name"],
            "dataset_name": dataset["dataset_name"],
            "queue_status": dataset.get("status", ""),
            "total_frames": len(frame_names),
            "analyzed_frames": analyzed_frames,
            "save_frames": save_frames,
            "mask_fallback_frames": fallback_frames,
            "missing_frames": missing_frames,
            "empty_frames": empty_frames,
            "multi_component_frames": multi_frames,
            "multi_component_ratio": round(multi_frames / analyzed_frames, 6) if analyzed_frames else 0.0,
            "frames_with_small_components": frames_with_small,
            "frames_with_second_component": frames_with_second,
            "component_count_median": median_or_zero(comp_counts),
            "component_count_p95": percentile_or_zero(comp_counts, 95),
            "largest_component_area_median": median_or_zero(largest_areas),
            "largest_component_area_p10": percentile_or_zero(largest_areas, 10),
            "second_component_area_p95": percentile_or_zero(second_areas, 95),
            "largest_component_fraction_median": median_or_zero(largest_fracs),
            "small_component_count_median": median_or_zero(small_counts),
            "small_component_count_p95": percentile_or_zero(small_counts, 95),
        }
        summary["anomaly_score"] = dataset_anomaly_score(summary)
        dataset_rows.append(summary)

        if analyzed_frames > 0:
            frame_df = frame_df.copy()
            frame_df["flag_score"] = (
                pd.to_numeric(frame_df["multi_component"], errors="coerce").fillna(0) * 0.40
                + (pd.to_numeric(frame_df["small_component_count"], errors="coerce").fillna(0) > 0).astype(float) * 0.25
                + (pd.to_numeric(frame_df["second_component_area"], errors="coerce").fillna(0) > small_area_threshold).astype(float) * 0.20
                + pd.to_numeric(frame_df["empty_frame"], errors="coerce").fillna(0) * 0.15
            )
            top_flagged = frame_df.sort_values(
                ["flag_score", "small_component_count", "second_component_area"],
                ascending=[False, False, False],
            ).head(20)
            for _, row in top_flagged.iterrows():
                flagged_frames.append(
                    {
                        "dataset_key": dataset_key,
                        "group_name": dataset["group_name"],
                        "dataset_name": dataset["dataset_name"],
                        "frame_name": row["frame_name"],
                        "source_used": row["source_used"],
                        "flag_score": float(row["flag_score"]),
                        "component_count": int(row["component_count"]),
                        "second_component_area": int(row["second_component_area"]),
                        "small_component_count": int(row["small_component_count"]),
                        "empty_frame": int(row["empty_frame"]),
                    }
                )

            dataset_slug = sanitize_filename(f"d{dataset_index:02d}__{dataset['dataset_name']}", max_len=48)
            dataset_plot_dir = per_dataset_dir / dataset_slug
            dataset_plot_dir.mkdir(parents=True, exist_ok=True)
            plot_dataset_histograms(dataset_plot_dir, frame_df.drop(columns=["flag_score"]))

    frame_rows_path = resolved_output_dir / "frame_metrics.csv"
    dataset_rows_path = resolved_output_dir / "dataset_summary.csv"
    flagged_frames_path = resolved_output_dir / "flagged_frames.csv"
    threshold_rows_path = resolved_output_dir / "threshold_sweep.csv"
    pd.DataFrame(frame_rows).to_csv(frame_rows_path, index=False, encoding="utf-8")
    dataset_summary_df = pd.DataFrame(dataset_rows)
    if dataset_summary_df.empty:
        dataset_summary_df = pd.DataFrame(
            columns=[
                "dataset_key",
                "group_name",
                "dataset_name",
                "queue_status",
                "total_frames",
                "analyzed_frames",
                "save_frames",
                "mask_fallback_frames",
                "missing_frames",
                "empty_frames",
                "multi_component_frames",
                "multi_component_ratio",
                "frames_with_small_components",
                "frames_with_second_component",
                "component_count_median",
                "component_count_p95",
                "largest_component_area_median",
                "largest_component_area_p10",
                "second_component_area_p95",
                "largest_component_fraction_median",
                "small_component_count_median",
                "small_component_count_p95",
                "anomaly_score",
            ]
        )
    else:
        dataset_summary_df = dataset_summary_df.sort_values(
            ["anomaly_score", "group_name", "dataset_name"],
            ascending=[False, True, True],
        )
    dataset_summary_df.to_csv(dataset_rows_path, index=False, encoding="utf-8")
    pd.DataFrame(flagged_frames).to_csv(flagged_frames_path, index=False, encoding="utf-8")

    threshold_df = build_threshold_sweep_table(non_largest_component_counter, min_non_largest_per_frame)
    threshold_df.to_csv(threshold_rows_path, index=False, encoding="utf-8")
    component_area_counts_csv = write_component_area_counts_csv(
        resolved_output_dir,
        all_component_counter,
        non_largest_component_counter,
    )

    top_plot_paths = plot_top_datasets(resolved_output_dir, dataset_summary_df)
    non_largest_plot_paths = plot_non_largest_component_distribution(
        resolved_output_dir,
        non_largest_component_counter,
        small_area_threshold=small_area_threshold,
    )
    threshold_plot_paths = plot_threshold_sweep(
        resolved_output_dir,
        threshold_df,
        small_area_threshold=small_area_threshold,
    )

    coarse_status_path = Path(coarse_status_csv).resolve() if coarse_status_csv else default_coarse_status_path(resolved_session_path)
    if coarse_status_path.exists():
        rows = read_csv_rows(coarse_status_path)
        if rows:
            by_key = {str(row.get("dataset_key", "")).strip(): row for row in rows}
            for _, row in dataset_summary_df.iterrows():
                key = str(row["dataset_key"])
                target = by_key.get(key)
                if target is None:
                    continue
                target["qc_report_generated"] = "yes"
                target["qc_report_generated_at"] = now_text()
            fieldnames = list(rows[0].keys())
            write_csv_rows(coarse_status_path, list(by_key.values()), fieldnames)

    summary = {
        "session_path": str(resolved_session_path),
        "output_dir": str(resolved_output_dir),
        "dataset_count": int(len(dataset_rows)),
        "frame_metric_rows": int(len(frame_rows)),
        "small_area_threshold": int(small_area_threshold),
        "fallback_to_mask_dir": bool(fallback_to_mask_dir),
        "generated_at": now_text(),
        "dataset_summary_csv": str(dataset_rows_path),
        "frame_metrics_csv": str(frame_rows_path),
        "flagged_frames_csv": str(flagged_frames_path),
        "threshold_sweep_csv": str(threshold_rows_path),
        "component_area_counts_csv": component_area_counts_csv,
        "top_flagged_datasets_plots": top_plot_paths,
        "non_largest_component_distribution_plots": non_largest_plot_paths,
        "threshold_sweep_plots": threshold_plot_paths,
        "non_largest_component_count": int(sum(non_largest_component_counter.values())),
        "all_component_count": int(sum(all_component_counter.values())),
    }
    (resolved_output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    args = parse_args()
    summary = build_component_qc_report(
        session_path=args.session_path,
        output_dir=args.output_dir,
        small_area_threshold=args.small_area_threshold,
        fallback_to_mask_dir=bool(args.fallback_to_mask_dir),
        include_done=bool(args.include_done),
        limit=int(args.limit),
        coarse_status_csv=args.coarse_status_csv,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
