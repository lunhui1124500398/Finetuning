"""
查看 Binary 批量精修队列状态
--------------------------
显示当前队列会话的已完成、进行中、待处理数量，并指出当前加载的数据集。
"""

import os

from PyQt6.QtWidgets import QFileDialog, QMessageBox
from utils.path_utils import to_filesystem_path

SCRIPT_NAME = "查看会话进度..."
SCRIPT_ORDER = 15
SCRIPT_DESCRIPTION = "显示当前 Binary 批量精修会话的进度统计"


def run(main_window):
    from core.binary_queue_core import BinaryQueueCore

    session_path = BinaryQueueCore.load_session_from_config(main_window)
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
        session = BinaryQueueCore.refresh_session(session_path)
    except Exception as exc:
        QMessageBox.critical(main_window, "读取失败", f"无法读取会话文件：\n{exc}")
        return

    progress = BinaryQueueCore.summarize_progress(session)
    current_key = session.get("current_dataset_key", "")
    current_dataset = None
    if current_key:
        for dataset in session.get("datasets", []):
            if BinaryQueueCore.dataset_key(dataset) == current_key:
                current_dataset = dataset
                break

    current_text = "当前未加载任何数据集"
    if current_dataset:
        current_text = (
            f"{current_dataset['group_name']} / {current_dataset['dataset_name']}\n"
            f"save_count={current_dataset['save_count']}, status={current_dataset['status']}"
        )

    QMessageBox.information(
        main_window,
        "Binary 队列进度",
        f"会话文件：\n{session_path}\n\n"
        f"总数据集：{progress['total']}\n"
        f"已完成：{progress['done']}\n"
        f"进行中：{progress['in_progress']}\n"
        f"待处理：{progress['pending']}\n\n"
        f"当前：\n{current_text}",
    )
