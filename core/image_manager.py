import os
import cv2
import numpy as np
from PIL import Image, ImageQt
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPen
from PyQt6.QtCore import Qt

class ImageManager:
    """处理所有图像加载、处理、保存等任务。"""

    @staticmethod
    def get_image_files(directory):
        if not directory or not os.path.isdir(directory):
            return []
        supported_formats = ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff')
        return sorted([os.path.join(directory, f) for f in os.listdir(directory) if f.lower().endswith(supported_formats)])

    @staticmethod
    def load_pixmap(file_path):
        if not file_path or not os.path.exists(file_path):
            return None
        # 使用 Pillow 加载，以支持更多格式, 然后转换为 QPixmap
        try:
            image = Image.open(file_path)
            if image.mode != "RGBA":
                image = image.convert("RGBA")
            qimage = ImageQt.ImageQt(image)
            return QPixmap.fromImage(qimage)
        except Exception as e:
            print(f"Error loading image {file_path}: {e}")
            return None
    
    @staticmethod
    def save_pixmap(pixmap, file_path):
        if not pixmap or not file_path:
            return
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        pixmap.save(file_path, 'PNG')

    @staticmethod
    def create_overlay_pixmap(original_pixmap, mask_pixmap, style, color_rgba, contour_thickness=2):
        if not original_pixmap or not mask_pixmap:
            return original_pixmap or QPixmap()

        # 创建一个可绘制的副本
        output_pixmap = original_pixmap.copy()
        
        painter = QPainter(output_pixmap)
        
        if style == 'overlay':
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            temp_mask = mask_pixmap.copy()
            mask_color = QColor(*color_rgba)
            
            # 创建一个纯色图层，然后用二值化mask作为它的蒙版
            color_layer = QPixmap(temp_mask.size())
            color_layer.fill(mask_color)
            color_layer.setMask(temp_mask.createMaskFromColor(Qt.GlobalColor.black, Qt.MaskMode.MaskOutColor))
            
            painter.drawPixmap(0, 0, color_layer)

        elif style == 'contour':
            # 将 QPixmap 转换为 OpenCV 格式
            qimage = mask_pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
            ptr = qimage.bits()
            ptr.setsize(qimage.sizeInBytes())
            arr = np.array(ptr).reshape(qimage.height(), qimage.width())

            contours, _ = cv2.findContours(arr, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            pen = QPen(QColor(*color_rgba[:3]), contour_thickness)
            painter.setPen(pen)
            for contour in contours:
                for i in range(len(contour)):
                    p1 = contour[i][0]
                    p2 = contour[(i + 1) % len(contour)][0]
                    painter.drawLine(int(p1[0]), int(p1[1]), int(p2[0]), int(p2[1]))

        painter.end()
        return output_pixmap