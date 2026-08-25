# Finetuning/ui/widgets/image_canvas.py

from PyQt6.QtWidgets import QApplication, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QMessageBox, QGraphicsPathItem
from PyQt6.QtCore import Qt, pyqtSlot, QPointF, pyqtSignal, QTimer, QRectF, QDateTime
from PyQt6.QtGui import (
    QPixmap, QPainter, QPen, QColor, QCursor, QPainterPath, 
    QPolygonF, QImage, QPainterPathStroker
)
import os
from pathlib import Path
from utils.debugger import debugger
from utils.path_utils import to_filesystem_path
from core.semi_auto_mask_tools import mark_manual_saved_mask
from core.exclusion_region import (
    ExclusionRegionConfig,
    ManualRegion,
    load_region_config,
    manual_polygons_for_frame,
    save_region_config,
)

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

    def __init__(self, model, image_manager, parent=None, is_mirror=False):
        super().__init__(parent)
        self.model = model
        self.image_manager = image_manager

        # 对比视图: is_mirror 的实例是只读镜像 —— 不接编辑事件, 内容由主视图 push 过来,
        # 查看模式走自己的 override (默认"隐藏" = 纯净图), 不跟着 model.display_mode 走。
        # 这点很关键: 主视图在按下左键绘制时会把 model.display_mode 强制切成 'ants',
        # 没有 override 的话右边会跟着一起闪。
        self._is_mirror = is_mirror
        self._display_mode_override = 'hide' if is_mirror else None
        self._mirror = None
        self._view_peer = None
        self._syncing_view = False

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self._original_item = QGraphicsPixmapItem()
        self._selection_item = QGraphicsPathItem()
        self._selection_item.setPen(QPen(Qt.PenStyle.NoPen))
        self._region_item = self._make_region_item()

        self.scene.addItem(self._original_item)
        self.scene.addItem(self._selection_item)
        self.scene.addItem(self._region_item)

        self._original_pixmap = None
        self._contrast_pixmap = None
        self._denoised_pixmap = None

        self._selection_path = QPainterPath()

        # --- 排除区域: 与 _selection_path 平级但完全独立的第二条通道 ---
        # save_mask_for_index / get_pixmap_from_path 只序列化 _selection_path,
        # 所以区域永远不会被当成 mask 写盘 —— 这是"自动保存不用关"的根据。
        # 详见 core/exclusion_region.py 的模块注释。
        self._region_path = QPainterPath()
        self._region_undo_stack = []      # 区域自己的撤销栈, 绝不与 mask 撤销栈混用
        self._region_config = None        # ExclusionRegionConfig, 懒加载
        self._region_config_dir = None    # 已加载配置对应的 save_dir
        self._region_range = None         # (start, end); None = 全程
        self._drawing_into_region = False # 落笔瞬间锁定, 中途切模式不会把笔画劈两半

        self._temp_drawing_points = []
        self._current_tool = 'lasso'
        self._is_drawing_selection = False
        self._is_panning = False
        self._pan_start_pos = QPointF()
        self._mode_before_drawing = None
        self._erasing_image = None
        self._loaded_index = -1
        
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

        # 滚动条是平移的唯一出口 (中键拖动、ScrollHandDrag、fitInView 都落到它身上),
        # 所以挂在这里就能覆盖所有平移路径; 缩放另外在 wheelEvent / load_image 里补。
        self.horizontalScrollBar().valueChanged.connect(self._sync_view_to_peer)
        self.verticalScrollBar().valueChanged.connect(self._sync_view_to_peer)

    # ------------------------------------------------------------------
    # 对比视图 (双 canvas) 支持
    # ------------------------------------------------------------------
    @property
    def effective_display_mode(self):
        """本视图实际使用的查看模式。镜像用自己的 override, 主视图跟随 model。"""
        if self._display_mode_override is not None:
            return self._display_mode_override
        return self.model.display_mode

    def set_display_mode_override(self, mode):
        """给镜像单独设查看模式; 传 None 表示回去跟随 model。"""
        self._display_mode_override = mode
        self.update_selection_display()
        self.scene.update()

    def attach_mirror(self, mirror):
        """把只读镜像挂到主视图上, 并让两边的视图变换互相同步。"""
        self._mirror = mirror
        self._view_peer = mirror
        mirror._view_peer = self

    def sync_mirror_now(self):
        """强制把当前内容+视角推给镜像 (用于刚打开对比视图的瞬间)。"""
        if self._mirror is None:
            return
        self._mirror.sync_from(self)

    def _push_to_mirror(self):
        mirror = self._mirror
        if mirror is None or not mirror.isVisible():
            return
        mirror.sync_from(self)

    def sync_from(self, source):
        """从主视图取底图和 mask, 按本视图自己的查看模式重画。

        mask 只在这里单向流动 (主 -> 镜像), 镜像永远不写回, 所以不存在两边分叉。
        """
        self._original_pixmap = source._original_pixmap
        self._denoised_pixmap = source._denoised_pixmap
        self._contrast_pixmap = None
        self._selection_path = QPainterPath(source._selection_path)
        # 区域也镜像过去: 右边设成"纯净图"时就是一张无遮挡原图 + 区域轮廓,
        # 正好用来核对区域画得准不准。和 mask 一样是单向流动, 镜像永不写回。
        self._region_path = QPainterPath(source._region_path)
        self._loaded_index = source._loaded_index

        if not self._original_pixmap or self._original_pixmap.isNull():
            self._original_item.setPixmap(QPixmap())
            self._selection_item.setPath(QPainterPath())
            self._region_item.setPath(QPainterPath())
            return

        self._refresh_region_item()

        self.update_selection_display()
        self.setSceneRect(self._original_item.boundingRect())
        source._sync_view_to_peer(force=True)
        self.scene.update()

    def _sync_view_to_peer(self, *args, force=False):
        """把本视图的缩放+平移原样复制给对面。_syncing_view 双向置位防递归回弹。"""
        peer = self._view_peer
        if peer is None or self._syncing_view:
            return
        if not force and (not peer.isVisible() or not self.isVisible()):
            return

        self._syncing_view = True
        peer._syncing_view = True
        try:
            peer.setTransform(self.transform())
            peer.horizontalScrollBar().setValue(self.horizontalScrollBar().value())
            peer.verticalScrollBar().setValue(self.verticalScrollBar().value())
        finally:
            self._syncing_view = False
            peer._syncing_view = False

    # ------------------------------------------------------------------
    # 排除区域 (exclusion region)
    # ------------------------------------------------------------------
    @staticmethod
    def _make_region_item():
        """区域的半透明填充项。轮廓 (红/黄反向蚂蚁线) 在 drawForeground 里画。"""
        item = QGraphicsPathItem()
        item.setPen(QPen(Qt.PenStyle.NoPen))
        item.setBrush(QColor(255, 40, 40, 30))
        item.setZValue(10)
        return item

    @property
    def has_region(self):
        return not self._region_path.isEmpty()

    def region_config(self):
        """当前 save_dir 对应的区域配置 (懒加载, 按目录缓存)。"""
        save_dir = self.model.get_path('save_path')
        if not save_dir:
            if self._region_config is None:
                self._region_config = ExclusionRegionConfig()
            return self._region_config
        if self._region_config is None or self._region_config_dir != save_dir:
            self._region_config = load_region_config(save_dir)
            self._region_config_dir = save_dir
        return self._region_config

    def set_region_range(self, start, end):
        """设定新画区域的生效帧范围; 传 (None, None) 表示全程。"""
        if start is None or end is None:
            self._region_range = None
        else:
            self._region_range = (int(start), int(end))

    def _effective_region_range(self):
        if self._region_range is not None:
            return self._region_range
        total = len(self.model._original_files)
        return (0, max(0, total - 1))

    def _region_polygons_from_path(self):
        """QPainterPath -> [[(x, y), ...], ...]。

        刻意不走 process_selection_path 的像素吸附 —— 那是为 mask 精度做的,
        会把边界拆成纯水平/垂直线段导致顶点数暴涨。区域保留平滑多边形即可。
        """
        polygons = []
        for poly in self._region_path.toSubpathPolygons():
            points = [(float(p.x()), float(p.y())) for p in poly]
            if len(points) >= 3:
                polygons.append(points)
        return polygons

    def _apply_region_polygons(self, polygons):
        path = QPainterPath()
        for points in polygons or []:
            if len(points) < 3:
                continue
            path.addPolygon(QPolygonF([QPointF(float(x), float(y)) for x, y in points]))
            path.closeSubpath()
        self._region_path = path

    def commit_region_to_config(self, persist=True):
        """把画布上的区域写回配置 (并落盘)。

        当前 UI 只维护"一条生效范围"的手动区域, 但文件格式本身支持多段 ——
        以后加多段 UI 不需要改格式。
        """
        config = self.region_config()
        start, end = self._effective_region_range()
        polygons = self._region_polygons_from_path()

        config.manual = [r for r in config.manual if not (r.start == start and r.end == end)]
        if polygons:
            config.manual.append(ManualRegion(
                start=start,
                end=end,
                polygons=polygons,
                created_at=QDateTime.currentDateTimeUtc().toString(Qt.DateFormat.ISODate),
            ))

        if persist:
            save_dir = self.model.get_path('save_path')
            if save_dir:
                try:
                    save_region_config(save_dir, config)
                except OSError as exc:
                    print(f"[region] 区域配置写盘失败: {exc}")
        self.model.region_updated.emit()

    def reload_region_for_frame(self, index):
        """按帧从配置重建区域路径 (换帧时调用)。"""
        if index is None or index < 0:
            self._apply_region_polygons([])
        else:
            self._apply_region_polygons(manual_polygons_for_frame(self.region_config(), index))
        self._refresh_region_item()

    def _refresh_region_item(self):
        self._region_item.setPath(self._region_path)
        self._region_item.setVisible(not self._region_path.isEmpty())

    def clear_region(self, persist=True):
        if self._region_path.isEmpty():
            return
        self._region_undo_stack.append(QPainterPath(self._region_path))
        self._region_path = QPainterPath()
        self._refresh_region_item()
        self.commit_region_to_config(persist=persist)
        self.scene.update()

    def undo_region(self):
        if not self._region_undo_stack:
            return False
        self._region_path = self._region_undo_stack.pop()
        self._refresh_region_item()
        self.commit_region_to_config()
        self.scene.update()
        return True

    def get_region_mask_pixmap(self) -> QPixmap:
        """当前帧手动区域的二值图 (黑底白区), 尺寸与原图一致。"""
        if self._original_pixmap is None:
            return QPixmap()
        image = QImage(self._original_pixmap.size(), QImage.Format.Format_Grayscale8)
        image.fill(Qt.GlobalColor.black)
        painter = QPainter(image)
        painter.setBrush(Qt.GlobalColor.white)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(self._region_path)
        painter.end()
        return QPixmap.fromImage(image)

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
                self._sync_view_to_peer()

    @pyqtSlot(int)
    def load_image(self, index):
        # 在加载新图片之前，如果缩放被锁定，则捕获当前视图的状态
        if self.model.is_zoom_locked:
            self.capture_view_state()
        if self._loaded_index >= len(self.model._original_files):
            self._loaded_index = -1
        if self.model.auto_save and self._loaded_index >= 0 and self._loaded_index != index:
            self.save_mask_for_index(self._loaded_index)
        
        if index < 0:
            self.scene.clear()   # 注意: 这会销毁所有 item, 下面必须逐个重建
            self._original_item = QGraphicsPixmapItem()
            self._selection_item = QGraphicsPathItem()
            self._selection_item.setPen(QPen(Qt.PenStyle.NoPen))
            self._region_item = self._make_region_item()
            self.scene.addItem(self._original_item)
            self.scene.addItem(self._selection_item)
            self.scene.addItem(self._region_item)
            self._region_path = QPainterPath()
            self._loaded_index = -1
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
            if saved_mask_path and os.path.exists(to_filesystem_path(saved_mask_path)):
                path_to_load = saved_mask_path
            elif binary_mask_path:
                path_to_load = binary_mask_path # 回退
        else:
            # 优先加载 'mask_path' (二值化图)
            if binary_mask_path:
                path_to_load = binary_mask_path
            elif saved_mask_path and os.path.exists(to_filesystem_path(saved_mask_path)):
                path_to_load = saved_mask_path # 回退

        if path_to_load:
            mask_pixmap = self.image_manager.load_pixmap(path_to_load)
            # print(f"Loaded mask from: {path_to_load}")


        # if self.model._mask_files and index < len(self.model._mask_files):
        #     mask_pixmap = self.image_manager.load_pixmap(self.model._mask_files[index])
        
        if mask_pixmap and not mask_pixmap.isNull():
            self._selection_path = self.image_manager.create_path_from_mask(mask_pixmap)

        # 区域按帧从配置重建 —— 配置是唯一真源, 换帧不会丢
        self.reload_region_for_frame(index)

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
        self._loaded_index = index
        self.scene.update()
        # fitInView/setTransform 不发信号, 换图后显式把新画面和新视角一起推给镜像
        self._push_to_mirror()
        self._sync_view_to_peer()

    @pyqtSlot()
    def update_selection_display(self, base_pixmap_for_overlay=None):
        # 壳: 真正的绘制在 _impl 里 (它有多处 early return), 画完统一把内容推给镜像
        self._update_selection_display_impl(base_pixmap_for_overlay)
        self._push_to_mirror()

    def _update_selection_display_impl(self, base_pixmap_for_overlay=None):
        # self.update_display_pixmap()
        if base_pixmap_for_overlay is None:
            self.update_display_pixmap()
        self._selection_item.setPath(QPainterPath())

        mode = self.effective_display_mode
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
        if self.effective_display_mode == 'ants':
            self.scene.update(self._selection_item.boundingRect())
        # 区域蚂蚁线不看 display_mode —— mask 隐藏时区域仍要爬
        if not self._region_path.isEmpty():
            self.scene.update(self._region_item.boundingRect())

    def wheelEvent(self, event):
        # 如果模型被设置为 "固定缩放"，则忽略所有滚轮事件（包括双指缩放）
        if self.model.is_zoom_locked:
            event.accept() # 消耗掉这个事件，防止父类处理
            return
        zoom_factor = 1.25 if event.angleDelta().y() > 0 else 1 / 1.25
        self.scale(zoom_factor, zoom_factor)
        # scale() 不走滚动条信号, 得手动同步
        self._sync_view_to_peer()

    def mouseDoubleClickEvent(self, event):
        if self._is_mirror:
            # 镜像上双击不能触发"保存并下一张", 否则一次操作会被算两遍
            super().mouseDoubleClickEvent(event)
            return
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
        if self._is_mirror:
            # 只读镜像: 中键平移放行 (会同步回主视图), 其余一律不接
            if event.button() == Qt.MouseButton.MiddleButton:
                self._is_panning = True
                self._pan_start_pos = event.pos()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
            super().mousePressEvent(event)
            return

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
            # 落笔瞬间锁定目标通道 —— 中途按 G 切模式不会把同一笔劈成两半
            self._drawing_into_region = bool(self.model.region_mode)
            if self._drawing_into_region:
                # 区域模式不碰 display_mode: 用户原来的 mask 显示方式 (蚂蚁线/轮廓/
                # 面积) 原样保留。老脚本正是因为强切模式 + 清空 _selection_path,
                # 才导致"画区域时看不见蚂蚁线"。
                if self._current_tool == 'erase':
                    # 橡皮擦作用于 mask 位图, 区域没有对应语义。用 Alt/Ctrl 减去。
                    event.accept()
                    return
            else:
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
            self._erasing_base_pixmap = self._render_display_pixmap()
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
        
        if self._drawing_into_region:
            self._end_region_drawing(commit_selection)
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

    def _end_region_drawing(self, commit_selection=True):
        """把一笔提交到 _region_path。

        与 mask 提交路径两点不同, 每一点都是刻意的:
          1. **不 push_undo_state** —— 区域有自己的撤销栈, 混进 mask 撤销栈会让
             Ctrl+Z 撤出别人的东西。
          2. **不触发 auto_save** —— 区域根本不在写盘路径上, 这是整套设计的根据。

        但**照走 process_selection_path**, 和 mask 用同一套像素吸附:
        它把路径栅格化进一张 image_size 的位图, 于是同时拿到两件事 ——
        图像外的部分被天然裁掉, 边界变成严格水平/垂直的阶梯 (与蚂蚁线一致)。
        吸附后坐标本就是整数, JSON 反而更小, 早先"顶点数暴涨"的顾虑不成立。
        """
        try:
            if not (commit_selection and len(self._temp_drawing_points) >= 3):
                return

            drawn = QPainterPath()
            drawn.addPolygon(QPolygonF(self._temp_drawing_points))
            drawn.closeSubpath()

            modifier = self._get_current_modifier()
            if modifier == 'subtract':
                candidate = self._region_path.subtracted(drawn)
            elif modifier == 'add' or not self._region_path.isEmpty():
                # 区域默认累加: 液池边界常要分几笔围起来, 每笔都清空会很难用
                candidate = self._region_path.united(drawn)
            else:
                candidate = drawn

            # 减到空是合法结果, 不能被下面的"未覆盖有效像素"判定挡住
            if modifier == 'subtract' and candidate.isEmpty():
                self._push_region_undo()
                self._region_path = QPainterPath()
            elif self._original_pixmap and not self._original_pixmap.isNull():
                is_valid, snapped = self.image_manager.process_selection_path(
                    candidate, self._original_pixmap.size()
                )
                if not is_valid:
                    # 整笔画在图像外。静默忽略而不弹窗: 边缘处画过头是常态
                    # (超出的部分已被裁掉, 图像内的部分照常生效), 真正"全在外面"
                    # 的情况很罕见, 为它打断绘制流程不值得。
                    print("[region] 这一笔没有覆盖到图像内的任何像素, 已忽略。")
                    return
                if snapped == self._region_path:
                    # 什么都没改变的一笔不该占撤销栈 —— 否则 Ctrl+Z 会"空按一下"。
                    # 已有区域非空时, 一笔完全画在图像外正好落到这里:
                    # 联集里含已有区域故 is_valid 为真, 但裁剪后结果与原来相同。
                    return
                self._push_region_undo()
                self._region_path = snapped
            else:
                self._push_region_undo()
                self._region_path = candidate

            self._refresh_region_item()
            self.commit_region_to_config()
        finally:
            self._is_drawing_selection = False
            self._drawing_into_region = False
            self._temp_drawing_points = []
            self.scene.update()

    def _push_region_undo(self):
        """只在真的要改 _region_path 之前调用 —— 被拒绝的笔画不该占撤销栈。"""
        self._region_undo_stack.append(QPainterPath(self._region_path))
        if len(self._region_undo_stack) > 64:
            self._region_undo_stack.pop(0)

    def _apply_eraser(self, scene_pos: QPointF):
        if self._erasing_image is None: return
        size = self.model.eraser_size
        radius = size / 2.0
        painter = QPainter(self._erasing_image)
        painter.setBrush(Qt.GlobalColor.black)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(scene_pos, radius, radius)
        painter.end()

        base_pixmap = getattr(self, '_erasing_base_pixmap', None) or self._render_display_pixmap()
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
            self._erasing_base_pixmap = None
            self.scene.update()

    def _cancel_drawing(self):
        """取消当前的绘制或擦除操作。"""
        print("Drawing cancelled by user.")
        try:
            self.update_selection_display()
        finally:
            if self._mode_before_drawing is not None:
                self.model.set_display_mode(self._mode_before_drawing)
                self._mode_before_drawing = None

            self._is_drawing_selection = False
            self._drawing_into_region = False
            self._temp_drawing_points = []
            self._erasing_image = None
            self._erasing_base_pixmap = None
            self.scene.update()

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
        
        if self.effective_display_mode == 'ants' and not self._selection_path.isEmpty():
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

        if not self._region_path.isEmpty():
            # 区域蚂蚁线: 红/黄 + 线宽 2 + **反向滚动**。
            # 反向是刻意的 —— 即便和 mask 蚂蚁线贴在一起, 靠动画方向也能一眼分开。
            # 与 display_mode 无关: mask 设成"隐藏"时区域照常显示。
            painter.setBrush(Qt.BrushStyle.NoBrush)
            dash_length = 5.0
            offset = (QDateTime.currentMSecsSinceEpoch() / 150.0) % (dash_length * 2.0)
            region_width = pen_width * 2.0
            pen_red = QPen(QColor(255, 40, 40), region_width, Qt.PenStyle.CustomDashLine)
            pen_red.setDashPattern([dash_length, dash_length])
            pen_red.setDashOffset(-offset)
            pen_yellow = QPen(QColor(255, 230, 0), region_width, Qt.PenStyle.CustomDashLine)
            pen_yellow.setDashPattern([dash_length, dash_length])
            pen_yellow.setDashOffset(-offset - dash_length)
            painter.setPen(pen_red)
            painter.drawPath(self._region_path)
            painter.setPen(pen_yellow)
            painter.drawPath(self._region_path)

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
        if self._is_mirror:
            # 镜像不编辑, 只给个"能拖着看"的手形, 不要出现加/减号十字
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if self._current_tool == 'erase':
            self.setCursor(Qt.CursorShape.BlankCursor)
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            return
        if self.effective_display_mode != 'ants' and not self._is_drawing_selection:
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

    def _current_base_pixmap(self):
        active_base_pixmap = self._original_pixmap
        if self.model.show_denoised and self._denoised_pixmap:
            active_base_pixmap = self._denoised_pixmap
        return active_base_pixmap

    def _render_display_pixmap(self, settings=None):
        active_base_pixmap = self._current_base_pixmap()
        if not active_base_pixmap:
            return active_base_pixmap
        if getattr(self.model, "effects_bypassed", False):
            return active_base_pixmap
        if settings is None:
            settings = getattr(self.model, "preview_effect_settings", self.model.effect_settings)
        if self.model.settings_have_active_effects(settings):
            return self.image_manager.apply_image_effects(active_base_pixmap, settings)
        return active_base_pixmap

    def update_display_pixmap(self):
        """根据模型状态（原图/去噪/高对比度）更新显示的底图。"""
        display_pixmap = self._render_display_pixmap()
        if display_pixmap:
            self._original_item.setPixmap(display_pixmap)

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
        if self.model.region_mode:
            # 区域模式下 W 清的是区域, 不是 mask
            self.clear_region()
            self.setFocus()
            return

        should_persist_empty = False
        had_selection = not self._selection_path.isEmpty()
        if had_selection:
            self.push_undo_state()
            self._selection_path = QPainterPath()
            self.model.mask_updated.emit()
            should_persist_empty = True
        elif self._original_pixmap is not None and not self._original_pixmap.isNull():
            # Even when the mask is already empty, treat an explicit clear action
            # as a deliberate "this frame should be empty" confirmation.
            self._selection_path = QPainterPath()
            self.model.mask_updated.emit()
            should_persist_empty = True
        if should_persist_empty or self.model.auto_save:
            self.save_current_mask()
        self.setFocus()
            
    def save_current_mask(self):
        return self.save_mask_for_index(self.model.current_index)

    def save_mask_for_index(self, index):
        if index < 0: return False
        if index >= len(self.model._original_files):
            print(f"Skip saving mask: index {index} is out of range for current file list.")
            return False
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
        mark_manual_saved_mask(Path(save_path))
        self.model.mask_saved.emit(index)
        print(f"Mask saved to {save_path}")
        self.setFocus()
        return True

    def push_undo_state(self):
        self.model.push_undo_state(self.model.current_index, self._selection_path)
    
    def undo(self):
        if self.model.region_mode:
            # 区域模式下 Ctrl+Z 只撤区域。没得撤就什么都不做 ——
            # 绝不能"顺手"去撤 mask, 那是用户看不见的破坏。
            if not self.undo_region():
                print("No region step to undo.")
            return

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
        preview_settings = self.model.preview_effect_settings
        preview_pixmap = self._render_display_pixmap(preview_settings)
        if not preview_pixmap:
            return

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
