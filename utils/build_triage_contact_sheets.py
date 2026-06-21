#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from utils.cv_image_io import cv_imwrite, load_grayscale


VALID_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}

BG = (245, 246, 248)
PANEL_BG = (255, 255, 255)
TITLE = (38, 44, 53)
SUBTITLE = (104, 114, 128)
BORDER = (223, 227, 234)
ACCENT = (188, 105, 46)
ACCENT_LIGHT = (240, 232, 224)
ACCENT_DARK = (120, 69, 34)
BADGE_GRAY = (132, 140, 152)
TIMELINE_BG = (230, 233, 239)
TIMELINE_FG = (112, 139, 177)
MASK_BG = (17, 27, 19)
MASK_BORDER = (60, 74, 62)


@dataclass
class DatasetSourceInfo:
    source_origin_dir: Path
    source_mask_dir: Path
    pack_local_index_by_frame: Dict[str, int]


@dataclass
class SegmentWindow:
    segment_id: int
    start_index: int
    end_index: int
    issue_indices: List[int]
    issue_frames: List[str]
    issue_local_indices: List[int]


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
    keys = list(fieldnames or (rows[0].keys() if rows else []))
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        if rows:
            writer.writerows(rows)


def write_markdown(md_path: Path, triage_rows: Sequence[Dict[str, object]]) -> None:
    lines = [
        "# Triage Contact Sheets",
        "",
        "Each segment now has its own storyboard PNG.",
        "Orange tiles are suspected issue frames. All pack-local frames carry an `Lxx` badge for quick note taking.",
        "Only suspected issue frames show a mask inset; context-only frames show origin only.",
        "",
        "| b_id | Dataset | Segments | Suspected issue frames | Segment Folder |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for row in triage_rows:
        lines.append(
            f"| `{row['b_id']}` | `{row['group_name']}/{row['dataset_name']}` | {row['segment_count']} | {row['issue_frame_count']} | `{row['contact_sheet']}` |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")


def build_html_gallery(meta_dir: Path, flat_index_rows: Sequence[Dict[str, object]]) -> None:
    html_path = meta_dir / "triage_contacts_flat.html"
    card_blocks: List[str] = []
    for row in flat_index_rows:
        issue_text = str(row.get("issue_local_indices_display", "")).strip() or "none"
        card_blocks.append(
            "\n".join(
                [
                    '<article class="card">',
                    f'  <img src="triage_contacts_flat/{row["flat_name"]}" loading="lazy" alt="{row["segment_key"]}">',
                    '  <div class="meta">',
                    f'    <div class="title">{row["order"]:04d} | {row["segment_key"]}</div>',
                    f'    <div class="sub">{row["group_name"]} / {row["dataset_name"]}</div>',
                    f'    <div class="sub">source {row["source_start_index"]}-{row["source_end_index"]} / {row["dataset_total_frames"]} total</div>',
                    f'    <div class="sub">highlighted {issue_text}</div>',
                    "  </div>",
                    "</article>",
                ]
            )
        )

    cards_html = "\n".join(card_blocks)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Triage Contacts Flat</title>
  <style>
    :root {{
      --bg: #f3f4f6;
      --panel: #ffffff;
      --text: #1f2937;
      --muted: #6b7280;
      --accent: #9a5528;
      --border: #e5e7eb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
      background: linear-gradient(180deg, #f9fafb 0%, #eef2f7 100%);
      color: var(--text);
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(255,255,255,0.92);
      backdrop-filter: blur(10px);
      border-bottom: 1px solid var(--border);
      padding: 18px 22px 14px;
    }}
    header h1 {{
      margin: 0 0 6px;
      font-size: 24px;
      font-weight: 700;
    }}
    header p {{
      margin: 0;
      color: var(--muted);
      font-size: 14px;
    }}
    main {{
      padding: 22px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(460px, 1fr));
      gap: 18px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 18px;
      overflow: hidden;
      box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
    }}
    .card img {{
      display: block;
      width: 100%;
      height: auto;
      background: #fff;
    }}
    .meta {{
      padding: 14px 16px 16px;
    }}
    .title {{
      font-size: 16px;
      font-weight: 700;
      margin-bottom: 4px;
      color: var(--accent);
    }}
    .sub {{
      font-size: 13px;
      color: var(--muted);
      line-height: 1.5;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Triage Contacts Flat</h1>
    <p>One scrollable page for all segment storyboards. Context frames now include mask previews too.</p>
  </header>
  <main>
    {cards_html}
  </main>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")


def build_flat_contact_gallery(output_dir: Path, meta_dir: Path, segment_rows: Sequence[Dict[str, object]]) -> None:
    flat_dir = meta_dir / "triage_contacts_flat"
    if flat_dir.exists():
        for child in flat_dir.iterdir():
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
    flat_dir.mkdir(parents=True, exist_ok=True)

    flat_index_rows: List[Dict[str, object]] = []
    for order, row in enumerate(segment_rows, start=1):
        source_path = Path(str(row["segment_image"]))
        suffix = source_path.suffix or ".png"
        flat_name = f"{order:04d}_{row['segment_key']}_{re.sub(r'[^A-Za-z0-9._-]+', '_', str(row['dataset_name']))}{suffix}"
        target_path = flat_dir / flat_name
        shutil.copy2(source_path, target_path)
        flat_index_rows.append(
            {
                "order": order,
                "flat_name": flat_name,
                "segment_key": row["segment_key"],
                "b_id": row["b_id"],
                "group_name": row["group_name"],
                "dataset_name": row["dataset_name"],
                "source_start_index": row["source_start_index"],
                "source_end_index": row["source_end_index"],
                "dataset_total_frames": row["dataset_total_frames"],
                "issue_local_indices_display": row["issue_local_indices_display"],
                "original_segment_image": str(source_path),
            }
        )
    write_csv(meta_dir / "triage_contacts_flat_index.csv", flat_index_rows)
    build_html_gallery(meta_dir, flat_index_rows)


def parse_index_tokens(spec: str) -> List[int]:
    spec = str(spec).strip()
    if not spec:
        return []
    indices = set()
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = [part.strip() for part in token.split("-", 1)]
            start_text = re.sub(r"^[Ll]", "", start_text)
            end_text = re.sub(r"^[Ll]", "", end_text)
            if start_text.isdigit() and end_text.isdigit():
                start = int(start_text)
                end = int(end_text)
                if start > end:
                    start, end = end, start
                indices.update(range(start, end + 1))
            continue
        token = re.sub(r"^[Ll]", "", token)
        if token.isdigit():
            indices.add(int(token))
    return sorted(indices)


def compress_indices(indices: Sequence[int]) -> str:
    if not indices:
        return ""
    ordered = sorted(set(indices))
    ranges: List[str] = []
    start = ordered[0]
    prev = ordered[0]
    for value in ordered[1:]:
        if value == prev + 1:
            prev = value
            continue
        ranges.append(f"L{start:02d}-L{prev:02d}" if start != prev else f"L{start:02d}")
        start = value
        prev = value
    ranges.append(f"L{start:02d}-L{prev:02d}" if start != prev else f"L{start:02d}")
    return ",".join(ranges)


def load_existing_issue_table(meta_dir: Path) -> Dict[str, Dict[str, str]]:
    table_path = meta_dir / "triage_fill_table.csv"
    if not table_path.exists():
        return {}
    return {row["b_id"].strip().lower(): row for row in read_csv(table_path)}


def find_session_datasets(pack_root: Path) -> List[Dict[str, str]]:
    session_dir = pack_root / "_finetuning_batch_sessions"
    if not session_dir.is_dir():
        return []
    session_files = sorted(session_dir.glob("binary_queue_session_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not session_files:
        return []
    data = json.loads(session_files[0].read_text(encoding="utf-8"))
    return list(data.get("datasets", []))


def discover_pack_datasets(pack_root: Path) -> List[Dict[str, str]]:
    session_datasets = find_session_datasets(pack_root)
    if session_datasets:
        return session_datasets

    discovered: List[Dict[str, str]] = []
    for group_dir in sorted([path for path in pack_root.iterdir() if path.is_dir() and not path.name.startswith("_")], key=lambda p: natural_sort_key(p.name)):
        child_dirs = {path.name: path for path in group_dir.iterdir() if path.is_dir()}
        for dataset_name, origin_dir in sorted(child_dirs.items(), key=lambda item: natural_sort_key(item[0])):
            if dataset_name.endswith(("-mask", "-mask_new", "-hrtem", "-lrtem")):
                continue
            mask_dir = child_dirs.get(f"{dataset_name}-mask")
            if mask_dir is None:
                continue
            discovered.append(
                {
                    "group_name": group_dir.name,
                    "dataset_name": dataset_name,
                    "origin_dir": str(origin_dir),
                    "mask_dir": str(mask_dir),
                    "save_dir": str(group_dir / f"{dataset_name}-mask_new"),
                }
            )
    return discovered


def load_gray(path: Path) -> np.ndarray:
    image = load_grayscale(path)
    if image is None:
        raise FileNotFoundError(f"Failed to read image: {path}")
    return image


def frame_stem(frame_name: str) -> str:
    return Path(frame_name).stem


def fit_text(text: str, max_chars: int = 18) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1]}..."


def draw_text(image: np.ndarray, text: str, origin: Tuple[int, int], *, scale: float, color: Tuple[int, int, int], thickness: int = 1) -> None:
    cv2.putText(image, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def letterbox_gray(gray: np.ndarray, width: int, height: int, *, background: int = 245) -> np.ndarray:
    canvas = np.full((height, width), background, dtype=np.uint8)
    src_h, src_w = gray.shape[:2]
    scale = min(width / max(1, src_w), height / max(1, src_h))
    resized_w = max(1, int(round(src_w * scale)))
    resized_h = max(1, int(round(src_h * scale)))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(gray, (resized_w, resized_h), interpolation=interpolation)
    y0 = (height - resized_h) // 2
    x0 = (width - resized_w) // 2
    canvas[y0 : y0 + resized_h, x0 : x0 + resized_w] = resized
    return cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)


def letterbox_mask(mask: np.ndarray, width: int, height: int) -> np.ndarray:
    canvas = np.full((height, width, 3), MASK_BG, dtype=np.uint8)
    src_h, src_w = mask.shape[:2]
    scale = min(width / max(1, src_w), height / max(1, src_h))
    resized_w = max(1, int(round(src_w * scale)))
    resized_h = max(1, int(round(src_h * scale)))
    resized = cv2.resize(mask, (resized_w, resized_h), interpolation=cv2.INTER_NEAREST)
    mask_canvas = np.full((resized_h, resized_w, 3), MASK_BG, dtype=np.uint8)
    mask_canvas[:, :, 1] = np.maximum(resized, 28)
    mask_canvas[:, :, 0] = resized // 6
    mask_canvas[:, :, 2] = resized // 8
    y0 = (height - resized_h) // 2
    x0 = (width - resized_w) // 2
    canvas[y0 : y0 + resized_h, x0 : x0 + resized_w] = mask_canvas
    return canvas


def render_mask_inset(mask_path: Optional[Path], size: Tuple[int, int]) -> np.ndarray:
    inset_w, inset_h = size
    inset = np.full((inset_h, inset_w, 3), MASK_BG, dtype=np.uint8)
    cv2.rectangle(inset, (0, 0), (inset_w - 1, inset_h - 1), MASK_BORDER, 1)
    if mask_path is not None and mask_path.exists():
        mask = load_gray(mask_path)
        inset[2:-2, 2:-2] = letterbox_mask(mask, inset_w - 4, inset_h - 4)
    return inset


def render_tile(
    *,
    origin_path: Path,
    mask_path: Optional[Path],
    frame_name: str,
    sequence_index: int,
    total_frames: int,
    tile_width: int,
    tile_height: int,
    is_issue: bool,
    local_badge: Optional[str],
) -> np.ndarray:
    canvas = np.full((tile_height, tile_width, 3), PANEL_BG, dtype=np.uint8)
    header_h = 24
    footer_h = 18
    pad = 6
    image_box_w = tile_width - 2 * pad
    image_box_h = tile_height - header_h - footer_h - 2 * pad

    if is_issue:
        canvas[:] = ACCENT_LIGHT
        cv2.rectangle(canvas, (0, 0), (tile_width - 1, tile_height - 1), ACCENT, 3)
        cv2.rectangle(canvas, (0, 0), (tile_width - 1, header_h), (246, 239, 233), -1)
    else:
        cv2.rectangle(canvas, (0, 0), (tile_width - 1, tile_height - 1), BORDER, 1)
        cv2.rectangle(canvas, (0, 0), (tile_width - 1, header_h), (249, 250, 252), -1)

    origin = load_gray(origin_path)
    origin_bgr = letterbox_gray(origin, image_box_w, image_box_h, background=243 if is_issue else 247)
    canvas[header_h + pad : header_h + pad + image_box_h, pad : pad + image_box_w] = origin_bgr

    draw_text(canvas, f"#{sequence_index}/{total_frames}", (8, 15), scale=0.36, color=TITLE if is_issue else SUBTITLE)
    draw_text(canvas, fit_text(frame_stem(frame_name), max_chars=15), (8, tile_height - 6), scale=0.36, color=TITLE)

    if local_badge:
        badge_size, _ = cv2.getTextSize(local_badge, cv2.FONT_HERSHEY_SIMPLEX, 0.38, 1)
        badge_w = badge_size[0] + 12
        x1 = tile_width - badge_w - 8
        y1 = 5
        cv2.rectangle(canvas, (x1, y1), (x1 + badge_w, y1 + 15), ACCENT_DARK if is_issue else BADGE_GRAY, -1)
        draw_text(canvas, local_badge, (x1 + 6, y1 + 11), scale=0.38, color=(255, 255, 255))

    if local_badge and mask_path is not None and mask_path.exists():
        inset_side = max(28, min(image_box_h - 6, tile_width // 3))
        inset = render_mask_inset(mask_path, (inset_side, inset_side))
        y0 = header_h + pad + image_box_h - inset.shape[0] - 4
        x0 = tile_width - inset.shape[1] - 6
        canvas[y0 : y0 + inset.shape[0], x0 : x0 + inset.shape[1]] = inset
    if not is_issue:
        draw_text(canvas, "context", (tile_width - 54, 15), scale=0.34, color=SUBTITLE)

    return canvas


def get_dataset_source_info(
    dataset: Dict[str, str],
    manifest_by_dataset: Dict[Tuple[str, str], List[Dict[str, str]]],
) -> DatasetSourceInfo:
    key = (dataset["group_name"], dataset["dataset_name"])
    manifest_rows = manifest_by_dataset.get(key, [])
    pack_origin_dir = Path(dataset["origin_dir"])
    pack_mask_dir = Path(dataset["mask_dir"])
    pack_frame_names = iter_image_names(pack_origin_dir)
    pack_local_index_by_frame = {frame_name: idx for idx, frame_name in enumerate(pack_frame_names, start=1)}

    if manifest_rows:
        first_row = manifest_rows[0]
        source_origin_dir = Path(first_row["source_origin"]).parent
        source_mask_dir = Path(first_row["source_mask"]).parent
    else:
        source_origin_dir = pack_origin_dir
        source_mask_dir = pack_mask_dir

    return DatasetSourceInfo(source_origin_dir, source_mask_dir, pack_local_index_by_frame)


def cluster_issue_indices(issue_indices: Sequence[int], *, radius: int, total_frames: int) -> List[Tuple[int, int, List[int]]]:
    if not issue_indices:
        if total_frames <= 0:
            return []
        return [(0, total_frames - 1, [])]

    sorted_unique = sorted(set(issue_indices))
    clusters: List[Tuple[int, int, List[int]]] = []
    current_start = max(0, sorted_unique[0] - radius)
    current_end = min(total_frames - 1, sorted_unique[0] + radius)
    current_issues = [sorted_unique[0]]

    for index in sorted_unique[1:]:
        window_start = max(0, index - radius)
        window_end = min(total_frames - 1, index + radius)
        if window_start <= current_end + 1:
            current_end = max(current_end, window_end)
            current_issues.append(index)
        else:
            clusters.append((current_start, current_end, current_issues))
            current_start = window_start
            current_end = window_end
            current_issues = [index]
    clusters.append((current_start, current_end, current_issues))
    return clusters


def build_segment_windows(
    *,
    full_frame_names: Sequence[str],
    issue_frame_names: Sequence[str],
    pack_local_index_by_frame: Dict[str, int],
    context_radius: int,
) -> List[SegmentWindow]:
    frame_index_by_name = {frame_name: idx for idx, frame_name in enumerate(full_frame_names)}
    issue_indices = [frame_index_by_name[name] for name in issue_frame_names if name in frame_index_by_name]
    clusters = cluster_issue_indices(issue_indices, radius=max(0, context_radius), total_frames=len(full_frame_names))

    windows: List[SegmentWindow] = []
    for segment_id, (start_idx, end_idx, cluster_issue_indices_list) in enumerate(clusters, start=1):
        issue_frames = [full_frame_names[idx] for idx in cluster_issue_indices_list]
        windows.append(
            SegmentWindow(
                segment_id=segment_id,
                start_index=start_idx,
                end_index=end_idx,
                issue_indices=[idx + 1 for idx in cluster_issue_indices_list],
                issue_frames=issue_frames,
                issue_local_indices=[pack_local_index_by_frame[name] for name in issue_frames if name in pack_local_index_by_frame],
            )
        )
    return windows


def issue_summary_text(local_indices: Sequence[int]) -> str:
    if not local_indices:
        return "No highlighted issue frames"
    ordered = sorted(set(local_indices))
    segments: List[str] = []
    start = ordered[0]
    prev = ordered[0]
    for value in ordered[1:]:
        if value == prev + 1:
            prev = value
            continue
        segments.append(f"L{start:02d}-L{prev:02d}" if start != prev else f"L{start:02d}")
        start = value
        prev = value
    segments.append(f"L{start:02d}-L{prev:02d}" if start != prev else f"L{start:02d}")
    return ", ".join(segments)


def draw_timeline(
    canvas: np.ndarray,
    *,
    x: int,
    y: int,
    width: int,
    total_frames: int,
    window_start: int,
    window_end: int,
    issue_indices: Sequence[int],
) -> None:
    cv2.rectangle(canvas, (x, y), (x + width, y + 8), TIMELINE_BG, -1)
    if total_frames <= 1:
        cv2.rectangle(canvas, (x, y), (x + width, y + 8), TIMELINE_FG, -1)
    else:
        wx0 = x + int(round((window_start / (total_frames - 1)) * width))
        wx1 = x + int(round((window_end / (total_frames - 1)) * width))
        cv2.rectangle(canvas, (wx0, y), (max(wx0 + 2, wx1), y + 8), TIMELINE_FG, -1)
        for idx in issue_indices:
            px = x + int(round(((idx - 1) / (total_frames - 1)) * width))
            cv2.line(canvas, (px, y - 2), (px, y + 10), ACCENT, 2)
    cv2.rectangle(canvas, (x, y), (x + width, y + 8), BORDER, 1)


def make_segment_sheet(
    *,
    source_origin_dir: Path,
    source_mask_dir: Path,
    full_frame_names: Sequence[str],
    pack_local_index_by_frame: Dict[str, int],
    window: SegmentWindow,
    output_path: Path,
    title: str,
    columns: int,
    tile_size: Tuple[int, int],
) -> None:
    tile_width, tile_height = tile_size
    frame_names = list(full_frame_names[window.start_index : window.end_index + 1])
    rows = max(1, math.ceil(len(frame_names) / max(1, columns)))
    margin = 18
    header_h = 96
    footer_pad = 16
    width = margin * 2 + columns * tile_width
    height = header_h + rows * tile_height + footer_pad

    sheet = np.full((height, width, 3), BG, dtype=np.uint8)
    draw_text(sheet, title, (18, 28), scale=0.8, color=TITLE, thickness=2)

    total_frames = len(full_frame_names)
    remaining_tail = max(0, total_frames - window.end_index - 1)
    coverage_text = (
        f"Segment {window.segment_id}  |  source frames {window.start_index + 1}-{window.end_index + 1} / {total_frames} total"
        f"  |  tail remaining {remaining_tail}"
    )
    draw_text(sheet, coverage_text, (18, 52), scale=0.46, color=SUBTITLE)
    draw_text(sheet, f"Highlighted: {issue_summary_text(window.issue_local_indices)}", (18, 74), scale=0.46, color=ACCENT_DARK)
    draw_text(sheet, "Orange tiles are suspected issue frames. Gray-badge tiles are context-only pack frames.", (18, 92), scale=0.4, color=SUBTITLE)
    draw_timeline(
        sheet,
        x=width - 290,
        y=64,
        width=250,
        total_frames=total_frames,
        window_start=window.start_index,
        window_end=window.end_index,
        issue_indices=window.issue_indices,
    )

    issue_index_set = set(window.issue_indices)
    for offset, frame_name in enumerate(frame_names):
        row = offset // columns
        col = offset % columns
        sequence_index = window.start_index + offset + 1
        local_index = pack_local_index_by_frame.get(frame_name)
        is_issue = sequence_index in issue_index_set
        tile = render_tile(
            origin_path=source_origin_dir / frame_name,
            mask_path=(source_mask_dir / frame_name),
            frame_name=frame_name,
            sequence_index=sequence_index,
            total_frames=total_frames,
            tile_width=tile_width,
            tile_height=tile_height,
            is_issue=is_issue,
            local_badge=(f"L{local_index:02d}" if local_index is not None else None),
        )
        y0 = header_h + row * tile_height
        x0 = margin + col * tile_width
        sheet[y0 : y0 + tile_height, x0 : x0 + tile_width] = tile

    if not cv_imwrite(output_path, sheet):
        raise OSError(f"Failed to write contact sheet: {output_path}")


def load_selected_issue_frames(meta_dir: Path) -> Dict[Tuple[str, str], List[str]]:
    selected_events_path = meta_dir / "selected_events_review.csv"
    issue_frames: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    if selected_events_path.exists():
        for row in read_csv(selected_events_path):
            key = (row["group_name"], row["dataset_name"])
            frame_name = row.get("frame_name", "").strip()
            if frame_name and frame_name not in issue_frames[key]:
                issue_frames[key].append(frame_name)
    return issue_frames


def load_manifest_sources(meta_dir: Path) -> Dict[Tuple[str, str], List[Dict[str, str]]]:
    manifest_path = meta_dir / "frame_manifest.csv"
    manifest_by_dataset: Dict[Tuple[str, str], List[Dict[str, str]]] = defaultdict(list)
    if manifest_path.exists():
        for row in read_csv(manifest_path):
            manifest_by_dataset[(row["group_name"], row["dataset_name"])].append(row)
    return manifest_by_dataset


def read_segment_notes(notes_path: Path) -> Dict[str, Dict[str, str]]:
    if not notes_path.exists():
        return {}
    sections: Dict[str, Dict[str, str]] = {}
    current: Optional[str] = None
    for raw_line in notes_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        section_match = re.match(r"^\[([^\]]+)\]$", line)
        if section_match:
            current = section_match.group(1).strip()
            sections.setdefault(current, {})
            continue
        if current is None or "=" not in line:
            continue
        key, value = line.split("=", 1)
        sections[current][key.strip()] = value.strip()
    return sections


def write_segment_notes(notes_path: Path, segment_rows: Sequence[Dict[str, object]]) -> None:
    existing = read_segment_notes(notes_path)
    existing_issue_table = load_existing_issue_table(notes_path.parent)
    lines = [
        "# Segment notes template for fast triage",
        "# Fill frame numbers with pack-local badges like L04,L11,L16-L17 or plain numbers like 4,11,16-17.",
        "# Edit only the values after '='. Keep the section headers unchanged.",
        "",
    ]
    for row in segment_rows:
        segment_key = str(row["segment_key"])
        stored = existing.get(segment_key, {})
        existing_table_row = existing_issue_table.get(str(row["b_id"]).strip().lower(), {})
        segment_indices = parse_index_tokens(str(row.get("segment_pack_local_indices", "")))

        def default_issue_value(issue_code: str) -> str:
            if stored.get(f"issue{issue_code}_frames", "").strip():
                return stored.get(f"issue{issue_code}_frames", "").strip()
            existing_spec = existing_table_row.get(f"issue{issue_code}_frames", "")
            if not existing_spec:
                return ""
            subset = [value for value in parse_index_tokens(existing_spec) if value in set(segment_indices)]
            return compress_indices(subset)

        lines.extend(
            [
                f"# {segment_key} | {row['group_name']} / {row['dataset_name']}",
                f"# image={row['segment_image']}",
                f"# source_range={row['source_start_index']}-{row['source_end_index']} / {row['dataset_total_frames']} total | highlighted={row['issue_local_indices_display'] or 'none'}",
                f"[{segment_key}]",
                f"issue1_frames={default_issue_value('1')}",
                f"issue2_frames={default_issue_value('2')}",
                f"issue4_frames={default_issue_value('4')}",
                f"issue5_frames={default_issue_value('5')}",
                f"note={stored.get('note', '')}",
                f"done={stored.get('done', '')}",
                "",
            ]
        )
    notes_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build long-context triage storyboards, one PNG per segment.")
    parser.add_argument("--pack-root", required=True, help="Reduced label pack root.")
    parser.add_argument("--output-dir", help="Optional output directory. Defaults to _label_pack_meta/triage_contacts.")
    parser.add_argument("--columns", type=int, default=10, help="Number of columns per segment storyboard.")
    parser.add_argument("--tile-width", type=int, default=148, help="Tile width.")
    parser.add_argument("--tile-height", type=int, default=116, help="Tile height.")
    parser.add_argument("--context-radius", type=int, default=50, help="How many full-sequence frames to show on each side of highlighted issue frames.")
    args = parser.parse_args()

    pack_root = Path(args.pack_root).resolve()
    meta_dir = pack_root / "_label_pack_meta"
    output_dir = Path(args.output_dir).resolve() if args.output_dir else (meta_dir / "triage_contacts")
    if output_dir.exists():
        for child in output_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            elif child.is_file():
                child.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)

    datasets = discover_pack_datasets(pack_root)
    if not datasets:
        raise RuntimeError(f"No dataset pairs found under {pack_root}")

    issue_frames_by_dataset = load_selected_issue_frames(meta_dir)
    manifest_by_dataset = load_manifest_sources(meta_dir)

    triage_rows: List[Dict[str, object]] = []
    frame_rows: List[Dict[str, object]] = []
    segment_rows: List[Dict[str, object]] = []

    for index, dataset in enumerate(datasets, start=1):
        source_info = get_dataset_source_info(dataset, manifest_by_dataset)
        full_frame_names = iter_image_names(source_info.source_origin_dir)
        if not full_frame_names:
            continue

        b_id = f"b{index}"
        dataset_contact_dir = output_dir / b_id
        dataset_contact_dir.mkdir(parents=True, exist_ok=True)
        key = (dataset["group_name"], dataset["dataset_name"])
        dataset_issue_frames = sorted(issue_frames_by_dataset.get(key, []), key=natural_sort_key)

        windows = build_segment_windows(
            full_frame_names=full_frame_names,
            issue_frame_names=dataset_issue_frames,
            pack_local_index_by_frame=source_info.pack_local_index_by_frame,
            context_radius=max(0, args.context_radius),
        )

        safe_dataset = re.sub(r"[^A-Za-z0-9._-]+", "_", dataset["dataset_name"])
        for window in windows:
            segment_key = f"{b_id}_s{window.segment_id:02d}"
            segment_image_path = dataset_contact_dir / f"{segment_key}_{safe_dataset}.png"
            segment_pack_local_indices = [
                source_info.pack_local_index_by_frame[frame_name]
                for frame_name in full_frame_names[window.start_index : window.end_index + 1]
                if frame_name in source_info.pack_local_index_by_frame
            ]
            make_segment_sheet(
                source_origin_dir=source_info.source_origin_dir,
                source_mask_dir=source_info.source_mask_dir,
                full_frame_names=full_frame_names,
                pack_local_index_by_frame=source_info.pack_local_index_by_frame,
                window=window,
                output_path=segment_image_path,
                title=f"{segment_key} | {dataset['group_name']} / {dataset['dataset_name']}",
                columns=max(1, args.columns),
                tile_size=(args.tile_width, args.tile_height),
            )
            segment_rows.append(
                {
                    "segment_key": segment_key,
                    "b_id": b_id,
                    "group_name": dataset["group_name"],
                    "dataset_name": dataset["dataset_name"],
                    "segment_id": window.segment_id,
                    "source_start_index": window.start_index + 1,
                    "source_end_index": window.end_index + 1,
                    "source_frame_count": window.end_index - window.start_index + 1,
                    "dataset_total_frames": len(full_frame_names),
                    "tail_remaining_frames": max(0, len(full_frame_names) - window.end_index - 1),
                    "issue_frame_names": "|".join(window.issue_frames),
                    "issue_source_indices": "|".join(str(value) for value in window.issue_indices),
                    "issue_local_indices": "|".join(str(value) for value in window.issue_local_indices),
                    "issue_local_indices_display": issue_summary_text(window.issue_local_indices),
                    "segment_pack_local_indices": compress_indices(segment_pack_local_indices),
                    "segment_image": str(segment_image_path),
                }
            )

        triage_rows.append(
            {
                "b_id": b_id,
                "group_name": dataset["group_name"],
                "dataset_name": dataset["dataset_name"],
                "frame_count": len(full_frame_names),
                "issue_frame_count": len(dataset_issue_frames),
                "segment_count": len(windows),
                "contact_sheet": str(dataset_contact_dir),
                "origin_dir": str(Path(dataset["origin_dir"])),
                "mask_dir": str(Path(dataset["mask_dir"])),
                "save_dir": dataset.get("save_dir", ""),
                "source_origin_dir": str(source_info.source_origin_dir),
                "source_mask_dir": str(source_info.source_mask_dir),
            }
        )

        pack_frame_names = iter_image_names(Path(dataset["origin_dir"]))
        source_sequence_index_by_frame = {frame_name: idx for idx, frame_name in enumerate(full_frame_names, start=1)}
        highlighted = set(dataset_issue_frames)
        for local_index, frame_name in enumerate(pack_frame_names, start=1):
            frame_rows.append(
                {
                    "b_id": b_id,
                    "group_name": dataset["group_name"],
                    "dataset_name": dataset["dataset_name"],
                    "local_index": local_index,
                    "frame_name": frame_name,
                    "origin_path": str(Path(dataset["origin_dir"]) / frame_name),
                    "mask_path": str(Path(dataset["mask_dir"]) / frame_name),
                    "source_sequence_index": source_sequence_index_by_frame.get(frame_name, ""),
                    "source_origin_path": str(source_info.source_origin_dir / frame_name),
                    "source_mask_path": str(source_info.source_mask_dir / frame_name),
                    "is_highlighted_issue": "yes" if frame_name in highlighted else "",
                }
            )

    write_csv(
        meta_dir / "triage_index.csv",
        triage_rows,
        fieldnames=(
            "b_id",
            "group_name",
            "dataset_name",
            "frame_count",
            "issue_frame_count",
            "segment_count",
            "contact_sheet",
            "origin_dir",
            "mask_dir",
            "save_dir",
            "source_origin_dir",
            "source_mask_dir",
        ),
    )
    write_csv(
        meta_dir / "triage_frame_map.csv",
        frame_rows,
        fieldnames=(
            "b_id",
            "group_name",
            "dataset_name",
            "local_index",
            "frame_name",
            "origin_path",
            "mask_path",
            "source_sequence_index",
            "source_origin_path",
            "source_mask_path",
            "is_highlighted_issue",
        ),
    )
    write_csv(
        meta_dir / "triage_segments.csv",
        segment_rows,
        fieldnames=(
            "segment_key",
            "b_id",
            "group_name",
            "dataset_name",
            "segment_id",
            "source_start_index",
            "source_end_index",
            "source_frame_count",
            "dataset_total_frames",
            "tail_remaining_frames",
            "issue_frame_names",
            "issue_source_indices",
            "issue_local_indices",
            "issue_local_indices_display",
            "segment_pack_local_indices",
            "segment_image",
        ),
    )
    write_segment_notes(meta_dir / "triage_segment_notes.txt", segment_rows)
    build_flat_contact_gallery(output_dir, meta_dir, segment_rows)
    write_markdown(meta_dir / "triage_index.md", triage_rows)
    print(
        json.dumps(
            {
                "dataset_count": len(triage_rows),
                "pack_frame_count": len(frame_rows),
                "segment_count": len(segment_rows),
                "context_radius": max(0, args.context_radius),
                "output_dir": str(output_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
