#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence, Set


ISSUE_CODE_LABELS = {
    "1": "target_miss_or_weak_response",
    "2": "boundary_false_positive",
    "3": "target_miss_or_weak_response",
    "4": "tail_empty_normal",
    "5": "other",
}


def normalize_issue_code(issue_code: str) -> str:
    normalized = str(issue_code).strip()
    if normalized == "3":
        return "1"
    return normalized


def read_csv(csv_path: Path) -> List[Dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(csv_path: Path, rows: Sequence[Dict[str, object]], fieldnames: Sequence[str]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def natural_sort_key(value: str) -> List[object]:
    return [int(token) if token.isdigit() else token.lower() for token in re.split(r"(\d+)", str(value))]


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
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        start = value
        prev = value
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(ranges)


def merge_index_specs(*specs: str) -> str:
    merged: Set[int] = set()
    for spec in specs:
        merged.update(parse_index_tokens(spec))
    return compress_indices(sorted(merged))


def merge_notes(*notes: str) -> str:
    ordered: List[str] = []
    for note in notes:
        for part in str(note).split("|"):
            value = part.strip()
            if value and value not in ordered:
                ordered.append(value)
    return " | ".join(ordered)


def parse_index_tokens(spec: str) -> List[int]:
    spec = str(spec).strip()
    if not spec:
        return []
    indices: Set[int] = set()
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


def read_segment_notes(notes_path: Path) -> Dict[str, Dict[str, str]]:
    if not notes_path.exists():
        return {}
    sections: Dict[str, Dict[str, str]] = {}
    current: str | None = None
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or refresh a CSV triage fill table for faster manual labeling.")
    parser.add_argument("--pack-root", required=True, help="Stage-1 pack root, for example suspicious_label_pack_top180.")
    args = parser.parse_args()

    pack_root = Path(args.pack_root).resolve()
    meta_dir = pack_root / "_label_pack_meta"
    triage_index_path = meta_dir / "triage_index.csv"
    record_expanded_path = meta_dir / "record_expanded.csv"
    summary_path = meta_dir / "record_dataset_summary.csv"
    existing_table_path = meta_dir / "triage_fill_table.csv"
    segment_notes_path = meta_dir / "triage_segment_notes.txt"
    triage_segments_path = meta_dir / "triage_segments.csv"
    if not triage_index_path.exists():
        raise FileNotFoundError(f"Missing triage_index.csv under {meta_dir}")

    triage_rows = read_csv(triage_index_path)
    existing_table_by_bid = {row["b_id"].strip().lower(): row for row in read_csv(existing_table_path)} if existing_table_path.exists() else {}
    record_rows = read_csv(record_expanded_path) if record_expanded_path.exists() else []
    summary_rows = {row["b_id"].strip().lower(): row for row in read_csv(summary_path)} if summary_path.exists() else {}
    segment_rows = read_csv(triage_segments_path) if triage_segments_path.exists() else []
    segment_notes = read_segment_notes(segment_notes_path)
    segment_notes_active = any(
        any(section.get(f"issue{code}_frames", "").strip() for code in ("1", "2", "4", "5"))
        or section.get("note", "").strip()
        or section.get("done", "").strip()
        for section in segment_notes.values()
    )

    indices_by_bid_issue: Dict[str, Dict[str, Set[int]]] = defaultdict(lambda: defaultdict(set))
    notes_by_bid_issue: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    general_notes_by_bid: Dict[str, List[str]] = defaultdict(list)
    done_markers_by_bid: Dict[str, List[str]] = defaultdict(list)
    if not segment_notes_active:
        for row in record_rows:
            b_id = row["b_id"].strip().lower()
            issue_code = normalize_issue_code(row["issue_code"].strip())
            local_index = int(row["local_index"])
            indices_by_bid_issue[b_id][issue_code].add(local_index)
            note = str(row.get("note", "")).strip()
            if note and note not in notes_by_bid_issue[b_id][issue_code]:
                notes_by_bid_issue[b_id][issue_code].append(note)

    for row in segment_rows:
        segment_key = str(row.get("segment_key", "")).strip()
        if not segment_key:
            continue
        section = segment_notes.get(segment_key)
        if not section:
            continue
        b_id = str(row.get("b_id", "")).strip().lower()
        if not b_id:
            continue
        for issue_code in ("1", "2", "4", "5"):
            spec = section.get(f"issue{issue_code}_frames", "")
            for local_index in parse_index_tokens(spec):
                indices_by_bid_issue[b_id][issue_code].add(local_index)
        note = section.get("note", "").strip()
        if note and note not in general_notes_by_bid[b_id]:
            general_notes_by_bid[b_id].append(note)
        done = section.get("done", "").strip()
        if done and done not in done_markers_by_bid[b_id]:
            done_markers_by_bid[b_id].append(done)

    fieldnames = [
        "done",
        "b_id",
        "group_name",
        "dataset_name",
        "frame_count",
        "contact_sheet",
    ]
    for code in ("1", "2", "3", "4", "5"):
        fieldnames.extend((f"issue{code}_frames", f"issue{code}_note"))
    fieldnames.extend(("general_note", "save_for_refine_override", "user_status"))

    output_rows: List[Dict[str, object]] = []
    for triage_row in sorted(triage_rows, key=lambda row: natural_sort_key(row["b_id"])):
        b_id = triage_row["b_id"].strip().lower()
        existing = existing_table_by_bid.get(b_id, {})
        summary = summary_rows.get(b_id, {})
        issue_source = {} if segment_notes_active else existing
        output_row: Dict[str, object] = {
            "done": existing.get("done", "") or (" | ".join(done_markers_by_bid.get(b_id, []))),
            "b_id": triage_row["b_id"],
            "group_name": triage_row["group_name"],
            "dataset_name": triage_row["dataset_name"],
            "frame_count": triage_row["frame_count"],
            "contact_sheet": triage_row["contact_sheet"],
        }
        for code in ("1", "2", "3", "4", "5"):
            if code == "1":
                frames_value = merge_index_specs(
                    issue_source.get("issue1_frames", ""),
                    issue_source.get("issue3_frames", ""),
                    compress_indices(sorted(indices_by_bid_issue[b_id].get("1", set()))),
                    compress_indices(sorted(indices_by_bid_issue[b_id].get("3", set()))),
                )
                note_value = merge_notes(
                    issue_source.get("issue1_note", ""),
                    issue_source.get("issue3_note", ""),
                    " | ".join(notes_by_bid_issue[b_id].get("1", [])),
                    " | ".join(notes_by_bid_issue[b_id].get("3", [])),
                )
            elif code == "3":
                frames_value = ""
                note_value = ""
            else:
                frames_value = issue_source.get(f"issue{code}_frames", "").strip()
                if not frames_value:
                    frames_value = compress_indices(sorted(indices_by_bid_issue[b_id].get(code, set())))
                note_value = issue_source.get(f"issue{code}_note", "").strip()
                if not note_value and notes_by_bid_issue[b_id].get(code):
                    note_value = " | ".join(notes_by_bid_issue[b_id][code])
            output_row[f"issue{code}_frames"] = frames_value
            output_row[f"issue{code}_note"] = note_value
        output_row["general_note"] = merge_notes(
            existing.get("general_note", "").strip(),
            summary.get("general_note", "").strip(),
            " | ".join(general_notes_by_bid.get(b_id, [])),
        )
        output_row["save_for_refine_override"] = existing.get("save_for_refine_override", "")
        output_row["user_status"] = existing.get("user_status", "")
        output_rows.append(output_row)

    write_csv(existing_table_path, output_rows, fieldnames)
    print(f"Saved triage fill table to {existing_table_path}")


if __name__ == "__main__":
    main()
