from PyQt6.QtWidgets import QWidget, QGridLayout, QLabel, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QPixmap

class PreviewPanel(QWidget):
    """动态生成预览图像网格的面板。"""
    def __init__(self, model, image_manager, parent=None):
        super().__init__(parent)
        self.model = model
        self.image_manager = image_manager
        
        self.grid_layout = QGridLayout(self)
        self.labels = [] # 用于存储QLabel的二维列表
        
        self.init_ui()

    def init_ui(self):
        # 清空旧的布局
        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            if widget is not None:
                widget.setParent(None)
        self.labels.clear()

        # 从配置读取布局
        self.rows = self.model.config['Preview'].getint('rows', 3)
        self.cols = self.model.config['Preview'].getint('columns', 2)
        
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

    @pyqtSlot(int)
    def update_previews(self, current_index):
        if current_index < 0:
            self.clear_previews()
            return
            
        offset = self.rows // 2
        
        for r in range(self.rows):
            target_index = current_index - offset + r
            
            # 处理第一列：去噪图
            if self.cols > 0:
                self.update_label_content(r, 0, target_index, "denoised")

            # 处理第二列：合成图
            if self.cols > 1:
                self.update_label_content(r, 1, target_index, "overlay")
            
            # 未来如果想加第三列，在这里加个 if self.cols > 2 ... 即可

    def update_label_content(self, r, c, index, image_type):
        label = self.labels[r][c]
        if 0 <= index < len(self.model._original_files):
            pixmap = self.get_pixmap_for_type(index, image_type)
            if pixmap:
                scaled_pixmap = pixmap.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                label.setPixmap(scaled_pixmap)
            else:
                label.setText("图像加载失败")
        else:
            label.setText("") # 索引越界，显示空白
            label.setPixmap(QPixmap())


    def get_pixmap_for_type(self, index, image_type):
        if image_type == "denoised":
            if self.model._denoised_files:
                return self.image_manager.load_pixmap(self.model._denoised_files[index])
            else:
                return None # 如果没有去噪图路径
        
        if image_type == "overlay":
            original_pixmap = self.image_manager.load_pixmap(self.model._original_files[index])
            mask_pixmap = self.image_manager.load_pixmap(self.model._mask_files[index])
            
            # 如果mask不存在，为它创建一个临时的空mask
            if original_pixmap and not mask_pixmap:
                 mask_pixmap = QPixmap(original_pixmap.size())
                 mask_pixmap.fill(Qt.GlobalColor.black)

            style = self.model.config['Preview'].get('overlay_style', 'overlay')
            color_str = self.model.config['Colors'].get('mask_overlay_color')
            color_rgba = tuple(map(int, color_str.split(',')))
            
            return self.image_manager.create_overlay_pixmap(original_pixmap, mask_pixmap, style, color_rgba)

        return None

    def clear_previews(self):
        for row in self.labels:
            for label in row:
                label.setText("")
                label.setPixmap(QPixmap())