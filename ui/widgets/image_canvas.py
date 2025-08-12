from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem
from PyQt6.QtCore import Qt, pyqtSlot, QPointF
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QBrush

class ImageCanvas(QGraphicsView):
    """核心画布，用于显示和编辑图像/Mask。"""
    def __init__(self, model, image_manager, parent=None):
        super().__init__(parent)
        self.model = model
        self.image_manager = image_manager
        
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

        # 加载原图
        original_path = self.model._original_files[index]
        original_pixmap = self.image_manager.load_pixmap(original_path)
        if not original_pixmap:
            print(f"Failed to load original image: {original_path}")
            return
        
        self._original_item.setPixmap(original_pixmap)
        
        # 加载或创建Mask
        if self.model._mask_files and index < len(self.model._mask_files):
            self._mask_pixmap = self.image_manager.load_pixmap(self.model._mask_files[index])
        
        # 如果没有加载到mask，或者mask尺寸不对，就创建一个新的
        if self._mask_pixmap is None or self._mask_pixmap.size() != original_pixmap.size():
            self._mask_pixmap = QPixmap(original_pixmap.size())
            self._mask_pixmap.fill(Qt.GlobalColor.black)

        self.update_mask_item()
        
        self.setSceneRect(self._original_item.boundingRect())
        self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    @pyqtSlot(bool)
    def set_mask_visibility(self, visible):
        self._mask_item.setVisible(visible)

    def update_mask_item(self):
        """用当前_mask_pixmap更新显示的mask图元。"""
        if not self._mask_pixmap:
            return
            
        # 为了实现半透明效果，我们不直接设置opacity，而是创建一个带透明度的彩色副本
        color_str = self.model.config['Colors'].get('mask_overlay_color')
        color_rgba = tuple(map(int, color_str.split(',')))
        mask_color = QColor(*color_rgba)

        colored_mask = QPixmap(self._mask_pixmap.size())
        colored_mask.fill(Qt.GlobalColor.transparent) # 全透明背景
        
        p = QPainter(colored_mask)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(mask_color))
        # 用二值化图作为蒙版进行绘制
        p.drawPixmap(0, 0, self._mask_pixmap.createMaskFromColor(Qt.GlobalColor.black, Qt.MaskMode.MaskOutColor))
        p.end()
        
        self._mask_item.setPixmap(colored_mask)
        
    def wheelEvent(self, event):
        """鼠标滚轮缩放"""
        zoom_in_factor = 1.25
        zoom_out_factor = 1 / zoom_in_factor
        
        if event.angleDelta().y() > 0:
            self.scale(zoom_in_factor, zoom_in_factor)
        else:
            self.scale(zoom_out_factor, zoom_out_factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._original_item.pixmap():
            self._is_drawing = True
            self.draw_on_mask(event.pos())
        else:
            super().mousePressEvent(event) # 否则执行默认的拖拽事件

    def mouseMoveEvent(self, event):
        if self._is_drawing and self._original_item.pixmap():
            self.draw_on_mask(event.pos())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_drawing = False
            # 如果开启了自动保存，则在鼠标释放时触发
            if self.model.auto_save:
                self.save_current_mask()
        else:
            super().mouseReleaseEvent(event)

    def draw_on_mask(self, view_pos):
        scene_pos = self.mapToScene(view_pos)
        item_pos = self._original_item.mapFromScene(scene_pos)
        
        brush_size = self.model.config['Drawing'].getint('brush_size', 20)
        
        painter = QPainter(self._mask_pixmap)
        
        if self.model.drawing_mode == "draw":
            painter.setPen(QPen(Qt.GlobalColor.white, brush_size, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(QBrush(Qt.GlobalColor.white))
        else: # erase mode
            painter.setPen(QPen(Qt.GlobalColor.black, brush_size, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(QBrush(Qt.GlobalColor.black))

        painter.drawPoint(item_pos.toPoint())
        painter.end()

        # 实时更新视图
        self.update_mask_item()
        # 通知model数据已变动
        self.model.mask_updated.emit()
    
    def clear_current_mask(self):
        if self._mask_pixmap:
            self._mask_pixmap.fill(Qt.GlobalColor.black)
            self.update_mask_item()
            self.model.mask_updated.emit()
            if self.model.auto_save:
                self.save_current_mask()
                
    def save_current_mask(self):
        index = self.model.current_index
        if index < 0 or not self._mask_pixmap:
            return
            
        mask_dir = self.model.get_path('mask_path')
        if not mask_dir:
            print("Mask path not set. Cannot save.")
            # 可以在这里弹窗提示用户
            return
        
        # 从原图文件名生成mask文件名
        original_filename = os.path.basename(self.model._original_files[index])
        mask_filename = os.path.splitext(original_filename)[0] + '.png'
        save_path = os.path.join(mask_dir, mask_filename)
        
        self.image_manager.save_pixmap(self._mask_pixmap, save_path)
        print(f"Mask saved to {save_path}")