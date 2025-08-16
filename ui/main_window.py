# Finetuning/ui/main_window.py

import os
import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QCheckBox, QFrame, QSplitter, QMessageBox, QDockWidget,
    QButtonGroup, QRadioButton, QLabel, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QAction, QKeySequence

from ..core.app_model import AppModel
from ..core.image_manager import ImageManager
from .widgets.path_selector import PathSelector
from .widgets.image_canvas import ImageCanvas
from .widgets.preview_panel import PreviewPanel
from .widgets.progress_slider import ProgressSlider

class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.model = AppModel()
        self.image_manager = ImageManager()

        self.init_ui()
        self._create_menu()
        self._create_actions_and_shortcuts()
        self._connect_signals()
        
        # 保存主窗口、主分割器和右侧分割器的初始状态
        self.initial_layout_states = {
            'main_window': self.saveState(),
            'main_splitter': self.main_splitter.saveState(),
            'right_splitter': self.right_splitter.saveState()
        }

        self._load_initial_settings()

        self.initial_state = self.saveState()  

    def init_ui(self):
        self.setWindowTitle("手动抠图工具 V3.2")
        self.setGeometry(100, 100, 1800, 1000)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # Path Dock Widget
        self.path_dock_widget = QDockWidget("路径设置 (可拖拽)", self)
        self.path_dock_widget.setObjectName("PathDockWidget") # 修复无名问题
        self.path_dock_widget.setAllowedAreas(Qt.DockWidgetArea.TopDockWidgetArea | Qt.DockWidgetArea.BottomDockWidgetArea)
        path_widget = QWidget()
        path_layout = QVBoxLayout(path_widget)
        self.original_path_selector = PathSelector("原图路径*:")
        self.denoised_path_selector = PathSelector("去噪图路径:")
        self.mask_path_selector = PathSelector("二值化图路径(参考):")
        self.save_path_selector = PathSelector("保存路径*:")
        self.import_button = QPushButton("加载/刷新图像 (I)")
        path_layout.addWidget(self.original_path_selector)
        path_layout.addWidget(self.denoised_path_selector)
        path_layout.addWidget(self.mask_path_selector)
        path_layout.addWidget(self.save_path_selector)
        path_layout.addWidget(self.import_button)
        self.path_dock_widget.setWidget(path_widget)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.path_dock_widget)
        
        # Main Splitter
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Canvas Area (Left)
        canvas_area = QFrame()
        canvas_area.setFrameShape(QFrame.Shape.StyledPanel)
        canvas_layout = QVBoxLayout(canvas_area)
        self.canvas = ImageCanvas(self.model, self.image_manager)
        self.progress_slider = ProgressSlider()
        canvas_layout.addWidget(self.canvas)
        canvas_layout.addWidget(self.progress_slider)
        
        # Right Splitter (Preview + Functions)
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.preview_panel = PreviewPanel(self.model, self.image_manager)
        
        # Function Frame
        function_frame = QFrame()
        function_frame.setFrameShape(QFrame.Shape.StyledPanel)
        function_layout = QVBoxLayout(function_frame)

        # Display Options Group
        display_group = QGroupBox("显示选项")
        display_layout = QVBoxLayout(display_group)
        mask_options_layout = QHBoxLayout()
        self.show_mask_checkbox = QCheckBox("显示Mask (Z)")
        self.mask_invert_checkbox = QCheckBox("反相显示")
        mask_options_layout.addWidget(self.show_mask_checkbox)
        mask_options_layout.addWidget(self.mask_invert_checkbox)
        mask_style_layout = QHBoxLayout()
        self.area_radio = QRadioButton("面积")
        self.contour_radio = QRadioButton("轮廓")
        self.area_radio.setChecked(True)
        self.mask_style_group = QButtonGroup(self)
        self.mask_style_group.addButton(self.area_radio)
        self.mask_style_group.addButton(self.contour_radio)
        mask_style_layout.addWidget(QLabel("显示方式:"))
        mask_style_layout.addWidget(self.area_radio)
        mask_style_layout.addWidget(self.contour_radio)
        auto_options_layout = QHBoxLayout()
        self.auto_save_checkbox = QCheckBox("自动保存 (X)")
        self.high_contrast_checkbox = QCheckBox("高对比度 (C)")
        auto_options_layout.addWidget(self.auto_save_checkbox)
        auto_options_layout.addWidget(self.high_contrast_checkbox)
        display_layout.addLayout(mask_options_layout)
        display_layout.addLayout(mask_style_layout)
        display_layout.addLayout(auto_options_layout)

        # Edit Tools Group
        tools_group = QGroupBox("编辑工具")
        tools_layout = QVBoxLayout(tools_group)
        tool_buttons_layout = QHBoxLayout()
        self.draw_button = QPushButton("画笔 (Q)")
        self.erase_button = QPushButton("橡皮 (E)")
        self.draw_button.setCheckable(True)
        self.erase_button.setCheckable(True)
        self.tool_button_group = QButtonGroup(self)
        self.tool_button_group.addButton(self.draw_button)
        self.tool_button_group.addButton(self.erase_button)
        self.draw_button.setChecked(True)
        tool_buttons_layout.addWidget(self.draw_button)
        tool_buttons_layout.addWidget(self.erase_button)
        action_buttons_layout = QHBoxLayout()
        self.clear_button = QPushButton("清除Mask (W)")
        self.save_button = QPushButton("保存 (Ctrl+S)")
        action_buttons_layout.addWidget(self.clear_button)
        action_buttons_layout.addWidget(self.save_button)
        tools_layout.addLayout(tool_buttons_layout)
        tools_layout.addLayout(action_buttons_layout)

        # Nav buttons
        nav_layout = QHBoxLayout()
        self.prev_button = QPushButton("上一张 (A/←)")
        self.next_button = QPushButton("下一张 (D/→)")
        nav_layout.addWidget(self.prev_button)
        nav_layout.addWidget(self.next_button)

        # Assemble function layout
        function_layout.addWidget(display_group)
        function_layout.addWidget(tools_group)
        function_layout.addStretch()
        function_layout.addLayout(nav_layout)
        function_frame.setLayout(function_layout) # 确保function_frame有布局
        
        # Assemble splitters and main layout
        self.right_splitter.addWidget(self.preview_panel)
        self.right_splitter.addWidget(function_frame)
        self.right_splitter.setSizes([600, 200]) # 调整初始比例
        self.main_splitter.addWidget(canvas_area)
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setSizes([1200, 600]) # 调整初始比例
        main_layout.addWidget(self.main_splitter)
    
    def _create_menu(self):
        # ... (此部分未修改，保持原样)
        self.menu_bar = self.menuBar()
        file_menu = self.menu_bar.addMenu("文件(&F)")
        import_action = QAction("加载/刷新图像 (I)", self)
        import_action.triggered.connect(self.import_images)
        file_menu.addAction(import_action)
        file_menu.addSeparator()
        exit_action = QAction("退出(&Q)", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        edit_menu = self.menu_bar.addMenu("编辑(&E)")
        undo_action = QAction("撤销", self)
        undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        undo_action.triggered.connect(self.canvas.undo)
        edit_menu.addAction(undo_action)
        view_menu = self.menu_bar.addMenu("视图(&V)")
        toggle_path_dock_action = self.path_dock_widget.toggleViewAction()
        toggle_path_dock_action.setText("显示/隐藏路径面板")
        view_menu.addAction(toggle_path_dock_action)
        view_menu.addSeparator()
        self.restore_layout_action = QAction("恢复默认布局", self)
        self.restore_layout_action.triggered.connect(self.restore_layout)
        view_menu.addAction(self.restore_layout_action) 
        settings_menu = self.menu_bar.addMenu("设置(&S)")

    def _create_actions_and_shortcuts(self):
        def create_shortcut(key_name, function):
            shortcut_str = self.model.get_keybinding(key_name)
            action = QAction(self)
            shortcuts = [QKeySequence(key.strip()) for key in shortcut_str.replace(';', ',').split(',')]
            action.setShortcuts(shortcuts)
            action.triggered.connect(function)
            self.addAction(action)
        
        create_shortcut('next_image', self.model.increment_index)
        create_shortcut('prev_image', self.model.decrement_index)
        create_shortcut('save', self.canvas.save_current_mask)
        create_shortcut('draw_mode', lambda: self.model.set_drawing_mode("draw"))
        create_shortcut('erase_mode', lambda: self.model.set_drawing_mode("erase"))
        create_shortcut('clear_mask', self.canvas.clear_current_mask)
        create_shortcut('import_files', self.import_images)

        # --- START: 核心修正 - 快捷键直接更新模型，而不是模拟UI点击 ---
        create_shortcut('toggle_mask', lambda: self.model.set_show_mask(not self.model.show_mask))
        create_shortcut('auto_save', lambda: self.model.set_auto_save(not self.model.auto_save))
        create_shortcut('high_contrast', lambda: self.model.set_high_contrast(not self.model.high_contrast))
        # --- END: 核心修正 ---

    def _connect_signals(self):
        # 路径与导航
        self.import_button.clicked.connect(self.import_images)
        self.prev_button.clicked.connect(self.model.decrement_index)
        self.next_button.clicked.connect(self.model.increment_index)
        self.progress_slider.slider.valueChanged.connect(self.model.set_current_index)
        
        # 编辑操作
        self.clear_button.clicked.connect(self.canvas.clear_current_mask)
        self.save_button.clicked.connect(self.canvas.save_current_mask)

        # --- START: 核心修正 - 修正信号连接以打破递归 ---

        # 1. 工具按钮: 使用 toggled 信号, 并且只在选中时触发
        self.draw_button.toggled.connect(lambda checked: self.model.set_drawing_mode("draw") if checked else None)
        self.erase_button.toggled.connect(lambda checked: self.model.set_drawing_mode("erase") if checked else None)
        
        # 2. 复选框: toggled 信号直接连接到模型的 set 方法
        self.show_mask_checkbox.toggled.connect(self.model.set_show_mask)
        self.auto_save_checkbox.toggled.connect(self.model.set_auto_save)
        self.high_contrast_checkbox.toggled.connect(self.model.set_high_contrast)
        self.mask_invert_checkbox.toggled.connect(self.model.set_mask_invert)
        
        # 3. 单选按钮
        self.area_radio.toggled.connect(lambda checked: self.model.set_mask_display_style("area") if checked else None)
        self.contour_radio.toggled.connect(lambda checked: self.model.set_mask_display_style("contour") if checked else None)
        
        # --- END: 核心修正 ---

        # === 模型 -> UI (单向数据流，负责同步界面) ===
        self.model.index_changed.connect(self.on_index_changed)
        self.model.files_changed.connect(self.on_files_changed)
        
        # 同步功能按钮/复选框的状态
        self.model.mode_changed.connect(self.on_mode_changed)
        self.model.show_mask_changed.connect(self.show_mask_checkbox.setChecked)
        self.model.auto_save_changed.connect(self.auto_save_checkbox.setChecked)
        self.model.high_contrast_changed.connect(self.high_contrast_checkbox.setChecked)
        self.model.mask_display_changed.connect(self.on_mask_display_changed) # 新增槽
        
        # 同步画布
        self.model.mask_updated.connect(self.canvas.update_mask_item)
        self.model.high_contrast_changed.connect(self.canvas.set_high_contrast)
        self.model.mask_display_changed.connect(self.canvas.update_mask_item)
        self.model.show_mask_changed.connect(self.canvas.set_mask_visibility)

    # --- Slots for Model -> UI updates ---
    @pyqtSlot(str)
    def on_mode_changed(self, mode):
        self.canvas.set_drawing_mode(mode)
        if mode == 'draw':
            self.draw_button.setChecked(True)
        elif mode == 'erase':
            self.erase_button.setChecked(True)

    @pyqtSlot()
    def on_mask_display_changed(self):
        """当模型的显示风格或反相状态改变时，更新UI"""
        style = self.model.mask_display_style
        if style == "area":
            self.area_radio.setChecked(True)
        elif style == "contour":
            self.contour_radio.setChecked(True)
        self.mask_invert_checkbox.setChecked(self.model.mask_invert)
        # canvas的更新已通过独立信号连接处理

    @pyqtSlot(int)
    def on_index_changed(self, index):
        if index < 0: return
        self.progress_slider.slider.blockSignals(True)
        self.progress_slider.set_value(index)
        self.progress_slider.slider.blockSignals(False)
        self.progress_slider.update_label() # <-- 新增
        self.canvas.load_image(index)
        self.preview_panel.update_previews(index)

    @pyqtSlot(int)
    def on_files_changed(self, total_files):
        if total_files > 0:
            self.progress_slider.set_range(0, total_files - 1)
            self.on_index_changed(self.model.current_index)
        else:
            self.progress_slider.set_range(0, -1)
            self.preview_panel.clear_previews()
            self.canvas.load_image(-1)
            QMessageBox.information(self, "提示", "在指定路径下未找到图像文件。")
    
    # --- Other methods ---
    def _load_initial_settings(self):
        self.original_path_selector.set_path(self.model.get_path('original_path'))
        self.denoised_path_selector.set_path(self.model.get_path('denoised_path'))
        self.mask_path_selector.set_path(self.model.get_path('mask_path'))
        save_path = self.model.get_path('save_path') or self.model.get_path('mask_path')
        self.save_path_selector.set_path(save_path)
        self.import_images()

    def import_images(self):
        original_path = self.original_path_selector.get_path()
        save_path = self.save_path_selector.get_path()
        if not original_path or not save_path:
            QMessageBox.warning(self, "路径错误", "请先选择“原图路径”和“保存路径”！")
            return
        self.model.update_file_lists(
            original_path, 
            self.denoised_path_selector.get_path(), 
            self.mask_path_selector.get_path()
        )

    def restore_layout(self):
        if hasattr(self, 'initial_state'):
            # 恢复主窗口（DockWidget）
            self.restoreState(self.initial_layout_states['main_window'])
            # 恢复主分割器
            self.main_splitter.restoreState(self.initial_layout_states['main_splitter'])
            # 恢复右侧分割器
            self.right_splitter.restoreState(self.initial_layout_states['right_splitter'])
            self.path_dock_widget.setVisible(True)

    def closeEvent(self, event):
        try:
            self.model.config['Paths']['original_path'] = self.original_path_selector.get_path()
            self.model.config['Paths']['denoised_path'] = self.denoised_path_selector.get_path()
            self.model.config['Paths']['mask_path'] = self.mask_path_selector.get_path()
            self.model.config['Paths']['save_path'] = self.save_path_selector.get_path()
            with open(self.model.config_path, 'w', encoding='utf-8') as configfile:
                self.model.config.write(configfile)
        except Exception as e:
            print(f"关闭时保存配置文件失败: {e}")
        super().closeEvent(event)