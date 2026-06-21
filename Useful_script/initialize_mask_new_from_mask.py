"""
Initialize mask_new by copying mask_path into save_path.
-------------------------------------------------------
This saves users from manually dragging masks into mask_new before starting
refinement on a new dataset.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QVBoxLayout,
)

from core.semi_auto_mask_tools import build_frame_paths, initialize_saved_masks_from_sources


SCRIPT_NAME = "初始化: 复制 mask → 保存路径..."
SCRIPT_ORDER = 30
SCRIPT_DESCRIPTION = "把当前数据集的 mask_path 批量复制到 save_path（mask_new），便于直接开始精修。"


class InitializeMaskNewDialog(QDialog):
    def __init__(self, frame_count: int, existing_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("初始化 mask_new")
        self.setMinimumWidth(520)

        summary = QLabel(
            "这个脚本会把当前数据集的 mask_path 批量复制到 save_path（mask_new）。"
            "\n适合第一次开始精修前做初始化。"
            f"\n当前总帧数: {frame_count}"
            f"\nsave_path 中已存在结果: {existing_count}"
        )
        summary.setWordWrap(True)

        self.skip_existing_checkbox = QCheckBox("跳过已经存在的 mask_new（推荐）")
        self.skip_existing_checkbox.setChecked(True)

        note = QLabel(
            "开启时只补齐缺失的 mask_new，不会覆盖已经手工修过的结果。"
            "\n关闭时会用 mask_path 重新覆盖同名的 mask_new。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(self.skip_existing_checkbox)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def overwrite_existing(self) -> bool:
        return not self.skip_existing_checkbox.isChecked()


def run(main_window):
    model = main_window.model
    mask_dir = model.get_path("mask_path")
    save_dir = model.get_path("save_path")
    if not mask_dir:
        QMessageBox.warning(main_window, "缺少 Mask 路径", "请先加载当前数据集，并确保 mask_path 指向原始二值 Mask。")
        return
    if not save_dir:
        QMessageBox.warning(main_window, "缺少保存路径", "请先加载当前数据集，并确保 save_path 指向 mask_new。")
        return

    frames = build_frame_paths(model._original_files, model._mask_files, save_dir)
    if not frames:
        QMessageBox.warning(main_window, "没有图像", "当前数据集没有可初始化的帧。")
        return

    available_mask_frames = [frame for frame in frames if frame.has_original_mask]
    if not available_mask_frames:
        QMessageBox.warning(main_window, "没有原始 Mask", "mask_path 下没有找到和当前数据集匹配的 Mask 文件。")
        return

    existing_count = sum(1 for frame in frames if frame.has_saved_mask)
    dialog = InitializeMaskNewDialog(
        frame_count=len(frames),
        existing_count=existing_count,
        parent=main_window,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    overwrite_existing = dialog.overwrite_existing()
    if overwrite_existing:
        confirm_text = "这会用 mask_path 覆盖当前 save_path 中的同名 mask_new。是否继续？"
    else:
        confirm_text = "这会把缺失的 mask_new 从 mask_path 补齐，不会覆盖现有结果。是否继续？"
    if QMessageBox.question(
        main_window,
        "确认初始化",
        confirm_text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    ) != QMessageBox.StandardButton.Yes:
        return

    progress = QProgressDialog("正在初始化 mask_new...", "取消", 0, max(1, len(frames)), main_window)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)

    def progress_cb(current: int, total: int) -> bool:
        if progress.wasCanceled():
            return False
        progress.setMaximum(max(1, total))
        progress.setValue(current + 1)
        QApplication.processEvents()
        return True

    result = initialize_saved_masks_from_sources(
        frames=frames,
        overwrite_existing=overwrite_existing,
        progress_callback=progress_cb,
    )
    progress.close()

    if model.current_index >= 0:
        main_window.canvas.load_image(model.current_index)
        main_window.preview_panel.update_previews(model.current_index)
    if hasattr(main_window, "refresh_seed_cache"):
        main_window.refresh_seed_cache()
    if hasattr(main_window, "update_seed_status_label"):
        main_window.update_seed_status_label()

    mode_text = "覆盖初始化" if overwrite_existing else "补齐初始化"
    QMessageBox.information(
        main_window,
        "初始化完成",
        "\n".join(
            [
                f"模式: {mode_text}",
                f"成功写入: {result.copied_frames}",
                f"其中覆盖: {result.overwritten_frames if overwrite_existing else 0}",
                f"跳过已有: {result.skipped_existing_frames}",
                f"缺少原始 Mask: {result.missing_source_frames}",
                f"保存路径: {save_dir}",
            ]
        ),
    )
