# Finetuning/ui/widgets/image_canvas.py

from PyQt6.QtWidgets import QApplication, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QMessageBox, QGraphicsPathItem
from PyQt6.QtCore import Qt, pyqtSlot, QPointF, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QCursor, QPainterPath, QPolygonF, QImage
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
        # 【新增 Q4】用于标记鼠标是否悬浮在画布上准备绘图        
        self._is_hovering_to_draw = False
        
        # 蚂蚁线动画
        self.ant_offset = 0
        self.ant_timer = QTimer(self)
        self.ant_timer.timeout.connect(self.animate_ants)
        self.ant_timer.start(100)
        
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

        # 将视口更新模式设置为 FullViewportUpdate
        # 这会强制在场景发生任何变化时重绘整个视口，修复局部刷新不完整的问题
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        # 禁用缓存，确保每次都重新绘制图元，而不是使用可能过期的缓存版本
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheNone)

    @pyqtSlot(int)
    def load_image(self, index):
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

        original_path = self.model._original_files[index]
        self._original_pixmap = self.image_manager.load_pixmap(original_path)
        if not self._original_pixmap:
            print(f"Failed to load original image: {original_path}")
            return
        
        self.update_display_pixmap()

        # 加载参考Mask (用于显示)
        self._current_mask_pixmap = None
        if self.model._mask_files and index < len(self.model._mask_files):
            self._current_mask_pixmap = self.image_manager.load_pixmap(self.model._mask_files[index])
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
                 self._selection_path = self.image_manager.convert_mask_to_path(self._current_mask_pixmap)

        # 3. Mask不显示 -> 自动显示
        if not self.model.show_mask:
            self.model.set_show_mask(True)
            if self._selection_path.isEmpty():
                 self._current_mask_pixmap.fill(Qt.GlobalColor.black) # 确保是一个空图层

        # 4. 统一更新显示
        self.update_selection_display()

    def update_selection_display(self):
        """统一更新画布上的所有遮罩和选区显示"""
        if not self.model.show_mask or not self._original_pixmap:
            self._mask_overlay_item.setPixmap(QPixmap())
            self._selection_item.setPath(QPainterPath())
            return

        # 1. 更新传统的颜色叠加/轮廓 (用于参考)
        style = self.model.mask_display_style
        self.update_display_pixmap()
        # 确保原始图像被显示
        # self._original_item.setPixmap(self._original_pixmap)

        if style == "area":
            self._selection_item.setPath(QPainterPath()) # 面积模式不显示蚂蚁线
            area_color_str = self.model.config['Colors'].get('mask_overlay_color', '255,0,0,100')
            area_color_rgba = tuple(map(int, area_color_str.split(',')))
            
            # 从当前选区路径生成用于显示的pixmap
            mask_pixmap = self.get_pixmap_from_path()

            # 【修复 Q1】创建一个透明背景板，而不是默认的黑色背景
            transparent_bg = QPixmap(self._original_pixmap.size())
            transparent_bg.fill(Qt.GlobalColor.transparent)

            overlay = self.image_manager.create_overlay_pixmap(
                transparent_bg, mask_pixmap, 'area', area_color_rgba,
                invert=self.model.mask_invert
            )
            self._mask_overlay_item.setPixmap(overlay)
        else: # contour 模式
            self._mask_overlay_item.setPixmap(QPixmap()) # 轮廓模式用蚂蚁线代替
            # # 2. 更新蚂蚁线选区
            # pen_white = QPen(Qt.GlobalColor.white, 1, Qt.PenStyle.CustomDashLine)
            # pen_white.setDashPattern([5, 5])
            # pen_white.setDashOffset(self.ant_offset)
            # 蚂蚁线效果需要双层画笔
            # QGraphicsPathItem 只支持一个pen, 我们在paint里自己画
            self._selection_item.setPath(self._selection_path)
            self.scene.update()

            # # [调试用]
            # self._mask_overlay_item.setPixmap(QPixmap()) # 清空旧的叠加
            # # 从配置文件读取颜色和粗细
            # contour_color_str = self.model.config['Colors'].get('contour_line_color', '0,255,0,255')
            # contour_color_rgba = tuple(map(int, contour_color_str.split(',')))
            # contour_thickness = self.model.config['Colors'].getint('contour_thickness', 1)
            # # 调用 image_manager 来创建包含轮廓的 Pixmap
            # # 注意：这里 original_pixmap 我们传一个空的，因为我们只想得到轮廓层
            # # self._current_mask_pixmap 是我们想要处理的二值图
            # # 创建一个保证透明的背景板
            # transparent_bg = QPixmap(self._original_pixmap.size())
            # transparent_bg.fill(Qt.GlobalColor.transparent)

            # overlay_pixmap = self.image_manager.create_overlay_pixmap(
            #     transparent_bg,  # 一个透明的背景
            #     self._current_mask_pixmap,              # 包含形状的二值图
            #     'contour',
            #     contour_color_rgba,
            #     contour_thickness
            # )
            # if overlay_pixmap and not overlay_pixmap.isNull():
            #      debugger.save_image(overlay_pixmap, "3_final_pixmap_before_display")
            #  # 将这个最终的 Pixmap 设置到图元上
            # self._mask_overlay_item.setPixmap(overlay_pixmap)
            # self._selection_item.setPath(QPainterPath())

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
        
    def animate_ants(self):
        self.ant_offset = (self.ant_offset + 1) % 10
        if self.model.mask_display_style == 'contour':
            # 触发 QGraphicsPathItem 的重绘
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
        if self._is_drawing_selection and event.button() == Qt.MouseButton.RightButton:
            self._end_drawing(commit_selection=False)
            event.accept()
            return
        
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
        if not self._is_drawing_selection: return

        if commit_selection and len(self._temp_drawing_points) >= 3:
            poly = QPolygonF(self._temp_drawing_points)
            path = QPainterPath()
            path.addPolygon(poly)
            path.closeSubpath()
            
            modifier = self._get_current_modifier()
            if modifier == 'new':
                self._selection_path = path
            elif modifier == 'add':
                self._selection_path = self._selection_path.united(path)
            elif modifier == 'subtract':
                self._selection_path = self._selection_path.subtracted(path)
            
            self.model.mask_updated.emit()

        self._is_drawing_selection = False
        self._temp_drawing_points = []
        self.scene.update()

    # --- 覆盖 paintEvent 来绘制临时的线和蚂蚁线 ---
    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制正在进行中的选区线 (如多边形的橡皮筋)
        if self._is_drawing_selection and self._temp_drawing_points:
            pen = QPen(Qt.GlobalColor.cyan, 1 / self.transform().m11(), Qt.PenStyle.DotLine)
            painter.setPen(pen)
            
            points_f = self._temp_drawing_points
            if len(points_f) > 1:
                painter.drawPolyline(QPolygonF(points_f))
            
            if self._current_tool == 'polygon' and self.underMouse():
                 mouse_pos = self.mapToScene(self.mapFromGlobal(QCursor.pos()))
                 painter.drawLine(points_f[-1], mouse_pos)
        
        # 绘制蚂蚁线 (重写此部分以获得双色效果)
        if self.model.show_mask and self.model.mask_display_style == 'contour' and not self._selection_path.isEmpty():
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            
            # 【修改】如果鼠标悬浮准备绘制，且当前未在绘制中，则显示半透明轮廓
            if self._is_hovering_to_draw and not self._is_drawing_selection:
                contour_color_str = self.model.config['Colors'].get('contour_line_color', '0,255,0,255')
                r, g, b, a = map(int, contour_color_str.split(','))
                pen = QPen(QColor(r, g, b, 128), 1 / self.transform().m11()) # 半透明
                painter.setPen(pen)
                painter.drawPath(self._selection_path)
            else: # 否则，绘制正常的蚂蚁线
                painter.setBrush(Qt.BrushStyle.NoBrush)
                pen_black = QPen(Qt.GlobalColor.black, 1 / self.transform().m11(), Qt.PenStyle.CustomDashLine)
                pen_black.setDashPattern([5, 5])
                pen_black.setDashOffset(self.ant_offset + 5)
              
                pen_white = QPen(Qt.GlobalColor.white, 1 / self.transform().m11(), Qt.PenStyle.CustomDashLine)
                pen_white.setDashPattern([5, 5])
                pen_white.setDashOffset(self.ant_offset)

                painter.setPen(pen_black)
                painter.drawPath(self._selection_path)
                painter.setPen(pen_white)
                painter.drawPath(self._selection_path)
            painter.restore()

    def update_cursor(self):
        if self._is_panning:
             self.setCursor(Qt.CursorShape.ClosedHandCursor)
             return
        if self.model.mask_display_style == 'area' or self._current_tool not in ["lasso", "polygon", "erase"]:
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

        if self._original_pixmap and self.model.selection_tool in ["lasso", "polygon", "erase"]:
            style = self.model.mask_display_style
            is_hidden = not self.model.show_mask

        if style == 'area' or is_hidden:
            self._selection_path = QPainterPath()  # 确保在进入时清空选区路径
            if self._current_mask_pixmap:
                self._current_mask_pixmap.fill(Qt.GlobalColor.black)  # 确保是一个空图层
            self.update_selection_display()
            self.model.mask_updated.emit()

        elif style == 'contour':
            self._is_hovering_to_draw = True
            self.scene.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        # 鼠标离开取消高亮
        if self._is_hovering_to_draw:
            self._is_hovering_to_draw = False
            self.scene.update()

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