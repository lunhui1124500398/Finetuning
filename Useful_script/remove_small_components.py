"""
Remove very small connected components from binary masks.
--------------------------------------------------------
Batch-removes connected components whose area is less than or equal to a
user-specified threshold.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox, QProgressDialog

from core.semi_auto_mask_tools import batch_remove_small_components


SCRIPT_NAME = "去掉特别小的连通分量..."
SCRIPT_DESCRIPTION = "批量去掉面积小于等于指定阈值的连通分量。"


def run(main_window):
    from ui.widgets.script_dialogs import ScriptInputDialog

    model = main_window.model
    save_dir = model.get_path("save_path")
    if not save_dir:
        QMessageBox.warning(main_window, "缺少保存路径", "请先确保当前数据集的 save_path 已设置。")
        return

    show_dialog, auto_files, auto_output = ScriptInputDialog.get_script_config(model, save_dir)
    if show_dialog:
        dialog = ScriptInputDialog(
            script_name=SCRIPT_NAME,
            model=model,
            save_dir=save_dir,
            description="删除每张 Mask 中面积小于等于阈值的连通分量。",
            parent=main_window,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        mask_files = dialog.get_input_files()
        output_dir = dialog.get_output_dir()
    else:
        mask_files = auto_files
        output_dir = auto_output
        if not mask_files:
            QMessageBox.warning(main_window, "无输入文件", "未找到可处理的 Mask 文件。")
            return

    threshold, ok = QInputDialog.getInt(
        main_window,
        "设置连通分量阈值",
        "删除面积小于等于该值的连通分量：",
        value=4,
        min=0,
        max=1_000_000,
        step=1,
    )
    if not ok:
        return

    progress = QProgressDialog("正在去掉小连通分量...", "取消", 0, max(1, len(mask_files)), main_window)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)

    def progress_cb(current: int, total: int) -> bool:
        if progress.wasCanceled():
            return False
        progress.setMaximum(max(1, total))
        progress.setValue(current + 1)
        QApplication.processEvents()
        return True

    result = batch_remove_small_components(
        mask_files=mask_files,
        output_dir=output_dir,
        max_component_area=threshold,
        progress_callback=progress_cb,
        auto_method="remove_small_components",
    )
    progress.close()

    if model.current_index >= 0:
        main_window.canvas.load_image(model.current_index)
        main_window.preview_panel.update_previews(model.current_index)

    QMessageBox.information(
        main_window,
        "处理完成",
        "\n".join(
            [
                f"阈值: <= {threshold}",
                f"实际处理帧数: {result.processed_frames}",
                f"跳过帧数: {result.skipped_frames}",
                f"删除连通分量数: {result.removed_components}",
                f"删除像素数: {result.removed_pixels}",
            ]
        ),
    )
