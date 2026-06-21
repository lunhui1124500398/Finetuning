"""
启动 Binary 数据集批量精修队列
------------------------------
扫描指定根目录下的 dataset / dataset-mask 配对目录，
自动创建 dataset-mask_new，并把第一个数据集直接加载到 Finetuning。
"""

import os

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QInputDialog

SCRIPT_NAME = "创建会话: 传统布局..."
SCRIPT_ORDER = 10
SCRIPT_DESCRIPTION = "扫描 dataset/dataset-mask 配对目录，自动创建 mask_new 并加载首个数据集"


def _ask_selection_entries(main_window):
    selection_text, ok = QInputDialog.getMultiLineText(
        main_window,
        "可选：指定要加入会话的文件夹/数据集",
        (
            "留空表示加入全部数据集。\n"
            "每行一条规则，支持 * 通配符。\n"
            "写组名：加入整个组。\n"
            "写数据集名：加入同名数据集。\n"
            "写 组名/数据集名：只加入这一条。"
        ),
        "",
    )
    if not ok:
        return None

    entries = []
    for line in selection_text.splitlines():
        entry = line.strip()
        if entry and not entry.startswith("#"):
            entries.append(entry)
    return entries


def run(main_window):
    from core.binary_queue_core import BinaryQueueCore

    model = main_window.model
    start_dir = model.get_path("original_path") or ""
    if start_dir and os.path.isfile(start_dir):
        start_dir = os.path.dirname(start_dir)
    elif start_dir and os.path.isdir(start_dir):
        start_dir = os.path.dirname(start_dir)
    else:
        start_dir = ""

    root_dir = QFileDialog.getExistingDirectory(
        main_window,
        "选择包含大量 dataset / dataset-mask 的根目录",
        start_dir,
    )
    if not root_dir:
        return

    default_suffix = model.config.get("Scripts", "default_binary_mask_suffix", fallback="-mask_new")
    suffix, ok = QInputDialog.getText(
        main_window,
        "确认 mask_new 后缀",
        "将为每个数据集创建保存目录后缀：",
        text=default_suffix,
    )
    if not ok:
        return
    suffix = suffix.strip() or "-mask_new"

    selection_entries = _ask_selection_entries(main_window)
    if selection_entries is None:
        return

    try:
        if not model.config.has_section("Scripts"):
            model.config.add_section("Scripts")
        model.config.set("Scripts", "default_binary_mask_suffix", suffix)
        with open(model.config_path, "w", encoding="utf-8") as handle:
            model.config.write(handle)

        session_path = BinaryQueueCore.create_session(
            root_dir,
            save_suffix=suffix,
            selection_entries=selection_entries,
        )
        BinaryQueueCore.save_session_to_config(main_window, session_path)
        dataset, progress = BinaryQueueCore.load_current_or_next_dataset(main_window, session_path)
    except Exception as exc:
        QMessageBox.critical(main_window, "启动失败", f"创建 Binary 队列失败：\n{exc}")
        return

    selection_summary = "全部数据集"
    if selection_entries:
        preview = "\n".join(selection_entries[:8])
        if len(selection_entries) > 8:
            preview += f"\n... 另有 {len(selection_entries) - 8} 条规则"
        selection_summary = preview

    QMessageBox.information(
        main_window,
        "Binary 队列已启动",
        f"会话文件：\n{session_path}\n\n"
        f"筛选规则：\n{selection_summary}\n\n"
        f"总数据集：{progress['total']}\n"
        f"已完成：{progress['done']}\n"
        f"进行中：{progress['in_progress']}\n"
        f"待处理：{progress['pending']}\n\n"
        f"当前已加载：\n{dataset['group_name']} / {dataset['dataset_name']}\n"
        f"保存目录：\n{dataset['save_dir']}",
    )
