# Finetuning/ui/widgets/preview_panel.py

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSplitter,
    QLabel, QSizePolicy, QFrame
)
from PyQt6.QtCore import Qt, pyqtSlot, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
import os

# --- CollapsibleTitleBar (无变动) ---
class CollapsibleTitleBar(QWidget):
    toggled = pyqtSignal(bool)
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(35)
        self.init_ui(title)
    def init_ui(self, title):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(5)
        self.toggle_button = QPushButton("▲")
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(False)
        self.toggle_button.setFixedSize(25, 25)
        self.toggle_button.setStyleSheet("padding: 0px;")
        self.title_label = QLabel(title)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        font = self.title_label.font()
        font.setBold(True)
        self.title_label.setFont(font)
        self.tools_widget = QWidget()
        self.tools_layout = QHBoxLayout(self.tools_widget)
        self.tools_layout.setContentsMargins(0, 0, 0, 0)
        self.tools_layout.setSpacing(5)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.title_label)
        layout.addStretch()
        layout.addWidget(self.tools_widget)
        self.toggle_button.toggled.connect(self._on_toggle)
    def add_tool_widget(self, widget):
        self.tools_layout.addWidget(widget)
    def _on_toggle(self, checked):
        self.toggle_button.setText("▼" if checked else "▲")
        self.toggled.emit(checked)
    def set_collapsed(self, is_collapsed):
        self.toggle_button.blockSignals(True)
        self.toggle_button.setChecked(is_collapsed)
        self.toggle_button.setText("▼" if is_collapsed else "▲")
        self.toggle_button.blockSignals(False)


