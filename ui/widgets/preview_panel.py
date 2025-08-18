# Finetuning/ui/widgets/preview_panel.py

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSplitter, 
    QLabel, QSizePolicy, QFrame
)
from PyQt6.QtCore import Qt, pyqtSlot, QSize, QTimer
from PyQt6.QtGui import QPixmap
import os

# --- START: 新增可折叠标题栏控件 ---
class CollapsibleHeader(QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.is_collapsed = False
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(5)

        self.toggle_button = QPushButton("v")
        self.toggle_button.setFixedSize(QSize(20, 20))
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(False)
        
        self.title_label = QLabel(title)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
        self.content_widget = QWidget() # 用于容纳 HC 和交换按钮
        self.content_layout = QHBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.addStretch()

        layout.addWidget(self.toggle_button)
        layout.addWidget(self.title_label)
        layout.addWidget(self.content_widget)

        self.toggle_button.toggled.connect(self.toggle)

    def add_tool_widget(self, widget):
        self.content_layout.addWidget(widget)

    def toggle(self, checked):
        self.is_collapsed = checked
        if checked:
            self.toggle_button.setText(">")
            self.title_label.setVisible(False)
            self.content_widget.setVisible(False)
        else:
            self.toggle_button.setText("v")
            self.title_label.setVisible(True)
            self.content_widget.setVisible(True)

# --- END: 新增控件 ---


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
        
        self.column_widgets = {}
        self.column_labels = {}
        self.contrast_buttons = {}

        self.column_contrast_state = {key: False for key in self.column_keys}
        self.init_ui()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)
        
        self.preview_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_layout.addWidget(self.preview_splitter)

        self.rows = self.model.config['Preview'].getint('rows', 3)
        
        for col_index, key in enumerate(self.column_keys):
            col_container = QFrame()
            col_container.setFrameShape(QFrame.Shape.StyledPanel)
            col_layout = QVBoxLayout(col_container)
            col_layout.setContentsMargins(2,2,2,2)
            col_layout.setSpacing(2)

            # --- START: 使用可折叠标题栏 ---
            header = CollapsibleHeader(self.column_titles.get(key, "N/A"))
            
            contrast_button = QPushButton("HC")
            contrast_button.setCheckable(True)
            contrast_button.setFixedWidth(40)
            contrast_button.toggled.connect(lambda checked, k=key: self._toggle_column_contrast(k, checked))
            header.add_tool_widget(contrast_button)
            
            if col_index < len(self.column_keys) - 1:
                swap_button = QPushButton("↔")
                swap_button.setFixedWidth(30)
                swap_button.clicked.connect(lambda _, idx=col_index: self._swap_columns(idx))
                header.add_tool_widget(swap_button)
            
            col_layout.addWidget(header)
            # --- END: 使用可折叠标题栏 ---
            
            self.column_labels[key] = []
            for _ in range(self.rows):
                label = QLabel()
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
                label.setMinimumSize(50, 50)
                label.setStyleSheet("border: 1px solid gray;")
                col_layout.addWidget(label)
                self.column_labels[key].append(label)

            self.preview_splitter.addWidget(col_container)
            self.column_widgets[key] = col_container
            self.contrast_buttons[key] = contrast_button
    
    def _toggle_column_contrast(self, key, checked):
        if key in self.column_contrast_state:
            self.column_contrast_state[key] = checked
            self.update_previews(self.model.current_index)

    def _swap_columns(self, left_index):
        right_index = left_index + 1
        if right_index < len(self.column_keys):
            # 交换Key和状态
            keys = self.column_keys
            keys[left_index], keys[right_index] = keys[right_index], keys[left_index]
            
            # 获取当前splitter的大小
            sizes = self.preview_splitter.sizes()
            sizes[left_index], sizes[right_index] = sizes[right_index], sizes[left_index]

            # 获取要交换的控件
            widget1 = self.preview_splitter.widget(left_index)
            widget2 = self.preview_splitter.widget(right_index)
            
            # 从splitter中移除控件
            widget1.setParent(None)
            widget2.setParent(None)

            # 按新顺序插入
            self.preview_splitter.insertWidget(left_index, widget2)
            self.preview_splitter.insertWidget(right_index, widget1)
            
            # 恢复大小
            self.preview_splitter.setSizes(sizes)
            
            self.update_previews(self.model.current_index)

    @pyqtSlot(int)
    def update_previews(self, current_index):
        if current_index < 0:
            self.clear_previews()
            return
            
        offset = self.rows // 2
        
        for r in range(self.rows):
            target_index = current_index - offset + r
            for key in self.column_keys:
                self.update_label_content(r, key, target_index)

    def update_label_content(self, row_index, image_type_key, image_file_index):
        label = self.column_labels[image_type_key][row_index]
        
        if 0 <= image_file_index < len(self.model._original_files):
            pixmap = self.get_pixmap_for_type(image_file_index, image_type_key)
            if pixmap and not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                label.setPixmap(scaled_pixmap)
            else:
                label.setText("N/A")
                label.setPixmap(QPixmap())
        else:
            label.setText("")
            label.setPixmap(QPixmap())

    def get_pixmap_for_type(self, index, image_type):
        if not (0 <= index < len(self.model._original_files)):
            return None
        
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
                 # “当前效果”应该实时反映画布上的选区
                if index == self.model.current_index:
                    mask_pixmap = self.canvas.get_pixmap_from_path()
                else: # 对于非当前图片，加载已保存的
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
        """辅助函数：获取指定索引已保存的mask"""
        save_dir = self.model.get_path('save_path')
        if save_dir and 0 <= index < len(self.model._original_files):
            original_filename = os.path.basename(self.model._original_files[index])
            mask_filename = os.path.splitext(original_filename)[0] + '.png'
            saved_mask_path = os.path.join(save_dir, mask_filename)
            if os.path.exists(saved_mask_path):
                return self.image_manager.load_pixmap(saved_mask_path)
        # 如果保存路径没有，尝试从原始mask路径加载
        if self.model._mask_files and index < len(self.model._mask_files):
            return self.image_manager.load_pixmap(self.model._mask_files[index])
        return None


    def clear_previews(self):
        for key in self.column_keys:
            for label in self.column_labels.get(key, []):
                label.setText("")
                label.setPixmap(QPixmap())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 延迟更新，避免频繁重绘
        QTimer.singleShot(50, lambda: self.update_previews(self.model.current_index))