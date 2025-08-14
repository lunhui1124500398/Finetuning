from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QMessageBox
from PyQt6.QtCore import Qt, pyqtSlot, QPointF
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QBrush, QCursor #引入qcursor
import os

class ImageCanvas(QGraphicsView):
    """核心画布，用于显示和编辑图像/Mask。"""
    def __init__(self, model, image_manager, parent=None):
        super().__init__(parent)
        self.model = model
        self.image_manager = image_manager
        self._original_pixmap = None # 保存未经修改的原始Pixmap
        self._contrast_pixmap = None # 保存高对比度后的Pixmap
        self._mask_pixmap = None
        
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        # 图像和Mask的图元
        self._original_item = QGraphicsPixmapItem()
        self._mask_item = QGraphicsPixmapItem()
        self.scene.addItem(self._original_item)
        self.scene.addItem(self._mask_item)

        # 内部状态
        self._mask_pixmap = None
        self._is_drawing = False
        self.last_draw_point = None

        # --- B4. 初始化光标 ---
        self.draw_cursor = QCursor(Qt.CursorShape.CrossCursor)
        self.erase_cursor = QCursor(Qt.CursorShape.PointingHandCursor) # 可自定义
        self.setCursor(self.draw_cursor) # 默认

        self.init_ui()

    def init_ui(self):
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    @pyqtSlot(int)
    def load_image(self, index):
        if index < 0:
            self.scene.clear()
            self._original_item = QGraphicsPixmapItem()
            self._mask_item = QGraphicsPixmapItem()
            self.scene.addItem(self._original_item)
            self.scene.addItem(self._mask_item)
            return
        
        # (V3.0新增) 重置缓存
        self._contrast_pixmap = None

        # 加载原图
        original_path = self.model._original_files[index]
        self._original_pixmap = self.image_manager.load_pixmap(original_path)
        if not self._original_pixmap:
            print(f"Failed to load original image: {original_path}")
            return
        
        # self._original_item.setPixmap(original_pixmap)
        # 根据高对比度状态决定显示哪个pixmap
        self.update_display_pixmap()

        # 加载或创建Mask
        if self.model._mask_files and index < len(self.model._mask_files):
            self._mask_pixmap = self.image_manager.load_pixmap(self.model._mask_files[index])
        
        # 如果没有加载到mask，或者mask尺寸不对，就创建一个新的
        if self._mask_pixmap is None or self._mask_pixmap.size() != self._original_pixmap.size():
            self._mask_pixmap = QPixmap(self._original_pixmap.size())
            self._mask_pixmap.fill(Qt.GlobalColor.black)

        self.update_mask_item()
        
        self.setSceneRect(self._original_item.boundingRect())
        # fitInView应该在显示后调用，可以移到showEvent中或在需要时手动调用
        self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
    
    @pyqtSlot(bool)
    def set_high_contrast(self, enabled):
        """响应高对比度模式切换"""
        self.update_display_pixmap()
        self.update() # 强制重绘

    def update_display_pixmap(self):
        """根据高对比度状态更新主画布显示的图像"""
        if self.model.high_contrast:
            if not self._contrast_pixmap: # 如果还没有生成过，就生成一次
                self._contrast_pixmap = self.image_manager.apply_clahe(self._original_pixmap)
            self._original_item.setPixmap(self._contrast_pixmap)
        else:
            self._original_item.setPixmap(self._original_pixmap)

    @pyqtSlot(bool)
    def set_mask_visibility(self, visible):
        self._mask_item.setVisible(visible)

    
    @pyqtSlot(str)
    def set_drawing_mode(self, mode):
        """响应工具切换，改变光标"""
        if mode == "draw":
            self.setCursor(self.draw_cursor)
        else:
            self.setCursor(self.erase_cursor)

    def update_mask_item(self):
        if not self.model.show_mask or not self._mask_pixmap:
            self._mask_item.setPixmap(QPixmap())
            return

        # 从配置中获取颜色和样式
        style = self.model.mask_display_style
        invert = self.model.mask_invert

        area_color_str = self.model.config['Colors'].get('mask_overlay_color', '255,0,0,100')
        area_color_rgba = tuple(map(int, area_color_str.split(',')))

        contour_color_str = self.model.config['Colors'].get('contour_line_color', '0,255,0,255')
        contour_color_rgba = tuple(map(int, contour_color_str.split(',')))

        # (新增) 为内轮廓获取颜色，如果未定义，则使用与外轮廓相同的颜色
        inner_color_str = self.model.config['Colors'].get('inner_contour_color', contour_color_str)
        inner_color_rgba = tuple(map(int, inner_color_str.split(',')))

        thickness = self.model.config['Colors'].getint('contour_thickness', 2)

        # 创建一个透明的底图用于叠加
        base_pixmap = QPixmap(self._mask_pixmap.size())
        base_pixmap.fill(Qt.GlobalColor.transparent)

        # 直接调用 image_manager 的强大方法
        final_overlay = self.image_manager.create_overlay_pixmap(
            base_pixmap,
            self._mask_pixmap,
            style,
            area_color_rgba if style == 'area' else contour_color_rgba,
            thickness,
            invert,
            inner_color_rgba
        )

        self._mask_item.setPixmap(final_overlay)
        
    def wheelEvent(self, event):
        """鼠标滚轮缩放"""
        zoom_in_factor = 1.25
        zoom_out_factor = 1 / zoom_in_factor
        
        if event.angleDelta().y() > 0:
            self.scale(zoom_in_factor, zoom_in_factor)
        else:
            self.scale(zoom_out_factor, zoom_out_factor)

    # In /ui/widgets/image_canvas.py

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._original_item.pixmap():
            self._is_drawing = True
            self.setDragMode(QGraphicsView.DragMode.NoDrag) # (新增) 禁用拖拽
            # (新增) 在绘图开始时记录撤销状态
            self.push_undo_state() # <-- B.8中会实现
            # 记录下笔点，但不记录上一个点
            self.last_draw_point = None 
            self.draw_on_mask(event.pos())
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_drawing and self._original_item.pixmap():
            self.draw_on_mask(event.pos())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._is_drawing: #确保是我们自己的绘图事件
            self._is_drawing = False
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag) # (新增) 恢复拖拽
            # 如果开启了自动保存，则在鼠标释放时触发
            if self.model.auto_save:
                self.save_current_mask()
            self.last_draw_point = None # (新增) 抬笔后重置
        else:
            super().mouseReleaseEvent(event)

    def draw_on_mask(self, view_pos):
        scene_pos = self.mapToScene(view_pos)
        item_pos = self._original_item.mapFromScene(scene_pos)

        brush_size = self.model.config['Drawing'].getint('brush_size', 10) # 减小默认值

        painter = QPainter(self._mask_pixmap)

        # (修改) 设置画笔，不再需要设置Brush
        color = Qt.GlobalColor.white if self.model.drawing_mode == "draw" else Qt.GlobalColor.black
        pen = QPen(color, brush_size, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        # (修改) 从画点改为画线，实现平滑绘制
        if self.last_draw_point:
            painter.drawLine(self.last_draw_point, item_pos)
        else: # 如果是第一个点，就只画一个点
            painter.drawPoint(item_pos)

        self.last_draw_point = item_pos # 更新上一个点的位置

        painter.end()

        self.update_mask_item()
        self.model.mask_updated.emit()
    
    def clear_current_mask(self):
        if self._mask_pixmap:
            # (新增) 在清除前记录撤销状态
            self.push_undo_state() # <-- B.8中会实现
            self._mask_pixmap.fill(Qt.GlobalColor.black)
            self.update_mask_item()
            self.model.mask_updated.emit()
            if self.model.auto_save:
                self.save_current_mask()
            self.setFocus() #(新增)清楚后恢复焦点
                
    def save_current_mask(self):
        index = self.model.current_index
        if index < 0 or not self._mask_pixmap:
            return
            
        # START: 修正 - 从模型获取保存路径
        mask_dir = self.model.get_path('save_path')
        if not mask_dir:
            # 现在QMessageBox已经被正确导入，可以正常使用了
            QMessageBox.warning(self, "保存失败", "请在路径设置中指定有效的“保存路径”！")
            self.setFocus() # (新增) 即使失败也要恢复焦点
            return
        
        # 从原图文件名生成mask文件名
        original_filename = os.path.basename(self.model._original_files[index])
        mask_filename = os.path.splitext(original_filename)[0] + '.png'
        save_path = os.path.join(mask_dir, mask_filename)
        
        self.image_manager.save_pixmap(self._mask_pixmap, save_path)
        print(f"Mask saved to {save_path}")
        self.setFocus() # (新增) 保存成功后也要恢复焦点

    # 推入栈
    def push_undo_state(self):
        if self._mask_pixmap:
            self.model.push_undo_state(self.model.current_index, self._mask_pixmap)
    
    def undo(self):
        last_state = self.model.pop_undo_state(self.model.current_index)
        if last_state:
            # (可选) 将当前状态推入redo栈
            # self.model.push_redo_state(self.model.current_index, self._mask_pixmap)

            self._mask_pixmap = last_state
            self.update_mask_item()
            self.model.mask_updated.emit()
            print("Undo successful.")