class PreviewPanel(QWidget):
    def __init__(self, model, image_manager, canvas_widget, parent=None):
        super().__init__(parent)
        self.model = model
        self.image_manager = image_manager
        self.canvas = canvas_widget
        
        self.column_keys = ["saved_overlay", "overlay", "denoised"]
        self.column_titles = {
            "denoised": "去噪图",
            "overlay": "当前效果",
            "saved_overlay": "已存效果"
        }
        
        self.column_labels = {}
        self.contrast_buttons = {}
        self.column_contrast_state = {key: False for key in self.column_keys}
        
        # --- FIX 1 START: 添加一个列表来存储列分割器 ---
        self.column_splitters = []
        # --- FIX 1 END ---

        self.init_ui()

    def init_ui(self):
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.preview_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_layout.addWidget(self.preview_splitter)

        self.rows = self.model.config['Preview'].getint('rows', 3)
        
        for col_index, key in enumerate(self.column_keys):
            column_splitter = QSplitter(Qt.Orientation.Vertical)
            title_bar = CollapsibleTitleBar(self.column_titles.get(key, "N/A"))
            image_panel = QFrame()
            image_panel.setFrameShape(QFrame.Shape.StyledPanel)
            image_panel_layout = QVBoxLayout(image_panel)
            image_panel_layout.setContentsMargins(2, 2, 2, 2)
            image_panel_layout.setSpacing(2)
            contrast_button = QPushButton("HC")
            contrast_button.setCheckable(True)
            contrast_button.setFixedSize(40, 25)
            contrast_button.toggled.connect(lambda checked, k=key: self._toggle_column_contrast(k, checked))
            title_bar.add_tool_widget(contrast_button)
            if col_index < len(self.column_keys) - 1:
                swap_button = QPushButton("↔")
                swap_button.setFixedSize(30, 25)
                swap_button.clicked.connect(lambda _, idx=col_index: self._swap_columns(idx))
                title_bar.add_tool_widget(swap_button)
            self.column_labels[key] = []
            for _ in range(self.rows):
                label = QLabel()
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
                label.setMinimumSize(50, 50)
                label.setStyleSheet("border: 1px solid gray;")
                image_panel_layout.addWidget(label)
                self.column_labels[key].append(label)
            column_splitter.addWidget(title_bar)
            column_splitter.addWidget(image_panel)
            column_splitter.setSizes([35, 600])
            column_splitter.setHandleWidth(5)
            title_bar.toggled.connect(
                lambda checked, s=column_splitter: self._handle_title_toggle(checked, s)
            )
            column_splitter.splitterMoved.connect(
                lambda pos, index, s=column_splitter, t=title_bar: self._sync_button_to_splitter(s, t)
            )
            self.preview_splitter.addWidget(column_splitter)
            self.contrast_buttons[key] = contrast_button
            
            # --- FIX 2 START: 将创建的列分割器存入列表 ---
            self.column_splitters.append(column_splitter)
            # --- FIX 2 END ---

    def _handle_title_toggle(self, is_collapsed, splitter: QSplitter):
        if is_collapsed:
            splitter.setSizes([0, 1])
        else:
            splitter.setSizes([35, 1])
    
    def _sync_button_to_splitter(self, splitter: QSplitter, title_bar: CollapsibleTitleBar):
        is_collapsed = splitter.sizes()[0] == 0
        title_bar.set_collapsed(is_collapsed)

    def _toggle_column_contrast(self, key, checked):
        if key in self.column_contrast_state:
            self.column_contrast_state[key] = checked
            self.update_previews(self.model.current_index)

    def _swap_columns(self, left_index):
        right_index = left_index + 1
        if right_index < len(self.column_keys):
            keys = self.column_keys
            keys[left_index], keys[right_index] = keys[right_index], keys[left_index]
            
            # --- FIX: 同时交换列分割器列表中的顺序 ---
            self.column_splitters[left_index], self.column_splitters[right_index] = self.column_splitters[right_index], self.column_splitters[left_index]

            sizes = self.preview_splitter.sizes()
            sizes[left_index], sizes[right_index] = sizes[right_index], sizes[left_index]

            widget1 = self.preview_splitter.widget(left_index)
            widget2 = self.preview_splitter.widget(right_index)
            
            widget1.setParent(None)
            widget2.setParent(None)

            self.preview_splitter.insertWidget(left_index, widget2)
            self.preview_splitter.insertWidget(right_index, widget1)
            
            self.preview_splitter.setSizes(sizes)
            self.update_previews(self.model.current_index)

    @pyqtSlot(int)
    def update_previews(self, current_index):
        if current_index < 0:
            self.clear_previews()
            return

        # --- FIX 3 START: 保存所有分割器的当前状态 ---
        main_splitter_state = self.preview_splitter.saveState()
        column_splitter_states = [s.saveState() for s in self.column_splitters]
        # --- FIX 3 END ---
            
        offset = self.rows // 2
        
        for r in range(self.rows):
            target_index = current_index - offset + r
            for key in self.column_keys:
                self.update_label_content(r, key, target_index)

        # --- FIX 4 START: 恢复所有分割器的状态 ---
        self.preview_splitter.restoreState(main_splitter_state)
        for i, splitter in enumerate(self.column_splitters):
            # 检查状态是否存在，防止索引越界
            if i < len(column_splitter_states):
                splitter.restoreState(column_splitter_states[i])
        # --- FIX 4 END ---

    def update_label_content(self, row_index, image_type_key, image_file_index):
        # (此函数内部无变动)
        label = self.column_labels[image_type_key][row_index]
        if 0 <= image_file_index < len(self.model._original_files):
            pixmap = self.get_pixmap_for_type(image_file_index, image_type_key)
            if pixmap and not pixmap.isNull():
                # 使用 scaled 方法时传递 Qt.AspectRatioMode.KeepAspectRatioByExpanding 
                # 可以更好地填充空间，避免图片周围出现过多空白
                scaled_pixmap = pixmap.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                label.setPixmap(scaled_pixmap)
            else:
                label.setText("N/A")
                label.setPixmap(QPixmap())
        else:
            label.setText("")
            label.setPixmap(QPixmap())

    def get_pixmap_for_type(self, index, image_type):
        # (此函数内部无变动)
        if not (0 <= index < len(self.model._original_files)): return None
        base_pixmap = None
        if image_type == "denoised":
            if self.model._denoised_files and index < len(self.model._denoised_files):
                base_pixmap = self.image_manager.load_pixmap(self.model._denoised_files[index])
        else:
            base_pixmap = self.image_manager.load_pixmap(self.model._original_files[index])
        if not base_pixmap: return None
        if self.column_contrast_state.get(image_type, False):
            base_pixmap = self.image_manager.apply_clahe(base_pixmap)
        if image_type in ["overlay", "saved_overlay"]:
            mask_pixmap = None
            if image_type == "overlay":
                if index == self.model.current_index:
                    mask_pixmap = self.canvas.get_pixmap_from_path()
                else:
                    mask_pixmap = self._get_saved_mask(index)
            elif image_type == "saved_overlay":
                mask_pixmap = self._get_saved_mask(index)
            if mask_pixmap:
                style = self.model.config['Preview'].get('overlay_style', 'area')
                color_str = self.model.config['Colors'].get('mask_overlay_color', '255,0,0,100')
                color_rgba = tuple(map(int, color_str.split(',')))
                return self.image_manager.create_overlay_pixmap(base_pixmap, mask_pixmap, style, color_rgba)
        return base_pixmap

    def _get_saved_mask(self, index):
        # (此函数内部无变动)
        save_dir = self.model.get_path('save_path')
        if save_dir and 0 <= index < len(self.model._original_files):
            original_filename = os.path.basename(self.model._original_files[index])
            mask_filename = os.path.splitext(original_filename)[0] + '.png'
            saved_mask_path = os.path.join(save_dir, mask_filename)
            if os.path.exists(saved_mask_path):
                return self.image_manager.load_pixmap(saved_mask_path)
        if self.model._mask_files and index < len(self.model._mask_files):
            return self.image_manager.load_pixmap(self.model._mask_files[index])
        return None

    def clear_previews(self):
        # (此函数内部无变动)
        for key in self.column_keys:
            for label in self.column_labels.get(key, []):
                label.setText("")
                label.setPixmap(QPixmap())

    def resizeEvent(self, event):
        # --- FIX 5 START: 移除不必要的刷新调用 ---
        # 旧的调用 `QTimer.singleShot(50, lambda: self.update_previews(self.model.current_index))`
        # 是导致拖拽不流畅的元凶，将其移除。
        super().resizeEvent(event)
        # --- FIX 5 END ---