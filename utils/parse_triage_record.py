#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple


ISSUE_CODE_MAP = {
    "1": "target_miss_or_weak_response",
    "2": "boundary_false_positive",
    "3": "target_miss_or_weak_response",
    "4": "tail_empty_normal",
    "5": "other",
}
ISSUE_CODES = ("1", "2", "3", "4", "5")


def normalize_issue_code(issue_code: str) -> str:
    """Collapse legacy issue code 3 into issue code 1."""
    normalized = str(issue_code).strip()
    if normalized == "3":
        return "1"
    return normalized


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


def parse_index_tokens(spec: str, max_index: int) -> List[int]:
    spec = spec.strip()
    if not spec:
        return []
    if spec.lower() in {"all", "*", "yes", "y"}:
        return list(range(1, max_index + 1))
    if spec.startswith("(") and spec.endswith(")"):
        spec = spec[1:-1]

    indices: Set[int] = set()
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            parts = [part.strip() for part in token.split("-", 1)]
            if len(parts) == 2:
                start_text = re.sub(r"^[Ll]", "", parts[0])
                end_text = re.sub(r"^[Ll]", "", parts[1])
            else:
                start_text = ""
                end_text = ""
            if start_text.isdigit() and end_text.isdigit():
                start = int(start_text)
                end = int(end_text)
                if start > end:
                    start, end = end, start
                for value in range(start, end + 1):
                    if 1 <= value <= max_index:
                        indices.add(value)
            continue
        token = re.sub(r"^[Ll]", "", token)
        if token.isdigit():
            value = int(token)
            if 1 <= value <= max_index:
                indices.add(value)
    return sorted(indices)


def parse_whole_dataset_issue(payload: str) -> Tuple[Optional[str], str]:
    stripped = payload.strip()
    if stripped in ISSUE_CODE_MAP:
        return stripped, ""

    match = re.search(r"主要问题是\s*([1-5])", stripped)
    if match:
        return match.group(1), stripped

    match = re.search(r"主要是\s*([1-5])", stripped)
    if match:
        return match.group(1), stripped

    match = re.search(r"都是\s*([1-5])", stripped)
    if match:
        return match.group(1), stripped

    return None, stripped


def parse_payload_segments(payload: str, max_index: int) -> Tuple[List[Dict[str, object]], Optional[str]]:
    payload = payload.strip()
    if not payload:
        return [], None

    whole_code, whole_note = parse_whole_dataset_issue(payload)
    if whole_code is not None:
        return [{"scope": "all", "issue_code": whole_code, "note": whole_note}], None

    segments: List[Dict[str, object]] = []
    for raw_segment in payload.split(";"):
        segment = raw_segment.strip()
        if not segment:
            continue

        match = re.match(r"^\(([^)]*)\)\s+([1-5])(?:\s+(.*))?$", segment)
        if match:
            indices = parse_index_tokens(match.group(1), max_index)
            if indices:
                segments.append({"scope": "partial", "indices": indices, "issue_code": match.group(2), "note": (match.group(3) or "").strip()})
                continue

        match = re.match(r"^([Ll0-9,\-\s]+)\s+([1-5])(?:\s+(.*))?$", segment)
        if match:
            indices = parse_index_tokens(match.group(1), max_index)
            if indices:
                segments.append({"scope": "partial", "indices": indices, "issue_code": match.group(2), "note": (match.group(3) or "").strip()})
                continue

        return [], segment

    if not segments:
        return [], payload
    return segments, None


def read_record_lines(record_path: Path) -> List[str]:
    return record_path.read_text(encoding="utf-8").splitlines()


