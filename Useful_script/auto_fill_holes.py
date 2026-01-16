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
    from core.image_manager import ImageManager
    
    model = main_window.model
    
    # 获取 Mask 文件列表和保存路径
    mask_files = model._mask_files
    save_dir = model.get_path('save_path')

    if not mask_files or not save_dir:
        QMessageBox.warning(main_window, "路径未设置", "请确保已加载 Mask 路径且设置了 Save Path。")
        return

    count = len(mask_files)
    reply = QMessageBox.question(
        main_window, 
        "批量处理确认", 
        f"即将对 {count} 张 Mask 图像进行填洞处理。\n结果将保存到: {save_dir}\n是否继续？",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    if reply != QMessageBox.StandardButton.Yes:
        return

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
        
        # 保存到 save_dir，保持原文件名
        filename = os.path.basename(mask_path)
        save_path = os.path.join(save_dir, filename)
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


