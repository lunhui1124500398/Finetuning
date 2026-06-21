"""
Switch to the next dataset in the Binary queue.

If the queue still has unfinished datasets, this script behaves like the
original workflow: save the current mask, mark the current dataset as done,
and load the next unfinished dataset.

If the queue is already fully done, it falls back to the next dataset in the
session order so users can keep navigating through initialized `mask_new`
datasets without manually browsing folders.
"""

import os

from PyQt6.QtWidgets import QFileDialog, QMessageBox
from utils.path_utils import to_filesystem_path

SCRIPT_NAME = "下一个数据集 (N)"
SCRIPT_ORDER = 20
SCRIPT_DESCRIPTION = "保存当前帧并切换到下一个 Binary 数据集；如果会话已全部完成，则按顺序继续切换。"


def run(main_window):
    from core.binary_queue_core import BinaryQueueCore

    session_path = BinaryQueueCore.load_session_from_config(main_window)
    if not session_path or not QFileDialog:
        session_path = ""

    if not session_path or not os.path.exists(to_filesystem_path(session_path)):
        session_path, _ = QFileDialog.getOpenFileName(
            main_window,
            "选择 Binary 队列会话文件",
            "",
            "JSON Files (*.json)",
        )
        if not session_path:
            return
        BinaryQueueCore.save_session_to_config(main_window, session_path)

    try:
        if getattr(main_window.model, "current_index", -1) >= 0:
            main_window.canvas.save_current_mask()

        BinaryQueueCore.mark_current_done(session_path, main_window=main_window)

        try:
            dataset, progress = BinaryQueueCore.load_next_dataset(main_window, session_path)
        except RuntimeError as exc:
            if "already completed" not in str(exc).lower():
                raise
            dataset, progress = BinaryQueueCore.load_ordered_next_dataset(main_window, session_path)
    except Exception as exc:
        QMessageBox.information(main_window, "无法切换到下一个 Binary", str(exc))
        return

    QMessageBox.information(
        main_window,
        "已切换到下一个 Binary 数据集",
        f"当前进度：{progress['done']}/{progress['total']} 已完成\n"
        f"进行中：{progress['in_progress']}\n"
        f"待处理：{progress['pending']}\n\n"
        f"当前已加载：\n{dataset['group_name']} / {dataset['dataset_name']}\n"
        f"保存目录：\n{dataset['save_dir']}",
    )
