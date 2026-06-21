#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_step(command: list[str]) -> None:
    print("Running:", " ".join(f'"{part}"' if " " in part else part for part in command))
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh triage outputs and rebuild the smaller refine pack from a CSV table or record.txt.")
    parser.add_argument("--pack-root", required=True, help="Stage-1 pack root, for example suspicious_label_pack_top180.")
    parser.add_argument("--refine-output", required=True, help="Stage-2 refine pack output root.")
    parser.add_argument("--context-radius", type=int, default=2, help="Context radius for stage-2 refine pack.")
    parser.add_argument("--triage-context-radius", type=int, default=50, help="Context radius for stage-1 long-context storyboard sheets.")
    parser.add_argument("--include-issue-codes", nargs="*", default=("1", "2", "5"), help="Issue codes that should enter stage-2 refine pack.")
    parser.add_argument("--skip-contact-sheets", action="store_true", help="Skip rebuilding stage-1 contact sheets.")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    python_exe = sys.executable

    if not args.skip_contact_sheets:
        run_step(
            [
                python_exe,
                str(script_dir / "build_triage_contact_sheets.py"),
                "--pack-root",
                args.pack_root,
                "--context-radius",
                str(args.triage_context_radius),
            ]
        )

    run_step([python_exe, str(script_dir / "build_triage_fill_table.py"), "--pack-root", args.pack_root])
    run_step([python_exe, str(script_dir / "parse_triage_record.py"), "--pack-root", args.pack_root])

    cmd = [
        python_exe,
        str(script_dir / "build_refine_pack_from_record.py"),
        "--pack-root",
        args.pack_root,
        "--output",
        args.refine_output,
        "--context-radius",
        str(args.context_radius),
    ]
    if args.include_issue_codes:
        cmd.extend(["--include-issue-codes", *args.include_issue_codes])
    run_step(cmd)

    try:
        sys.path.insert(0, str(Path(script_dir).parents[0]))
        from core.binary_queue_core import BinaryQueueCore

        session_path = BinaryQueueCore.create_session(args.refine_output, save_suffix="-mask_new")
        print(f"Created Binary queue session: {session_path}")
    except Exception as exc:  # pragma: no cover - best effort helper
        print(f"Warning: failed to create Binary queue session automatically: {exc}")


if __name__ == "__main__":
    main()
