"""
Switch to the previous dataset in the Binary queue.

This script saves the current frame mask and loads the previous dataset in the
current Binary queue without changing completion status.
"""

import os

from PyQt6.QtWidgets import QFileDialog, QMessageBox
from utils.path_utils import to_filesystem_path

SCRIPT_NAME = "上一个数据集 (B)"
SCRIPT_ORDER = 21
SCRIPT_DESCRIPTION = "保存当前帧并切换到上一个 Binary 数据集，不修改完成状态。"


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
        dataset, progress = BinaryQueueCore.load_previous_dataset(main_window, session_path)
    except Exception as exc:
        QMessageBox.information(main_window, "无法切换到上一个 Binary", str(exc))
        return

    QMessageBox.information(
        main_window,
        "已切换到上一个 Binary 数据集",
        f"当前进度：{progress['done']}/{progress['total']} 已完成\n"
        f"进行中：{progress['in_progress']}\n"
        f"待处理：{progress['pending']}\n\n"
        f"当前已加载：\n{dataset['group_name']} / {dataset['dataset_name']}\n"
        f"保存目录：\n{dataset['save_dir']}",
    )
