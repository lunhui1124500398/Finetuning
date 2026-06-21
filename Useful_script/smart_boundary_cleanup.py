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
    _load_binary_mask,
    apply_boundary_cleanup,
    build_frame_paths,
    learn_boundary_cleanup_model,
    propagate_masks_by_template,
    resolve_seed_indices,
)


SCRIPT_NAME = "智能去除边界阳性..."
SCRIPT_DESCRIPTION = "从当前数据集已修好的 mask_new 学习边界阳性，并批量清理后续帧。"


class BoundaryCleanupDialog(QDialog):
    def __init__(self, total_frames: int, seed_frames: int, seed_mode: str, start_index: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("智能去除边界阳性")
        self.setMinimumWidth(560)

        self.start_spin = QSpinBox()
        self.start_spin.setRange(1, max(1, total_frames))
        self.start_spin.setValue(max(1, min(total_frames, start_index + 1)))

        self.end_spin = QSpinBox()
        self.end_spin.setRange(1, max(1, total_frames))
        self.end_spin.setValue(max(1, total_frames))

        self.skip_existing_checkbox = QCheckBox("跳过已经存在的 mask_new")
        self.skip_existing_checkbox.setChecked(True)

        self.experimental_recover_checkbox = QCheckBox("同时尝试镜像模板补圈（实验）")
        self.experimental_recover_checkbox.setChecked(False)

        self.search_radius_spin = QSpinBox()
        self.search_radius_spin.setRange(4, 80)
        self.search_radius_spin.setValue(24)
        self.search_radius_spin.setEnabled(False)

        self.template_margin_spin = QSpinBox()
        self.template_margin_spin.setRange(2, 32)
        self.template_margin_spin.setValue(8)
        self.template_margin_spin.setEnabled(False)

        self.experimental_recover_checkbox.toggled.connect(self.search_radius_spin.setEnabled)
        self.experimental_recover_checkbox.toggled.connect(self.template_margin_spin.setEnabled)

        seed_mode_text = {
            "explicit": "当前使用的是你手动指定的 seed。",
            "edited": "当前没有手动指定 seed，自动使用与你原 mask 有差异的已修帧。",
            "saved": "当前没有手动指定 seed，也没有明显改动帧，自动使用已保存帧。",
        }.get(seed_mode, "当前将自动选择 seed。")

        summary = QLabel(
            f"当前数据集共 {total_frames} 帧，检测到 {seed_frames} 张可用于学习边界阳性的 seed。"
            f"\n{seed_mode_text}"
            "\n脚本会优先保护你已经手工修过的帧，只批量处理指定范围内的其他帧。"
        )
        summary.setWordWrap(True)

        warning = QLabel(
            "实验补圈不是神经网络重推理，而是基于已修帧做镜像模板传播，适合边界附近漏圈和轻微位移。"
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: gray;")

        form = QFormLayout()
        form.addRow("起始帧:", self.start_spin)
        form.addRow("结束帧:", self.end_spin)
        form.addRow("", self.skip_existing_checkbox)
        form.addRow("", self.experimental_recover_checkbox)
        form.addRow("补圈搜索半径:", self.search_radius_spin)
        form.addRow("补圈模板边距:", self.template_margin_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addLayout(form)
        layout.addWidget(warning)
        layout.addWidget(buttons)

    def get_values(self) -> dict:
        return {
            "start_index": self.start_spin.value() - 1,
            "end_index": self.end_spin.value() - 1,
            "skip_existing_saves": self.skip_existing_checkbox.isChecked(),
            "experimental_recover": self.experimental_recover_checkbox.isChecked(),
            "search_radius": self.search_radius_spin.value(),
            "template_margin": self.template_margin_spin.value(),
        }


def _refresh_views(main_window) -> None:
    model = main_window.model
    if model.current_index >= 0:
        main_window.canvas.load_image(model.current_index)
        main_window.preview_panel.update_previews(model.current_index)


def _tiny_or_empty_saved_indices(frames, start_index: int, end_index: int, area_threshold: int) -> list[int]:
    indices: list[int] = []
    for frame in frames:
        if frame.index < start_index or frame.index > end_index or not frame.has_saved_mask:
            continue
        mask = _load_binary_mask(frame.save_path)
        if mask is None:
            continue
        if int(mask.sum()) <= area_threshold:
            indices.append(frame.index)
    return indices


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

    training_indices, seed_mode = resolve_seed_indices(frames, min_changed_pixels=1)
    if not training_indices:
        QMessageBox.warning(main_window, "没有已修帧", "请先手工修几张边界阳性的帧并保存到 mask_new。")
        return

    start_hint = max(model.current_index, max(training_indices))
    dialog = BoundaryCleanupDialog(
        total_frames=len(frames),
        seed_frames=len(training_indices),
        seed_mode=seed_mode,
        start_index=start_hint,
        parent=main_window,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    values = dialog.get_values()

    if values["start_index"] > values["end_index"]:
        QMessageBox.warning(main_window, "范围错误", "起始帧不能大于结束帧。")
        return

    try:
        boundary_model, _ = learn_boundary_cleanup_model(frames, training_indices)
    except Exception as exc:
        QMessageBox.warning(main_window, "学习失败", str(exc))
        return

    target_total = values["end_index"] - values["start_index"] + 1
    progress = QProgressDialog("正在学习并批量去除边界阳性...", "取消", 0, max(1, target_total), main_window)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)

    def cleanup_progress(current: int, total: int) -> bool:
        if progress.wasCanceled():
            return False
        progress.setMaximum(max(1, total))
        progress.setValue(current + 1)
        QApplication.processEvents()
        return True

    cleanup_result = apply_boundary_cleanup(
        frames=frames,
        model=boundary_model,
        start_index=values["start_index"],
        end_index=values["end_index"],
        training_indices=training_indices,
        skip_existing_saves=values["skip_existing_saves"],
        progress_callback=cleanup_progress,
    )

    recover_result = None
    if values["experimental_recover"]:
        seed_areas = []
        frame_map = {frame.index: frame for frame in frames}
        for index in training_indices:
            seed_frame = frame_map.get(index)
            seed_mask = _load_binary_mask(seed_frame.save_path) if seed_frame else None
            if seed_mask is not None:
                seed_areas.append(int(seed_mask.sum()))
        tiny_threshold = int(max(8, min(seed_areas) * 0.35)) if seed_areas else 24
        recover_targets = _tiny_or_empty_saved_indices(
            frames,
            start_index=values["start_index"],
            end_index=values["end_index"],
            area_threshold=tiny_threshold,
        )

        def recover_progress(current: int, total: int) -> bool:
            if progress.wasCanceled():
                return False
            progress.setLabelText("正在做镜像模板补圈（实验）...")
            progress.setMaximum(max(1, total))
            progress.setValue(current + 1)
            QApplication.processEvents()
            return True

        if recover_targets:
            recover_result = propagate_masks_by_template(
                frames=frames,
                start_index=values["start_index"],
                end_index=values["end_index"],
                seed_indices=training_indices,
                target_indices=recover_targets,
                search_radius=values["search_radius"],
                template_margin=values["template_margin"],
                skip_existing_saves=False,
                allow_generated_masks_as_references=False,
                progress_callback=recover_progress,
            )

    progress.close()
    _refresh_views(main_window)

    message_lines = [
        f"学习帧数: {cleanup_result.training_frame_count}",
        f"学到的边界阳性组件: {cleanup_result.positive_component_count}",
        f"学到的保留组件: {cleanup_result.negative_component_count}",
        f"实际处理帧数: {cleanup_result.processed_frames}",
        f"跳过帧数: {cleanup_result.skipped_frames}",
        f"去除组件数: {cleanup_result.removed_components}",
        f"去除像素数: {cleanup_result.removed_pixels}",
    ]
    if recover_result is not None:
        message_lines.extend(
            [
                "",
                "实验补圈:",
                f"补圈处理帧数: {recover_result.processed_frames}",
                f"补圈跳过帧数: {recover_result.skipped_frames}",
                f"平均匹配分数: {recover_result.average_match_score:.3f}",
            ]
        )
    QMessageBox.information(main_window, "边界阳性处理完成", "\n".join(message_lines))
