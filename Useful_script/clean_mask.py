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
    from PyQt6.QtWidgets import QDialog
    from ui.widgets.script_dialogs import ScriptInputDialog
    
    model = main_window.model
    batch_processor = main_window.batch_processor
    
    save_dir = model.get_path('save_path')

    if not save_dir:
        QMessageBox.warning(main_window, "路径未设置", "请确保已设置 Save Path。")
        return

    # 检查是否需要显示对话框
    show_dialog, auto_files, auto_output = ScriptInputDialog.get_script_config(model, save_dir)
    
    if show_dialog:
        # 显示输入源选择对话框
        dialog = ScriptInputDialog(
            script_name=SCRIPT_NAME,
            model=model,
            save_dir=save_dir,
            description="仅保留每张图像中最大的连通分量，去除小噪点。",
            parent=main_window
        )
        
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        
        mask_files = dialog.get_input_files()
        output_dir = dialog.get_output_dir()
    else:
        # 使用配置的默认值，跳过对话框
        mask_files = auto_files
        output_dir = auto_output
        
        if not mask_files:
            QMessageBox.warning(main_window, "无输入文件", "未找到可处理的 Mask 文件。")
            return

    count = len(mask_files)

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
    processed = batch_processor.run_clean_masks(mask_files, output_dir, progress_cb)
    
    progress.setValue(count)
    
    # 刷新界面
    if model.load_from_save_path:
        main_window.canvas.load_image(model.current_index)
        main_window.preview_panel.update_previews(model.current_index)

    QMessageBox.information(main_window, "完成", f"已清洗 {processed} 张 Mask。")
