"""
Create a Binary queue session directly from a flat Exports directory.
--------------------------------------------------------------------
Lets the user pick a MagicImageJ Exports folder, select which contrasted ROI
folders should enter the Binary queue, and load the first selected dataset.
"""

from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QDialog


SCRIPT_NAME = "创建会话: Exports 目录..."
SCRIPT_DESCRIPTION = "选择 Exports 总目录，默认加入所有 *_contrasted 文件夹并创建 Binary 会话。"
SCRIPT_CATEGORY = "Binary 会话"
SCRIPT_ORDER = 11


def _short_session_name(dataset_count: int) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"exports_binary_session_{dataset_count}_{timestamp}.json"


def _start_dir_from_model(main_window) -> str:
    model = main_window.model
    candidates = [
        model.get_path("original_path") or "",
        model.get_path("mask_path") or "",
        model.get_path("save_path") or "",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            path = path.parent
        if path.is_dir():
            for parent in [path, *path.parents]:
                if parent.name.endswith("_Exports"):
                    return str(parent)
            return str(path)
    return ""


def run(main_window):
    from core.binary_queue_core import BinaryQueueCore
    from ui.widgets.binary_session_dialogs import BinaryExportsSessionDialog

    model = main_window.model
    start_dir = _start_dir_from_model(main_window)
    exports_dir = QFileDialog.getExistingDirectory(
        main_window,
        "选择包含 *_contrasted 文件夹的 Exports 总目录",
        start_dir,
    )
    if not exports_dir:
        return

    origin_suffix = model.config.get("Scripts", "default_origin_suffix", fallback="_contrasted")
    mask_suffix = model.config.get("Scripts", "default_mask_suffix", fallback="_origin_mask_new")
    save_suffix = model.config.get("Scripts", "default_binary_exports_save_suffix", fallback="_origin_mask_refined")

    dialog = BinaryExportsSessionDialog(
        exports_dir,
        origin_suffix=origin_suffix,
        mask_suffix=mask_suffix,
        save_suffix=save_suffix,
        parent=main_window,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    selected_datasets, origin_suffix, mask_suffix, save_suffix = dialog.get_config()
    if not selected_datasets:
        return

    try:
        if not model.config.has_section("Scripts"):
            model.config.add_section("Scripts")
        model.config.set("Scripts", "default_origin_suffix", origin_suffix)
        model.config.set("Scripts", "default_mask_suffix", mask_suffix)
        model.config.set("Scripts", "default_binary_exports_save_suffix", save_suffix)
        with open(model.config_path, "w", encoding="utf-8") as handle:
            model.config.write(handle)

        session_name = _short_session_name(len(selected_datasets))
        session_path = BinaryQueueCore.create_session_from_datasets(
            exports_dir,
            selected_datasets,
            save_suffix=save_suffix,
            selection_entries=[dataset.get("source_folder", dataset["dataset_name"]) for dataset in selected_datasets],
            session_name=session_name,
            create_missing_mask_dirs=True,
            metadata={
                "source_layout": "exports",
                "origin_suffix": origin_suffix,
                "mask_suffix": mask_suffix,
                "save_suffix": save_suffix,
            },
        )
        BinaryQueueCore.save_session_to_config(main_window, session_path)

        try:
            dataset, progress = BinaryQueueCore.load_current_or_next_dataset(main_window, session_path)
        except RuntimeError as exc:
            if "already completed" not in str(exc).lower():
                raise
            dataset, progress = BinaryQueueCore.load_ordered_next_dataset(main_window, session_path)
    except Exception as exc:
        QMessageBox.critical(main_window, "创建失败", f"从 Exports 创建 Binary 会话失败：\n{exc}")
        return

    QMessageBox.information(
        main_window,
        "Binary 会话已创建",
        f"会话文件：\n{session_path}\n\n"
        f"来源目录：\n{exports_dir}\n\n"
        f"原图后缀：{origin_suffix}\n"
        f"初始 Mask 后缀：{mask_suffix}\n"
        f"保存后缀：{save_suffix}\n\n"
        f"总数据集：{progress['total']}\n"
        f"已完成：{progress['done']}\n"
        f"进行中：{progress['in_progress']}\n"
        f"待处理：{progress['pending']}\n\n"
        f"当前已加载：\n{dataset['group_name']} / {dataset['dataset_name']}\n"
        f"保存目录：\n{dataset['save_dir']}",
    )
