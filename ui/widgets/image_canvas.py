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
        """【重大修改】根据显示方式(面积/轮廓/反相)来更新Mask图层"""
        if not self._mask_pixmap: return
            
        color_str = self.model.config['Colors'].get('mask_overlay_color', '255,0,0,100')
        color_rgba = tuple(map(int, color_str.split(',')))
        mask_color = QColor(*color_rgba)
        
        contour_color_str = self.model.config['Colors'].get('contour_line_color', '0,255,0,255')
        contour_color_rgba = tuple(map(int, contour_color_str.split(',')))
        
        contour_thickness = self.model.config['Colors'].getint('contour_thickness', 2)

        # 使用ImageManager中的叠加函数，因为它已经实现了轮廓和面积
        # 我们需要一个基础pixmap来叠加，这里创建一个透明的
        base_pixmap = QPixmap(self._mask_pixmap.size())
        base_pixmap.fill(Qt.GlobalColor.transparent)

        # 如果是反相模式，先创建一个反相的mask
        mask_to_use = self._mask_pixmap
        if self.model.mask_invert:
            inverted_mask = QPixmap(self._mask_pixmap.size())
            inverted_mask.fill(Qt.GlobalColor.white)
            painter = QPainter(inverted_mask)
            # 在白色背景上“画出”黑色部分
            painter.drawPixmap(0, 0, self._mask_pixmap.createMaskFromColor(Qt.GlobalColor.white, Qt.MaskMode.MaskOutColor))
            painter.end()
            mask_to_use = inverted_mask

        # 调用 manager 的方法生成最终效果
        final_mask_overlay = self.image_manager.create_overlay_pixmap(
            base_pixmap, 
            mask_to_use, 
            self.model.mask_display_style, 
            mask_color if self.model.mask_display_style == 'area' else contour_color_rgba,
            contour_thickness
        )

        self._mask_item.setPixmap(final_mask_overlay)
        
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
            
        # START: 修正 - 从模型获取保存路径
        mask_dir = self.model.get_path('save_path')
        # END: 修正
        if not mask_dir:
            # 现在QMessageBox已经被正确导入，可以正常使用了
            QMessageBox.warning(self, "保存失败", "请在路径设置中指定有效的“保存路径”！")
            return
        
        # 从原图文件名生成mask文件名
        original_filename = os.path.basename(self.model._original_files[index])
        mask_filename = os.path.splitext(original_filename)[0] + '.png'
        save_path = os.path.join(mask_dir, mask_filename)
        
        self.image_manager.save_pixmap(self._mask_pixmap, save_path)
        print(f"Mask saved to {save_path}")