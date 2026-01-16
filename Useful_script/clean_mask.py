"""
清洗 Mask (保留最大连通分量)
-----------------------------
批量处理 Mask 图像，仅保留每张图中最大的连通分量，去除噪点。
"""

from PyQt6.QtWidgets import QMessageBox, QProgressDialog, QApplication
from PyQt6.QtCore import Qt

# --- Script Metadata ---
SCRIPT_NAME = "清洗 Mask (保留最大连通分量)"
SCRIPT_DESCRIPTION = "批量处理 Mask，仅保留最大连通分量"


def run(main_window):
    """
    Entry point for the script.
    
    Args:
        main_window: MainWindow instance, provides access to model, batch_processor, etc.
    """
    model = main_window.model
    batch_processor = main_window.batch_processor
    
    mask_files = model._mask_files
    save_dir = model.get_path('save_path')

    if not mask_files or not save_dir:
        QMessageBox.warning(main_window, "路径未设置", "请确保已加载 Mask 路径且设置了 Save Path。")
        return

    count = len(mask_files)
    reply = QMessageBox.question(
        main_window, 
        "批量处理确认", 
        f"即将处理 {count} 张图像，结果将覆盖保存路径中的文件。\n是否继续？",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    if reply != QMessageBox.StandardButton.Yes:
        return

    # 进度条
    progress = QProgressDialog("正在清洗 Mask...", "取消", 0, count, main_window)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)

    def progress_cb(current, total):
        if progress.wasCanceled():
            return False
        progress.setValue(current + 1)
        QApplication.processEvents()
        return True

    # 调用核心逻辑
    processed = batch_processor.run_clean_masks(mask_files, save_dir, progress_cb)
    
    progress.setValue(count)
    
    # 刷新界面
    if model.load_from_save_path:
        main_window.canvas.load_image(model.current_index)
        main_window.preview_panel.update_previews(model.current_index)

    QMessageBox.information(main_window, "完成", f"已清洗 {processed} 张 Mask。")
