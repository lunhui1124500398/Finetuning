# Finetuning/ui/widgets/image_canvas.py

from PyQt6.QtWidgets import QApplication, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QMessageBox, QGraphicsPathItem
from PyQt6.QtCore import Qt, pyqtSlot, QPointF, pyqtSignal, QTimer, QRectF, QDateTime
from PyQt6.QtGui import (
    QPixmap, QPainter, QPen, QColor, QCursor, QPainterPath, 
    QPolygonF, QImage, QPainterPathStroker
)
import os
from Finetuning.utils.debugger import debugger   # 导入调试器

# --- 从Demo中借鉴并优化的光标创建函数 ---
def create_cursor(text):
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    center_x, center_y = 15, 15
    line_len = 10
    painter.setPen(QPen(Qt.GlobalColor.black, 3, Qt.PenStyle.SolidLine))
    painter.drawLine(center_x - line_len, center_y, center_x + line_len, center_y)
    painter.drawLine(center_x, center_y - line_len, center_x, center_y + line_len)
    painter.setPen(QPen(Qt.GlobalColor.white, 1, Qt.PenStyle.SolidLine))
    painter.drawLine(center_x - line_len, center_y, center_x + line_len, center_y)
    painter.drawLine(center_x, center_y - line_len, center_x, center_y + line_len)
    font = painter.font()
    font.setPixelSize(14)
    font.setBold(True)
    painter.setFont(font)
    rect = pixmap.rect().adjusted(2, 2, -2, -2)
    painter.setPen(Qt.GlobalColor.black)
    painter.drawText(rect.translated(1, 1), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, text)
    painter.setPen(Qt.GlobalColor.white)
    painter.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, text)
    painter.end()
    return QCursor(pixmap, center_x, center_y)


