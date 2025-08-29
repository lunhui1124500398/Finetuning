import os
import cv2
import numpy as np
from PIL import Image, ImageQt
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QBitmap, QPainterPath, QPolygonF
from PyQt6.QtCore import Qt, QPointF
from Finetuning.utils.debugger import debugger

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
    
    # --- START: 新增方法，用于将轮廓图转换为路径 ---
    @staticmethod
    def convert_mask_to_path(mask_pixmap: QPixmap) -> QPainterPath:
        """将包含轮廓的二值图QPixmap转换为QPainterPath"""
        path = QPainterPath()
        if not mask_pixmap or mask_pixmap.isNull():
            return path
        
        mask_image = mask_pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
        
        ptr = mask_image.bits()
        ptr.setsize(mask_image.sizeInBytes())
        arr = np.array(ptr).reshape(mask_image.height(), mask_image.width())

        # 阈值处理，确保是二值图像
        _, binary_arr = cv2.threshold(arr, 127, 255, cv2.THRESH_BINARY)
        
        # 寻找所有轮廓
        contours, _ = cv2.findContours(binary_arr, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        for contour in contours:
            polygon = QPolygonF([QPointF(p[0][0], p[0][1]) for p in contour])
            path.addPolygon(polygon)
            
        return path
    # --- END: 新增方法 ---

    # @staticmethod [注释是因为该代码画出的轮廓看起来不连续，也不知道为什么]
    # def create_overlay_pixmap(original_pixmap, mask_pixmap, style, color_rgba, contour_thickness=2, invert=False, inner_contour_color_rgba=None):
    #     if not original_pixmap or not mask_pixmap:
    #         return original_pixmap or QPixmap()

    #     output_pixmap = original_pixmap.copy()
    #     painter = QPainter(output_pixmap)

    #     # 步骤1: 获取用于操作的二值化图像 (QImage)
    #     mask_image = mask_pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)

    #     # (新增) 处理反相逻辑
    #     if invert:
    #         mask_image.invertPixels()

    #     if style == 'area':
    #         # 创建一个纯色图层
    #         color_layer = QPixmap(mask_pixmap.size())
    #         color_layer.fill(QColor(*color_rgba))

    #         # 使用处理后(可能已反相)的mask_image作为蒙版
    #         color_layer.setMask(QBitmap.fromImage(mask_image))

    #         painter.drawPixmap(0, 0, color_layer)

    #     elif style == 'contour':
    #         # 将 QImage 转换为 OpenCV 格式
    #         ptr = mask_image.bits()
    #         ptr.setsize(mask_image.sizeInBytes())
    #         arr = np.array(ptr).reshape(mask_image.height(), mask_image.width())

    #         # 【问题 #2 解决方案】 使用 RETR_TREE 来获取所有轮廓和层级
    #         contours, hierarchy = cv2.findContours(arr, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    #         if not hierarchy is None:
    #             hierarchy = hierarchy[0] # 简化层级数组
    #             for i, contour in enumerate(contours):
    #                 # 判断是外轮廓还是内轮廓(空洞)
    #                 # hierarchy[i][3] == -1 表示是顶层轮廓(外轮廓)
    #                 is_hole = hierarchy[i][3] != -1

    #                 if is_hole and inner_contour_color_rgba:
    #                     pen_color = QColor(*inner_contour_color_rgba)
    #                 else:
    #                     pen_color = QColor(*color_rgba)

    #                 pen = QPen(pen_color, contour_thickness)
    #                 painter.setPen(pen)

    #                 # OpenCV的轮廓可以直接绘制为QPolygonF
    #                 from PyQt6.QtGui import QPolygonF
    #                 from PyQt6.QtCore import QPointF
    #                 polygon = QPolygonF([QPointF(p[0][0], p[0][1]) for p in contour])
    #                 painter.drawPolygon(polygon)

    #     painter.end()
    #     return output_pixmap

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
            # 1. 将 QImage 转换为 OpenCV 格式 (numpy array)
            ptr = mask_image.bits()
            ptr.setsize(mask_image.sizeInBytes())
            # arr 是单通道灰度图
            arr = np.array(ptr).reshape(mask_image.height(), mask_image.width())

            # 2. 查找轮廓
            contours, hierarchy = cv2.findContours(arr, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

            debugger.log(f"In ImageManager: Found {len(contours)} contours.")
            if contours:
                # 3. 创建一个与原图等大的4通道透明画布 (BGRA格式)
                #    注意：高度和宽度从 arr.shape 获取
                h, w = arr.shape
                contour_overlay_np = np.zeros((h, w, 4), dtype=np.uint8)

                # 4. 在透明画布上使用 cv2.drawContours 绘制轮廓
                #    OpenCV 颜色是 BGR(A) 顺序，而 color_rgba 是 RGB(A)
                pen_color_bgr = (color_rgba[2], color_rgba[1], color_rgba[0], color_rgba[3])
                
                # 【关键】使用 cv2.drawContours，它能保证轮廓闭合
                cv2.drawContours(contour_overlay_np, contours, -1, pen_color_bgr, contour_thickness)
                debugger.save_image(contour_overlay_np, "2_opencv_drawn_overlay")

                # 5. 将绘制好的 numpy 数组转换回 QPixmap
                #    注意：QImage 需要 BGRA -> ARGB 的转换，但 Format_ARGB32 能正确处理
                bytes_per_line = 4 * w
                q_image = QImage(contour_overlay_np.data, w, h, bytes_per_line, QImage.Format.Format_ARGB32)
                contour_pixmap = QPixmap.fromImage(q_image)

                # 6. 将这个包含轮廓的 pixmap 叠加到主画布上
                painter.drawPixmap(0, 0, contour_pixmap)

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

    # 实现选区像素级精确对齐的关键方法
    @staticmethod
    def snap_path_to_pixels(path: QPainterPath, image_size) -> QPainterPath:
        """
        通过栅格化后再提取轮廓，将矢量路径对齐到像素网格。
        这是实现选区像素级精确的关键。

        Args:
            path: 原始的、平滑的 QPainterPath。
            image_size: 目标图像的尺寸 (QSize)。

        Returns:
            一个新的、与像素边界对齐的 QPainterPath。
        """
        if path.isEmpty() or image_size.isEmpty():
            return QPainterPath()

        # 步骤1: 将矢量路径栅格化到一个二值 QImage 上
        # 抗锯齿(Antialiasing)可以使栅格化结果更平滑，更符合用户直觉
        mask_image = QImage(image_size, QImage.Format.Format_Grayscale8)
        mask_image.fill(Qt.GlobalColor.black)

        painter = QPainter(mask_image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.GlobalColor.white)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)
        painter.end()

        # 步骤2: 将 QImage 转换为 Numpy 数组，以便 OpenCV 处理
        ptr = mask_image.bits()
        ptr.setsize(mask_image.sizeInBytes())
        arr = np.array(ptr).reshape(mask_image.height(), mask_image.width())

        # 步骤3: 使用 OpenCV 查找轮廓
        # cv2.CHAIN_APPROX_NONE 保证获取边界上的每一个像素点，确保精度
        contours, _ = cv2.findContours(arr, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)

        # 步骤4: 将 OpenCV 轮廓转换回新的 QPainterPath
        snapped_path = QPainterPath()
        for contour in contours:
            polygon = QPolygonF([QPointF(p[0][0], p[0][1]) for p in contour])
            snapped_path.addPolygon(polygon)
            snapped_path.closeSubpath() # 确保每个轮廓都是闭合的

        return snapped_path
    
    # @staticmethod
    # def process_selection_path(path: QPainterPath, image_size) -> tuple[bool, QPainterPath]:
    #     """
    #     栅格化路径，验证其是否覆盖任何像素超过50%，然后生成对齐到像素网格的新路径。
    #     """
    #     # 导入调试器
    #     from Finetuning.utils.debugger import debugger
        
    #     debugger.log("--- Starting process_selection_path ---")

    #     if path.isEmpty() or image_size.isEmpty():
    #         return (False, QPainterPath())

    #     # 步骤1: 栅格化为带抗锯齿的灰度图
    #     mask_image = QImage(image_size, QImage.Format.Format_Grayscale8)
    #     mask_image.fill(Qt.GlobalColor.black)
    #     painter = QPainter(mask_image)
    #     painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    #     painter.setBrush(Qt.GlobalColor.white)
    #     painter.setPen(Qt.PenStyle.NoPen)
    #     painter.drawPath(path)
    #     painter.end()

    #     # 步骤2: 转换为 Numpy 数组
    #     ptr = mask_image.bits()
    #     ptr.setsize(mask_image.sizeInBytes())
    #     arr = np.array(ptr).reshape(mask_image.height(), mask_image.width())

    #     # 【调试点 A】: 保存栅格化后的灰度图
    #     # 这是最关键的一步，它显示了每个像素被覆盖的真实程度。
    #     debugger.save_image(arr, "debug_1_grayscale_rasterized")

    #     # 步骤3: 验证覆盖率
    #     if not np.any(arr > 127):
    #         debugger.log("Validation failed: No pixel covered more than 50%.")
    #         return (False, QPainterPath())

    #     # 步骤4: 阈值化为二值图
    #     _, binary_arr = cv2.threshold(arr, 127, 255, cv2.THRESH_BINARY)
        
    #     # 【调试点 B】: 保存阈值化后的二值图
    #     # 这张图应该只包含纯黑和纯白，显示了哪些像素被最终选中。
    #     debugger.save_image(binary_arr, "debug_2_binary_after_threshold")

    #     # 步骤5: 查找轮廓
    #     contours, _ = cv2.findContours(binary_arr, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        
    #     # 【调试点 C】: 打印轮廓信息
    #     # 看看我们找到了什么形状。
    #     debugger.log(f"Found {len(contours)} contours.")
    #     if contours:
    #         # 只打印第一个轮廓的顶点数量和前5个点
    #         debugger.log(f"Contour 0 has {len(contours[0])} vertices.")
    #         debugger.log(f"First 5 points: {contours[0][:5].ravel()}")


    #     # 步骤6: 转换回 QPainterPath
    #     snapped_path = QPainterPath()
    #     for contour in contours:
    #         polygon = QPolygonF([QPointF(p[0][0], p[0][1]) for p in contour])
    #         snapped_path.addPolygon(polygon)
    #         snapped_path.closeSubpath()
            
    #     debugger.log("--- Finished process_selection_path ---")
    #     return (True, snapped_path)

# 请将此【最终版本】函数完整替换掉 /core/image_manager.py 中的旧函数

    @staticmethod
    def process_selection_path(path: QPainterPath, image_size) -> tuple[bool, QPainterPath]:
        """
        【最终版 - 直接构建像素路径】
        通过检查每个像素的中心点是否在路径内来确定选中的像素集合，
        然后直接由这些像素的矩形区域构建最终的、像素对齐的路径。
        """
        from Finetuning.utils.debugger import debugger
        from PyQt6.QtCore import QPointF, QRectF # 确保导入 QPointF 和 QRectF

        debugger.log("--- Starting FINAL process_selection_path (Direct Path Build) ---")

        if path.isEmpty() or image_size.isEmpty():
            return (False, QPainterPath())

        # 步骤1: 确定需要检查的像素范围
        height, width = image_size.height(), image_size.width()
        bounding_rect = path.boundingRect().toRect()
        
        x_start = max(0, bounding_rect.left())
        y_start = max(0, bounding_rect.top())
        x_end = min(width, bounding_rect.right() + 1)
        y_end = min(height, bounding_rect.bottom() + 1)

        # 步骤2: 找出所有被选中的像素坐标
        selected_pixels = []
        for y in range(y_start, y_end):
            for x in range(x_start, x_end):
                # 检查像素中心 (x + 0.5, y + 0.5) 是否在用户的矢量路径内
                if path.contains(QPointF(x + 0.5, y + 0.5)):
                    selected_pixels.append((x, y))

        # 步骤3: 如果没有选中任何像素，则操作无效
        if not selected_pixels:
            debugger.log("Validation failed: No pixel center was contained in the path.")
            return (False, QPainterPath())

        # 步骤4: 【核心】直接根据选中的像素构建路径
        # 我们不再需要OpenCV来找轮廓，而是为每个选中的像素画一个1x1的方块
        snapped_path = QPainterPath()
        for x, y in selected_pixels:
            # 为每个像素添加一个 1x1 的矩形
            # QRectF(x, y, 1, 1) 代表从(x,y)开始，宽高都为1的矩形
            snapped_path.addRect(QRectF(x, y, 1, 1))
        
        # 步骤 4: 【核心魔法】调用 .simplified() 方法
        # Qt 会自动计算这个复合路径的并集，并返回一个只包含最终轮廓的新路径。
        # 所有内部共享的边都会被自动消除。
        final_boundary_path = snapped_path.simplified()

        debugger.log(f"Path built directly from {len(selected_pixels)} selected pixels.")
        debugger.log("--- Finished FINAL process_selection_path ---")
        
    
        # 返回的 final_boundary_path 现在是所有像素块的并集，它会自动形成正确的阶梯状轮廓
        return (True, final_boundary_path)


    