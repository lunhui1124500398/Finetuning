from __future__ import annotations

"""
Remove connected components by region membership.
------------------------------------------------
Uses the current temporary canvas selection as a region mask, then removes
components inside or outside that region over a frame range.
"""

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainterPath
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from core.semi_auto_mask_tools import apply_region_component_filter, build_frame_paths


SCRIPT_NAME = "按区域去掉连通分量..."
SCRIPT_DESCRIPTION = "使用当前画布临时选区作为区域，在指定帧范围内删除区域内或区域外的连通分量。"


class RegionFilterDialog(QDialog):
    def __init__(self, total_frames: int, current_index: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("按区域去掉连通分量")
        self.setMinimumWidth(620)

        self.start_spin = QSpinBox()
        self.start_spin.setRange(1, max(1, total_frames))
        self.start_spin.setValue(max(1, current_index + 1))

        self.end_spin = QSpinBox()
        self.end_spin.setRange(1, max(1, total_frames))
        self.end_spin.setValue(max(1, total_frames))

        self.remove_inside_radio = QRadioButton("删除区域内的连通分量")
        self.remove_outside_radio = QRadioButton("删除区域外的连通分量")
        self.remove_inside_radio.setChecked(True)
        self.partial_mode_radio = QRadioButton("只删除区域覆盖到的部分（推荐）")
        self.whole_component_mode_radio = QRadioButton("删除整块命中的连通分量")
        self.partial_mode_radio.setChecked(True)
        self.match_overlap_radio = QRadioButton("只要与区域有重叠就算在区域内（推荐）")
        self.match_centroid_radio = QRadioButton("只有连通分量质心落在区域内才算在区域内")
        self.match_overlap_radio.setChecked(True)

        self.component_mode_group = QButtonGroup(self)
        self.component_mode_group.addButton(self.partial_mode_radio)
        self.component_mode_group.addButton(self.whole_component_mode_radio)

        self.match_mode_group = QButtonGroup(self)
        self.match_mode_group.addButton(self.match_overlap_radio)
        self.match_mode_group.addButton(self.match_centroid_radio)

        summary = QLabel(
            "先在这里设置帧范围、删除模式和处理方式。\n"
            "确认后，脚本会进入“临时区域绘制模式”，再让你绘制区域。"
        )
        summary.setWordWrap(True)

        note = QLabel(
            "推荐使用“只删除区域覆盖到的部分”。\n"
            "这样即使一次没有完全删干净，也能先把大连通分量削小，后续再配合“保留最大连通分量”清掉。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")

        form = QFormLayout()
        form.addRow("起始帧:", self.start_spin)
        form.addRow("结束帧:", self.end_spin)
        form.addRow("", self.remove_inside_radio)
        form.addRow("", self.remove_outside_radio)
        form.addRow("", self.partial_mode_radio)
        form.addRow("", self.whole_component_mode_radio)
        form.addRow("", self.match_overlap_radio)
        form.addRow("", self.match_centroid_radio)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

        self.partial_mode_radio.toggled.connect(self._update_match_mode_enabled)
        self._update_match_mode_enabled()

    def _update_match_mode_enabled(self) -> None:
        enabled = self.whole_component_mode_radio.isChecked()
        self.match_overlap_radio.setEnabled(enabled)
        self.match_centroid_radio.setEnabled(enabled)

    def get_values(self) -> dict:
        return {
            "start_index": self.start_spin.value() - 1,
            "end_index": self.end_spin.value() - 1,
            "remove_mode": "inside" if self.remove_inside_radio.isChecked() else "outside",
            "component_mode": "partial" if self.partial_mode_radio.isChecked() else "whole_component",
            "region_match_mode": "overlap" if self.match_overlap_radio.isChecked() else "centroid",
        }


class RegionCaptureDialog(QDialog):
    def __init__(self, main_window, frames, values: dict, region_mask_getter, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.frames = frames
        self.values = values
        self.region_mask_getter = region_mask_getter
        self._original_window_title = main_window.windowTitle()
        self._view_restored = False

        self.setWindowTitle("区域绘制模式：画好区域后继续处理")
        self.setMinimumWidth(640)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setStyleSheet(
            """
            QDialog {
                background: #fff7e8;
                border: 2px solid #d97706;
            }
            QLabel#ModeTitle {
                color: #9a3412;
                font-size: 20px;
                font-weight: 700;
                padding: 6px 2px;
            }
            QLabel#ModeNote {
                color: #7c2d12;
                background: #ffedd5;
                border: 1px solid #fdba74;
                padding: 10px 12px;
            }
            QPushButton {
                min-height: 38px;
                font-weight: 600;
                padding: 4px 14px;
            }
            """
        )

        mode_text = "删除区域内的连通分量" if values["remove_mode"] == "inside" else "删除区域外的连通分量"
        component_text = "只删区域覆盖到的部分" if values["component_mode"] == "partial" else "整块删掉命中的连通分量"
        match_text = "有重叠就算在区域内" if values["region_match_mode"] == "overlap" else "质心落在区域内才算在区域内"
        title = QLabel("当前处于“区域绘制模式”")
        title.setObjectName("ModeTitle")

        matching_line = ""
        if values["component_mode"] == "whole_component":
            matching_line = f"，判定方式：{match_text}"
        summary = QLabel(
            "步骤 1：回到主画布，在空白区域层上画出处理区域。\n"
            "步骤 2：画好后回到这里，点击“我已画好区域，开始处理”。\n"
            f"当前设置：{mode_text}，处理方式：{component_text}{matching_line}，帧范围 {values['start_index'] + 1}-{values['end_index'] + 1}"
        )
        summary.setWordWrap(True)
        summary.setObjectName("ModeNote")

        note = QLabel(
            "当前已自动切换到：蚂蚁线显示 + 套索工具。\n"
            "这里画的是临时区域，不会直接写回当前 mask。\n"
            "处理结束或取消后，当前帧会自动恢复正常显示。"
        )
        note.setWordWrap(True)
        note.setObjectName("ModeNote")

        buttons = QDialogButtonBox()
        self.continue_button = buttons.addButton("我已画好区域，开始处理", QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel_button = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.continue_button.clicked.connect(self._continue_processing)
        self.cancel_button.clicked.connect(self._cancel)
        self.continue_button.setStyleSheet("background: #16a34a; color: white;")
        self.cancel_button.setStyleSheet("background: #b91c1c; color: white;")

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(summary)
        layout.addWidget(note)
        layout.addWidget(buttons)

        self.main_window.setWindowTitle(f"{self._original_window_title}  [区域绘制模式进行中]")
        self.finished.connect(self._on_finished)

    def _restore_main_view(self) -> None:
        if self._view_restored:
            return
        self._view_restored = True
        model = self.main_window.model
        self.main_window.setWindowTitle(self._original_window_title)
        if model.current_index >= 0:
            self.main_window.canvas.load_image(model.current_index)
            self.main_window.preview_panel.update_previews(model.current_index)

    def _on_finished(self, _result: int) -> None:
        if getattr(self.main_window, "_region_component_filter_dialog", None) is self:
            self.main_window._region_component_filter_dialog = None

    def closeEvent(self, event) -> None:
        self._restore_main_view()
        super().closeEvent(event)

    def reject(self) -> None:
        self._restore_main_view()
        super().reject()

    def _cancel(self) -> None:
        self.reject()

    def _continue_processing(self) -> None:
        region_mask = self.region_mask_getter()
        if region_mask is None or int(region_mask.sum()) == 0:
            QMessageBox.warning(self, "缺少区域", "请先在主画布上画出一个非空区域，再继续。")
            return

        progress = QProgressDialog(
            "正在按区域去掉连通分量...",
            "取消",
            0,
            max(1, self.values["end_index"] - self.values["start_index"] + 1),
            self.main_window,
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        def progress_cb(current: int, total: int) -> bool:
            if progress.wasCanceled():
                return False
            progress.setMaximum(max(1, total))
            progress.setValue(current + 1)
            QApplication.processEvents()
            return True

        result = apply_region_component_filter(
            frames=self.frames,
            region_mask=region_mask,
            start_index=self.values["start_index"],
            end_index=self.values["end_index"],
            remove_mode=self.values["remove_mode"],
            component_mode=self.values["component_mode"],
            region_match_mode=self.values["region_match_mode"],
            progress_callback=progress_cb,
        )
        progress.close()

        self._restore_main_view()
        if hasattr(self.main_window, "refresh_seed_cache"):
            self.main_window.refresh_seed_cache()
        if hasattr(self.main_window, "update_seed_status_label"):
            self.main_window.update_seed_status_label()
        self.accept()

        mode_text = "区域内" if self.values["remove_mode"] == "inside" else "区域外"
        component_text = "只删区域覆盖到的部分" if self.values["component_mode"] == "partial" else "整块删掉命中的连通分量"
        match_text = "有重叠就算在区域内" if self.values["region_match_mode"] == "overlap" else "质心落在区域内"
        affected_line = "受影响连通分量数" if self.values["component_mode"] == "partial" else "删除连通分量数"
        QMessageBox.information(
            self.main_window,
            "处理完成",
            "\n".join(
                [
                    f"删除模式: {mode_text}",
                    f"处理方式: {component_text}",
                    f"判定方式: {match_text}" if self.values["component_mode"] == "whole_component" else "判定方式: 不适用（按像素区域直接裁剪）",
                    f"帧范围: {self.values['start_index'] + 1} - {self.values['end_index'] + 1}",
                    f"实际处理帧数: {result.processed_frames}",
                    f"跳过帧数: {result.skipped_frames}",
                    f"{affected_line}: {result.removed_components}",
                    f"删除像素数: {result.removed_pixels}",
                ]
            ),
        )


def _pixmap_to_binary_array(pixmap) -> np.ndarray:
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
    width = image.width()
    height = image.height()
    ptr = image.bits()
    ptr.setsize(height * image.bytesPerLine())
    arr = np.frombuffer(ptr, np.uint8).reshape((height, image.bytesPerLine()))
    return (arr[:, :width] > 0).astype(np.uint8)


def run(main_window):
    model = main_window.model
    save_dir = model.get_path("save_path")
    if not save_dir:
        QMessageBox.warning(main_window, "缺少保存路径", "请先加载当前数据集，并确保 save_path 指向 mask_new。")
        return

    if model.auto_save:
        QMessageBox.warning(
            main_window,
            "请先关闭自动保存",
            "这个脚本会把当前画布上的临时选区当作区域参考。\n"
            "为避免临时区域被自动写回，请先关闭自动保存（X）后再运行。",
        )
        return

    if model.current_index < 0:
        QMessageBox.warning(main_window, "没有当前帧", "请先加载当前数据集。")
        return

    frames = build_frame_paths(model._original_files, model._mask_files, save_dir)
    if not frames:
        QMessageBox.warning(main_window, "没有图像", "当前数据集没有可处理的帧。")
        return

    dialog = RegionFilterDialog(
        total_frames=len(frames),
        current_index=model.current_index,
        parent=main_window,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    values = dialog.get_values()

    if values["start_index"] > values["end_index"]:
        QMessageBox.warning(main_window, "范围错误", "起始帧不能大于结束帧。")
        return

    if model.current_index >= 0:
        main_window.canvas.save_current_mask()

    main_window.canvas._selection_path = QPainterPath()
    main_window.canvas.update_selection_display()
    model.set_display_mode("ants")
    model.set_selection_tool("lasso")
    main_window.canvas.setFocus()

    def region_mask_getter():
        region_pixmap = main_window.canvas.get_pixmap_from_path()
        if region_pixmap.isNull():
            return None
        return _pixmap_to_binary_array(region_pixmap)

    capture_dialog = RegionCaptureDialog(
        main_window=main_window,
        frames=frames,
        values=values,
        region_mask_getter=region_mask_getter,
        parent=main_window,
    )
    main_window._region_component_filter_dialog = capture_dialog
    capture_dialog.show()
    capture_dialog.raise_()
    main_window.raise_()
    main_window.activateWindow()
    main_window.canvas.setFocus()
