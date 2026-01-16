# File: ui/widgets/script_dialogs.py

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QGroupBox, QMessageBox)
from .path_selector import PathSelector

class ApplyMaskScriptDialog(QDialog):
    """
    专门用于配置“应用 Mask 抠图”脚本的对话框。
    包含三个路径选择器：Mask源、原图源、保存路径。
    """
    def __init__(self, default_mask_path="", default_img_path="", default_save_path="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("脚本配置: 应用 Mask 抠图")
        self.setMinimumWidth(500)
        
        self.mask_path = default_mask_path
        self.img_path = default_img_path
        self.save_path = default_save_path
        
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # 分组：输入设置
        input_group = QGroupBox("输入设置")
        input_layout = QVBoxLayout(input_group)
        
        self.selector_mask = PathSelector("Mask 路径 (二值图):")
        self.selector_mask.set_path(self.mask_path)
        
        self.selector_img = PathSelector("原图路径 (待抠图):")
        self.selector_img.set_path(self.img_path)
        
        input_layout.addWidget(self.selector_mask)
        input_layout.addWidget(self.selector_img)
        layout.addWidget(input_group)
        
        # 分组：输出设置
        output_group = QGroupBox("输出设置")
        output_layout = QVBoxLayout(output_group)
        
        self.selector_save = PathSelector("结果保存路径:")
        self.selector_save.set_path(self.save_path)
        
        output_layout.addWidget(self.selector_save)
        layout.addWidget(output_group)
        
        # 底部说明
        info_label = QLabel("说明：脚本将根据文件名匹配 Mask 和 原图。\n"
                            "Mask 中白色部分保留，黑色部分变透明。\n"
                            "结果将以 PNG 格式保存。")
        info_label.setStyleSheet("color: gray; margin-top: 10px;")
        layout.addWidget(info_label)
        
        layout.addStretch()
        
        # 按钮
        btn_layout = QHBoxLayout()
        self.btn_run = QPushButton("开始处理")
        self.btn_run.setDefault(True)
        self.btn_cancel = QPushButton("取消")
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_run)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)
        
        # 连接信号
        self.btn_run.clicked.connect(self.on_run)
        self.btn_cancel.clicked.connect(self.reject)
        
    def on_run(self):
        # 验证路径
        m_path = self.selector_mask.get_path()
        i_path = self.selector_img.get_path()
        s_path = self.selector_save.get_path()
        
        if not all([m_path, i_path, s_path]):
            QMessageBox.warning(self, "路径缺失", "请确保所有三个路径都已设置！")
            return
            
        self.mask_path = m_path
        self.img_path = i_path
        self.save_path = s_path
        self.accept() # 关闭对话框并返回 Accepted
        
    def get_paths(self):
        return self.mask_path, self.img_path, self.save_path