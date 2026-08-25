from __future__ import annotations

import json
import os
import re
from fnmatch import fnmatchcase
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from utils.path_utils import absolute_display_path, filesystem_path, to_display_path, to_filesystem_path


VALID_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


class BinaryQueueCore:
    @staticmethod
    def normalize_path(path: str) -> str:
        if not path:
            return ""
        return os.path.normcase(os.path.normpath(str(path)))

    @staticmethod
    def natural_sort_key(value: str) -> List[object]:
        return [int(token) if token.isdigit() else token.lower() for token in re.split(r"(\d+)", str(value))]

    @staticmethod
    def related_folder_name(source_name: str, source_suffix: str, target_suffix: str) -> str:
        if source_suffix and source_name.endswith(source_suffix):
            return f"{source_name[:-len(source_suffix)]}{target_suffix}"
        return f"{source_name}{target_suffix}"

    @staticmethod
    def count_image_files(directory: str) -> int:
        path = filesystem_path(directory)
        if not path.is_dir():
            return 0
        return len([f for f in path.iterdir() if f.is_file() and f.suffix.lower() in VALID_EXTENSIONS and not f.name.startswith(".")])

    @staticmethod
    def _dataset_dict(group_name: str, dataset_name: str, origin_dir: Path, mask_dir: Path, save_dir: Path) -> Dict:
        return {
            "group_name": group_name,
            "dataset_name": dataset_name,
            "origin_dir": to_display_path(origin_dir),
            "mask_dir": to_display_path(mask_dir),
            "save_dir": to_display_path(save_dir),
            "origin_count": BinaryQueueCore.count_image_files(str(origin_dir)),
            "mask_count": BinaryQueueCore.count_image_files(str(mask_dir)),
            "save_count": BinaryQueueCore.count_image_files(str(save_dir)),
            "status": "pending",
            "last_loaded_at": "",
            "completed_at": "",
        }

    @staticmethod
    def normalize_selection_entries(selection_entries: Optional[Iterable[str]]) -> List[str]:
        normalized: List[str] = []
        if not selection_entries:
            return normalized

        for entry in selection_entries:
            if entry is None:
                continue
            text = str(entry).strip()
            if not text or text.startswith("#"):
                continue
            normalized.append(text.replace("\\", "/"))
        return normalized

    @staticmethod
    def read_selection_file(selection_file: str) -> List[str]:
        path = filesystem_path(selection_file)
        if not path.is_file():
            raise FileNotFoundError(f"Selection file not found: {selection_file}")
        return BinaryQueueCore.normalize_selection_entries(path.read_text(encoding="utf-8").splitlines())

    @staticmethod
    def dataset_matches_selection(group_name: str, dataset_name: str, selection_entries: Optional[Iterable[str]]) -> bool:
        entries = BinaryQueueCore.normalize_selection_entries(selection_entries)
        if not entries:
            return True

        normalized_pair = f"{group_name}/{dataset_name}"
        for entry in entries:
            if "/" in entry:
                if fnmatchcase(normalized_pair, entry):
                    return True
                continue
            if fnmatchcase(group_name, entry) or fnmatchcase(dataset_name, entry):
                return True
        return False

    @staticmethod
    def discover_binary_datasets(
        root_dir: str,
        save_suffix: str = "-mask_new",
        selection_entries: Optional[Iterable[str]] = None,
    ) -> List[Dict]:
        root = filesystem_path(root_dir)
        datasets: List[Dict] = []
        normalized_selection = BinaryQueueCore.normalize_selection_entries(selection_entries)

        if not root.is_dir():
            return datasets

        for group_dir in sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: BinaryQueueCore.natural_sort_key(p.name)):
            child_dirs = {p.name: p for p in group_dir.iterdir() if p.is_dir()}
            for dataset_name, origin_dir in sorted(child_dirs.items(), key=lambda item: BinaryQueueCore.natural_sort_key(item[0])):
                if dataset_name.endswith(("-mask", "-mask_new", "-hrtem", "-lrtem")):
                    continue
                mask_dir = child_dirs.get(f"{dataset_name}-mask")
                if mask_dir is None:
                    continue
                if not BinaryQueueCore.dataset_matches_selection(group_dir.name, dataset_name, normalized_selection):
                    continue

                save_dir = group_dir / f"{dataset_name}{save_suffix}"
                datasets.append(BinaryQueueCore._dataset_dict(group_dir.name, dataset_name, origin_dir, mask_dir, save_dir))

        return datasets

    @staticmethod
    def discover_exports_binary_datasets(
        exports_dir: str,
        origin_suffix: str = "_contrasted",
        mask_suffix: str = "_mask",
        save_suffix: str = "_mask_refined",
        selection_entries: Optional[Iterable[str]] = None,
        require_mask_dir: bool = True,
    ) -> List[Dict]:
        """
        Discover Binary queue datasets in a MagicImageJ / Inference Exports directory.

        Origin folders are flat siblings, e.g.:
            ROI001_contrasted
        Masks may live either as flat siblings (legacy layout):
            ROI001_mask
            ROI001_mask_refined
        or, since the 2026-05-30 Inference reorg, inside a _masks/ subfolder:
            _masks/ROI001_mask
            _masks/ROI001_mask_refined
        The _masks/ location is preferred when present, with a fall back to the
        flat sibling layout for older datasets.

        The contrasted folder is loaded as original images, mask_suffix is used
        as the read-only initial binary mask, and save_suffix is the editable
        output folder (saved next to the resolved mask) for this Finetuning session.
        """
        exports_path = filesystem_path(exports_dir)
        datasets: List[Dict] = []
        normalized_selection = BinaryQueueCore.normalize_selection_entries(selection_entries)

        if not exports_path.is_dir():
            return datasets

        origin_dirs = [
            path
            for path in exports_path.iterdir()
            if path.is_dir() and (not origin_suffix or path.name.endswith(origin_suffix))
        ]
        origin_dirs.sort(key=lambda path: BinaryQueueCore.natural_sort_key(path.name))

        for origin_dir in origin_dirs:
            if origin_suffix and origin_dir.name.endswith(origin_suffix):
                dataset_name = origin_dir.name[: -len(origin_suffix)]
            else:
                dataset_name = origin_dir.name

            if normalized_selection:
                matches_dataset = BinaryQueueCore.dataset_matches_selection(
                    exports_path.name,
                    dataset_name,
                    normalized_selection,
                )
                matches_source_folder = BinaryQueueCore.dataset_matches_selection(
                    exports_path.name,
                    origin_dir.name,
                    normalized_selection,
                )
                if not matches_dataset and not matches_source_folder:
                    continue

            mask_folder = BinaryQueueCore.related_folder_name(origin_dir.name, origin_suffix, mask_suffix)
            save_folder = BinaryQueueCore.related_folder_name(origin_dir.name, origin_suffix, save_suffix)

            # [Reorg 2026-05-30] Inference now writes masks into an <Exports>/_masks/ subfolder
            # instead of as flat siblings of the origin folders. Prefer that location and fall
            # back to the legacy flat layout so older datasets keep working.
            masks_subdir = exports_path / "_masks"
            subfolder_mask = masks_subdir / mask_folder
            flat_mask = exports_path / mask_folder
            if subfolder_mask.is_dir():
                mask_dir = subfolder_mask
            elif flat_mask.is_dir():
                mask_dir = flat_mask
            else:
                # Neither exists yet: follow the new layout when a _masks/ dir is present,
                # otherwise keep the legacy flat layout.
                mask_dir = (masks_subdir if masks_subdir.is_dir() else exports_path) / mask_folder

            if require_mask_dir and not mask_dir.is_dir():
                continue

            # Save the refined output next to the resolved mask (same parent), matching the
            # Inference GUI behaviour (精修与 mask 同放 _masks/).
            save_dir = mask_dir.parent / save_folder
            dataset = BinaryQueueCore._dataset_dict(exports_path.name, dataset_name, origin_dir, mask_dir, save_dir)
            dataset.update(
                {
                    "source_layout": "exports",
                    "source_folder": origin_dir.name,
                    "mask_folder": mask_dir.name,
                    "save_folder": save_dir.name,
                    "origin_suffix": origin_suffix,
                    "mask_suffix": mask_suffix,
                    "save_suffix": save_suffix,
                }
            )
            datasets.append(dataset)

        return datasets

    @staticmethod
    def refresh_dataset_status(dataset: Dict) -> Dict:
        refreshed = dataset.copy()
        origin_count = BinaryQueueCore.count_image_files(refreshed["origin_dir"])
        mask_count = BinaryQueueCore.count_image_files(refreshed["mask_dir"])
        save_count = BinaryQueueCore.count_image_files(refreshed["save_dir"])

        refreshed["origin_count"] = origin_count
        refreshed["mask_count"] = mask_count
        refreshed["save_count"] = save_count

        if refreshed.get("status") == "done":
            if not refreshed.get("completed_at"):
                refreshed["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return refreshed

        if origin_count > 0 and save_count >= origin_count:
            refreshed["status"] = "done"
            if not refreshed.get("completed_at"):
                refreshed["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elif save_count > 0:
            refreshed["status"] = "in_progress"
            refreshed["completed_at"] = ""
        else:
            refreshed["status"] = "pending"
            refreshed["completed_at"] = ""

        return refreshed

    @staticmethod
    def create_session(
        root_dir: str,
        save_suffix: str = "-mask_new",
        session_dir: Optional[str] = None,
        selection_entries: Optional[Iterable[str]] = None,
        session_name: Optional[str] = None,
    ) -> str:
        normalized_selection = BinaryQueueCore.normalize_selection_entries(selection_entries)
        datasets = BinaryQueueCore.discover_binary_datasets(
            root_dir,
            save_suffix=save_suffix,
            selection_entries=normalized_selection,
        )
        if not datasets:
            raise RuntimeError(f"No paired binary datasets found under {root_dir}")

        return BinaryQueueCore.create_session_from_datasets(
            root_dir,
            datasets,
            save_suffix=save_suffix,
            session_dir=session_dir,
            selection_entries=normalized_selection,
            session_name=session_name,
        )

    @staticmethod
    def create_exports_session(
        exports_dir: str,
        origin_suffix: str = "_contrasted",
        mask_suffix: str = "_mask",
        save_suffix: str = "_mask_refined",
        session_dir: Optional[str] = None,
        selection_entries: Optional[Iterable[str]] = None,
        session_name: Optional[str] = None,
    ) -> str:
        normalized_selection = BinaryQueueCore.normalize_selection_entries(selection_entries)
        datasets = BinaryQueueCore.discover_exports_binary_datasets(
            exports_dir,
            origin_suffix=origin_suffix,
            mask_suffix=mask_suffix,
            save_suffix=save_suffix,
            selection_entries=normalized_selection,
            require_mask_dir=False,
        )
        if not datasets:
            raise RuntimeError(f"No paired Exports Binary datasets found under {exports_dir}")

        return BinaryQueueCore.create_session_from_datasets(
            exports_dir,
            datasets,
            save_suffix=save_suffix,
            session_dir=session_dir,
            selection_entries=normalized_selection,
            session_name=session_name,
            create_missing_mask_dirs=True,
            metadata={
                "source_layout": "exports",
                "origin_suffix": origin_suffix,
                "mask_suffix": mask_suffix,
                "save_suffix": save_suffix,
            },
        )

    @staticmethod
    def create_session_from_datasets(
        root_dir: str,
        datasets: Iterable[Dict],
        save_suffix: str = "-mask_new",
        session_dir: Optional[str] = None,
        selection_entries: Optional[Iterable[str]] = None,
        session_name: Optional[str] = None,
        create_missing_mask_dirs: bool = False,
        metadata: Optional[Dict] = None,
    ) -> str:
        root = Path(absolute_display_path(root_dir))
        normalized_selection = BinaryQueueCore.normalize_selection_entries(selection_entries)
        prepared_datasets = [dataset.copy() for dataset in datasets]
        if not prepared_datasets:
            raise RuntimeError(f"No binary datasets selected under {root_dir}")

        for dataset in prepared_datasets:
            if create_missing_mask_dirs:
                filesystem_path(dataset["mask_dir"]).mkdir(parents=True, exist_ok=True)
            filesystem_path(dataset["save_dir"]).mkdir(parents=True, exist_ok=True)
            refreshed = BinaryQueueCore.refresh_dataset_status(dataset)
            dataset.update(refreshed)

        session_root = Path(absolute_display_path(session_dir)) if session_dir else (root / "_finetuning_batch_sessions")
        filesystem_path(session_root).mkdir(parents=True, exist_ok=True)
        if session_name:
            filename = session_name if session_name.lower().endswith(".json") else f"{session_name}.json"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"binary_queue_session_{timestamp}.json"
        session_path = session_root / filename

        session = {
            "root_dir": absolute_display_path(root_dir),
            "save_suffix": save_suffix,
            "selection_entries": normalized_selection,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "current_dataset_key": "",
            "datasets": prepared_datasets,
        }
        if metadata:
            session["metadata"] = metadata
        BinaryQueueCore.write_session(str(session_path), session)
        return str(session_path)

    @staticmethod
    def read_session(session_path: str) -> Dict:
        with open(to_filesystem_path(session_path), "r", encoding="utf-8-sig") as handle:
            return json.load(handle)

    @staticmethod
    def write_session(session_path: str, session: Dict) -> None:
        filesystem_path(Path(session_path).parent).mkdir(parents=True, exist_ok=True)
        with open(to_filesystem_path(session_path), "w", encoding="utf-8") as handle:
            json.dump(session, handle, ensure_ascii=False, indent=2)

    @staticmethod
    def dataset_key(dataset: Dict) -> str:
        return f"{dataset['group_name']}::{dataset['dataset_name']}"

    @staticmethod
    def refresh_session(session_path: str) -> Dict:
        session = BinaryQueueCore.read_session(session_path)
        refreshed_datasets = []
        for dataset in session.get("datasets", []):
            refreshed_datasets.append(BinaryQueueCore.refresh_dataset_status(dataset))
        session["datasets"] = refreshed_datasets
        BinaryQueueCore.write_session(session_path, session)
        return session

    @staticmethod
    def prepare_session_for_navigation(session_path: str, main_window=None) -> Dict:
        """
        Lightweight session loader for hot navigation paths such as N/B.

        This intentionally avoids `refresh_session()`, which rescans every
        dataset directory in the queue and can block the GUI for several
        seconds on large sessions. Navigation only needs the persisted
        session state plus the currently opened dataset in the UI.
        """
        session = BinaryQueueCore.read_session(session_path)
        if main_window is not None:
            session = BinaryQueueCore.sync_current_dataset_from_main_window(main_window, session_path, session)
        return session

    @staticmethod
    def find_dataset_index(session: Dict, dataset_key: str) -> int:
        for idx, dataset in enumerate(session.get("datasets", [])):
            if BinaryQueueCore.dataset_key(dataset) == dataset_key:
                return idx
        return -1

    @staticmethod
    def next_incomplete_index(session: Dict, start_after: int = -1) -> int:
        datasets = session.get("datasets", [])
        for idx in range(start_after + 1, len(datasets)):
            if datasets[idx].get("status") != "done":
                return idx
        for idx in range(0, start_after + 1):
            if datasets[idx].get("status") != "done":
                return idx
        return -1

    @staticmethod
    def current_or_next_index(session: Dict) -> int:
        datasets = session.get("datasets", [])
        if not datasets:
            return -1

        current_key = session.get("current_dataset_key", "")
        if current_key:
            current_index = BinaryQueueCore.find_dataset_index(session, current_key)
            if current_index >= 0:
                if datasets[current_index].get("status") != "done":
                    return current_index
                next_index = BinaryQueueCore.next_incomplete_index(session, start_after=current_index)
                return next_index if next_index >= 0 else current_index

        return BinaryQueueCore.next_incomplete_index(session, start_after=-1)

    @staticmethod
    def previous_index(session: Dict) -> int:
        datasets = session.get("datasets", [])
        if not datasets:
            return -1

        current_key = session.get("current_dataset_key", "")
        if current_key:
            current_index = BinaryQueueCore.find_dataset_index(session, current_key)
            if current_index >= 0:
                return current_index - 1 if current_index > 0 else len(datasets) - 1

        return len(datasets) - 1

    @staticmethod
    def ordered_next_index(session: Dict) -> int:
        datasets = session.get("datasets", [])
        if not datasets:
            return -1

        current_key = session.get("current_dataset_key", "")
        if current_key:
            current_index = BinaryQueueCore.find_dataset_index(session, current_key)
            if current_index >= 0:
                return current_index + 1 if current_index < len(datasets) - 1 else 0

        return 0

    @staticmethod
    def summarize_progress(session: Dict) -> Dict[str, int]:
        datasets = session.get("datasets", [])
        done = sum(1 for dataset in datasets if dataset.get("status") == "done")
        in_progress = sum(1 for dataset in datasets if dataset.get("status") == "in_progress")
        pending = sum(1 for dataset in datasets if dataset.get("status") == "pending")
        return {"total": len(datasets), "done": done, "in_progress": in_progress, "pending": pending}

    @staticmethod
    def current_paths_from_main_window(main_window) -> Tuple[str, str, str]:
        model = getattr(main_window, "model", None)
        if model is None:
            return "", "", ""

        try:
            original_path = model.get_path("original_path") or ""
            mask_path = model.get_path("mask_path") or ""
            save_path = model.get_path("save_path") or ""
        except Exception:
            original_path = ""
            mask_path = ""
            save_path = ""

        return original_path, mask_path, save_path

    @staticmethod
    def find_dataset_key_from_paths(session: Dict, original_path: str = "", mask_path: str = "", save_path: str = "") -> str:
        normalized_original = BinaryQueueCore.normalize_path(original_path)
        normalized_mask = BinaryQueueCore.normalize_path(mask_path)
        normalized_save = BinaryQueueCore.normalize_path(save_path)

        for dataset in session.get("datasets", []):
            if normalized_save and BinaryQueueCore.normalize_path(dataset.get("save_dir", "")) == normalized_save:
                return BinaryQueueCore.dataset_key(dataset)

            dataset_original = BinaryQueueCore.normalize_path(dataset.get("origin_dir", ""))
            dataset_mask = BinaryQueueCore.normalize_path(dataset.get("mask_dir", ""))
            if normalized_original and dataset_original == normalized_original:
                if not normalized_mask or dataset_mask == normalized_mask:
                    return BinaryQueueCore.dataset_key(dataset)

        return ""

    @staticmethod
    def sync_current_dataset_from_main_window(main_window, session_path: str, session: Dict) -> Dict:
        original_path, mask_path, save_path = BinaryQueueCore.current_paths_from_main_window(main_window)
        dataset_key = BinaryQueueCore.find_dataset_key_from_paths(
            session,
            original_path=original_path,
            mask_path=mask_path,
            save_path=save_path,
        )
        if dataset_key and session.get("current_dataset_key", "") != dataset_key:
            session["current_dataset_key"] = dataset_key
            BinaryQueueCore.write_session(session_path, session)
        return session

    @staticmethod
    def save_session_to_config(main_window, session_path: str) -> None:
        model = main_window.model
        if not model.config.has_section("Scripts"):
            model.config.add_section("Scripts")
        model.config.set("Scripts", "binary_queue_session_path", session_path)
        with open(model.config_path, "w", encoding="utf-8") as handle:
            model.config.write(handle)

    @staticmethod
    def load_session_from_config(main_window) -> str:
        return main_window.model.config.get("Scripts", "binary_queue_session_path", fallback="")

    @staticmethod
    def clear_session_from_config(main_window) -> None:
        model = main_window.model
        if not model.config.has_section("Scripts"):
            return
        if model.config.has_option("Scripts", "binary_queue_session_path"):
            model.config.remove_option("Scripts", "binary_queue_session_path")
            with open(model.config_path, "w", encoding="utf-8") as handle:
                model.config.write(handle)

    @staticmethod
    def load_dataset_into_main_window(main_window, dataset: Dict, session_path: Optional[str] = None) -> None:
        model = main_window.model

        origin_dir = dataset["origin_dir"]
        mask_dir = dataset["mask_dir"]
        save_dir = dataset["save_dir"]
        filesystem_path(save_dir).mkdir(parents=True, exist_ok=True)

        # Reset the current canvas before swapping file lists so autosave
        # cannot try to save an old index against a new dataset.
        if hasattr(main_window, "canvas") and main_window.canvas is not None:
            main_window.canvas.load_image(-1)
        model.set_current_index(-1)

        if not model.config.has_section("Paths"):
            model.config.add_section("Paths")
        if not model.config.has_section("Scripts"):
            model.config.add_section("Scripts")

        model.config.set("Paths", "original_path", origin_dir)
        model.config.set("Paths", "denoised_path", "")
        model.config.set("Paths", "mask_path", mask_dir)
        model.config.set("Paths", "save_path", save_dir)
        model.config.set("Scripts", "default_input_source", "save_path")
        if session_path:
            model.config.set("Scripts", "binary_queue_session_path", session_path)

        with open(model.config_path, "w", encoding="utf-8") as handle:
            model.config.write(handle)

        model.update_file_lists(origin_dir, "", mask_dir)

        main_window.original_path_selector.set_path(origin_dir)
        main_window.denoised_path_selector.set_path("")
        main_window.mask_path_selector.set_path(mask_dir)
        main_window.save_path_selector.set_path(save_dir)

        model._load_from_save_path = True
        model.mask_source_changed.emit(True)

    @staticmethod
    def _load_dataset_by_index(main_window, session_path: str, session: Dict, target_index: int) -> Tuple[Dict, Dict]:
        if target_index < 0 or target_index >= len(session.get("datasets", [])):
            raise RuntimeError("No unfinished dataset found in the current queue.")

        dataset = session["datasets"][target_index]
        dataset["last_loaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session["current_dataset_key"] = BinaryQueueCore.dataset_key(dataset)
        BinaryQueueCore.write_session(session_path, session)

        BinaryQueueCore.load_dataset_into_main_window(main_window, dataset, session_path=session_path)
        progress = BinaryQueueCore.summarize_progress(session)
        progress["current_index"] = target_index + 1
        return dataset, progress

    @staticmethod
    def load_next_dataset(main_window, session_path: str) -> Tuple[Dict, Dict]:
        session = BinaryQueueCore.prepare_session_for_navigation(session_path, main_window=main_window)
        current_key = session.get("current_dataset_key", "")
        current_index = BinaryQueueCore.find_dataset_index(session, current_key) if current_key else -1
        target_index = BinaryQueueCore.next_incomplete_index(session, start_after=current_index)
        if target_index < 0:
            raise RuntimeError("All datasets in the current queue are already completed.")
        return BinaryQueueCore._load_dataset_by_index(main_window, session_path, session, target_index)

    @staticmethod
    def load_current_or_next_dataset(main_window, session_path: str) -> Tuple[Dict, Dict]:
        session = BinaryQueueCore.prepare_session_for_navigation(session_path, main_window=main_window)
        target_index = BinaryQueueCore.current_or_next_index(session)
        if target_index < 0:
            raise RuntimeError("All datasets in the current queue are already completed.")
        return BinaryQueueCore._load_dataset_by_index(main_window, session_path, session, target_index)

    @staticmethod
    def load_previous_dataset(main_window, session_path: str) -> Tuple[Dict, Dict]:
        session = BinaryQueueCore.prepare_session_for_navigation(session_path, main_window=main_window)
        target_index = BinaryQueueCore.previous_index(session)
        if target_index < 0:
            raise RuntimeError("No dataset found in the current queue.")
        return BinaryQueueCore._load_dataset_by_index(main_window, session_path, session, target_index)

    @staticmethod
    def load_ordered_next_dataset(main_window, session_path: str) -> Tuple[Dict, Dict]:
        session = BinaryQueueCore.prepare_session_for_navigation(session_path, main_window=main_window)
        target_index = BinaryQueueCore.ordered_next_index(session)
        if target_index < 0:
            raise RuntimeError("No dataset found in the current queue.")
        return BinaryQueueCore._load_dataset_by_index(main_window, session_path, session, target_index)

    @staticmethod
    def mark_current_done(session_path: str, main_window=None) -> Dict:
        session = BinaryQueueCore.prepare_session_for_navigation(session_path, main_window=main_window)
        current_key = session.get("current_dataset_key", "")
        current_index = BinaryQueueCore.find_dataset_index(session, current_key) if current_key else -1
        if current_index >= 0:
            dataset = session["datasets"][current_index]
            dataset["status"] = "done"
            dataset["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            session["datasets"][current_index] = dataset
            BinaryQueueCore.write_session(session_path, session)
            # Revolution data-management: reflect "refined" back to MagicImageJ manifest.json
            # (best-effort; only when refined masks were actually saved; never breaks the flow)
            try:
                BinaryQueueCore._writeback_refined_to_manifest(session, dataset)
            except Exception:
                pass
        return session

    @staticmethod
    def _writeback_refined_to_manifest(session: Dict, dataset: Dict) -> None:
        """Mark this particle 'refined' in the MagicImageJ manifest (Revolution data layer).

        Only when refined masks were actually saved (so skips / empty datasets are ignored).
        See D:/Revolution_Sample_Claude/tools/manifest_pipeline.py.
        """
        import sys
        root = session.get("root_dir", "")
        if not root:
            return
        manifest_path = filesystem_path(root) / "manifest.json"
        if not manifest_path.exists():
            return
        save_dir = dataset.get("save_dir", "")
        try:
            refined = BinaryQueueCore.count_image_files(str(filesystem_path(save_dir)))
        except Exception:
            refined = int(dataset.get("save_count", 0) or 0)
        if refined <= 0:
            return  # skipped / nothing saved → do not mark as refined
        tools_dir = r"D:\Revolution_Sample_Claude\tools"
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import manifest_pipeline as _mp
        _mp.mark_finetuning_done(
            str(manifest_path),
            base_name=dataset.get("dataset_name", ""),
            save_folder=save_dir,
            refined_count=refined,
            meta={"by": "finetuning"},
        )
        # [Revolution D4] best-effort: 精修回写后刷新该数据集 overview.html (tools 已在 sys.path)
        try:
            from overview_refresh import regenerate_overview_async
            regenerate_overview_async(manifest_path.parent)
        except Exception:
            pass
