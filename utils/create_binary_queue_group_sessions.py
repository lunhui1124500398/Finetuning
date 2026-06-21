from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", value).strip()
    return cleaned.rstrip(". ") or "unnamed_group"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create one Binary queue session per top-level group folder."
    )
    parser.add_argument(
        "--root-dir",
        required=True,
        help="Root directory that contains many Binary group folders.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where the per-group session JSON files will be written.",
    )
    parser.add_argument(
        "--save-suffix",
        default="-mask_new",
        help="Suffix used for the editable save directories. Default: -mask_new",
    )
    parser.add_argument(
        "--include-groups",
        action="append",
        default=[],
        help="Optional group name filter. Repeat this option to restrict generation.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip groups whose session file already exists in the output directory.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print a machine-readable summary after generation.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))

    from core.binary_queue_core import BinaryQueueCore

    root = Path(args.root_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir_resolved = output_dir.resolve()

    include_groups = set(args.include_groups or [])
    group_dirs = [
        path
        for path in root.iterdir()
        if path.is_dir()
        and path.resolve() != output_dir_resolved
        and not path.name.startswith("_")
        and path.name != "all_origin_flattened"
    ]
    group_dirs = sorted(group_dirs, key=lambda path: BinaryQueueCore.natural_sort_key(path.name))
    if include_groups:
        group_dirs = [path for path in group_dirs if path.name in include_groups]

    manifest_rows = []
    for group_dir in group_dirs:
        session_name = f"GROUP_BINARY_QUEUE_SESSION__{sanitize_filename(group_dir.name)}.json"
        target_session_path = output_dir / session_name
        if args.skip_existing and target_session_path.exists():
            session = BinaryQueueCore.read_session(str(target_session_path))
            progress = BinaryQueueCore.summarize_progress(session)
            manifest_rows.append(
                {
                    "group_name": group_dir.name,
                    "session_path": str(target_session_path.resolve()),
                    "dataset_count": progress["total"],
                    "done": progress["done"],
                    "in_progress": progress["in_progress"],
                    "pending": progress["pending"],
                }
            )
            continue

        session_path = BinaryQueueCore.create_session(
            str(root),
            save_suffix=args.save_suffix,
            session_dir=str(output_dir),
            selection_entries=[group_dir.name],
            session_name=session_name,
        )
        session = BinaryQueueCore.read_session(session_path)
        progress = BinaryQueueCore.summarize_progress(session)
        manifest_rows.append(
            {
                "group_name": group_dir.name,
                "session_path": str(Path(session_path).resolve()),
                "dataset_count": progress["total"],
                "done": progress["done"],
                "in_progress": progress["in_progress"],
                "pending": progress["pending"],
            }
        )

    index_json_path = output_dir / "GROUP_BINARY_QUEUE_SESSION_INDEX.json"
    index_tsv_path = output_dir / "GROUP_BINARY_QUEUE_SESSION_INDEX.tsv"
    index_json_path.write_text(json.dumps(manifest_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    with index_tsv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["group_name", "dataset_count", "done", "in_progress", "pending", "session_path"],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(manifest_rows)

    summary = {
        "output_dir": str(output_dir.resolve()),
        "session_count": len(manifest_rows),
        "index_json": str(index_json_path.resolve()),
        "index_tsv": str(index_tsv_path.resolve()),
        "sessions": manifest_rows,
    }

    if args.print_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"Created {len(manifest_rows)} group session files in: {output_dir.resolve()}")
        print(f"Index JSON: {index_json_path.resolve()}")
        print(f"Index TSV: {index_tsv_path.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
