from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a Binary queue session from a flat MagicImageJ Exports directory."
    )
    parser.add_argument("--exports-dir", required=True, help="Exports directory containing *_contrasted ROI folders.")
    parser.add_argument("--origin-suffix", default="_contrasted", help="Origin folder suffix. Default: _contrasted")
    parser.add_argument("--mask-suffix", default="_mask", help="Initial mask folder suffix.")
    parser.add_argument("--save-suffix", default="_mask_refined", help="Editable save folder suffix.")
    parser.add_argument(
        "--session-dir",
        default="",
        help="Optional output directory for the session JSON. Defaults to <exports-dir>/_finetuning_batch_sessions",
    )
    parser.add_argument(
        "--session-name",
        default="",
        help="Optional session JSON filename. Defaults to an EXPORTS_BINARY_QUEUE_SESSION name.",
    )
    parser.add_argument(
        "--select",
        action="append",
        default=[],
        help="Selection rule for dataset base name, origin folder name, or exports/dataset. Supports * wildcards.",
    )
    parser.add_argument("--select-file", default="", help="Optional text file with one selection rule per line.")
    parser.add_argument("--print-json", action="store_true", help="Print a machine-readable summary.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))

    from core.binary_queue_core import BinaryQueueCore

    selection_entries = list(args.select)
    if args.select_file:
        selection_entries.extend(BinaryQueueCore.read_selection_file(args.select_file))

    session_name = args.session_name.strip()
    if not session_name:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_name = f"exports_binary_session_{timestamp}.json"

    session_path = BinaryQueueCore.create_exports_session(
        args.exports_dir,
        origin_suffix=args.origin_suffix,
        mask_suffix=args.mask_suffix,
        save_suffix=args.save_suffix,
        session_dir=args.session_dir or None,
        selection_entries=selection_entries,
        session_name=session_name,
    )
    session = BinaryQueueCore.read_session(session_path)
    progress = BinaryQueueCore.summarize_progress(session)
    target_index = BinaryQueueCore.current_or_next_index(session)
    first_dataset = session["datasets"][target_index] if target_index >= 0 else None

    summary = {
        "session_path": str(Path(session_path).resolve()),
        "exports_dir": session["root_dir"],
        "origin_suffix": args.origin_suffix,
        "mask_suffix": args.mask_suffix,
        "save_suffix": args.save_suffix,
        "selection_entries": session.get("selection_entries", []),
        "progress": progress,
        "current_or_next_dataset": first_dataset,
    }

    if args.print_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"Session created: {summary['session_path']}")
        print(
            "Progress summary: "
            f"total={progress['total']}, done={progress['done']}, "
            f"in_progress={progress['in_progress']}, pending={progress['pending']}"
        )
        if first_dataset:
            print(f"Current or next dataset: {first_dataset['group_name']} / {first_dataset['dataset_name']}")
            print(f"Save dir: {first_dataset['save_dir']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
