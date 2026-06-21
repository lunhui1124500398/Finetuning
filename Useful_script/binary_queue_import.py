"""
Import or resume an existing Binary queue session.
-------------------------------------------------
Lets the user pick a previously generated JSON session file and loads the
current unfinished dataset into the main window so drawing can continue
without recreating the queue.
"""

import os

from PyQt6.QtWidgets import QFileDialog, QMessageBox
from utils.path_utils import to_filesystem_path

SCRIPT_NAME = "导入/恢复已有会话..."
SCRIPT_ORDER = 12
SCRIPT_DESCRIPTION = "选择已有 Binary 队列会话 JSON，并恢复当前未完成的数据集"


def run(main_window):
    from core.binary_queue_core import BinaryQueueCore

    current_session = BinaryQueueCore.load_session_from_config(main_window)
    start_dir = ""
    if current_session and os.path.exists(to_filesystem_path(current_session)):
        start_dir = os.path.dirname(current_session)

    session_path, _ = QFileDialog.getOpenFileName(
        main_window,
        "选择 Binary 队列会话文件",
        start_dir,
        "JSON Files (*.json)",
    )
    if not session_path:
        return

    try:
        BinaryQueueCore.save_session_to_config(main_window, session_path)
        dataset, progress = BinaryQueueCore.load_current_or_next_dataset(main_window, session_path)
    except Exception as exc:
        QMessageBox.critical(main_window, "导入失败", f"无法加载 Binary 会话：\n{exc}")
        return

    QMessageBox.information(
        main_window,
        "Binary 会话已导入",
        f"会话文件：\n{session_path}\n\n"
        f"总数据集：{progress['total']}\n"
        f"已完成：{progress['done']}\n"
        f"进行中：{progress['in_progress']}\n"
        f"待处理：{progress['pending']}\n\n"
        f"当前已加载：\n{dataset['group_name']} / {dataset['dataset_name']}\n"
        f"保存目录：\n{dataset['save_dir']}",
    )
