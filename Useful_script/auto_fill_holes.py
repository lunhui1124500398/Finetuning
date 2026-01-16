"""
批量填洞 (Batch Fill Holes)
----------------------------
批量处理 Mask 图像，填充每张图中的内部孔洞。
使用形态学方法 (scipy.ndimage.binary_fill_holes)，不会创建新的外部轮廓。
"""

import os
import cv2
import numpy as np
try:
    from scipy import ndimage
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

from PyQt6.QtWidgets import QMessageBox, QProgressDialog, QApplication
from PyQt6.QtCore import Qt

# --- Script Metadata ---
SCRIPT_NAME = "批量填洞 (Fill Holes)"
SCRIPT_DESCRIPTION = "批量填补 Mask 图像中的内部孔洞 (形态学方法)"


def fill_holes_in_image(image_path: str) -> np.ndarray:
    """
    读取单张图像，使用形态学方法填充孔洞，返回处理后的 numpy 数组。
    """
    if not HAS_SCIPY:
        print("Scipy not found, skipping hole filling.")
        return None

    # 读取为灰度图
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    
    # 二值化
    _, binary = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
    
    # 转换为 bool 类型用于形态学操作
    binary_bool = binary > 0
    
    # 使用形态学填洞
    filled_bool = ndimage.binary_fill_holes(binary_bool)
    
    # 转回 uint8
    filled = (filled_bool.astype(np.uint8)) * 255
    
    return filled


def run(main_window):
    """
    Entry point for the script.
    
    Args:
        main_window: MainWindow instance.
    """
    from PyQt6.QtWidgets import QDialog
    from ui.widgets.script_dialogs import ScriptInputDialog
    
    model = main_window.model
    
    # 获取保存路径
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
            description="使用形态学方法填补 Mask 中的内部孔洞，不会改变外部轮廓。",
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
    progress = QProgressDialog("正在批量填洞...", "取消", 0, count, main_window)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)

    processed = 0
    for i, mask_path in enumerate(mask_files):
        if progress.wasCanceled():
            break
        
        # 处理图像
        filled = fill_holes_in_image(mask_path)
        if filled is None:
            continue
        
        # 保存到 output_dir，保持原文件名
        filename = os.path.basename(mask_path)
        save_path = os.path.join(output_dir, filename)
        cv2.imwrite(save_path, filled)
        processed += 1
        
        progress.setValue(i + 1)
        QApplication.processEvents()

    progress.setValue(count)
    
    # 刷新界面
    if model.load_from_save_path:
        main_window.canvas.load_image(model.current_index)
        main_window.preview_panel.update_previews(model.current_index)

    QMessageBox.information(main_window, "完成", f"已填洞处理 {processed} 张 Mask 图像。")


