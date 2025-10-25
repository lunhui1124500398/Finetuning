# Finetuning/ui/widgets/image_canvas.py

from PyQt6.QtWidgets import QApplication, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QMessageBox, QGraphicsPathItem
from PyQt6.QtCore import Qt, pyqtSlot, QPointF, pyqtSignal, QTimer, QRectF, QDateTime
from PyQt6.QtGui import (
    QPixmap, QPainter, QPen, QColor, QCursor, QPainterPath, 
    QPolygonF, QImage, QPainterPathStroker
)
import os
from utils.debugger import debugger

# --- create_cursor 函数 (无变动) ---
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

        self._original_item = QGraphicsPixmapItem()
        self._selection_item = QGraphicsPathItem()
        self._selection_item.setPen(QPen(Qt.PenStyle.NoPen))
        
        self.scene.addItem(self._original_item)
        self.scene.addItem(self._selection_item)

        self._original_pixmap = None
        self._contrast_pixmap = None
        self._denoised_pixmap = None

        self._selection_path = QPainterPath()
        self._temp_drawing_points = []
        self._current_tool = 'lasso'
        self._is_drawing_selection = False
        self._is_panning = False
        self._pan_start_pos = QPointF()
        self._mode_before_drawing = None
        self._erasing_image = None
        
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self._animate_ants)
        self.animation_timer.start(50)
        
        self.cursors = {
            'add': create_cursor('+'),
            'subtract': create_cursor('−'),
            'default': QCursor(Qt.CursorShape.CrossCursor)
        }
        
        self.setMouseTracking(True)
        self.init_ui()

    # ... (init_ui, load_image, update_selection_display, get_pixmap_from_path, _animate_ants, wheelEvent, mouseDoubleClickEvent 不变) ...
    def init_ui(self):
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheNone)

    def capture_view_state(self):
        """捕获当前的视图变换和滚动条位置，并保存到模型中。"""
        # 确保场景中有内容可以捕获
        if self._original_pixmap is None or self._original_pixmap.isNull():
            return
        
        transform = self.transform()
        h_scroll = self.horizontalScrollBar().value()
        v_scroll = self.verticalScrollBar().value()
        self.model.store_zoom_state(transform, h_scroll, v_scroll)
        
    @pyqtSlot(bool)
    def on_zoom_lock_changed(self, locked):
        """当缩放锁定状态改变时调用"""
        if not locked:
            # 当解锁时，将当前视图重置为适应窗口大小
            if self._original_item and not self._original_item.pixmap().isNull():
                self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    @pyqtSlot(int)
    def load_image(self, index):
        # 在加载新图片之前，如果缩放被锁定，则捕获当前视图的状态
        if self.model.is_zoom_locked:
            self.capture_view_state()
        
        if index < 0:
            self.scene.clear()
            self._original_item = QGraphicsPixmapItem()
            self._selection_item = QGraphicsPathItem()
            self._selection_item.setPen(QPen(Qt.PenStyle.NoPen))
            self.scene.addItem(self._original_item)
            self.scene.addItem(self._selection_item)
            return
        
        self._contrast_pixmap = None
        self._is_drawing_selection = False
        self._temp_drawing_points = []
        self._selection_path = QPainterPath()

        original_path = self.model._original_files[index]
        self._original_pixmap = self.image_manager.load_pixmap(original_path)
        
        # 加载去噪图
        self._denoised_pixmap = None # 每次加载新图时重置
        if self.model._denoised_files and index < len(self.model._denoised_files):
            denoised_path = self.model._denoised_files[index]
            self._denoised_pixmap = self.image_manager.load_pixmap(denoised_path)
        
        if not self._original_pixmap: return
        
        self.update_display_pixmap()

        self._selection_path = QPainterPath()
        mask_pixmap = None

        # 1. 获取 'save_path' (已存效果) 的路径
        save_dir = self.model.get_path('save_path')
        saved_mask_path = None
        if save_dir and index >= 0:
            original_filename = os.path.basename(self.model._original_files[index])
            mask_filename = os.path.splitext(original_filename)[0] + '.png'
            saved_mask_path = os.path.join(save_dir, mask_filename)
        # 2. 获取 'mask_path' (二值化图) 的路径
        binary_mask_path = None
        if self.model._mask_files and index < len(self.model._mask_files):
            binary_mask_path = self.model._mask_files[index]
        # 3. 根据 model 中的状态决定加载哪个
        path_to_load = None
        if self.model.load_from_save_path:
            # 优先加载 'save_path' (已存效果)
            if saved_mask_path and os.path.exists(saved_mask_path):
                path_to_load = saved_mask_path
            elif binary_mask_path:
                path_to_load = binary_mask_path # 回退
        else:
            # 优先加载 'mask_path' (二值化图)
            if binary_mask_path:
                path_to_load = binary_mask_path
            elif saved_mask_path and os.path.exists(saved_mask_path):
                path_to_load = saved_mask_path # 回退

        if path_to_load:
            mask_pixmap = self.image_manager.load_pixmap(path_to_load)
            # print(f"Loaded mask from: {path_to_load}")


        # if self.model._mask_files and index < len(self.model._mask_files):
        #     mask_pixmap = self.image_manager.load_pixmap(self.model._mask_files[index])
        
        if mask_pixmap and not mask_pixmap.isNull():
            self._selection_path = self.image_manager.create_path_from_mask(mask_pixmap)
        
        self.update_selection_display()
        self.setSceneRect(self._original_item.boundingRect())
        if self.model.is_zoom_locked:
            transform, h_scroll, v_scroll = self.model.get_zoom_state()
            if transform is not None:
                self.setTransform(transform)
                self.horizontalScrollBar().setValue(h_scroll)
                self.verticalScrollBar().setValue(v_scroll)
            else:
                # 如果是第一次在锁定状态下加载图片，则先适应窗口，再捕获状态
                self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
                self.capture_view_state() 
        else:
            # 默认行为：适应窗口
            self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.scene.update()

    @pyqtSlot()
    def update_selection_display(self, base_pixmap_for_overlay=None):
        # self.update_display_pixmap()
        if base_pixmap_for_overlay is None:
            self.update_display_pixmap()
        self._selection_item.setPath(QPainterPath())

        mode = self.model.display_mode
        if mode == "hide" or not self._original_pixmap: return

        #base_pixmap = self._original_item.pixmap()
        base_pixmap = base_pixmap_for_overlay if base_pixmap_for_overlay else self._original_item.pixmap()
        if not base_pixmap or base_pixmap.isNull(): return

        if mode == "ants":
            self._selection_item.setPath(self._selection_path)
            return

        mask_pixmap = self.get_pixmap_from_path()
        if not mask_pixmap or mask_pixmap.isNull(): return
        
        if mode == "area":
            style, color_str, thickness = 'area', self.model.config['Colors'].get('mask_overlay_color', '255,0,0,80'), 1
        elif mode == "contour":
            style, color_str, thickness = 'contour', self.model.config['Colors'].get('contour_line_color', '0,255,0,128'), self.model.config['Colors'].getint('contour_thickness', 1)
        else:
            return

        color_rgba = tuple(map(int, color_str.split(',')))
        composite_pixmap = self.image_manager.create_overlay_pixmap(base_pixmap, mask_pixmap, style, color_rgba, thickness, self.model.mask_invert)
        self._original_item.setPixmap(composite_pixmap)

    def get_pixmap_from_path(self) -> QPixmap:
        if self._original_pixmap is None: return QPixmap()
        mask_image = QImage(self._original_pixmap.size(), QImage.Format.Format_Grayscale8)
        mask_image.fill(Qt.GlobalColor.black)
        painter = QPainter(mask_image)
        painter.setBrush(Qt.GlobalColor.white)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(self._selection_path)
        painter.end()
        return QPixmap.fromImage(mask_image)
    
    def _animate_ants(self):
        if self.model.display_mode == 'ants':
            self.scene.update(self._selection_item.boundingRect())

    def wheelEvent(self, event):
        # 如果模型被设置为 "固定缩放"，则忽略所有滚轮事件（包括双指缩放）
        if self.model.is_zoom_locked:
            event.accept() # 消耗掉这个事件，防止父类处理
            return
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
    
    # --- START: 监听右键取消 ---
    def mousePressEvent(self, event):
        # 响应右键，取消正在进行的绘制
        if event.button() == Qt.MouseButton.RightButton:
            if self._is_drawing_selection:
                self._cancel_drawing()
                event.accept()
                return
            else:
                # 检查是否有图像加载
                if self.model.current_index >= 0:
                    print("Right-click (Stylus side button) captured for Save and Next.")
                    self.save_and_next_requested.emit()
                
                event.accept()
                return
            # super().mousePressEvent(event)
            # return

        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = True
            self._pan_start_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        
        if event.button() != Qt.MouseButton.LeftButton or not self._original_pixmap:
            super().mousePressEvent(event)
            return

        if not self._is_drawing_selection:
            self._mode_before_drawing = self.model.display_mode
            if self._mode_before_drawing != 'ants':
                self.model.set_display_mode('ants')
        
        # 撤销点移动到了_end_drawing和_end_erasing中
        self._is_drawing_selection = True
        scene_pos = self.mapToScene(event.pos())

        if self._current_tool in ['lasso', 'polygon', 'lasso_subtract', 'polygon_subtract']:
            if self._current_tool == 'lasso' or self._current_tool == 'lasso_subtract':
                self._temp_drawing_points = [scene_pos]
            elif self._current_tool == 'polygon' or self._current_tool == 'polygon_subtract':
                if len(self._temp_drawing_points) > 1 and \
                   (scene_pos - self._temp_drawing_points[0]).manhattanLength() < 15 / self.transform().m11():
                    self._end_drawing(commit_selection=True)
                else:
                    self._temp_drawing_points.append(scene_pos)
        elif self._current_tool == 'erase':
            self._erasing_image = self.get_pixmap_from_path().toImage()
            self._apply_eraser(scene_pos)
        
        self.scene.update()
        event.accept()
    # --- END: 监听右键取消 ---

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
        
        if self._is_drawing_selection:
            if self._current_tool == 'lasso' or self._current_tool == 'lasso_subtract':
                self._temp_drawing_points.append(scene_pos)
            elif self._current_tool == 'erase':
                self._apply_eraser(scene_pos)
        
        self.scene.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = False
            self.update_cursor()
            event.accept()
            return

        if self._is_drawing_selection:
            if self._current_tool in ['lasso', 'polygon','lasso_subtract', 'polygon_subtract']:
                if self._current_tool == 'lasso' or self._current_tool == 'lasso_subtract':
                    self._end_drawing(commit_selection=True)
            elif self._current_tool == 'erase':
                self._end_erasing()
            event.accept()
        
        super().mouseReleaseEvent(event)

    def _get_current_modifier(self):
        # --- START: 重写此方法 ---
        modifiers = QApplication.keyboardModifiers()
        # 1. 键盘快捷键优先
        if modifiers == Qt.KeyboardModifier.ShiftModifier: 
            return 'add'
        if modifiers in [Qt.KeyboardModifier.AltModifier, Qt.KeyboardModifier.ControlModifier]: 
            return 'subtract'
        
        # 2. 如果没有按键，检查工具和全局模式
   
        # 2a. 检查是否正在使用 "减去" 工具
        if self._current_tool in ["lasso_subtract", "polygon_subtract"]:
            return 'subtract'
    
        # 2b. 检查是否开启了 "添加模式" (来自平板用户的需求)
        if self.model.selection_add_mode:
            # 如果 "添加模式" 开启，则 "lasso" 和 "polygon" 工具的默认行为是 'add'
            if self._current_tool in ["lasso", "polygon"]:
                return 'add'
            
        # 3. 默认是 'new' (套索+ 或 多边形+)
        # (Shift键会将其变为 'add', 已在第1步处理)
        return 'new'
        # --- END: 重写此方法 ---

    def _end_drawing(self, commit_selection=True):
        if not self._is_drawing_selection or self._current_tool not in ['lasso', 'polygon','lasso_subtract', 'polygon_subtract']:
            if self._current_tool != 'erase':
                 self._is_drawing_selection = False
            return
        
        # --- START: 移动 Undo 点 ---
        self.push_undo_state() # 在即将修改路径前记录状态
        # --- END: 移动 Undo 点 ---
        try:
            if commit_selection and len(self._temp_drawing_points) >= 3:
                # ... (内部逻辑无变化) ...
                poly = QPolygonF(self._temp_drawing_points)
                new_drawn_path = QPainterPath()
                new_drawn_path.addPolygon(poly)
                new_drawn_path.closeSubpath()
                modifier = self._get_current_modifier()
                candidate_path = QPainterPath()
                if modifier == 'new': candidate_path = new_drawn_path
                elif modifier == 'add': candidate_path = self._selection_path.united(new_drawn_path)
                elif modifier == 'subtract': candidate_path = self._selection_path.subtracted(new_drawn_path)
                if modifier == 'subtract' and candidate_path.isEmpty():
                    self._selection_path = QPainterPath()
                else:
                    if self._original_pixmap and not self._original_pixmap.isNull():
                        is_valid, final_path = self.image_manager.process_selection_path(candidate_path, self._original_pixmap.size())
                        if not is_valid:
                            QMessageBox.warning(self, "提示", "选区未覆盖有效像素，操作无效。")
                            self.undo() # 操作无效，自动撤销
                        else:
                            self._selection_path = final_path
                self.model.mask_updated.emit()

                # 加入自动保存逻辑
                if self.model.auto_save:
                    self.save_current_mask()
            
        finally:
            if self._mode_before_drawing is not None:
                self.model.set_display_mode(self._mode_before_drawing)
                self._mode_before_drawing = None
            self._is_drawing_selection = False
            self._temp_drawing_points = []
            self.scene.update()

    def _apply_eraser(self, scene_pos: QPointF):
        if self._erasing_image is None: return
        # size = self.model.config['Drawing'].getint('eraser_size', 10)
        size = self.model.eraser_size
        radius = size / 2.0
        painter = QPainter(self._erasing_image)
        painter.setBrush(Qt.GlobalColor.black)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(scene_pos, radius, radius)
        painter.end()
        
        base_pixmap = self._original_item.pixmap()
        if not base_pixmap: return
        temp_mask_pixmap = QPixmap.fromImage(self._erasing_image)
        preview_pixmap = self.image_manager.create_overlay_pixmap(base_pixmap, temp_mask_pixmap, 'contour', (0,255,0,128), 1, self.model.mask_invert)
        self._original_item.setPixmap(preview_pixmap)

    def _end_erasing(self):
        if self._erasing_image is None: return
        
        # --- START: 移动 Undo 点 ---
        self.push_undo_state()
        # --- END: 移动 Undo 点 ---
        try:
            final_mask_pixmap = QPixmap.fromImage(self._erasing_image)
            new_path = self.image_manager.create_path_from_mask(final_mask_pixmap)
            if self._selection_path == new_path: # 如果路径没变
                self.undo() # 自动撤销，因为没有产生有效操作
            else:
                self._selection_path = new_path

            self.model.mask_updated.emit()
            
            # 自动保存
            if self.model.auto_save:
                self.save_current_mask()

        finally:
            if self._mode_before_drawing is not None:
                self.model.set_display_mode(self._mode_before_drawing)
                self._mode_before_drawing = None
            self._is_drawing_selection = False
            self._erasing_image = None
            self.scene.update()

    # --- START: 新增取消方法 ---
    def _cancel_drawing(self):
        """取消当前的绘制或擦除操作。"""
        print("Drawing cancelled by user.")
        try:
            # 恢复到操作前的视觉状态
            self.update_selection_display()
        finally:
            # 恢复显示模式
            if self._mode_before_drawing is not None:
                self.model.set_display_mode(self._mode_before_drawing)
                self._mode_before_drawing = None

            # 清理所有状态
            self._is_drawing_selection = False
            self._temp_drawing_points = []
            self._erasing_image = None
            self.scene.update() # 清除所有前景绘制（如辅助线）
    # --- END: 新增取消方法 ---
    
    def drawForeground(self, painter, rect):
        # ... (此方法内部无变化) ...
        super().drawForeground(painter, rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        current_scale = self.transform().m11()
        pen_width = 1.0 / current_scale

        if self._is_drawing_selection and self._current_tool in ['lasso', 'polygon', 'lasso_subtract', 'polygon_subtract'] and self._temp_drawing_points:
            pen = QPen(Qt.GlobalColor.cyan, pen_width, Qt.PenStyle.DotLine)
            painter.setPen(pen)
            points_f = self._temp_drawing_points
            if len(points_f) > 1:
                painter.drawPolyline(QPolygonF(points_f))
            if self._current_tool == 'polygon' or self._current_tool == 'polygon_subtract' and self.underMouse():
                mouse_pos = self.mapToScene(self.mapFromGlobal(QCursor.pos()))
                painter.drawLine(points_f[-1], mouse_pos)
        
        if self.model.display_mode == 'ants' and not self._selection_path.isEmpty():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            dash_length = 5.0
            dash_period = dash_length * 2.0
            offset = (QDateTime.currentMSecsSinceEpoch() / 150.0) % dash_period
            pen_black = QPen(Qt.GlobalColor.black, pen_width, Qt.PenStyle.CustomDashLine)
            pen_black.setDashPattern([dash_length, dash_length])
            pen_black.setDashOffset(offset)
            pen_white = QPen(Qt.GlobalColor.white, pen_width, Qt.PenStyle.CustomDashLine)
            pen_white.setDashPattern([dash_length, dash_length])
            pen_white.setDashOffset(offset - dash_length)
            painter.setPen(pen_black)
            painter.drawPath(self._selection_path)
            painter.setPen(pen_white)
            painter.drawPath(self._selection_path)

        if self._current_tool == 'erase' and self.underMouse() and not self._is_panning:
            # size = self.model.config['Drawing'].getint('eraser_size', 10)
            size = self.model.eraser_size
            radius = size / 2.0
            pos = self.mapToScene(self.mapFromGlobal(QCursor.pos()))
            painter.setPen(QPen(Qt.GlobalColor.white, pen_width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(pos, radius, radius)
            
    def update_cursor(self):
        # ... (此方法内部无变化) ...
        if self._is_panning:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if self._current_tool == 'erase':
            self.setCursor(Qt.CursorShape.BlankCursor)
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            return
        if self.model.display_mode != 'ants' and not self._is_drawing_selection:
             self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
             self.setCursor(Qt.CursorShape.OpenHandCursor)
             return
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        modifier = self._get_current_modifier()
        if modifier == 'add': self.setCursor(self.cursors['add'])
        elif modifier == 'subtract': self.setCursor(self.cursors['subtract'])
        else: self.setCursor(self.cursors['default'])

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        self.update_cursor()

    def keyReleaseEvent(self, event):
        super().keyReleaseEvent(event)
        self.update_cursor()
        
    def enterEvent(self, event):
        super().enterEvent(event)
        self.update_cursor()

    # @pyqtSlot(bool)
    # def set_high_contrast(self, enabled):
    #     self._contrast_pixmap = None  # 切换高对比度时，使缓存失效
    #     self.update_selection_display()

    def update_display_pixmap(self):
        """根据模型状态（原图/去噪/高对比度）更新显示的底图。"""
        # 1. 根据 self.model.show_denoised 决定基础图像
        active_base_pixmap = self._original_pixmap
        if self.model.show_denoised and self._denoised_pixmap:
            active_base_pixmap = self._denoised_pixmap

       # 2. 检查是否有效果需要应用
        settings = self.model.effect_settings
        if settings.get('manual_enabled', False) or settings.get('algo_enabled', False):
            # 应用效果
            effects_pixmap = self.image_manager.apply_image_effects(active_base_pixmap, settings)
            self._original_item.setPixmap(effects_pixmap)
        else:
            # 否则直接显示基础图像
            self._original_item.setPixmap(active_base_pixmap)

    @pyqtSlot()
    def on_image_source_changed(self):
        """响应模型发出的底图切换信号"""
        self._contrast_pixmap = None  # 底图已变，高对比度缓存必须失效
        self.update_selection_display() # 重新绘制所有内容

    @pyqtSlot(str)
    def set_tool(self, tool):
        if self._is_drawing_selection:
            if self._current_tool in ['lasso', 'polygon', 'lasso_subtract', 'polygon_subtract']:
                self._cancel_drawing() # 切换工具时取消当前绘制
            elif self._current_tool == 'erase':
                self._end_erasing()
        self._current_tool = tool
        self.update_cursor()

    def clear_current_selection(self):
        if not self._selection_path.isEmpty():
            self.push_undo_state()
            self._selection_path = QPainterPath()
            self.model.mask_updated.emit()
            if self.model.auto_save:
                self.save_current_mask()
        self.setFocus()
            
    def save_current_mask(self):
        index = self.model.current_index
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
        if last_state is not None:
            self._selection_path = last_state
            self.model.mask_updated.emit()

            # 自动保存
            if self.model.auto_save:
                self.save_current_mask()

            print("Undo successful.")
    
    @pyqtSlot()
    def on_effects_changed(self):
        """当正式效果参数改变时，刷新画布"""
        self.update_selection_display()

    @pyqtSlot()
    def on_preview_effects_changed(self):
        """当预览效果参数改变时，实时刷新画布"""
        active_base_pixmap = self._denoised_pixmap if self.model.show_denoised and self._denoised_pixmap else self._original_pixmap
        if not active_base_pixmap:
            return

        preview_settings = self.model.preview_effect_settings
        preview_pixmap = self.image_manager.apply_image_effects(active_base_pixmap, preview_settings)

        # 直接更新显示的pixmap，但不更新缓存
        self._original_item.setPixmap(preview_pixmap)
        # 如果有选区，需要重新绘制叠加层
        self.update_selection_display(base_pixmap_for_overlay=preview_pixmap)

    def push_undo_state_for_effects(self):
        """为效果更改专门记录撤销状态（待实现）"""
        # 注意：当前项目的撤销系统是基于 QPainterPath 的，
        # 要想让效果也能撤销，需要扩展撤销系统来保存 _effect_settings 字典。
        # 这是一个更复杂的重构，暂时打印一条消息。
        print("记录效果更改到撤销栈（功能待扩展）")

# 同时需要稍微修改 update_selection_display 接收一个可选参数
# 找到 def update_selection_display(self):
# 修改为 def update_selection_display(self, base_pixmap_for_overlay=None):
# 在该函数内部，找到 base_pixmap = self._original_item.pixmap()
# 修改为 base_pixmap = base_pixmap_for_overlay if base_pixmap_for_overlay else self._original_item.pixmap()