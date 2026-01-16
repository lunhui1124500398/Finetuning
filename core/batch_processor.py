# File: core/batch_processor.py

import os
import cv2
import numpy as np
from PyQt6.QtGui import QPixmap, QImage
from .image_manager import ImageManager
from PyQt6.QtCore import Qt

class BatchProcessor:
    """
    负责处理所有批量脚本的核心逻辑。
    该类不包含任何 UI 代码，通过 callback 回调函数汇报进度。
    """
    
    def __init__(self):
        self.image_manager = ImageManager()

    def run_clean_masks(self, mask_files, save_dir, progress_callback=None):
        """
        批量清洗 Mask (保留最大连通分量)。
        :param mask_files: Mask 文件路径列表
        :param save_dir: 保存目录
        :param progress_callback: 回调函数 func(current_index, total) -> bool (返回 False 停止)
        """
        total = len(mask_files)
        processed_count = 0
        
        for i, file_path in enumerate(mask_files):
            # 检查取消
            if progress_callback and progress_callback(i, total) is False:
                break

            pixmap = self.image_manager.load_pixmap(file_path)
            if not pixmap or pixmap.isNull():
                continue

            # 核心算法
            cleaned_pixmap = self.image_manager.keep_largest_component(pixmap)

            # 保存
            file_name = os.path.basename(file_path)
            name_no_ext = os.path.splitext(file_name)[0]
            save_full_path = os.path.join(save_dir, name_no_ext + ".png")
            self.image_manager.save_pixmap(cleaned_pixmap, save_full_path)
            
            processed_count += 1
            
        return processed_count

    def run_apply_mask_to_images(self, mask_dir, image_dir, save_dir, progress_callback=None):
        """
        批量应用 Mask 到原图 (抠图)。
        :param mask_dir: Mask 所在目录
        :param image_dir: 原图所在目录
        :param save_dir: 保存目录
        """
        # 获取文件列表
        mask_files = self.image_manager.get_image_files(mask_dir)
        # 我们以 Mask 为基准去寻找对应的原图
        total = len(mask_files)
        processed_count = 0
        
        # 建立原图的索引 (文件名无后缀 -> 完整路径) 以便快速查找
        image_files = self.image_manager.get_image_files(image_dir)
        image_map = {os.path.splitext(os.path.basename(f))[0]: f for f in image_files}

        for i, mask_path in enumerate(mask_files):
            if progress_callback and progress_callback(i, total) is False:
                break
            
            # 1. 解析文件名
            mask_filename = os.path.basename(mask_path)
            name_key = os.path.splitext(mask_filename)[0]
            
            # 2. 查找对应的原图
            image_path = image_map.get(name_key)
            if not image_path:
                print(f"Skipping {name_key}: No corresponding original image found.")
                continue
                
            # 3. 加载图片
            mask_pixmap = self.image_manager.load_pixmap(mask_path)
            orig_pixmap = self.image_manager.load_pixmap(image_path)
            
            if not mask_pixmap or not orig_pixmap:
                continue

            # 4. 执行抠图操作 (应用 Alpha 通道)
            result_pixmap = self._apply_alpha_mask(orig_pixmap, mask_pixmap)
            
            # 5. 保存
            save_full_path = os.path.join(save_dir, name_key + ".png") # 强制存为 PNG 以保留透明通道
            self.image_manager.save_pixmap(result_pixmap, save_full_path)
            
            processed_count += 1
            
        return processed_count

    def _apply_alpha_mask(self, image_pixmap: QPixmap, mask_pixmap: QPixmap) -> QPixmap:
        """
        将 mask 应用为 image 的 Alpha 通道。
        会自动处理尺寸不匹配的问题 (resize mask to fit image)。
        """
        # 转为 Image
        img_qimage = image_pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        mask_qimage = mask_pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)

        w, h = img_qimage.width(), img_qimage.height()
        
        # 如果尺寸不一致，缩放 Mask
        if mask_qimage.size() != img_qimage.size():
            mask_qimage = mask_qimage.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)

        # 转换为 Numpy 处理 (效率最高)
        # 1. 提取原图 (RGBA)
        ptr_img = img_qimage.bits()
        ptr_img.setsize(img_qimage.sizeInBytes())
        arr_img = np.array(ptr_img).reshape(h, w, 4).copy()

        # 2. 提取 Mask (Gray)
        ptr_mask = mask_qimage.bits()
        ptr_mask.setsize(mask_qimage.sizeInBytes())
        # QImage 内存对齐可能导致 bytesPerLine > width
        bpl = mask_qimage.bytesPerLine()
        arr_mask = np.array(ptr_mask).reshape(h, bpl)[:, :w].copy()
        
        # 3. 二值化 Mask (确保非黑即白，或者保留灰度做软边缘均可，这里做二值化处理比较干净)
        # 如果需要边缘平滑，可以注释掉下面这行
        _, arr_mask = cv2.threshold(arr_mask, 127, 255, cv2.THRESH_BINARY)
        
        # 4. 将 Mask 赋值给原图的 Alpha 通道 (通道索引 3)
        # 注意：Mask 中白色(255)为保留，黑色(0)为透明。如果你的逻辑相反，这里需要反转。
        arr_img[:, :, 3] = arr_mask

        # 5. 转回 QPixmap
        result_qimage = QImage(arr_img.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
        return QPixmap.fromImage(result_qimage.copy())

    