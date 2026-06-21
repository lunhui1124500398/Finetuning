"""
Skip the current dataset in the Binary queue.
--------------------------------------------
Marks the current dataset as completed without saving the current frame,
then loads the next unfinished dataset automatically.
"""

import os

from PyQt6.QtWidgets import QFileDialog, QMessageBox
from utils.path_utils import to_filesystem_path

SCRIPT_NAME = "跳过当前数据集..."
SCRIPT_ORDER = 22
SCRIPT_DESCRIPTION = "不保存当前编辑，直接将当前 Binary 数据集标记完成并切换到下一个"


def run(main_window):
    from core.binary_queue_core import BinaryQueueCore

    model = main_window.model
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

    skipped_name = ""
    try:
        session = BinaryQueueCore.prepare_session_for_navigation(session_path, main_window=main_window)
        current_key = session.get("current_dataset_key", "")
        current_index = BinaryQueueCore.find_dataset_index(session, current_key) if current_key else -1
        if current_index >= 0:
            current_dataset = session["datasets"][current_index]
            skipped_name = f"{current_dataset['group_name']} / {current_dataset['dataset_name']}"

        confirm_before_skip = model.config.getboolean(
            "Scripts",
            "confirm_before_skip_binary_dataset",
            fallback=True,
        )
        if confirm_before_skip:
            target_name = skipped_name or "当前 Binary 数据集"
            reply = QMessageBox.question(
                main_window,
                "确认跳过当前 Binary 数据集",
                f"确定要跳过：\n{target_name}\n\n该操作会将此数据集直接标记为完成，并切换到下一个未完成数据集。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        BinaryQueueCore.mark_current_done(session_path, main_window=main_window)
        dataset, progress = BinaryQueueCore.load_next_dataset(main_window, session_path)
    except Exception as exc:
        QMessageBox.information(main_window, "队列结束或无法继续", str(exc))
        return

    header = "已跳过当前 Binary 数据集"
    if skipped_name:
        header += f"\n已跳过：{skipped_name}"

    QMessageBox.information(
        main_window,
        "已跳过当前 Binary 数据集",
        f"{header}\n\n"
        f"当前进度：{progress['done']}/{progress['total']} 已完成\n"
        f"进行中：{progress['in_progress']}\n"
        f"待处理：{progress['pending']}\n\n"
        f"当前已加载：\n{dataset['group_name']} / {dataset['dataset_name']}\n"
        f"保存目录：\n{dataset['save_dir']}",
    )
