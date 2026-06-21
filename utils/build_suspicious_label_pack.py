#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


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
                hrtem_dir=child_dirs.get(f"{dataset_name}-hrtem"),
                lrtem_dir=child_dirs.get(f"{dataset_name}-lrtem"),
            )
    return pairs


def read_events(csv_path: Path) -> List[Dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_event_types(value: Sequence[str]) -> Set[str]:
    return {item.strip() for item in value if item.strip()}


def copy_if_exists(source: Path, target: Path) -> bool:
    if not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


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


def select_events(
    rows: Sequence[Dict[str, str]],
    *,
    event_types: Set[str],
    max_events: int,
    max_events_per_dataset: int,
    min_severity: float,
    dataset_filters: Set[str],
) -> List[Dict[str, str]]:
    selected: List[Dict[str, str]] = []
    per_dataset_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    seen_keys: Set[Tuple[str, str, str, str]] = set()

    sorted_rows = sorted(
        rows,
        key=lambda row: (
            -float(row.get("severity_score") or 0.0),
            row.get("group_name", ""),
            row.get("dataset_name", ""),
            row.get("frame_name", ""),
        ),
    )

    for row in sorted_rows:
        event_type = row.get("event_type", "").strip()
        if event_types and event_type not in event_types:
            continue
        severity = float(row.get("severity_score") or 0.0)
        if severity < min_severity:
            continue

        group_name = row.get("group_name", "").strip()
        dataset_name = row.get("dataset_name", "").strip()
        dataset_key = (group_name, dataset_name)
        dataset_label = f"{group_name}/{dataset_name}"
        if dataset_filters and dataset_name not in dataset_filters and dataset_label not in dataset_filters:
            continue

        row_key = (group_name, dataset_name, row.get("frame_name", "").strip(), event_type)
        if row_key in seen_keys:
            continue
        if per_dataset_counts[dataset_key] >= max_events_per_dataset:
            continue

        selected.append(dict(row))
        seen_keys.add(row_key)
        per_dataset_counts[dataset_key] += 1
        if len(selected) >= max_events:
            break

    return selected


def parse_context_names(row: Dict[str, str], include_context: bool) -> List[str]:
    center = row.get("frame_name", "").strip()
    if not include_context:
        return [center] if center else []
    names = [name.strip() for name in row.get("context_names", "").split("|") if name.strip()]
    if center and center not in names:
        names.append(center)
    return sorted(set(names), key=natural_sort_key)


def write_readme(readme_path: Path, summary: Dict[str, object]) -> None:
    lines = [
        "# Suspicious Label Pack",
        "",
        "This pack contains only suspicious frames exported from the binary segmentation audit.",
        "",
        "## How To Use",
        "",
        "1. Open Finetuning.",
        "2. Run the Binary queue starter and choose this pack root as the queue root.",
        "3. Review only the small subset copied here instead of the full 657 datasets.",
        "4. Save refinements into the automatically created `-mask_new` folders.",
        "5. Return both the edited `-mask_new` folders and the filled review CSV files.",
        "",
        "## Important",
        "",
        "- Frame names such as `00237.png` are heavily reused across datasets, so always identify a frame with `group_name + dataset_name + frame_name` together.",
        "",
        "## Files",
        "",
        "- `_label_pack_meta/selected_events_review.csv`: event-level review sheet with extra user columns.",
        "- `_label_pack_meta/frame_manifest.csv`: every copied frame and whether it is a center frame or context frame.",
        "- `_label_pack_meta/manual_frame_requests_template.csv`: add extra frames not already selected by the audit.",
        "",
        "## Export Summary",
        "",
        f"- Source root: `{summary['root']}`",
        f"- Audit dir: `{summary['audit_dir']}`",
        f"- Selected events: `{summary['selected_events']}`",
        f"- Datasets covered: `{summary['dataset_count']}`",
        f"- Frames copied: `{summary['frame_count']}`",
        f"- Context included: `{summary['include_context']}`",
        f"- HRTEM copied: `{summary['copy_hrtem']}`",
        f"- LRTEM copied: `{summary['copy_lrtem']}`",
    ]
    readme_path.write_text("\n".join(lines), encoding="utf-8")


def write_labeling_guide(guide_path: Path) -> None:
    lines = [
        "# 标注回填说明",
        "",
        "## 先说清一个约定",
        "",
        "- 用户口头里说的“黑球”只是一个便于交流的叫法，不代表目标一定真的是黑球。",
        "- 标注时请以“真正希望模型分出来的目标区域”为准，而不是以颜色或形状字面含义为准。",
        "",
        "## 推荐的 `user_issue_type` 填法",
        "",
        "- `target_miss_or_weak_response`: 真正目标没有被稳定分出来，表现为漏检、响应很弱、或因为过暗/对比度太差导致几乎没响应。",
        "- `boundary_false_positive`: 模型把液池边界或横向亮/暗条带误分进了 mask。",
        "- `internal_gap`: 中间几帧突然掉空，但前后邻帧是正常的。",
        "- `tail_empty_normal`: 结尾处变空，而且用户判断这段本来就可以接受。",
        "- `other`: 其他无法归到以上几类的问题，可在 `user_notes` 里说明。",
        "",
        "说明：暗、浅、对比度差导致的弱响应，都建议统一填成 `target_miss_or_weak_response`，不用再单独拆一类。",
        "",
        "## `selected_events_review.csv` 怎么填",
        "",
        "- `user_keep`: 建议填 `yes` / `no`。",
        "- `user_need_pixel_label`: 需要你真正修 mask 的填 `yes`。",
        "- `user_need_rerun`: 你觉得先尝试重新推理/增强复跑就够的填 `yes`。",
        "- `user_notes`: 写清楚真正目标是什么，尤其是“上半部分目标区域，不是液池边界”这类语义信息。",
        "",
        "## `manual_frame_requests_template.csv` 什么时候用",
        "",
        "- 当你发现某个重要坏帧没有被当前审计抓到，就把它补进这个模板。",
        "- 请一定同时填写 `group_name`、`dataset_name`、`frame_name`，仅写帧号不够，因为同一个帧号会在很多数据集中重复出现。",
        "",
        "## 最快的实际操作流程",
        "",
        "1. 打开 Finetuning。",
        "2. 运行菜单 `0. 启动 Binary 批量精修队列...`。",
        "3. 根目录选择当前小包根目录，也就是包含很多 `dataset / dataset-mask` 的那一层。",
        "4. 工具会自动把保存目录指向同级的 `dataset-mask_new`，不会覆盖原始 `dataset-mask`。",
        "5. 修完当前数据集后，运行 `0.1 下一个 Binary 数据集...` 继续。",
        "6. 想看还剩多少时，运行 `0.2 查看 Binary 队列进度...`。",
        "7. 同时在 `selected_events_review.csv` 里把你确认的事件填上 `user_issue_type` 和简短备注。",
        "8. 如果发现有重要坏帧没进包，就在 `manual_frame_requests_template.csv` 里补进去。",
        "",
        "## 怎么把反馈给我",
        "",
        "- 最简单：直接告诉我你改好的 `-mask_new` 目录路径，或告诉我你已经更新了哪一个 `selected_events_review.csv`。",
        "- 如果只想先给少量结论，也可以直接告诉我几条三元组：`group_name / dataset_name / frame_name`，再加一句“真正目标是什么、哪里分错了”。",
        "- 如果你补了 `manual_frame_requests_template.csv`，告诉我那个文件已经填好，我就可以继续帮你把新增坏帧打包出来。",
        "",
        "## 建议的优先级",
        "",
        "1. `target_miss_or_weak_response`",
        "2. `boundary_false_positive`",
        "3. `internal_gap`",
        "4. 其余局部时序断裂样本",
    ]
    guide_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a small label pack from suspicious segmentation audit events.")
    parser.add_argument("--root", required=True, help="Root directory containing dataset / dataset-mask pairs.")
    parser.add_argument("--audit-dir", required=True, help="Audit output directory containing suspicious_events.csv.")
    parser.add_argument("--output", required=True, help="Output directory for the reduced label pack.")
    parser.add_argument("--max-events", type=int, default=240, help="Maximum suspicious events to export.")
    parser.add_argument("--max-events-per-dataset", type=int, default=12, help="Cap events exported per dataset.")
    parser.add_argument("--min-severity", type=float, default=0.0, help="Minimum severity_score to keep.")
    parser.add_argument(
        "--event-types",
        nargs="*",
        default=("internal_gap", "abrupt_drop"),
        help="Event types to export. Defaults to both internal_gap and abrupt_drop.",
    )
    parser.add_argument(
        "--dataset-filter",
        nargs="*",
        default=(),
        help="Optional dataset filters. Accepts either dataset_name or 'group_name/dataset_name'.",
    )
    parser.add_argument(
        "--center-only",
        action="store_true",
        help="Copy only center frames. By default, the full local context window is copied too.",
    )
    parser.add_argument("--copy-hrtem", action="store_true", help="Copy matching hrtem frames when available.")
    parser.add_argument("--copy-lrtem", action="store_true", help="Copy matching lrtem frames when available.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    audit_dir = Path(args.audit_dir).resolve()
    output = Path(args.output).resolve()
    meta_dir = output / "_label_pack_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    events_csv = audit_dir / "suspicious_events.csv"
    if not events_csv.exists():
        raise FileNotFoundError(f"Missing suspicious_events.csv under {audit_dir}")

    dataset_lookup = discover_dataset_pairs(root)
    if not dataset_lookup:
        raise RuntimeError(f"No dataset / mask pairs found under {root}")

    selected_events = select_events(
        read_events(events_csv),
        event_types=parse_event_types(args.event_types),
        max_events=max(0, args.max_events),
        max_events_per_dataset=max(1, args.max_events_per_dataset),
        min_severity=float(args.min_severity),
        dataset_filters={item.strip() for item in args.dataset_filter if item.strip()},
    )
    if not selected_events:
        raise RuntimeError("No suspicious events matched the current selection filters.")

    include_context = not args.center_only
    frame_manifest_rows: List[Dict[str, object]] = []
    selected_events_rows: List[Dict[str, object]] = []
    copied_frames = 0
    dataset_count = 0

    grouped_events: Dict[Tuple[str, str], List[Dict[str, str]]] = defaultdict(list)
    for row in selected_events:
        grouped_events[(row["group_name"], row["dataset_name"])].append(row)

    for dataset_key, dataset_events in sorted(grouped_events.items(), key=lambda item: natural_sort_key(f"{item[0][0]}::{item[0][1]}")):
        dataset = dataset_lookup.get(dataset_key)
        if dataset is None:
            continue
        dataset_count += 1

        frames_to_copy: Dict[str, Set[str]] = defaultdict(set)
        center_frames: Set[str] = set()
        for row in dataset_events:
            center = row.get("frame_name", "").strip()
            if center:
                center_frames.add(center)
            for name in parse_context_names(row, include_context):
                frames_to_copy[name].add(center or name)
            selected_events_rows.append(
                {
                    **row,
                    "user_keep": "",
                    "user_issue_type": "",
                    "user_need_pixel_label": "",
                    "user_need_rerun": "",
                    "user_notes": "",
                }
            )

        pack_group_dir = output / dataset.group_dir.name
        pack_origin_dir = pack_group_dir / dataset.dataset_name
        pack_mask_dir = pack_group_dir / f"{dataset.dataset_name}-mask"
        pack_hrtem_dir = pack_group_dir / f"{dataset.dataset_name}-hrtem" if args.copy_hrtem else None
        pack_lrtem_dir = pack_group_dir / f"{dataset.dataset_name}-lrtem" if args.copy_lrtem else None
        pack_origin_dir.mkdir(parents=True, exist_ok=True)
        pack_mask_dir.mkdir(parents=True, exist_ok=True)
        if pack_hrtem_dir is not None:
            pack_hrtem_dir.mkdir(parents=True, exist_ok=True)
        if pack_lrtem_dir is not None:
            pack_lrtem_dir.mkdir(parents=True, exist_ok=True)

        for frame_name in sorted(frames_to_copy.keys(), key=natural_sort_key):
            source_origin = dataset.origin_dir / frame_name
            source_mask = dataset.mask_dir / frame_name
            if not source_origin.exists():
                continue

            copied_origin = copy_if_exists(source_origin, pack_origin_dir / frame_name)
            copied_mask = copy_if_exists(source_mask, pack_mask_dir / frame_name)
            copied_hrtem = False
            copied_lrtem = False
            if args.copy_hrtem and dataset.hrtem_dir is not None:
                copied_hrtem = copy_if_exists(dataset.hrtem_dir / frame_name, pack_hrtem_dir / frame_name)  # type: ignore[arg-type]
            if args.copy_lrtem and dataset.lrtem_dir is not None:
                copied_lrtem = copy_if_exists(dataset.lrtem_dir / frame_name, pack_lrtem_dir / frame_name)  # type: ignore[arg-type]

            if copied_origin:
                copied_frames += 1
                frame_manifest_rows.append(
                    {
                        "group_name": dataset.group_dir.name,
                        "dataset_name": dataset.dataset_name,
                        "frame_name": frame_name,
                        "frame_role": "center" if frame_name in center_frames else "context",
                        "selected_by_centers": "|".join(sorted(frames_to_copy[frame_name], key=natural_sort_key)),
                        "source_origin": str(source_origin),
                        "source_mask": str(source_mask),
                        "pack_origin": str(pack_origin_dir / frame_name),
                        "pack_mask": str(pack_mask_dir / frame_name),
                        "copied_mask": copied_mask,
                        "copied_hrtem": copied_hrtem,
                        "copied_lrtem": copied_lrtem,
                    }
                )

    write_csv(meta_dir / "selected_events_review.csv", selected_events_rows)
    write_csv(meta_dir / "frame_manifest.csv", frame_manifest_rows)
    write_csv(
        meta_dir / "manual_frame_requests_template.csv",
        [],
        fieldnames=(
            "group_name",
            "dataset_name",
            "frame_name",
            "user_issue_type",
            "user_need_pixel_label",
            "user_need_rerun",
            "user_notes",
        ),
    )
    write_labeling_guide(meta_dir / "labeling_guide_zh.md")

    summary = {
        "root": str(root),
        "audit_dir": str(audit_dir),
        "selected_events": len(selected_events_rows),
        "dataset_count": dataset_count,
        "frame_count": copied_frames,
        "include_context": include_context,
        "copy_hrtem": bool(args.copy_hrtem),
        "copy_lrtem": bool(args.copy_lrtem),
    }
    (meta_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_readme(output / "README.md", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved suspicious label pack to {output}")


if __name__ == "__main__":
    main()
