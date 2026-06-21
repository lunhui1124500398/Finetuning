from __future__ import annotations

"""
Clear saved mask results after a chosen frame.
---------------------------------------------
Clears all connected components in mask_new after the specified frame by
writing empty masks, without mixing this action into seed management.
"""

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QMessageBox, QSpinBox, QVBoxLayout

from core.semi_auto_mask_tools import build_frame_paths, clear_saved_results_after_index


SCRIPT_NAME = "清空某帧之后的结果..."
SCRIPT_DESCRIPTION = "保留指定帧本身，并将它之后的全部 mask_new 清空为空白 mask。"


class ClearAfterFrameDialog(QDialog):
    def __init__(self, total_frames: int, current_index: int, current_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("清空某帧之后的结果")
        self.setMinimumWidth(520)

        self.anchor_spin = QSpinBox()
        self.anchor_spin.setRange(1, max(1, total_frames))
        self.anchor_spin.setValue(max(1, current_index + 1))

        summary = QLabel(
            "会保留你指定的那一帧本身，并将它之后的所有 mask_new 清空为空白 mask。"
            f"\n当前帧: {current_name or 'N/A'}"
        )
        summary.setWordWrap(True)

        note = QLabel("这个操作不会修改原始 mask_path，只会把 save_path（mask_new）中的后续结果清空为全黑空白 mask。")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")

        form = QFormLayout()
        form.addRow("保留到帧:", self.anchor_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def get_anchor_index(self) -> int:
        return self.anchor_spin.value() - 1


def run(main_window):
    model = main_window.model
    save_dir = model.get_path("save_path")
    if not save_dir:
        QMessageBox.warning(main_window, "缺少保存路径", "请先加载当前数据集，并确保 save_path 指向 mask_new。")
        return

    frames = build_frame_paths(model._original_files, model._mask_files, save_dir)
    if not frames:
        QMessageBox.warning(main_window, "没有图像", "当前数据集没有可处理的帧。")
        return

    current_name = ""
    if 0 <= model.current_index < len(frames):
        current_name = frames[model.current_index].frame_name

    dialog = ClearAfterFrameDialog(
        total_frames=len(frames),
        current_index=max(0, model.current_index),
        current_name=current_name,
        parent=main_window,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    anchor_index = dialog.get_anchor_index()
    anchor_name = frames[anchor_index].frame_name
    if QMessageBox.question(
        main_window,
        "确认清空",
        f"将保留 {anchor_name}，并把它之后的所有 mask_new 清空为空白 mask。是否继续？",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    ) != QMessageBox.StandardButton.Yes:
        return

    result = clear_saved_results_after_index(frames, anchor_index, include_anchor=False)

    if model.current_index >= 0:
        main_window.canvas.load_image(model.current_index)
        main_window.preview_panel.update_previews(model.current_index)
    if hasattr(main_window, "refresh_seed_cache"):
        main_window.refresh_seed_cache()
    if hasattr(main_window, "update_seed_status_label"):
        main_window.update_seed_status_label()

    QMessageBox.information(
        main_window,
        "清空完成",
        (
            f"已清空 {result['cleared_files']} 张后续 mask。"
            f"\n更新元数据: {result['updated_metadata']} 条"
            f"\n跳过帧数: {result['skipped_frames']}"
        ),
    )
