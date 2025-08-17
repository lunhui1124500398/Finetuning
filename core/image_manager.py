import os
import cv2
import numpy as np
from PIL import Image, ImageQt
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QBitmap
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
    
    # --- START: B3. 新增高对比度方法 ---
    @staticmethod
    def apply_clahe(pixmap: QPixmap) -> QPixmap:
        if not pixmap or pixmap.isNull():
            return pixmap

        # QPixmap -> QImage -> numpy array
        qimage = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
        width = qimage.width()
        height = qimage.height()
        ptr = qimage.bits()
        ptr.setsize(qimage.sizeInBytes())
        arr = np.array(ptr).reshape(height, width, 3)

        # 转换为灰度图进行处理
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        
        # 应用CLAHE
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced_gray = clahe.apply(gray)
        
        # 将处理后的灰度图转回三通道，以便显示
        enhanced_rgb = cv2.cvtColor(enhanced_gray, cv2.COLOR_GRAY2RGB)

        # numpy array -> QImage -> QPixmap
        h, w, ch = enhanced_rgb.shape
        bytes_per_line = ch * w
        enhanced_qimage = QImage(enhanced_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        
        return QPixmap.fromImage(enhanced_qimage)
    # --- END: B3 ---

    @staticmethod
    def save_pixmap(pixmap, file_path):
        if not pixmap or not file_path:
            return
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        pixmap.save(file_path, 'PNG')

    @staticmethod
    def create_overlay_pixmap(original_pixmap, mask_pixmap, style, color_rgba, contour_thickness=2, invert=False, inner_contour_color_rgba=None):
        if not original_pixmap or not mask_pixmap:
            return original_pixmap or QPixmap()

        output_pixmap = original_pixmap.copy()
        painter = QPainter(output_pixmap)

        # 步骤1: 获取用于操作的二值化图像 (QImage)
        mask_image = mask_pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)

        # (新增) 处理反相逻辑
        if invert:
            mask_image.invertPixels()

        if style == 'area':
            # 创建一个纯色图层
            color_layer = QPixmap(mask_pixmap.size())
            color_layer.fill(QColor(*color_rgba))

            # 使用处理后(可能已反相)的mask_image作为蒙版
            color_layer.setMask(QBitmap.fromImage(mask_image))

            painter.drawPixmap(0, 0, color_layer)

        elif style == 'contour':
            # 将 QImage 转换为 OpenCV 格式
            ptr = mask_image.bits()
            ptr.setsize(mask_image.sizeInBytes())
            arr = np.array(ptr).reshape(mask_image.height(), mask_image.width())

            # (修改) 使用 RETR_TREE 来获取所有轮廓和层级
            contours, hierarchy = cv2.findContours(arr, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            if not hierarchy is None:
                hierarchy = hierarchy[0] # 简化层级数组
                for i, contour in enumerate(contours):
                    # 判断是外轮廓还是内轮廓(空洞)
                    # hierarchy[i][3] == -1 表示是顶层轮廓(外轮廓)
                    is_hole = hierarchy[i][3] != -1

                    if is_hole and inner_contour_color_rgba:
                        pen_color = QColor(*inner_contour_color_rgba)
                    else:
                        pen_color = QColor(*color_rgba)

                    pen = QPen(pen_color, contour_thickness)
                    painter.setPen(pen)

                    # OpenCV的轮廓可以直接绘制为QPolygonF
                    from PyQt6.QtGui import QPolygonF
                    from PyQt6.QtCore import QPointF
                    polygon = QPolygonF([QPointF(p[0][0], p[0][1]) for p in contour])
                    painter.drawPolyline(polygon)

        painter.end()
        return output_pixmap
    
    # --- START: 新增方法 (解决问题 #8) ---
    @staticmethod
    def create_filled_mask(pixmap: QPixmap) -> QPixmap:
        """
        接收一个包含轮廓线条的pixmap，返回一个填充了这些轮廓的二值化pixmap。
        """
        if not pixmap or pixmap.isNull():
            return pixmap

        # QPixmap -> QImage -> numpy array (grayscale)
        qimage = pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
        ptr = qimage.bits()
        ptr.setsize(qimage.sizeInBytes())
        arr = np.array(ptr).reshape(qimage.height(), qimage.width())

        # 寻找最外层的轮廓
        contours, _ = cv2.findContours(arr, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # 创建一个纯黑的背景
        filled_arr = np.zeros_like(arr)

        # 在黑色背景上绘制填充后的轮廓
        # thickness=cv2.FILLED 表示填充
        cv2.drawContours(filled_arr, contours, -1, (255), thickness=cv2.FILLED)

        # numpy array -> QImage -> QPixmap
        h, w = filled_arr.shape
        bytes_per_line = w
        filled_qimage = QImage(filled_arr.data, w, h, bytes_per_line, QImage.Format.Format_Grayscale8)
        
        # 转换为RGBA格式以确保兼容性
        final_pixmap = QPixmap.fromImage(filled_qimage.convertToFormat(QImage.Format.Format_RGBA8888))
        return final_pixmap
    # --- END: 新增方法 ---