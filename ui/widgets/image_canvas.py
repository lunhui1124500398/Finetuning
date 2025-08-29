# Finetuning/ui/widgets/image_canvas.py

from PyQt6.QtWidgets import QApplication, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QMessageBox, QGraphicsPathItem
from PyQt6.QtCore import Qt, pyqtSlot, QPointF, pyqtSignal, QTimer, QRectF, QDateTime
from PyQt6.QtGui import (
    QPixmap, QPainter, QPen, QColor, QCursor, QPainterPath, 
    QPolygonF, QImage, QPainterPathStroker
)
import os
from Finetuning.utils.debugger import debugger

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
        self._selection_item = QGraphicsPathItem() # 仅用于蚂蚁线
        self._mask_overlay_item = QGraphicsPixmapItem() # 废弃，逻辑合并到_original_item
        
        self._selection_item.setPen(QPen(Qt.PenStyle.NoPen))

        self.scene.addItem(self._original_item)
        self.scene.addItem(self._selection_item)

        self._original_pixmap = None
        self._contrast_pixmap = None
        self._current_mask_pixmap = None

        self._selection_path = QPainterPath()
        self._temp_drawing_points = []
        self._current_tool = 'lasso'
        self._is_drawing_selection = False
        self._is_panning = False
        self._pan_start_pos = QPointF()
        
        # --- START: 新增状态，用于模式切换 ---
        self._mode_before_drawing = None
        # --- END: 新增状态 ---
        
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

    def init_ui(self):
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheNone)

    @pyqtSlot(int)
    def load_image(self, index):
        debugger.log(f"--- Loading image index: {index} ---")

        if index < 0:
            self.scene.clear()
            self._original_item = QGraphicsPixmapItem()
            self._selection_item = QGraphicsPathItem()
            self.scene.addItem(self._original_item)
            self.scene.addItem(self._selection_item)
            return
        
        self._contrast_pixmap = None
        self._is_drawing_selection = False
        self._temp_drawing_points = []
        self._selection_path = QPainterPath()
        self._current_mask_pixmap = None

        original_path = self.model._original_files[index]
        self._original_pixmap = self.image_manager.load_pixmap(original_path)
        if not self._original_pixmap:
            print(f"Failed to load original image: {original_path}")
            return
        
        self.update_display_pixmap()

        mask_pixmap = None
        if self.model._mask_files and index < len(self.model._mask_files):
            mask_pixmap = self.image_manager.load_pixmap(self.model._mask_files[index])
        
        if mask_pixmap and not mask_pixmap.isNull():
            self._selection_path = self.image_manager.create_path_from_mask(mask_pixmap)
        
        self.update_selection_display()
        self.setSceneRect(self._original_item.boundingRect())
        self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.scene.update()

    # --- START: 重构 update_selection_display ---
    @pyqtSlot()
    def update_selection_display(self):
        """根据模型当前的 display_mode 更新画布显示"""
        self.update_display_pixmap() # 恢复干净的底图
        self._selection_item.setPath(QPainterPath()) # 默认清除蚂蚁线

        mode = self.model.display_mode
        if mode == "hide" or not self._original_pixmap:
            return

        base_pixmap = self._original_item.pixmap()
        if not base_pixmap or base_pixmap.isNull(): return

        if mode == "ants":
            self._selection_item.setPath(self._selection_path) # 只显示蚂蚁线
            return

        # 对于 area 和 contour 模式，我们需要生成合成图
        mask_pixmap = self.get_pixmap_from_path()
        if not mask_pixmap or mask_pixmap.isNull():
            return
        
        if mode == "area":
            style = 'area'
            color_str = self.model.config['Colors'].get('mask_overlay_color', '255,0,0,80')
            thickness = 1
        elif mode == "contour":
            style = 'contour'
            color_str = self.model.config['Colors'].get('contour_line_color', '0,255,0,128')
            thickness = self.model.config['Colors'].getint('contour_thickness', 1)
        else:
            return

        color_rgba = tuple(map(int, color_str.split(',')))

        composite_pixmap = self.image_manager.create_overlay_pixmap(
            base_pixmap,
            mask_pixmap,
            style,
            color_rgba,
            contour_thickness=thickness,
            invert=self.model.mask_invert
        )
        self._original_item.setPixmap(composite_pixmap)
    # --- END: 重构 update_selection_display ---

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

    # --- 事件处理 ---
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

    # --- START: 修改 mousePressEvent 以自动切换模式 ---
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

        # 【核心】自动进入绘制模式
        if not self._is_drawing_selection:
            self._mode_before_drawing = self.model.display_mode
            if self._mode_before_drawing != 'ants':
                self.model.set_display_mode('ants')

        self.push_undo_state()
        self._is_drawing_selection = True
        scene_pos = self.mapToScene(event.pos())

        if self._current_tool in ['lasso', 'erase']:
            self._temp_drawing_points = [scene_pos]
        elif self._current_tool == 'polygon':
            if len(self._temp_drawing_points) > 1 and \
               (scene_pos - self._temp_drawing_points[0]).manhattanLength() < 15 / self.transform().m11():
                self._end_drawing(commit_selection=True)
            else:
                self._temp_drawing_points.append(scene_pos)
        
        self.scene.update()
        event.accept()
    # --- END: 修改 mousePressEvent ---

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
        
        if self._is_drawing_selection and self._current_tool in ['lasso', 'erase']:
            self._temp_drawing_points.append(scene_pos)
        
        self.scene.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = False
            self.update_cursor()
            event.accept()
            return

        if self._is_drawing_selection and self._current_tool in ['lasso', 'erase']:
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

    # --- START: 修改 _end_drawing 以自动恢复模式 ---
    def _end_drawing(self, commit_selection=True):
        if not self._is_drawing_selection:
            return

        try: # 使用 try...finally 确保模式总能被恢复
            if commit_selection and len(self._temp_drawing_points) >= 3:
                poly = QPolygonF(self._temp_drawing_points)
                new_drawn_path = QPainterPath()
                new_drawn_path.addPolygon(poly)
                new_drawn_path.closeSubpath()

                modifier = self._get_current_modifier()
                candidate_path = QPainterPath()
                if modifier == 'new':
                    candidate_path = new_drawn_path
                elif modifier == 'add':
                    candidate_path = self._selection_path.united(new_drawn_path)
                elif modifier == 'subtract':
                    candidate_path = self._selection_path.subtracted(new_drawn_path)

                if modifier == 'subtract' and candidate_path.isEmpty():
                    self._selection_path = QPainterPath()
                else:
                    if self._original_pixmap and not self._original_pixmap.isNull():
                        is_valid, final_path = self.image_manager.process_selection_path(
                            candidate_path, self._original_pixmap.size()
                        )
                        if not is_valid:
                            QMessageBox.warning(self, "提示", "选区未覆盖有效像素，操作无效。")
                        else:
                            self._selection_path = final_path
                
                # 【核心】在恢复模式前，先发射信号让预览等更新
                self.model.mask_updated.emit()
        finally:
            # 【核心】无论成功与否，都恢复之前的显示模式
            if self._mode_before_drawing is not None:
                self.model.set_display_mode(self._mode_before_drawing)
                self._mode_before_drawing = None
            
            # 重置绘制状态
            self._is_drawing_selection = False
            self._temp_drawing_points = []
            self.scene.update()
    # --- END: 修改 _end_drawing ---
    
    # --- START: 修改 drawForeground ---
    def drawForeground(self, painter, rect):
        """此方法现在只负责绘制临时的编辑线和最上层的蚂蚁线"""
        super().drawForeground(painter, rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        current_scale = self.transform().m11()
        pen_width = 1.0 / current_scale

        # 绘制正在进行中的选区线 (橡皮筋)
        if self._is_drawing_selection and self._temp_drawing_points:
            pen = QPen(Qt.GlobalColor.cyan, pen_width, Qt.PenStyle.DotLine)
            painter.setPen(pen)
            points_f = self._temp_drawing_points
            if len(points_f) > 1:
                painter.drawPolyline(QPolygonF(points_f))
            if self._current_tool == 'polygon' and self.underMouse():
                mouse_pos = self.mapToScene(self.mapFromGlobal(QCursor.pos()))
                painter.drawLine(points_f[-1], mouse_pos)
        
        # 【核心】只在 display_mode 为 'ants' 时绘制蚂蚁线
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
    # --- END: 修改 drawForeground ---
            
    def update_cursor(self):
        if self._is_panning:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        # 在查看模式下，总是允许拖动
        if self.model.display_mode != 'ants' and not self._is_drawing_selection:
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

    # --- 公共方法 (无大变动) ---
    @pyqtSlot(bool)
    def set_high_contrast(self, enabled):
        self.update_display_pixmap()
        # 高对比度变化后需要刷新整个显示
        self.update_selection_display()

    def update_display_pixmap(self):
        if self.model.high_contrast:
            if not self._contrast_pixmap:
                self._contrast_pixmap = self.image_manager.apply_clahe(self._original_pixmap)
            self._original_item.setPixmap(self._contrast_pixmap)
        else:
            self._original_item.setPixmap(self._original_pixmap)

    @pyqtSlot(str)
    def set_tool(self, tool):
        self._end_drawing(commit_selection=False)
        self._current_tool = tool
        self.update_cursor()

    def clear_current_selection(self):
        if not self._selection_path.isEmpty():
            self.push_undo_state()
            self._selection_path = QPainterPath()
            self.model.mask_updated.emit() # 发射信号以更新UI
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
            print("Undo successful.")