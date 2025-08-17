from PyQt6.QtWidgets import QWidget, QGridLayout, QLabel, QSizePolicy, QVBoxLayout, QHBoxLayout, QPushButton
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QPixmap
import os

class PreviewPanel(QWidget):
    """动态生成预览图像网格的面板, 支持列交换"""
    def __init__(self, model, image_manager, parent=None):
        super().__init__(parent)
        self.model = model
        self.image_manager = image_manager
        
        # 【新增 #6】 定义列的初始内容和顺序
        self.column_order = ["denoised", "overlay", "saved_overlay"]
        self.column_titles = {
            "denoised": "去噪图",
            "overlay": "当前效果",
            "saved_overlay": "已存效果"
        }
        
        self.main_layout = QVBoxLayout(self)
        self.grid_layout = QGridLayout()
        self.labels = [] # 用于存储QLabel的二维列表
        
        self.init_ui()

    def init_ui(self):
        # 清空旧布局
        for i in reversed(range(self.main_layout.count())): 
            layout_item = self.main_layout.itemAt(i)
            if layout_item.widget():
                layout_item.widget().setParent(None)
            elif layout_item.layout():
                 # 清理子布局中的所有 widget
                while layout_item.layout().count():
                    child = layout_item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()

        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            if widget is not None:
                widget.setParent(None)
        self.labels.clear()

        # 从配置读取布局
        self.rows = self.model.config['Preview'].getint('rows', 3)
        self.cols = self.model.config['Preview'].getint('columns', 3)
        
        # 【新增】 创建按钮和标题行
        header_layout = QHBoxLayout()
        for c in range(self.cols):
            # 标题
            title_label = QLabel()
            title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header_layout.addWidget(title_label)
            
            # 交换按钮
            if c < self.cols - 1:
                swap_button = QPushButton("↔")
                swap_button.setFixedWidth(40)
                swap_button.clicked.connect(lambda checked, col=c: self.swap_columns(col))
                header_layout.addWidget(swap_button)
        
        self.main_layout.addLayout(header_layout)
    
        for r in range(self.rows):
            row_labels = []
            for c in range(self.cols):
                label = QLabel() # 移除文字
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)

                # --- START: A4 - 移除固定尺寸，让其可伸缩 ---
                # label.setFixedSize(...) # <--- 这是问题的根源，删除掉
                label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored) # 允许label被拉伸
                # --- END: A4 ---

                label.setStyleSheet("border: 1px solid gray;")
                self.grid_layout.addWidget(label, r, c)
                row_labels.append(label)
            self.labels.append(row_labels)
        
        self.main_layout.addLayout(self.grid_layout)
    
    # 【新增】 交换列的逻辑
    def swap_columns(self, left_index):
        if left_index + 1 < len(self.column_order):
            self.column_order[left_index], self.column_order[left_index + 1] = \
                self.column_order[left_index + 1], self.column_order[left_index]
            # 交换后立即刷新预览
            self.update_previews(self.model.current_index)
    
    def update_headers(self):
        """更新列标题"""
        header_layout = self.main_layout.itemAt(0).layout()
        if not header_layout: return

        for c in range(self.cols):
            # 标题标签在 header_layout 中的索引是 c * 2
            title_widget = header_layout.itemAt(c * 2).widget()
            if isinstance(title_widget, QLabel):
                col_key = self.column_order[c]
                title_widget.setText(self.column_titles.get(col_key, ""))
    
    @pyqtSlot(int)
    def update_previews(self, current_index):
        self.update_headers() # 【新增】 每次更新时也更新标题
        
        if current_index < 0:
            self.clear_previews()
            return
            
        offset = self.rows // 2
        
        for r in range(self.rows):
            target_index = current_index - offset + r
            
            # 【修改 #5, #6】 动态地根据 column_order 更新每一列
            for c in range(self.cols):
                if c < len(self.column_order):
                    image_type = self.column_order[c]
                    self.update_label_content(r, c, target_index, image_type)
    
    def update_label_content(self, r, c, index, image_type):
        label = self.labels[r][c]
        if 0 <= index < len(self.model._original_files):
            pixmap = self.get_pixmap_for_type(index, image_type)
            if pixmap and not pixmap.isNull(): # 增加 not pixmap.isNull() 判断
                # --- A4. 核心逻辑: scaled() 现在会使用label动态调整后的大小 ---
                scaled_pixmap = pixmap.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                label.setPixmap(scaled_pixmap)
            else:
                label.setText("无图像") # 提示更清晰
                label.setPixmap(QPixmap()) # 清空旧图像
        else:
            label.setText("") # 索引越界，显示空白
            label.setPixmap(QPixmap()) # 清空旧图像

    def get_pixmap_for_type(self, index, image_type):
        # 确保索引在有效范围内
        if not (0 <= index < len(self.model._original_files)):
            return None
        
        if image_type == "denoised":
            if self.model._denoised_files and index < len(self.model._denoised_files):
                return self.image_manager.load_pixmap(self.model._denoised_files[index])
            return None
        
        original_pixmap = self.image_manager.load_pixmap(self.model._original_files[index])
        if not original_pixmap: return None

        mask_pixmap = None
        if image_type == "overlay":
            # 使用参考路径下的mask
            if self.model._mask_files and index < len(self.model._mask_files):
                mask_pixmap = self.image_manager.load_pixmap(self.model._mask_files[index])

        # 【新增 #5】为第三列获取已保存的Mask
        elif image_type == "saved_overlay":
            save_dir = self.model.get_path('save_path')
            if save_dir:
                original_filename = os.path.basename(self.model._original_files[index])
                mask_filename = os.path.splitext(original_filename)[0] + '.png'
                saved_mask_path = os.path.join(save_dir, mask_filename)
                mask_pixmap = self.image_manager.load_pixmap(saved_mask_path)
        
        # 如果需要合成但没有找到mask，返回原图即可
        if not mask_pixmap:
            return original_pixmap
            
        style = self.model.config['Preview'].get('overlay_style', 'area')
        color_str = self.model.config['Colors'].get('mask_overlay_color', '255,0,0,100')
        color_rgba = tuple(map(int, color_str.split(',')))
        
        return self.image_manager.create_overlay_pixmap(original_pixmap, mask_pixmap, style, color_rgba)

    def clear_previews(self):
        for row in self.labels:
            for label in row:
                label.setText("")
                label.setPixmap(QPixmap())