class ImageCanvas(QGraphicsView):
    save_and_next_requested = pyqtSignal()

    def __init__(self, model, image_manager, parent=None):
        super().__init__(parent)
        self.model = model
        self.image_manager = image_manager
        
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        # 图元
        self._original_item = QGraphicsPixmapItem()
        self._selection_item = QGraphicsPathItem() # 用于显示蚂蚁线
        self._mask_overlay_item = QGraphicsPixmapItem() # 用于显示旧的颜色叠加
        self._selection_item.setPen(QPen(Qt.PenStyle.NoPen)) # 不使用边框
        
        self.scene.addItem(self._original_item)
        self.scene.addItem(self._mask_overlay_item)
        self.scene.addItem(self._selection_item)

        # 状态变量
        self._original_pixmap = None
        self._contrast_pixmap = None
        self._current_mask_pixmap = None # 用于加载和显示旧的mask

        # --- START: 选区工具状态 ---
        self._selection_path = QPainterPath()
        self._temp_drawing_points = []
        self._current_tool = 'lasso'
        self._is_drawing_selection = False
        self._is_panning = False
        self._pan_start_pos = QPointF()
        
        # 蚂蚁线动画
        self.ant_offset = 0
        # self.ant_timer = QTimer(self)
        # self.ant_timer.timeout.connect(self.animate_ants)
        # self.ant_timer.start(100)
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self._animate_ants)
        self.animation_timer.start(50) # 每50毫秒触发一次动画更新
        
        # 自定义光标
        self.cursors = {
            'add': create_cursor('+'),
            'subtract': create_cursor('−'),
            'default': QCursor(Qt.CursorShape.CrossCursor)
        }
        # --- END: 选区工具状态 ---
        
        self.setMouseTracking(True)
        self.init_ui()

    def init_ui(self):
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

        # 【核心修正】: 添加下面这行代码
        # 将视口更新模式设置为 FullViewportUpdate
        # 这会强制在场景发生任何变化时重绘整个视口，修复局部刷新不完整的问题
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

        # 禁用缓存，确保每次都重新绘制图元，而不是使用可能过期的缓存版本
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheNone)

    @pyqtSlot(int)
    def load_image(self, index):
        # ...
        debugger.log(f"--- Loading image index: {index} ---") # 替换 print

        if index < 0:
            self.scene.clear()
            self._original_item = QGraphicsPixmapItem()
            self._mask_overlay_item = QGraphicsPixmapItem()
            self._selection_item = QGraphicsPathItem()
            self.scene.addItem(self._original_item)
            self.scene.addItem(self._mask_overlay_item)
            self.scene.addItem(self._selection_item)
            return
        
        self._contrast_pixmap = None
        self._selection_path = QPainterPath() # 切换图片时清空选区
        self._is_drawing_selection = False
        self._temp_drawing_points = []

        self._selection_path = QPainterPath()
        self._current_mask_pixmap = None

        # 加载原图
        original_path = self.model._original_files[index]
        self._original_pixmap = self.image_manager.load_pixmap(original_path)
        if not self._original_pixmap:
            print(f"Failed to load original image: {original_path}")
            return
        
        self.update_display_pixmap()

        # 加载参考Mask (用于显示)
        self._current_mask_pixmap = None
        if self.model._mask_files and index < len(self.model._mask_files):
            # 临时加载到 _current_mask_pixmap
            mask_pixmap = self.image_manager.load_pixmap(self.model._mask_files[index])
            if mask_pixmap and not mask_pixmap.isNull():
                 self._current_mask_pixmap = mask_pixmap
                 # 【修改点 2】立刻将其转换为像素级精确的路径
                 self._selection_path = self.image_manager.create_path_from_mask(self._current_mask_pixmap)
        
        # 如果没有参考mask，确保创建一个空的黑色pixmap
        if self._current_mask_pixmap is None or self._current_mask_pixmap.size() != self._original_pixmap.size():
            self._current_mask_pixmap = QPixmap(self._original_pixmap.size())
            self._current_mask_pixmap.fill(Qt.GlobalColor.black)
        
        if self._current_mask_pixmap:
            debugger.save_image(self._current_mask_pixmap, f"1_input_mask_index_{index}")

        self.update_selection_display()
        
        self.setSceneRect(self._original_item.boundingRect())
        self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.scene.update()  # 确保场景立即更新

    def _prepare_for_drawing(self):
        """核心逻辑：根据当前状态准备开始绘制选区"""
        # 1. 面积模式 -> 轮廓模式
        if self.model.mask_display_style == 'area':
            self.model.set_mask_display_style('contour')
            # 切换后，下面的逻辑会继续执行
        
        # 2. 轮廓模式 -> 选区路径
        if self.model.mask_display_style == 'contour' and self._selection_path.isEmpty():
            if self._current_mask_pixmap:
                 # self._selection_path = self.image_manager.convert_mask_to_path(self._current_mask_pixmap)
                self._selection_path = self.image_manager.create_path_from_mask(self._current_mask_pixmap)
        
        # 3. Mask不显示 -> 自动显示
        if not self.model.show_mask:
            self.model.set_show_mask(True)
            if self._selection_path.isEmpty():
                 self._current_mask_pixmap.fill(Qt.GlobalColor.black) # 确保是一个空图层

        # 4. 统一更新显示
        self.update_selection_display()

    def update_selection_display(self):
        """统一更新画布上的所有遮罩和选区显示"""
        # 确保在操作前，底图是干净的原始图像（或高对比度图像）
        self.update_display_pixmap()

        if not self.model.show_mask or not self._original_pixmap:
            self._mask_overlay_item.setPixmap(QPixmap())
            self._selection_item.setPath(QPainterPath())
            return

        base_pixmap = self._original_item.pixmap()
        if not base_pixmap or base_pixmap.isNull(): return

        style = self.model.mask_display_style
        
        # 为两种模式统一获取用于生成遮罩的二值图
        # area 模式下，可能使用已保存的mask；contour 模式下，总使用当前编辑的路径
        mask_pixmap = self._get_display_mask() if style == "area" else self.get_pixmap_from_path()
        if not mask_pixmap or mask_pixmap.isNull():
            # 如果没有mask，contour模式不显示绿色轮廓，area模式不显示区域
            if style == 'contour':
                self._selection_item.setPath(self._selection_path) # 仅显示蚂蚁线
            else:
                self._selection_item.setPath(QPainterPath()) # 面积模式隐藏蚂蚁线
            return

        # 读取配置
        if style == "area":
            color_str = self.model.config['Colors'].get('mask_overlay_color', '255,0,0,80')
            color_rgba = tuple(map(int, color_str.split(',')))
            thickness = 1 # 面积模式厚度无用
        else: # contour 模式
            color_str = self.model.config['Colors'].get('contour_line_color', '0,255,0,128')
            color_rgba = tuple(map(int, color_str.split(',')))
            thickness = self.model.config['Colors'].getint('contour_thickness', 1)

        # 【核心修改】调用ImageManager生成一个包含底图和遮罩的“最终合成图”
        composite_pixmap = self.image_manager.create_overlay_pixmap(
            base_pixmap,
            mask_pixmap,
            style,
            color_rgba,
            contour_thickness=thickness,
            invert=self.model.mask_invert
        )

        # 将合成图直接设置给底图图元
        self._original_item.setPixmap(composite_pixmap)
        # 清空上层遮罩图元，因为它已经被合并到底图中了
        self._mask_overlay_item.setPixmap(QPixmap())

        # 根据模式决定是否显示蚂蚁线
        if style == "area":
            self._selection_item.setPath(QPainterPath())  # 面积模式不显示蚂蚁线
        else: # contour 模式
            # 蚂蚁线路径依然需要设置，由 drawForeground 方法负责绘制
            self._selection_item.setPath(self._selection_path)
        

        ## 调试代码
        # if style == "area":
        #     from Finetuning.utils.debugger import debugger # 确保导入

        #     # 1. 获取当前显示的底图
        #     base_pixmap = self._original_item.pixmap()
        #     if not base_pixmap or base_pixmap.isNull(): return
        #     debugger.save_image(base_pixmap, "debug_1_base_for_area_mode") # <-- 调试点1

        #     # 2. 从当前选区路径生成用于叠加的二值化mask
        #     mask_pixmap = self.get_pixmap_from_path()
        #     debugger.save_image(mask_pixmap, "debug_2_mask_for_area_mode") # <-- 调试点2
            
        #     # 3. 读取配置
        #     area_color_str = self.model.config['Colors'].get('mask_overlay_color', '255,0,0,100')
        #     area_color_rgba = tuple(map(int, area_color_str.split(',')))

        #     # 4. 调用ImageManager生成“最终合成图”
        #     composite_pixmap = self.image_manager.create_overlay_pixmap(
        #         base_pixmap,
        #         mask_pixmap,
        #         'area',
        #         area_color_rgba,
        #         invert=self.model.mask_invert
        #     )
        #     debugger.save_image(composite_pixmap, "debug_3_final_composite_image") # <-- 调试点3

        #     # 5. 将合成图直接设置给底图图元，并清空上层遮罩
        #     self._original_item.setPixmap(composite_pixmap)
        #     self._mask_overlay_item.setPixmap(QPixmap()) 
        #     self._selection_item.setPath(QPainterPath())

    def get_pixmap_from_path(self) -> QPixmap:
        """从当前 _selection_path 生成一个二值化的 QPixmap"""
        if self._original_pixmap is None: return QPixmap()
        
        mask_image = QImage(self._original_pixmap.size(), QImage.Format.Format_Grayscale8)
        mask_image.fill(Qt.GlobalColor.black)
        
        painter = QPainter(mask_image)
        painter.setBrush(Qt.GlobalColor.white)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(self._selection_path)
        painter.end()
        
        return QPixmap.fromImage(mask_image)
    
    # Finetuning/ui/widgets/image_canvas.py -> 在 ImageCanvas 类中新增此方法

    def _get_display_mask(self) -> QPixmap:
        """
        获取用于面积模式显示的Mask。
        该方法模仿了PreviewPanel的逻辑，确保数据来源的正确性。
        """
        # 优先级1: 如果当前有正在绘制的、未保存的选区，则优先使用它。
        if not self._selection_path.isEmpty():
            return self.get_pixmap_from_path()

        index = self.model.current_index
        if index < 0:
            return None

        # 优先级2: 尝试从“保存路径”加载已保存的Mask。
        save_dir = self.model.get_path('save_path')
        if save_dir and index < len(self.model._original_files):
            original_filename = os.path.basename(self.model._original_files[index])
            mask_filename = os.path.splitext(original_filename)[0] + '.png'
            saved_mask_path = os.path.join(save_dir, mask_filename)
            if os.path.exists(saved_mask_path):
                return self.image_manager.load_pixmap(saved_mask_path)

        # 优先级3: 尝试从“参考路径”加载初始Mask。
        if self.model._mask_files and index < len(self.model._mask_files):
            return self.image_manager.load_pixmap(self.model._mask_files[index])

        # 优先级4: 如果都找不到，返回一个与底图等大的纯黑Mask。
        if self._original_pixmap:
            empty_pixmap = QPixmap(self._original_pixmap.size())
            empty_pixmap.fill(Qt.GlobalColor.black)
            return empty_pixmap
        
        return None
        
    # def animate_ants(self):
    #     self.ant_offset = (self.ant_offset + 1) % 10
    #     if self.model.mask_display_style == 'contour':
    #         # 触发 QGraphicsPathItem 的重绘
    #         self.scene.update(self._selection_item.boundingRect())

    def _animate_ants(self):
        """用于触发蚂蚁线动画的刷新"""
        if self.model.show_mask and self.model.mask_display_style == 'contour':
            # 更新整个选区所在的区域以重绘蚂蚁线
            self.scene.update(self._selection_item.boundingRect())

    # --- 事件处理 (大量借鉴Demo) ---
    def wheelEvent(self, event):
        zoom_factor = 1.25 if event.angleDelta().y() > 0 else 1 / 1.25
        self.scale(zoom_factor, zoom_factor)

    def mouseDoubleClickEvent(self, event):
        if self._current_tool == 'polygon' and len(self._temp_drawing_points) > 2:
            self._end_drawing(commit_selection=True)
            event.accept()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.save_and_next_requested.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = True
            self._pan_start_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        
        if event.button() != Qt.MouseButton.LeftButton or not self._original_pixmap:
            super().mousePressEvent(event)
            return

        # 核心逻辑：准备画布
        self._prepare_for_drawing()
        
        if self.model.mask_display_style == 'area':
             # 此时已自动切换到 contour，但需要用户再次点击开始
             return
        
        self.push_undo_state() # 记录操作前状态
        self._is_drawing_selection = True
        scene_pos = self.mapToScene(event.pos())

        if self._current_tool == 'lasso' or self._current_tool == 'erase':
            self._temp_drawing_points = [scene_pos]
        elif self._current_tool == 'polygon':
            if len(self._temp_drawing_points) > 1 and \
               (scene_pos - self._temp_drawing_points[0]).manhattanLength() < 15 / self.transform().m11():
                self._end_drawing(commit_selection=True)
            else:
                self._temp_drawing_points.append(scene_pos)
        
        self.scene.update()
        event.accept()

    def mouseMoveEvent(self, event):
        self.update_cursor()
        scene_pos = self.mapToScene(event.pos())

        if self._is_panning:
            delta = event.pos() - self._pan_start_pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self._pan_start_pos = event.pos()
            event.accept()
            return
        
        if self._is_drawing_selection and (self._current_tool == 'lasso' or self._current_tool == 'erase'):
            self._temp_drawing_points.append(scene_pos)
        
        self.scene.update() # For polygon tool's rubber band line
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = False
            self.update_cursor()
            event.accept()
            return

        if self._is_drawing_selection and (self._current_tool == 'lasso' or self._current_tool == 'erase'):
            self._end_drawing(commit_selection=True)
            event.accept()
        
        super().mouseReleaseEvent(event)

    def _get_current_modifier(self):
        modifiers = QApplication.keyboardModifiers()
        if self.model.selection_tool == 'erase':
             return 'subtract'
        if modifiers == Qt.KeyboardModifier.ShiftModifier:
            return 'add'
        elif modifiers in [Qt.KeyboardModifier.AltModifier, Qt.KeyboardModifier.ControlModifier]:
            return 'subtract'
        return 'new'

    def _end_drawing(self, commit_selection=True):
        if not self._is_drawing_selection:
            return

        if commit_selection and len(self._temp_drawing_points) >= 3:
            poly = QPolygonF(self._temp_drawing_points)
            new_drawn_path = QPainterPath()
            new_drawn_path.addPolygon(poly)
            new_drawn_path.closeSubpath()

            # 根据当前的修改键(Shift/Alt)确定操作后的候选路径
            modifier = self._get_current_modifier()
            candidate_path = QPainterPath()
            if modifier == 'new':
                candidate_path = new_drawn_path
            elif modifier == 'add':
                candidate_path = self._selection_path.united(new_drawn_path)
            elif modifier == 'subtract':
                candidate_path = self._selection_path.subtracted(new_drawn_path)

            # 减选到0是可以接受的
            if modifier == 'subtract' and candidate_path.isEmpty():
                # 直接将选区设置为空路径
                self._selection_path = QPainterPath()
                # 通知模型选区已更新，UI需要刷新
                self.model.mask_updated.emit()
            
            else:
                if self._original_pixmap and not self._original_pixmap.isNull():
                    
                    # 调用新的处理方法，它会返回验证结果和处理后的路径
                    is_valid, final_path = self.image_manager.process_selection_path(
                        candidate_path, self._original_pixmap.size()
                    )

                    if not is_valid:
                        # 如果验证失败 (包括减去后完全为空的情况)，弹出提示，并且不更新选区。
                        # 注意：如果路径在相减后变为空，is_valid 也将为 False，这是符合预期的行为。
                        QMessageBox.warning(self, "提示", "选区未覆盖任何像素面积的50%以上，选区线将不可见。")
                        # 不更新 self._selection_path，相当于撤销了本次绘制
                    else:
                        # 验证成功, 更新最终选区路径
                        self._selection_path = final_path
                        # 通知模型选区已更新，UI需要刷新
                        self.model.mask_updated.emit()

        # 无论成功与否，都重置绘制状态
        self._is_drawing_selection = False
        self._temp_drawing_points = []
        self.scene.update()

    # --- 覆盖 paintEvent 来绘制临时的线和蚂蚁线 ---
    # def drawForeground(self, painter, rect):
    #     super().drawForeground(painter, rect)
    #     painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    #     # 绘制正在进行中的选区线 (如多边形的橡皮筋)
    #     if self._is_drawing_selection and self._temp_drawing_points:
    #         pen = QPen(Qt.GlobalColor.cyan, 1 / self.transform().m11(), Qt.PenStyle.DotLine)
    #         painter.setPen(pen)
            
    #         points_f = self._temp_drawing_points
    #         if len(points_f) > 1:
    #             painter.drawPolyline(QPolygonF(points_f))
            
    #         if self._current_tool == 'polygon' and self.underMouse():
    #              mouse_pos = self.mapToScene(self.mapFromGlobal(QCursor.pos()))
    #              painter.drawLine(points_f[-1], mouse_pos)
        
    #     # 绘制蚂蚁线 (重写此部分以获得双色效果)
    #     if self.model.show_mask and self.model.mask_display_style == 'contour' and not self._selection_path.isEmpty():
    #         painter.setBrush(Qt.BrushStyle.NoBrush)
            
    #         pen_black = QPen(Qt.GlobalColor.black, 1 / self.transform().m11(), Qt.PenStyle.CustomDashLine)
    #         pen_black.setDashPattern([5, 5])
    #         pen_black.setDashOffset(self.ant_offset + 5)
            
    #         pen_white = QPen(Qt.GlobalColor.white, 1 / self.transform().m11(), Qt.PenStyle.CustomDashLine)
    #         pen_white.setDashPattern([5, 5])
    #         pen_white.setDashOffset(self.ant_offset)

    #         painter.setPen(pen_black)
    #         painter.drawPath(self._selection_path)
    #         painter.setPen(pen_white)
    #         painter.drawPath(self._selection_path)

    # 文件: /ui/widgets/image_canvas.py