def parse_table_rows(
    table_rows: Sequence[Dict[str, str]],
    frames_by_bid: Dict[str, Dict[int, Dict[str, str]]],
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
    expanded_rows: List[Dict[str, object]] = []
    dataset_summary_rows: List[Dict[str, object]] = []
    parse_notes_rows: List[Dict[str, object]] = []

    for row_number, row in enumerate(table_rows, start=2):
        b_id = str(row.get("b_id", "")).strip().lower()
        if not b_id:
            continue
        frames_map = frames_by_bid.get(b_id, {})
        if not frames_map:
            parse_notes_rows.append(
                {"line_number": row_number, "b_id": b_id, "status": "unknown_b_id", "raw_text": "", "note": "No matching dataset in triage_index.csv"}
            )
            continue

        group_name = str(row.get("group_name", "")).strip()
        dataset_name = str(row.get("dataset_name", "")).strip()
        frame_count = len(frames_map)
        issue_codes_seen: Set[str] = set()
        dataset_parse_status = "pending"

        for issue_code in ISSUE_CODES:
            field_name = f"issue{issue_code}_frames"
            note_field = f"issue{issue_code}_note"
            spec = str(row.get(field_name, "")).strip()
            note = str(row.get(note_field, "")).strip()
            if not spec:
                continue

            indices = parse_index_tokens(spec, frame_count)
            if not indices:
                parse_notes_rows.append(
                    {"line_number": row_number, "b_id": b_id, "status": "invalid_range", "raw_text": spec, "note": f"Could not parse {field_name}"}
                )
                dataset_parse_status = "note_only"
                continue

            dataset_parse_status = "parsed"
            normalized_issue_code = normalize_issue_code(issue_code)
            issue_codes_seen.add(normalized_issue_code)
            issue_label = ISSUE_CODE_MAP.get(normalized_issue_code, "other")
            for local_index in indices:
                frame = frames_map.get(local_index)
                if frame is None:
                    continue
                expanded_rows.append(
                    {
                        "b_id": b_id,
                        "group_name": group_name,
                        "dataset_name": dataset_name,
                        "local_index": local_index,
                        "frame_name": frame["frame_name"],
                        "issue_code": normalized_issue_code,
                        "issue_label": issue_label,
                        "note": note,
                        "raw_record": "",
                    }
                )

        dataset_summary_rows.append(
            {
                "b_id": b_id,
                "group_name": group_name,
                "dataset_name": dataset_name,
                "frame_count": frame_count,
                "raw_record": "",
                "parse_status": dataset_parse_status,
                "general_note": str(row.get("general_note", "")).strip(),
                "issue_codes_seen": "|".join(sorted(issue_codes_seen)),
                "done": str(row.get("done", "")).strip(),
            }
        )

    return expanded_rows, dataset_summary_rows, parse_notes_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse shorthand triage notes from record.txt into structured CSV files.")
    parser.add_argument("--pack-root", required=True, help="Reduced label pack root.")
    parser.add_argument("--record", help="record.txt path. Defaults to <pack-root>/record.txt.")
    parser.add_argument("--table", help="CSV triage table path. Defaults to <pack-root>/_label_pack_meta/triage_fill_table.csv.")
    args = parser.parse_args()

    pack_root = Path(args.pack_root).resolve()
    meta_dir = pack_root / "_label_pack_meta"
    record_path = Path(args.record).resolve() if args.record else (pack_root / "record.txt")
    table_path = Path(args.table).resolve() if args.table else (meta_dir / "triage_fill_table.csv")
    triage_index_path = meta_dir / "triage_index.csv"
    triage_frame_map_path = meta_dir / "triage_frame_map.csv"
    if not triage_index_path.exists() or not triage_frame_map_path.exists():
        raise FileNotFoundError("Missing triage_index.csv or triage_frame_map.csv. Run build_triage_contact_sheets.py first.")

    triage_rows = read_csv(triage_index_path)
    frame_rows = read_csv(triage_frame_map_path)
    dataset_by_bid = {row["b_id"]: row for row in triage_rows}
    frames_by_bid: Dict[str, Dict[int, Dict[str, str]]] = defaultdict(dict)
    for row in frame_rows:
        frames_by_bid[row["b_id"]][int(row["local_index"])] = row

    expanded_rows: List[Dict[str, object]]
    dataset_summary_rows: List[Dict[str, object]]
    parse_notes_rows: List[Dict[str, object]]
    input_mode = ""

    use_table = False
    if table_path.exists():
        table_rows = read_csv(table_path)
        use_table = any(
            any(str(row.get(f"issue{code}_frames", "")).strip() for code in ISSUE_CODES) or str(row.get("general_note", "")).strip()
            for row in table_rows
        )
        if use_table:
            expanded_rows, dataset_summary_rows, parse_notes_rows = parse_table_rows(table_rows, frames_by_bid)
            input_mode = "csv_table"
        else:
            expanded_rows, dataset_summary_rows, parse_notes_rows = [], [], []
    else:
        expanded_rows, dataset_summary_rows, parse_notes_rows = [], [], []

    if not use_table:
        if not record_path.exists():
            raise FileNotFoundError(f"Missing both filled triage table and record file under {pack_root}")
        input_mode = "record_txt"

        expanded_rows = []
        dataset_summary_rows = []
        parse_notes_rows = []

        for line_number, raw_line in enumerate(read_record_lines(record_path), start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = re.match(r"^(b\d+)\s*(.*)$", stripped, flags=re.IGNORECASE)
            if not match:
                continue

            b_id = match.group(1).lower()
            payload = match.group(2).strip()
            dataset = dataset_by_bid.get(b_id)
            if dataset is None:
                parse_notes_rows.append(
                    {"line_number": line_number, "b_id": b_id, "status": "unknown_b_id", "raw_text": stripped, "note": "No matching dataset in triage_index.csv"}
                )
                continue

            max_index = int(dataset["frame_count"])
            segments, unparsed_note = parse_payload_segments(payload, max_index)
            dataset_summary = {
                "b_id": b_id,
                "group_name": dataset["group_name"],
                "dataset_name": dataset["dataset_name"],
                "frame_count": dataset["frame_count"],
                "raw_record": payload,
                "parse_status": "parsed" if segments else ("note_only" if payload else "pending"),
                "general_note": unparsed_note or "",
            }

            if not payload:
                dataset_summary_rows.append(dataset_summary)
                continue

            if not segments:
                dataset_summary_rows.append(dataset_summary)
                parse_notes_rows.append(
                    {"line_number": line_number, "b_id": b_id, "status": dataset_summary["parse_status"], "raw_text": stripped, "note": unparsed_note or "No structured segments parsed"}
                )
                continue

            for segment in segments:
                issue_code = normalize_issue_code(str(segment["issue_code"]))
                issue_label = ISSUE_CODE_MAP.get(issue_code, "other")
                note = str(segment.get("note", "")).strip()
                if segment["scope"] == "all":
                    target_indices = sorted(frames_by_bid[b_id].keys())
                else:
                    target_indices = list(segment["indices"])

                for local_index in target_indices:
                    frame = frames_by_bid[b_id].get(local_index)
                    if frame is None:
                        continue
                    expanded_rows.append(
                        {
                            "b_id": b_id,
                            "group_name": dataset["group_name"],
                            "dataset_name": dataset["dataset_name"],
                            "local_index": local_index,
                            "frame_name": frame["frame_name"],
                            "issue_code": issue_code,
                            "issue_label": issue_label,
                            "note": note,
                            "raw_record": payload,
                        }
                    )

            dataset_summary["issue_codes_seen"] = "|".join(sorted({normalize_issue_code(str(segment["issue_code"])) for segment in segments}))
            dataset_summary_rows.append(dataset_summary)

    default_label_types = {"1", "2", "5"}
    refine_rows = [
        {
            **row,
            "need_pixel_label": "yes" if str(row["issue_code"]) in default_label_types else "",
        }
        for row in expanded_rows
    ]

    write_csv(meta_dir / "record_expanded.csv", expanded_rows, fieldnames=("b_id", "group_name", "dataset_name", "local_index", "frame_name", "issue_code", "issue_label", "note", "raw_record"))
    write_csv(meta_dir / "record_dataset_summary.csv", dataset_summary_rows)
    write_csv(meta_dir / "record_parse_notes.csv", parse_notes_rows, fieldnames=("line_number", "b_id", "status", "raw_text", "note"))
    write_csv(meta_dir / "refine_candidates.csv", refine_rows, fieldnames=("b_id", "group_name", "dataset_name", "local_index", "frame_name", "issue_code", "issue_label", "need_pixel_label", "note", "raw_record"))

    summary = {
        "datasets_in_triage": len(triage_rows),
        "datasets_with_record_lines": len(dataset_summary_rows),
        "frame_assignments": len(expanded_rows),
        "parse_notes": len(parse_notes_rows),
        "input_mode": input_mode,
        "record_path": str(record_path),
        "table_path": str(table_path),
    }
    (meta_dir / "record_parse_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
