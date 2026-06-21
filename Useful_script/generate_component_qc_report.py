"""
Generate a connected-component QC report for the current Binary queue session.
"""

import os
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox, QProgressDialog
from utils.path_utils import to_filesystem_path


SCRIPT_NAME = "生成连通分量 QC 报告..."
SCRIPT_ORDER = 41
SCRIPT_DESCRIPTION = "统计当前 Binary 队列里各数据集的连通分量情况，并生成阈值分布图与 QC 报告。"


def run(main_window):
    from core.binary_queue_core import BinaryQueueCore
    from utils.build_component_qc_report import build_component_qc_report, default_output_dir

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

    threshold, ok = QInputDialog.getInt(
        main_window,
        "设置小连通分量阈值",
        "将面积 <= 该值的连通分量视作 small component：",
        value=50,
        min=0,
        max=1_000_000,
        step=1,
    )
    if not ok:
        return

    include_done_reply = QMessageBox.question(
        main_window,
        "分析范围",
        "是否分析当前会话中的全部数据集？\n\n"
        "是：分析全部数据集（适合当前 mask_new 已初始化后的会话）\n"
        "否：只分析未完成或进行中的数据集",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Yes,
    )
    if include_done_reply == QMessageBox.StandardButton.Cancel:
        return
    include_done = include_done_reply == QMessageBox.StandardButton.Yes

    output_dir = default_output_dir(Path(session_path))
    progress = QProgressDialog("正在准备连通分量 QC 报告...", "取消", 0, 1, main_window)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)

    def progress_cb(dataset_index: int, dataset_total: int, frame_index: int, frame_total: int, dataset_label: str) -> bool:
        if progress.wasCanceled():
            return False
        progress.setMaximum(max(1, dataset_total))
        progress.setValue(min(max(dataset_index - 1, 0), max(dataset_total - 1, 0)))
        frame_text = f"Frame {frame_index}/{frame_total}" if frame_total > 0 else "Preparing frames..."
        progress.setLabelText(
            "正在生成连通分量 QC 报告...\n"
            f"{dataset_index}/{dataset_total}\n"
            f"{dataset_label}\n"
            f"{frame_text}"
        )
        QApplication.processEvents()
        return True

    try:
        summary = build_component_qc_report(
            session_path=session_path,
            output_dir=str(output_dir),
            small_area_threshold=int(threshold),
            fallback_to_mask_dir=True,
            include_done=include_done,
            progress_callback=progress_cb,
        )
    except Exception as exc:
        progress.close()
        QMessageBox.critical(main_window, "QC 报告生成失败", str(exc))
        return

    progress.setValue(progress.maximum())
    progress.close()

    plot_path = ""
    if summary.get("non_largest_component_distribution_plots"):
        plot_path = summary["non_largest_component_distribution_plots"][0]

    sweep_path = ""
    if summary.get("threshold_sweep_plots"):
        sweep_path = summary["threshold_sweep_plots"][0]

    QMessageBox.information(
        main_window,
        "QC 报告已生成",
        "\n".join(
            [
                f"输出目录：\n{summary['output_dir']}",
                "",
                f"数据集数量：{summary['dataset_count']}",
                f"small component 阈值：<= {summary['small_area_threshold']}",
                "",
                f"数据集汇总：\n{summary['dataset_summary_csv']}",
                f"阈值扫描表：\n{summary['threshold_sweep_csv']}",
                f"面积分布图：\n{plot_path}" if plot_path else "面积分布图：未生成",
                f"阈值扫描图：\n{sweep_path}" if sweep_path else "阈值扫描图：未生成",
            ]
        ),
    )
