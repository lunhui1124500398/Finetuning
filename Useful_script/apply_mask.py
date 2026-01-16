"""
应用 Mask (图像抠取)
---------------------
批量将 Mask 应用到图像上，生成透明背景的抠图结果。
"""

import os
from PyQt6.QtWidgets import QMessageBox, QProgressDialog, QApplication, QDialog
from PyQt6.QtCore import Qt

# --- Script Metadata ---
SCRIPT_NAME = "应用 Mask (图像抠取)..."
SCRIPT_DESCRIPTION = "批量将 Mask 应用到原图，生成抠图结果"


def run(main_window):
    """
    Entry point for the script.
    
    Args:
        main_window: MainWindow instance.
    """
    from ui.widgets.script_dialogs import ApplyMaskScriptDialog
    from core.image_manager import ImageManager
    
    model = main_window.model
    batch_processor = main_window.batch_processor

    # 1. 准备默认路径
    default_mask = model.get_path('save_path') or model.get_path('mask_path')
    default_img = model.get_path('original_path')
    default_save = os.path.join(default_img, "masked_output") if default_img else ""

    # 2. 弹出配置对话框
    dialog = ApplyMaskScriptDialog(default_mask, default_img, default_save, main_window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    # 3. 获取配置
    mask_path, img_path, save_path = dialog.get_paths()
    
    # 确保保存目录存在
    if not os.path.exists(save_path):
        try:
            os.makedirs(save_path)
        except OSError as e:
            QMessageBox.critical(main_window, "错误", f"无法创建保存目录:\n{e}")
            return

    # 4. 准备进度条
    total_files = len(ImageManager.get_image_files(mask_path))
    
    progress = QProgressDialog("正在批量抠图...", "取消", 0, total_files, main_window)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    
    def progress_cb(current, total):
        if progress.wasCanceled():
            return False
        progress.setValue(current + 1)
        QApplication.processEvents()
        return True

    # 5. 调用核心逻辑
    processed = batch_processor.run_apply_mask_to_images(
        mask_path, img_path, save_path, progress_cb
    )
    
    progress.setValue(total_files)
    QMessageBox.information(
        main_window, 
        "完成", 
        f"处理完成！\n共生成 {processed} 张抠图结果。\n保存在: {save_path}"
    )
