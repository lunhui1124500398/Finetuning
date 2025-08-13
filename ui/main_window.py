import os
import sys
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QCheckBox, QFrame, QSplitter, QMessageBox)
from PyQt6.QtCore import Qt,pyqtSlot
from PyQt6.QtGui import QAction, QKeySequence

# 导入我们自己的模块
from ..core.app_model import AppModel
from ..core.image_manager import ImageManager
from .widgets.path_selector import PathSelector
from .widgets.image_canvas import ImageCanvas
from .widgets.preview_panel import PreviewPanel
from .widgets.progress_slider import ProgressSlider

class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 1. 初始化核心组件
        self.model = AppModel()
        self.image_manager = ImageManager()

        # 2. 初始化UI
        self.init_ui()
        
        # 3. 创建所有动作和快捷键
        self._create_actions_and_shortcuts()

        # 4. 连接所有信号和槽
        self._connect_signals()
        
        # 5. 加载初始配置
        self._load_initial_settings()

    def init_ui(self):
        self.setWindowTitle("手动抠图工具")
        self.setGeometry(100, 100, 1600, 900)

        # --- 主布局 ---
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- 顶部：路径区 ---
        path_frame = QFrame()
        path_frame.setFrameShape(QFrame.Shape.StyledPanel)
        path_layout = QVBoxLayout(path_frame)
        self.original_path_selector = PathSelector("原图路径*:")
        self.denoised_path_selector = PathSelector("去噪图路径:")
        self.mask_path_selector = PathSelector("二值化图路径:")
        self.import_button = QPushButton("导入图像 (I)")
        path_layout.addWidget(self.original_path_selector)
        path_layout.addWidget(self.denoised_path_selector)
        path_layout.addWidget(self.mask_path_selector)
        path_layout.addWidget(self.import_button)

        # --- 中部：操作区和功能区 (使用可拖拽的分隔器) ---
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 中左部：图像画布和进度条
        canvas_area = QWidget()
        canvas_layout = QVBoxLayout(canvas_area)
        self.canvas = ImageCanvas(self.model, self.image_manager)
        self.progress_slider = ProgressSlider()
        canvas_layout.addWidget(self.canvas)
        canvas_layout.addWidget(self.progress_slider)
        
        # 中右部：预览区和功能按钮
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self.preview_panel = PreviewPanel(self.model, self.image_manager)
        
        # 功能区
        function_frame = QFrame()
        function_frame.setFrameShape(QFrame.Shape.StyledPanel)
        function_layout = QVBoxLayout(function_frame)
        
        self.show_mask_checkbox = QCheckBox("展示Mask (Z)")
        self.auto_save_checkbox = QCheckBox("自动保存 (X)")
        self.high_contrast_checkbox = QCheckBox("高对比度 (C)") # 功能待实现
        
        self.draw_button = QPushButton("画笔 (Q)")
        self.erase_button = QPushButton("橡皮 (E)")
        self.clear_button = QPushButton("清除Mask (W)")
        self.save_button = QPushButton("保存 (Ctrl+S)")
        
        nav_layout = QHBoxLayout()
        self.prev_button = QPushButton("上一张 (A)")
        self.next_button = QPushButton("下一张 (D)")
        nav_layout.addWidget(self.prev_button)
        nav_layout.addWidget(self.next_button)

        function_layout.addWidget(self.show_mask_checkbox)
        function_layout.addWidget(self.auto_save_checkbox)
        function_layout.addWidget(self.high_contrast_checkbox)
        function_layout.addStretch()
        function_layout.addWidget(self.draw_button)
        function_layout.addWidget(self.erase_button)
        function_layout.addWidget(self.clear_button)
        function_layout.addWidget(self.save_button)
        function_layout.addStretch()
        function_layout.addLayout(nav_layout)
        
        right_layout.addWidget(self.preview_panel)
        right_layout.addWidget(function_frame)

        main_splitter.addWidget(canvas_area)
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 4) # 画布区域占比大
        main_splitter.setStretchFactor(1, 1)

        # --- 组装主布局 ---
        main_layout.addWidget(path_frame)
        main_layout.addWidget(main_splitter)

    def _create_actions_and_shortcuts(self):
        # 为每个功能创建一个QAction，这样可以同时绑定到菜单、工具栏和快捷键
        # 这里简化处理，直接用QShortcut绑定到窗口
        def create_shortcut(key_name, function):
            shortcut_str = self.model.get_keybinding(key_name)
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut_str))
            action.triggered.connect(function)
            self.addAction(action)
        
        create_shortcut('next_image', self.model.increment_index)
        create_shortcut('prev_image', self.model.decrement_index)
        create_shortcut('save', self.canvas.save_current_mask)
        create_shortcut('draw_mode', lambda: self.model.set_drawing_mode("draw"))
        create_shortcut('erase_mode', lambda: self.model.set_drawing_mode("erase"))
        create_shortcut('clear_mask', self.canvas.clear_current_mask)
        create_shortcut('toggle_mask', self.show_mask_checkbox.toggle)
        create_shortcut('auto_save', self.auto_save_checkbox.toggle)
        create_shortcut('import_files', self.import_images)
        # ... 其他快捷键

    def _connect_signals(self):
        # 路径选择器 -> 模型
        self.import_button.clicked.connect(self.import_images)

        # 功能按钮/复选框 -> 模型/画布
        self.prev_button.clicked.connect(self.model.decrement_index)
        self.next_button.clicked.connect(self.model.increment_index)
        self.draw_button.clicked.connect(lambda: self.model.set_drawing_mode("draw"))
        self.erase_button.clicked.connect(lambda: self.model.set_drawing_mode("erase"))
        self.show_mask_checkbox.toggled.connect(self.model.toggle_show_mask)
        self.auto_save_checkbox.toggled.connect(self.model.toggle_auto_save)
        self.clear_button.clicked.connect(self.canvas.clear_current_mask)
        self.save_button.clicked.connect(self.canvas.save_current_mask)

        # 进度条 -> 模型
        self.progress_slider.slider.valueChanged.connect(self.model.set_current_index)
        
        # 模型 -> UI (这是关键的解耦步骤)
        self.model.files_changed.connect(self.on_files_changed)
        # self.model.index_changed.connect(self.progress_slider.slider.setValue)
        self.model.index_changed.connect(self.canvas.load_image)
        self.model.index_changed.connect(self.preview_panel.update_previews)
        self.model.show_mask_changed.connect(self.canvas.set_mask_visibility)
        # self.model.show_mask_changed.connect(self.show_mask_checkbox.setChecked)

    def _load_initial_settings(self):
        # 加载上次的路径
        self.original_path_selector.set_path(self.model.get_path('original_path'))
        self.denoised_path_selector.set_path(self.model.get_path('denoised_path'))
        self.mask_path_selector.set_path(self.model.get_path('mask_path'))
        
        # 设置初始状态
        self.show_mask_checkbox.setChecked(self.model.show_mask)
        self.auto_save_checkbox.setChecked(self.model.auto_save)

    def import_images(self):
        original_path = self.original_path_selector.get_path()
        if not original_path:
            QMessageBox.warning(self, "路径错误", "请先选择必须的“原图路径”！")
            return
            
        denoised_path = self.denoised_path_selector.get_path()
        mask_path = self.mask_path_selector.get_path()
        self.model.update_file_lists(original_path, denoised_path, mask_path)

    @pyqtSlot(int)
    def on_files_changed(self, total_files):
        if total_files > 0:
            self.progress_slider.set_range(0, total_files - 1)
        else:
            self.progress_slider.set_range(0, -1) # 禁用
            self.preview_panel.clear_previews()
            self.canvas.load_image(-1) # 清空画布
            QMessageBox.information(self, "导入完成", "未在原图路径中找到任何图片。")

    def closeEvent(self, event):
        # 关闭程序前保存当前路径到配置文件
        self.model.config['Paths']['original_path'] = self.original_path_selector.get_path()
        self.model.config['Paths']['denoised_path'] = self.denoised_path_selector.get_path()
        self.model.config['Paths']['mask_path'] = self.mask_path_selector.get_path()
        with open(self.model.config_path, 'w') as configfile:
            self.model.config.write(configfile)
        
        super().closeEvent(event)