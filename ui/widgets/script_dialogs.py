# File: ui/widgets/script_dialogs.py

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QGroupBox, QMessageBox, QRadioButton,
                             QButtonGroup)
from PyQt6.QtCore import Qt
from .path_selector import PathSelector
from utils.path_utils import to_filesystem_path


class ScriptInputDialog(QDialog):
    """
    通用的脚本输入/输出配置对话框。
    支持从配置文件读取默认设置，允许用户修改输入源和输出路径。
    """
    def __init__(self, script_name: str, model, save_dir: str, 
                 description: str = "", parent=None):
        """
        Args:
            script_name: 脚本名称，用于对话框标题
            model: AppModel 实例 (包含 config)
            save_dir: 默认保存目录路径
            description: 脚本说明文字
            parent: 父窗口
        """
        super().__init__(parent)
        self.setWindowTitle(f"脚本配置: {script_name}")
        self.setMinimumWidth(550)
        
        self.model = model
        self.config = model.config
        self.default_save_dir = save_dir
        self.description = description
        
        # 从配置读取默认设置
        self._load_config_defaults()
        
        # 获取可用路径
        self.mask_path = model.get_path('mask_path') or ""
        self._init_file_counts()
        
        # 结果
        self.selected_files = []
        self.selected_source = ""
        self.output_dir = save_dir
        
        self.init_ui()
        
    def _load_config_defaults(self):
        """从配置文件加载默认设置"""
        self.default_input = self.config.get('Scripts', 'default_input_source', fallback='auto')
        self.default_output = self.config.get('Scripts', 'default_output_source', fallback='save_path')
        
    def _init_file_counts(self):
        """初始化各路径的文件计数"""
        from core.image_manager import ImageManager
        import os
        
        self.save_files = []
        self.mask_files = []
        
        if self.default_save_dir and os.path.isdir(to_filesystem_path(self.default_save_dir)):
            self.save_files = ImageManager.get_image_files(self.default_save_dir)
        if self.mask_path and os.path.isdir(to_filesystem_path(self.mask_path)):
            self.mask_files = ImageManager.get_image_files(self.mask_path)
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # ===== 输入来源选择组 =====
        source_group = QGroupBox("选择输入来源")
        source_layout = QVBoxLayout(source_group)
        
        self.source_button_group = QButtonGroup(self)
        
        # 选项1: Save Path
        save_count = len(self.save_files)
        self.radio_save = QRadioButton(
            f"使用 Save Path (已处理) - {save_count} 个文件"
        )
        self.radio_save.setEnabled(save_count > 0)
        self.radio_save.setToolTip(self.default_save_dir if save_count > 0 else "Save Path 中没有图像文件")
        
        # 选项2: Mask Path
        mask_count = len(self.mask_files)
        self.radio_mask = QRadioButton(
            f"使用 Mask Path (原始) - {mask_count} 个文件"
        )
        self.radio_mask.setEnabled(mask_count > 0)
        self.radio_mask.setToolTip(self.mask_path if mask_count > 0 else "Mask Path 中没有图像文件")
        
        self.source_button_group.addButton(self.radio_save, 0)
        self.source_button_group.addButton(self.radio_mask, 1)
        
        # 根据配置设置默认选中
        self._apply_default_input_selection(save_count, mask_count)
        
        source_layout.addWidget(self.radio_save)
        source_layout.addWidget(self.radio_mask)
        
        # 路径详情
        path_detail = QLabel(
            f"Save Path: {self.default_save_dir or '(未设置)'}\n"
            f"Mask Path: {self.mask_path or '(未设置)'}"
        )
        path_detail.setStyleSheet("color: gray; font-size: 11px; margin-top: 5px;")
        path_detail.setWordWrap(True)
        source_layout.addWidget(path_detail)
        
        layout.addWidget(source_group)
        
        # ===== 输出设置组 =====
        output_group = QGroupBox("输出设置")
        output_layout = QVBoxLayout(output_group)
        
        # 输出路径选择器 (仅当 default_output == 'custom' 时可编辑)
        self.output_selector = PathSelector("保存路径:")
        self.output_selector.set_path(self.default_save_dir)
        
        if self.default_output == 'save_path':
            # 锁定为 save_path，但仍显示以便用户知道输出位置
            self.output_selector.setEnabled(False)
            self.output_selector.setToolTip("输出路径已锁定为 Save Path (可在设置中修改)")
        
        output_layout.addWidget(self.output_selector)
        
        warning_label = QLabel("⚠️ 将覆盖同名文件")
        warning_label.setStyleSheet("color: orange;")
        output_layout.addWidget(warning_label)
        layout.addWidget(output_group)
        
        # ===== 脚本说明 =====
        if self.description:
            desc_label = QLabel(self.description)
            desc_label.setStyleSheet("color: gray; margin-top: 10px;")
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)
        
        layout.addStretch()
        
        # ===== 按钮 =====
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
        
        # 检查是否有任何可用输入
        if not self.save_files and not self.mask_files:
            self.btn_run.setEnabled(False)
            self.btn_run.setToolTip("没有可用的输入文件")
    
    def _apply_default_input_selection(self, save_count: int, mask_count: int):
        """根据配置应用默认输入源选择"""
        if self.default_input == 'save_path':
            if save_count > 0:
                self.radio_save.setChecked(True)
            elif mask_count > 0:
                self.radio_mask.setChecked(True)
        elif self.default_input == 'mask_path':
            if mask_count > 0:
                self.radio_mask.setChecked(True)
            elif save_count > 0:
                self.radio_save.setChecked(True)
        else:  # 'auto' - 智能检测
            if save_count > 0:
                self.radio_save.setChecked(True)
            elif mask_count > 0:
                self.radio_mask.setChecked(True)
        
    def on_run(self):
        """处理开始按钮点击"""
        if self.radio_save.isChecked():
            self.selected_files = self.save_files
            self.selected_source = "save_path (已处理)"
        elif self.radio_mask.isChecked():
            self.selected_files = self.mask_files
            self.selected_source = "mask_path (原始)"
        else:
            QMessageBox.warning(self, "未选择来源", "请选择一个输入来源！")
            return
        
        if not self.selected_files:
            QMessageBox.warning(self, "无文件", "所选来源中没有图像文件！")
            return
        
        # 获取输出路径
        self.output_dir = self.output_selector.get_path()
        if not self.output_dir:
            QMessageBox.warning(self, "路径缺失", "请设置输出保存路径！")
            return
            
        self.accept()
        
    def get_input_files(self):
        """获取用户选择的输入文件列表"""
        return self.selected_files
    
    def get_source_name(self):
        """获取用户选择的来源名称"""
        return self.selected_source
    
    def get_output_dir(self):
        """获取用户选择的输出目录"""
        return self.output_dir
    
    @staticmethod
    def get_script_config(model, save_dir: str):
        """
        静态方法：根据配置判断是否需要显示对话框。
        如果 show_input_dialog = false，直接返回默认值。
        
        Returns:
            tuple: (should_show_dialog, input_files, output_dir) 或 (True, None, None) 如果需显示对话框
        """
        from core.image_manager import ImageManager
        import os
        
        config = model.config
        show_dialog = config.get('Scripts', 'show_input_dialog', fallback='true').lower() == 'true'
        
        if show_dialog:
            return True, None, None
        
        # 不显示对话框，直接使用默认配置
        default_input = config.get('Scripts', 'default_input_source', fallback='auto')
        default_output = config.get('Scripts', 'default_output_source', fallback='save_path')
        
        mask_path = model.get_path('mask_path') or ""
        
        # 获取文件列表
        save_files = ImageManager.get_image_files(save_dir) if save_dir and os.path.isdir(to_filesystem_path(save_dir)) else []
        mask_files = ImageManager.get_image_files(mask_path) if mask_path and os.path.isdir(to_filesystem_path(mask_path)) else []
        
        # 根据配置选择输入源
        if default_input == 'save_path':
            input_files = save_files if save_files else mask_files
        elif default_input == 'mask_path':
            input_files = mask_files if mask_files else save_files
        else:  # 'auto'
            input_files = save_files if save_files else mask_files
        
        # 输出目录
        output_dir = save_dir  # 当 show_dialog=false 时，输出始终使用 save_path
        
        return False, input_files, output_dir

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