# 替换 ImageCanvas 类的 drawForeground 方法中绘制 _selection_path 的部分

    # 保留以待修改
    def drawForeground(self, painter, rect):
        """
        【替换】使用新的、像素精确且视觉效果更佳的蚂蚁线绘制逻辑。
        """
        super().drawForeground(painter, rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 获取当前视图的缩放比例
        current_scale = self.transform().m11()
        # 保证蚂蚁线在屏幕上始终为1像素宽
        pen_width = 1.0 / current_scale

        # 绘制正在进行中的选区线 (如多边形的橡皮筋)
        if self._is_drawing_selection and self._temp_drawing_points:
            pen = QPen(Qt.GlobalColor.cyan, pen_width, Qt.PenStyle.DotLine)
            painter.setPen(pen)
            
            points_f = self._temp_drawing_points
            if len(points_f) > 1:
                painter.drawPolyline(QPolygonF(points_f))
            
            if self._current_tool == 'polygon' and self.underMouse():
                mouse_pos = self.mapToScene(self.mapFromGlobal(QCursor.pos()))
                painter.drawLine(points_f[-1], mouse_pos)
        
        # 绘制蚂蚁线 (重写此部分以解决“太粗”的问题)
        if self.model.show_mask and self.model.mask_display_style == 'contour' and not self._selection_path.isEmpty():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            
            # 蚂蚁线总周期长度（例如10个屏幕像素）
            dash_length = 5.0
            dash_period = dash_length * 2.0
            
            # 根据实时时间计算偏移量，实现平滑动画
            offset = (QDateTime.currentMSecsSinceEpoch() / 150.0) % dash_period
            
            # --- 绘制黑色部分 ---
            pen_black = QPen(Qt.GlobalColor.black, pen_width, Qt.PenStyle.CustomDashLine)
            # 设置虚线模式：[5像素实线, 5像素空白]
            pen_black.setDashPattern([dash_length, dash_length])
            pen_black.setDashOffset(offset)
            
            # --- 绘制白色部分 ---
            pen_white = QPen(Qt.GlobalColor.white, pen_width, Qt.PenStyle.CustomDashLine)
            pen_white.setDashPattern([dash_length, dash_length])
            # 白色部分的偏移与黑色部分错开半个周期，填补其空白
            pen_white.setDashOffset(offset - dash_length)

            # 先画黑色，再画白色，叠加形成蚂蚁线效果
            painter.setPen(pen_black)
            painter.drawPath(self._selection_path)
            
            painter.setPen(pen_white)
            painter.drawPath(self._selection_path)

    
            
    def update_cursor(self):
        if self._is_panning:
             self.setCursor(Qt.CursorShape.ClosedHandCursor)
             return
        if self.model.mask_display_style == 'area':
             self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
             self.setCursor(Qt.CursorShape.OpenHandCursor)
             return

        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        modifier = self._get_current_modifier()
        if modifier == 'add':
            self.setCursor(self.cursors['add'])
        elif modifier == 'subtract':
            self.setCursor(self.cursors['subtract'])
        else:
            self.setCursor(self.cursors['default'])

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        self.update_cursor()

    def keyReleaseEvent(self, event):
        super().keyReleaseEvent(event)
        self.update_cursor()
        
    def enterEvent(self, event):
        super().enterEvent(event)
        self.update_cursor()

    # --- 公共方法 ---
    @pyqtSlot(bool)
    def set_high_contrast(self, enabled):
        self.update_display_pixmap()

    def update_display_pixmap(self):
        if self.model.high_contrast:
            if not self._contrast_pixmap:
                self._contrast_pixmap = self.image_manager.apply_clahe(self._original_pixmap)
            self._original_item.setPixmap(self._contrast_pixmap)
        else:
            self._original_item.setPixmap(self._original_pixmap)

    @pyqtSlot(bool)
    def set_selection_visibility(self, visible):
        self.update_selection_display()

    @pyqtSlot(str)
    def set_tool(self, tool):
        self._end_drawing(commit_selection=False)
        self._current_tool = tool
        self.update_cursor()

    def clear_current_selection(self):
        if not self._selection_path.isEmpty():
            self.push_undo_state()
            self._selection_path = QPainterPath()
            self.update_selection_display()
            self.model.mask_updated.emit()
            if self.model.auto_save:
                self.save_current_mask()
        self.setFocus()
            
    def save_current_mask(self):
        index = self.model.current_index
        if index < 0 or self._selection_path.isEmpty():
            # 允许保存空mask
            if index < 0: return False

        save_dir = self.model.get_path('save_path')
        if not save_dir:
            QMessageBox.warning(self, "保存失败", "请在路径设置中指定有效的“保存路径”！")
            return False
        
        original_filename = os.path.basename(self.model._original_files[index])
        mask_filename = os.path.splitext(original_filename)[0] + '.png'
        save_path = os.path.join(save_dir, mask_filename)
        
        pixmap_to_save = self.get_pixmap_from_path()
        if self.model.mask_invert:
            img = pixmap_to_save.toImage()
            img.invertPixels()
            pixmap_to_save = QPixmap.fromImage(img)

        self.image_manager.save_pixmap(pixmap_to_save, save_path)
        print(f"Mask saved to {save_path}")
        self.setFocus()
        return True

    def push_undo_state(self):
        self.model.push_undo_state(self.model.current_index, self._selection_path)
    
    def undo(self):
        last_state = self.model.pop_undo_state(self.model.current_index)
        if last_state is not None: # Can be an empty path
            self._selection_path = last_state
            self.update_selection_display()
            self.model.mask_updated.emit()
            print("Undo successful.")