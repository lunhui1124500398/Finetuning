from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QSpinBox,
    QVBoxLayout,
)

from core.semi_auto_mask_tools import (
    build_frame_paths,
    propagate_masks_by_template,
    resolve_seed_indices,
)


SCRIPT_NAME = "依葫芦画瓢追踪 Mask..."
SCRIPT_DESCRIPTION = "基于当前数据集里已经修好的 mask_new，在指定帧范围内做镜像模板传播。"


class MaskTrackingDialog(QDialog):
    def __init__(self, total_frames: int, seed_frames: int, seed_mode: str, current_index: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("依葫芦画瓢追踪 Mask")
        self.setMinimumWidth(520)

        self.start_spin = QSpinBox()
        self.start_spin.setRange(1, max(1, total_frames))
        self.start_spin.setValue(max(1, min(total_frames, current_index + 1)))

        self.end_spin = QSpinBox()
        self.end_spin.setRange(1, max(1, total_frames))
        self.end_spin.setValue(max(1, total_frames))

        self.search_radius_spin = QSpinBox()
        self.search_radius_spin.setRange(4, 80)
        self.search_radius_spin.setValue(24)

        self.template_margin_spin = QSpinBox()
        self.template_margin_spin.setRange(2, 32)
        self.template_margin_spin.setValue(8)

        self.skip_existing_checkbox = QCheckBox("跳过已经存在的 mask_new")
        self.skip_existing_checkbox.setChecked(True)

        seed_mode_text = {
            "explicit": "当前使用的是你手动指定的 seed。",
            "edited": "当前没有手动指定 seed，自动使用与你原 mask 有差异的已修帧。",
            "saved": "当前没有手动指定 seed，也没有明显改动帧，自动使用已保存帧。",
        }.get(seed_mode, "当前将自动选择 seed。")
        summary = QLabel(
            f"当前数据集共 {total_frames} 帧，检测到 {seed_frames} 张已修帧可作为种子。"
            f"\n{seed_mode_text}"
            "\n适合颗粒运动较小、形状变化不激烈的连续视频。"
        )
        summary.setWordWrap(True)

        tip = QLabel(
            "默认只使用你手工保存过的种子帧。自动生成的结果不会再反向作为下一轮 seed，"
            "这样可以避免越跑 seed 越多、以及结果越传越像。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: gray;")

        form = QFormLayout()
        form.addRow("起始帧:", self.start_spin)
        form.addRow("结束帧:", self.end_spin)
        form.addRow("搜索半径:", self.search_radius_spin)
        form.addRow("模板边距:", self.template_margin_spin)
        form.addRow("", self.skip_existing_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addLayout(form)
        layout.addWidget(tip)
        layout.addWidget(buttons)

    def get_values(self) -> dict:
        return {
            "start_index": self.start_spin.value() - 1,
            "end_index": self.end_spin.value() - 1,
            "search_radius": self.search_radius_spin.value(),
            "template_margin": self.template_margin_spin.value(),
            "skip_existing_saves": self.skip_existing_checkbox.isChecked(),
        }


def _refresh_views(main_window) -> None:
    model = main_window.model
    if model.current_index >= 0:
        main_window.canvas.load_image(model.current_index)
        main_window.preview_panel.update_previews(model.current_index)


def run(main_window):
    model = main_window.model
    save_dir = model.get_path("save_path")
    if not save_dir:
        QMessageBox.warning(main_window, "缺少保存路径", "请先加载当前数据集，并确保 save_path 指向 mask_new。")
        return

    if model.current_index >= 0:
        main_window.canvas.save_current_mask()

    frames = build_frame_paths(model._original_files, model._mask_files, save_dir)
    if not frames:
        QMessageBox.warning(main_window, "没有图像", "当前数据集没有可处理的帧。")
        return

    seed_indices, seed_mode = resolve_seed_indices(frames, min_changed_pixels=1)
    if not seed_indices:
        QMessageBox.warning(main_window, "没有已修帧", "请先修几张代表性的帧并保存到 mask_new。")
        return

    dialog = MaskTrackingDialog(
        total_frames=len(frames),
        seed_frames=len(seed_indices),
        seed_mode=seed_mode,
        current_index=max(0, model.current_index),
        parent=main_window,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    values = dialog.get_values()

    if values["start_index"] > values["end_index"]:
        QMessageBox.warning(main_window, "范围错误", "起始帧不能大于结束帧。")
        return

    total = values["end_index"] - values["start_index"] + 1
    progress = QProgressDialog("正在按已修帧追踪 Mask...", "取消", 0, max(1, total), main_window)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)

    def tracking_progress(current: int, progress_total: int) -> bool:
        if progress.wasCanceled():
            return False
        progress.setMaximum(max(1, progress_total))
        progress.setValue(current + 1)
        QApplication.processEvents()
        return True

    try:
        result = propagate_masks_by_template(
            frames=frames,
            start_index=values["start_index"],
            end_index=values["end_index"],
            seed_indices=seed_indices,
            search_radius=values["search_radius"],
            template_margin=values["template_margin"],
            skip_existing_saves=values["skip_existing_saves"],
            allow_generated_masks_as_references=False,
            progress_callback=tracking_progress,
        )
    except Exception as exc:
        progress.close()
        QMessageBox.warning(main_window, "追踪失败", str(exc))
        return

    progress.close()
    _refresh_views(main_window)

    message_lines = [
        f"种子帧数: {result.seed_frame_count}",
        f"实际处理帧数: {result.processed_frames}",
        f"跳过帧数: {result.skipped_frames}",
        f"累计写入像素数: {result.propagated_pixels}",
        f"平均匹配分数: {result.average_match_score:.3f}",
        f"自动结果反向参与追踪: {result.reused_generated_reference_count}",
    ]
    if result.processed_frames == 0 and result.skipped_frames > 0 and values["skip_existing_saves"]:
        message_lines.append("当前范围内已经存在 mask_new，且勾选了跳过已有结果，所以这次没有覆盖写入。")
    QMessageBox.information(main_window, "Mask 追踪完成", "\n".join(message_lines))
