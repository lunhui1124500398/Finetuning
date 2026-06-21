"""
Generate a connected-component QC report for the currently loaded dataset
and preview the result directly inside Finetuning.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


SCRIPT_NAME = "分析当前数据集连通分量..."
SCRIPT_ORDER = 40
SCRIPT_DESCRIPTION = "只分析当前加载的数据集，并在窗口内直接显示分布图、阈值扫描图和推荐阈值。"


class CurrentDatasetQCDialog(QDialog):
    def __init__(self, summary: dict, parent=None):
        super().__init__(parent)
        self.summary = summary
        self.setWindowTitle("当前数据集连通分量分析")
        self.resize(1280, 980)
        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        summary_lines = [
            f"<b>数据集:</b> {self.summary['dataset_label']}",
            f"<b>推荐阈值:</b> <= {self.summary['recommended_threshold']}",
            f"<b>分布断层候选:</b> {self.summary['gap_threshold']}",
            f"<b>效率最优候选:</b> {self.summary['score_threshold']}",
            f"<b>推荐理由:</b> {self.summary['recommendation_reason']}",
        ]

        if self.summary.get("recommended_threshold", 0) > 0:
            summary_lines.extend(
                [
                    (
                        f"<b>若使用推荐阈值，预计去掉非最大连通分量比例:</b> "
                        f"{self.summary.get('components_removed_fraction', 0.0) * 100:.1f}%"
                    ),
                    (
                        f"<b>对应去掉的非最大连通分量像素比例:</b> "
                        f"{self.summary.get('non_largest_pixels_removed_fraction', 0.0) * 100:.1f}%"
                    ),
                    (
                        f"<b>预计受影响帧比例:</b> "
                        f"{self.summary.get('frames_affected_fraction', 0.0) * 100:.1f}%"
                    ),
                ]
            )
        else:
            summary_lines.append("<b>结论:</b> 当前数据集没有明显需要批量去除的小连通分量。")

        summary_label = QLabel("<br>".join(summary_lines))
        summary_label.setWordWrap(True)
        summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        main_layout.addWidget(summary_label)

        note_label = QLabel(
            "下方图会直接显示在窗口里，方便你边看边决定是否需要用“去掉特别小的连通分量”脚本。"
        )
        note_label.setWordWrap(True)
        main_layout.addWidget(note_label)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        container = QWidget()
        container_layout = QVBoxLayout(container)

        image_paths = [
            ("四项基础分布", self.summary.get("histogram_plot", "")),
            (
                "非最大连通分量面积分布",
                (self.summary.get("non_largest_component_distribution_plots") or [""])[0],
            ),
            (
                "阈值扫描",
                (self.summary.get("threshold_sweep_plots") or [""])[0],
            ),
        ]

        for title, image_path in image_paths:
            if not image_path:
                continue
            section_title = QLabel(f"<b>{title}</b>")
            section_title.setWordWrap(True)
            container_layout.addWidget(section_title)
            container_layout.addWidget(self._build_image_label(image_path))

        info_label = QLabel(
            "\n".join(
                [
                    f"面积统计表: {self.summary.get('component_area_counts_csv', '')}",
                    f"阈值扫描表: {self.summary.get('threshold_sweep_csv', '')}",
                ]
            )
        )
        info_label.setWordWrap(True)
        info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        container_layout.addWidget(info_label)
        container_layout.addStretch()

        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        main_layout.addWidget(buttons)

    def _build_image_label(self, image_path: str) -> QLabel:
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setWordWrap(True)

        pixmap = QPixmap(str(Path(image_path)))
        if pixmap.isNull():
            label.setText(f"无法加载图像:\n{image_path}")
            return label

        scaled = pixmap.scaledToWidth(1120, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(scaled)
        return label


def run(main_window):
    from utils.build_component_qc_report import build_current_dataset_component_qc

    model = main_window.model
    original_dir = model.get_path("original_path") or ""
    mask_dir = model.get_path("mask_path") or ""
    save_dir = model.get_path("save_path") or ""

    if not original_dir or not mask_dir or not save_dir:
        QMessageBox.warning(main_window, "路径不完整", "请先确保当前数据集已经正确加载。")
        return

    if getattr(model, "current_index", -1) >= 0:
        main_window.canvas.save_current_mask()

    progress = QProgressDialog("正在分析当前数据集的连通分量...", "取消", 0, 1, main_window)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)

    def progress_cb(frame_index: int, frame_total: int) -> bool:
        if progress.wasCanceled():
            return False
        progress.setMaximum(max(1, frame_total))
        progress.setValue(min(frame_index, frame_total))
        progress.setLabelText(
            "正在分析当前数据集的连通分量...\n"
            f"Frame {frame_index}/{frame_total}"
        )
        QApplication.processEvents()
        return True

    try:
        summary = build_current_dataset_component_qc(
            original_dir=original_dir,
            mask_dir=mask_dir,
            save_dir=save_dir,
            progress_callback=progress_cb,
        )
    except Exception as exc:
        progress.close()
        QMessageBox.critical(main_window, "分析失败", str(exc))
        return

    progress.setValue(progress.maximum())
    progress.close()

    dialog = CurrentDatasetQCDialog(summary, parent=main_window)
    dialog.exec()
