import os
import cv2
import numpy as np
from PIL import Image, ImageQt
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QBitmap, QPainterPath, QPolygonF
from PyQt6.QtCore import Qt, QPointF
from utils.debugger import debugger

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
    def apply_image_effects(pixmap: QPixmap, settings: dict) -> QPixmap:
        if not pixmap or pixmap.isNull():
            return pixmap

        # 1. 转换 QPixmap -> NumPy Array
        qimage = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
        width, height = qimage.width(), qimage.height()
        ptr = qimage.bits()
        ptr.setsize(qimage.sizeInBytes())
        # --- START: 修复 ---
        bpl = qimage.bytesPerLine()
        # 先重塑 (h, bpl)，再切片取 (h, w*3)，最后重塑为 (h, w, 3)
        arr = np.array(ptr).reshape(height, bpl)[:, :width * 3].reshape(height, width, 3).copy()

        processed_arr = arr

        # 2. 应用手动调整
        if settings.get('manual_enabled', False):
            # 对比度 和 亮度
            contrast = settings.get('manual_contrast', 0)
            brightness = settings.get('manual_brightness', 0)
            # alpha (对比度): [-100, 100] -> [0.0, 2.0]
            alpha = 1.0 + contrast / 100.0
            # beta (亮度): [-100, 100]
            beta = brightness
            processed_arr = cv2.convertScaleAbs(processed_arr, alpha=alpha, beta=beta)

            # Min/Max Levels
            min_level = settings.get('manual_min', 0)
            max_level = settings.get('manual_max', 255)
            if min_level >= max_level: # 防止除零错误
                max_level = min_level + 1

            # 使用查找表(LUT)进行高效的像素值重映射
            lut = np.arange(256, dtype=np.uint8)
            mask = (lut >= min_level) & (lut <= max_level)
            lut[~mask] = 0 # 小于min的设为0
            lut[lut > max_level] = 255 # 大于max的设为255
            lut[mask] = np.uint8(255.0 * (lut[mask] - min_level) / (max_level - min_level))

            processed_arr = cv2.LUT(processed_arr, lut)

        # 3. 应用算法增强
        if settings.get('algo_enabled', False):
            # 将彩色图像转为灰度进行处理
            gray = cv2.cvtColor(processed_arr, cv2.COLOR_RGB2GRAY)
            enhanced_gray = gray

            algo_name = settings.get('algo_name', 'clahe')
            if algo_name == 'clahe':
                clip_limit = settings.get('clahe_clip_limit', 2.0)
                grid_size = settings.get('clahe_grid_size', 8)
                clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(grid_size, grid_size))
                enhanced_gray = clahe.apply(gray)
            elif algo_name == 'global_histogram_equalization':
                enhanced_gray = cv2.equalizeHist(gray)

            # 将处理后的灰度图转回三通道RGB
            processed_arr = cv2.cvtColor(enhanced_gray, cv2.COLOR_GRAY2RGB)

        # 4. 转换 NumPy Array -> QPixmap
        h, w, ch = processed_arr.shape
        bytes_per_line = ch * w
        final_qimage = QImage(processed_arr.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)

        return QPixmap.fromImage(final_qimage)
    
    # @staticmethod
    # def apply_clahe(pixmap: QPixmap) -> QPixmap:
    #     if not pixmap or pixmap.isNull():
    #         return pixmap

    #     # QPixmap -> QImage -> numpy array
    #     qimage = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
    #     width = qimage.width()
    #     height = qimage.height()
    #     ptr = qimage.bits()
    #     ptr.setsize(qimage.sizeInBytes())
    #     arr = np.array(ptr).reshape(height, width, 3)

    #     # 转换为灰度图进行处理
    #     gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        
    #     # 应用CLAHE
    #     clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    #     enhanced_gray = clahe.apply(gray)
        
    #     # 将处理后的灰度图转回三通道，以便显示
    #     enhanced_rgb = cv2.cvtColor(enhanced_gray, cv2.COLOR_GRAY2RGB)

    #     # numpy array -> QImage -> QPixmap
    #     h, w, ch = enhanced_rgb.shape
    #     bytes_per_line = ch * w
    #     enhanced_qimage = QImage(enhanced_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        
    #     return QPixmap.fromImage(enhanced_qimage)
    # # --- END: B3 ---

    @staticmethod
    def calculate_auto_levels(pixmap: QPixmap, saturation_percentage: float = 0.5) -> tuple[int, int]:
        """
        使用百分位数 (Percentile) 计算自动对比度的 Min 和 Max 值。
        
        Args:
            pixmap: QPixmap 对象
            saturation_percentage: 允许饱和的像素百分比 (例如 0.5 表示 0.5% 和 99.5%)
        
        Returns:
            (min_level, max_level) 范围在 0-255 之间
        """
        if not pixmap or pixmap.isNull():
            return 0, 255

        # 1. 转换为灰度 NumPy 数组
        # 使用 QImage 转换确保数据准确
        qimage = pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
        
        ptr = qimage.bits()
        ptr.setsize(qimage.sizeInBytes())
        h, w = qimage.height(), qimage.width()
        bpl = qimage.bytesPerLine()
        
        # 提取有效数据区域
        arr = np.array(ptr).reshape(h, bpl)[:, :w].copy()

        # 2. 如果图像基本是纯色或全黑，直接返回默认值
        if arr.max() == arr.min():
            return 0, 255

        # 3. 使用 np.percentile 计算阈值
        # 为了提高速度，如果图像很大，可以进行降采样计算
        sample = arr
        if arr.size > 1000000:
             sample = arr.ravel()[::100] # 每100个像素取一个样

        # 计算低位和高位百分比
        # 例如 saturation=0.5 -> low=0.5, high=99.5
        low_p = saturation_percentage
        high_p = 100.0 - saturation_percentage
        
        auto_min, auto_max = np.percentile(sample, [low_p, high_p])
        
        # 4. 确保结果在 0-255 整数范围内，且 min < max
        auto_min = int(max(0, auto_min))
        auto_max = int(min(255, auto_max))

        # 防止 min >= max 的极端情况
        if auto_min >= auto_max:
             # 如果计算结果挤在一起，尝试稍微拉开
             mid = (auto_min + auto_max) // 2
             auto_min = max(0, mid - 10)
             auto_max = min(255, mid + 10)

        return auto_min, auto_max
    
    @staticmethod
    def keep_largest_component(mask_pixmap: QPixmap) -> QPixmap:
        """
        保留二值图中最大的连通分量，去除噪点。
        """
        if not mask_pixmap or mask_pixmap.isNull():
            return mask_pixmap

        # 转为单通道 numpy 数组
        qimage = mask_pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
        ptr = qimage.bits()
        ptr.setsize(qimage.sizeInBytes())
        h, w = qimage.height(), qimage.width()
        bpl = qimage.bytesPerLine()
        arr = np.array(ptr).reshape(h, bpl)[:, :w].copy()

        # 二值化确保只有 0 和 255 (容错)
        _, binary = cv2.threshold(arr, 127, 255, cv2.THRESH_BINARY)

        # 连通域分析
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)

        # 如果没有前景或只有一个背景，直接返回
        if num_labels <= 1:
            return mask_pixmap

        # 找到面积最大的连通域 (忽略 label 0，因为它是背景)
        largest_label = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
        
        # 创建新 Mask
        new_mask = np.zeros_like(binary)
        new_mask[labels == largest_label] = 255

        # 转回 QPixmap
        result_qimage = QImage(new_mask.data, w, h, w, QImage.Format.Format_Grayscale8)
        # 必须 copy() 否则数据所有权在 numpy 数组销毁后会出问题
        return QPixmap.fromImage(result_qimage.copy())

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
        # arr = np.array(ptr).reshape(mask_image.height(), mask_image.width())
        # --- START: 修复 ---
        h = mask_image.height()
        w = mask_image.width()
        bpl = mask_image.bytesPerLine()
        arr = np.array(ptr).reshape(h, bpl)[:, :w].copy()
        # --- END: 修复 ---

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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

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
            
            # [!!!] 这是原始的错误行
            # arr = np.array(ptr).reshape(mask_image.height(), mask_image.width())

            # --- START: 修复 ---
            h = mask_image.height()
            w = mask_image.width()
            bpl = mask_image.bytesPerLine() # 获取每行的实际字节数（含padding）
            
            # 先重塑为 (h, bpl)，然后切片取 [:, :w]
            # 必须使用 .copy()，否则 cv2.findContours 可能会出错
            arr = np.array(ptr).reshape(h, bpl)[:, :w].copy()
            # --- END: 修复 ---

            # 2. 查找轮廓
            contours, hierarchy = cv2.findContours(arr, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)

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
        # arr = np.array(ptr).reshape(qimage.height(), qimage.width())
        # --- START: 修复 ---
        h = qimage.height()
        w = qimage.width()
        bpl = qimage.bytesPerLine()
        arr = np.array(ptr).reshape(h, bpl)[:, :w].copy()
        # --- END: 修复 ---


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
        # arr = np.array(ptr).reshape(mask_image.height(), mask_image.width())
        # --- START: 修复 ---
        h = mask_image.height()
        w = mask_image.width()
        bpl = mask_image.bytesPerLine()
        arr = np.array(ptr).reshape(h, bpl)[:, :w].copy()
        # --- END: 修复 ---

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
    
    @staticmethod
    def create_path_from_mask(mask_pixmap: QPixmap) -> QPainterPath:
        """
        【新增，像素级精确】根据二值化图像中的亮像素，直接构建一个 QPainterPath。

        该方法通过为每个亮像素添加一个1x1的矩形，然后使用 .simplified() 方法将
        它们融合成一个单一的、精确贴合像素网格的轮廓，从根本上避免了
        cv2.findContours 可能带来的浮点数坐标错位问题。
        """
        if not mask_pixmap or mask_pixmap.isNull():
            return QPainterPath()

        from PyQt6.QtCore import QRectF # 局部导入以避免循环依赖问题

        # 步骤1: 将 QPixmap 转换为 Numpy 数组，以便高效访问像素
        mask_image = mask_pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
        
        ptr = mask_image.bits()
        ptr.setsize(mask_image.sizeInBytes())
        # arr = np.array(ptr).reshape(mask_image.height(), mask_image.width())
        # --- START: 修复 ---
        h = mask_image.height()
        w = mask_image.width()
        bpl = mask_image.bytesPerLine()
        arr = np.array(ptr).reshape(h, bpl)[:, :w].copy()
        # --- END: 修复 ---

        # 步骤2: 使用 Numpy 高效地找出所有亮像素的坐标
        # np.where 会返回两个数组，分别代表满足条件的元素的y坐标和x坐标
        bright_pixels_y, bright_pixels_x = np.where(arr > 127)

        # 步骤3: 为每个亮像素在路径中添加一个 1x1 的矩形
        pixel_path = QPainterPath()
        for x, y in zip(bright_pixels_x, bright_pixels_y):
            # QRectF(x, y, 1, 1) 代表覆盖从(x,y)开始的整个像素
            pixel_path.addRect(QRectF(float(x), float(y), 1.0, 1.0))

        # 步骤4: 【核心】调用 .simplified()，Qt会自动计算所有小矩形的并集，
        #         生成一个干净、单一、像素对齐的最终轮廓。
        final_path = pixel_path.simplified()

        return final_path
    
    # File: /core/image_manager.py

    @staticmethod
    def process_selection_path(path: QPainterPath, image_size) -> tuple[bool, QPainterPath]:
        """
        将矢量路径转换为严格像素对齐的边界路径。
        每个像素都是 1x1 的正方形，边界只能是水平或垂直线段。
        """
        from utils.debugger import debugger
        from PyQt6.QtCore import QPointF, QRectF
        
        debugger.log("--- Starting pixel-aligned process_selection_path ---")
        
        if path.isEmpty() or image_size.isEmpty():
            return (False, QPainterPath())
        
        # 步骤1：栅格化矢量路径
        height, width = image_size.height(), image_size.width()
        mask_image = QImage(image_size, QImage.Format.Format_Grayscale8)
        mask_image.fill(Qt.GlobalColor.black)
        
        painter = QPainter(mask_image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setBrush(Qt.GlobalColor.white)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)
        painter.end()
        
        # 步骤2：转换为 NumPy 数组
        ptr = mask_image.bits()
        ptr.setsize(mask_image.sizeInBytes())
        h = mask_image.height()
        w = mask_image.width()
        bpl = mask_image.bytesPerLine()
        arr = np.array(ptr).reshape(h, bpl)[:, :w].copy()
        
        if not np.any(arr > 127):
            debugger.log("Validation failed: No pixel covered.")
            return (False, QPainterPath())
        
        # 步骤3：二值化
        _, binary_arr = cv2.threshold(arr, 127, 255, cv2.THRESH_BINARY)
        
        # 步骤4：提取像素边界
        snapped_path = ImageManager._extract_pixel_boundaries(binary_arr)
        
        if snapped_path.isEmpty():
            return (False, QPainterPath())
        
        debugger.log("--- Finished pixel-aligned process_selection_path ---")
        return (True, snapped_path)

    @staticmethod
    def _extract_pixel_boundaries(binary_arr: np.ndarray) -> QPainterPath:
        """
        从二值图像中提取严格像素对齐的边界。
        
        算法：
        1. 找到所有选中的像素
        2. 提取外部边界的水平和垂直线段
        3. 追踪边界形成封闭路径
        """
        from collections import defaultdict
        from PyQt6.QtCore import QPointF
        
        height, width = binary_arr.shape
        
        # 找到所有选中的像素（y, x）
        selected_pixels = set()
        ys, xs = np.where(binary_arr > 0)
        for y, x in zip(ys, xs):
            selected_pixels.add((int(y), int(x)))
        
        if not selected_pixels:
            return QPainterPath()
        
        # 提取所有外部边界的线段
        # 边表示为：(start_point, end_point, direction)
        # direction: 'H' = 水平, 'V' = 垂直
        horizontal_edges = set()  # 水平边：((x, y), (x+1, y))
        vertical_edges = set()    # 垂直边：((x, y), (x, y+1))
        
        for py, px in selected_pixels:
            # 上边界（如果上方没有像素）
            if (py - 1, px) not in selected_pixels:
                horizontal_edges.add((px, py, px + 1, py))
            
            # 下边界（如果下方没有像素）
            if (py + 1, px) not in selected_pixels:
                horizontal_edges.add((px, py + 1, px + 1, py + 1))
            
            # 左边界（如果左边没有像素）
            if (py, px - 1) not in selected_pixels:
                vertical_edges.add((px, py, px, py + 1))
            
            # 右边界（如果右边没有像素）
            if (py, px + 1) not in selected_pixels:
                vertical_edges.add((px + 1, py, px + 1, py + 1))
        
        # 构建邻接图（点到点）
        graph = defaultdict(list)
        
        for x1, y1, x2, y2 in horizontal_edges:
            graph[(x1, y1)].append((x2, y2))
            graph[(x2, y2)].append((x1, y1))
        
        for x1, y1, x2, y2 in vertical_edges:
            graph[(x1, y1)].append((x2, y2))
            graph[(x2, y2)].append((x1, y1))
        
        # 追踪边界形成路径
        visited_edges = set()
        paths = []
        
        def trace_boundary(start_point):
            """从起点追踪一个完整的封闭边界"""
            path = [start_point]
            current = start_point
            prev = None
            
            while True:
                # 寻找下一个未访问的邻居
                found = False
                for neighbor in graph[current]:
                    edge = tuple(sorted([current, neighbor]))
                    
                    # 跳过刚来的边，避免立即返回
                    if neighbor == prev:
                        continue
                    
                    if edge not in visited_edges:
                        visited_edges.add(edge)
                        path.append(neighbor)
                        prev = current
                        current = neighbor
                        found = True
                        break
                
                if not found:
                    # 检查是否回到起点（形成闭环）
                    if current == start_point or (len(path) > 2 and path[-1] in graph[start_point]):
                        break
                    else:
                        # 死路，返回不完整路径
                        return []
            
            return path
        
        # 遍历所有可能的起点
        for point in graph:
            if point not in [p for path in paths for p in path]:
                boundary = trace_boundary(point)
                if len(boundary) >= 4:  # 至少4个点才能形成有效封闭区域
                    paths.append(boundary)
        
        # 转换为 QPainterPath
        final_path = QPainterPath()
        
        for boundary in paths:
            if not boundary:
                continue
            
            # 移动到起点
            final_path.moveTo(QPointF(boundary[0][0], boundary[0][1]))
            
            # 连接所有点
            for i in range(1, len(boundary)):
                final_path.lineTo(QPointF(boundary[i][0], boundary[i][1]))
            
            # 闭合路径
            final_path.closeSubpath()
        
        return final_path

    
    # 之前的调试代码
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


    