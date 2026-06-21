from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a Binary queue session JSON for bulk mask refinement."
    )
    parser.add_argument(
        "--root-dir",
        required=True,
        help="Root directory that contains many dataset / dataset-mask pairs.",
    )
    parser.add_argument(
        "--save-suffix",
        default="-mask_new",
        help="Suffix used for the editable save directories. Default: -mask_new",
    )
    parser.add_argument(
        "--session-dir",
        default="",
        help="Optional output directory for the session JSON. Defaults to <root-dir>/_finetuning_batch_sessions",
    )
    parser.add_argument(
        "--select",
        action="append",
        default=[],
        help=(
            "Selection rule. Can be a group name, a dataset name, or "
            "'group/dataset'. Supports * wildcards. Repeat this option to add more rules."
        ),
    )
    parser.add_argument(
        "--select-file",
        default="",
        help="Optional text file with one selection rule per line.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print a compact machine-readable summary as JSON after creating the session.",
    )
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

    session_path = BinaryQueueCore.create_session(
        args.root_dir,
        save_suffix=args.save_suffix,
        session_dir=args.session_dir or None,
        selection_entries=selection_entries,
    )
    session = BinaryQueueCore.read_session(session_path)
    progress = BinaryQueueCore.summarize_progress(session)

    first_pending = None
    target_index = BinaryQueueCore.current_or_next_index(session)
    if target_index >= 0:
        first_pending = session["datasets"][target_index]

    if args.print_json:
        payload = {
            "session_path": session_path,
            "root_dir": session["root_dir"],
            "save_suffix": session["save_suffix"],
            "selection_entries": session.get("selection_entries", []),
            "progress": progress,
            "current_or_next_dataset": (
                {
                    "group_name": first_pending["group_name"],
                    "dataset_name": first_pending["dataset_name"],
                    "origin_dir": first_pending["origin_dir"],
                    "mask_dir": first_pending["mask_dir"],
                    "save_dir": first_pending["save_dir"],
                    "status": first_pending["status"],
                }
                if first_pending
                else None
            ),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"Session created: {session_path}")
    if session.get("selection_entries"):
        print(f"Selection rules: {len(session['selection_entries'])}")
    print(
        "Progress summary: "
        f"total={progress['total']}, done={progress['done']}, "
        f"in_progress={progress['in_progress']}, pending={progress['pending']}"
    )
    if first_pending:
        print(
            "Current or next dataset: "
            f"{first_pending['group_name']} / {first_pending['dataset_name']}"
        )
        print(f"Save dir: {first_pending['save_dir']}")
    else:
        print("No unfinished dataset found in the generated session.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
