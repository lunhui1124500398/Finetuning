import os
import sys
# START: 修正 - 一次性导入所有需要的QtWidgets类
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QCheckBox, QFrame, QSplitter, QMessageBox, QDockWidget,
    QButtonGroup, QRadioButton, QLabel
)
# END: 修正
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
        
        # 3. 创建菜单栏(早于创建快捷键)
        self._create_menu()

        # 4. 创建所有动作和快捷键
        self._create_actions_and_shortcuts()

        # 5. 连接所有信号和槽
        self._connect_signals()
        
        # 6. 加载初始配置
        self._load_initial_settings()

    def init_ui(self):
        self.setWindowTitle("手动抠图工具 V2.0")
        self.setGeometry(100, 100, 1800, 1000)

        # --- 主布局 ---
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        # 主窗口的中心区域不再需要一个主布局，因为QSplitter将成为中心控件
        main_layout = QHBoxLayout(central_widget) # 使用QHBoxLayout来容纳QSplitter

        # --- 路径区 DockWidget ---
        self.path_dock_widget = QDockWidget("路径设置 (可拖拽)", self)
        self.path_dock_widget.setAllowedAreas(Qt.DockWidgetArea.TopDockWidgetArea | Qt.DockWidgetArea.BottomDockWidgetArea)
        
        path_widget = QWidget() # DockWidget需要一个内部的widget
        path_layout = QVBoxLayout(path_widget)
        
        self.original_path_selector = PathSelector("原图路径*:")
        self.denoised_path_selector = PathSelector("去噪图路径:")
        self.mask_path_selector = PathSelector("二值化图路径(参考):")
        self.save_path_selector = PathSelector("保存路径*:") # <--- A2. 新增保存路径
        self.import_button = QPushButton("加载/刷新图像 (I)")
        
        path_layout.addWidget(self.original_path_selector)
        path_layout.addWidget(self.denoised_path_selector)
        path_layout.addWidget(self.mask_path_selector)
        path_layout.addWidget(self.save_path_selector)
        path_layout.addWidget(self.import_button)
        path_widget.setLayout(path_layout)
        
        self.path_dock_widget.setWidget(path_widget)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.path_dock_widget)
        

        # --- 中部主分隔器 ---
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 中左部：图像画布和进度条
        canvas_area = QFrame() # 使用QFrame以获得边框
        canvas_area.setFrameShape(QFrame.Shape.StyledPanel)
        canvas_layout = QVBoxLayout(canvas_area)
        self.canvas = ImageCanvas(self.model, self.image_manager)
        self.progress_slider = ProgressSlider()
        canvas_layout.addWidget(self.canvas)
        canvas_layout.addWidget(self.progress_slider)
        
        # 中右部：预览区和功能按钮
        right_splitter = QSplitter(Qt.Orientation.Vertical) # 右侧再用一个垂直分隔器

        self.preview_panel = PreviewPanel(self.model, self.image_manager)
        
        # 功能区
        function_frame = QFrame()
        function_frame.setFrameShape(QFrame.Shape.StyledPanel)
        function_layout = QVBoxLayout(function_frame)

        # Mask显示控制
        mask_options_layout = QHBoxLayout()
        self.show_mask_checkbox = QCheckBox("显示Mask (Z)")
        # self.show_mask_checkbox.setChecked(True) # 默认开启
        self.mask_invert_checkbox = QCheckBox("反相显示")
        mask_options_layout.addWidget(self.show_mask_checkbox)
        mask_options_layout.addWidget(self.mask_invert_checkbox)

        mask_style_layout = QHBoxLayout()
        mask_style_label = QLabel("显示方式:")
        self.area_radio = QRadioButton("面积")
        self.contour_radio = QRadioButton("轮廓")
        self.area_radio.setChecked(True)
        self.mask_style_group = QButtonGroup(self)
        self.mask_style_group.addButton(self.area_radio)
        self.mask_style_group.addButton(self.contour_radio)
        mask_style_layout.addWidget(mask_style_label)
        mask_style_layout.addWidget(self.area_radio)
        mask_style_layout.addWidget(self.contour_radio)

        # 自动功能
        auto_options_layout = QHBoxLayout()
        self.auto_save_checkbox = QCheckBox("自动保存 (X)")
        self.high_contrast_checkbox = QCheckBox("高对比度 (C)")
        auto_options_layout.addWidget(self.auto_save_checkbox)
        auto_options_layout.addWidget(self.high_contrast_checkbox)

        # 绘图工具
        tool_layout = QHBoxLayout()
        self.draw_button = QPushButton("画笔 (Q)")
        self.erase_button = QPushButton("橡皮 (E)")
        self.draw_button.setCheckable(True) # 设置为可选中
        self.erase_button.setCheckable(True)
        self.tool_button_group = QButtonGroup(self) # 放入组中，实现互斥
        self.tool_button_group.addButton(self.draw_button)
        self.tool_button_group.addButton(self.erase_button)
        self.draw_button.setChecked(True) # 默认是画笔模式
        tool_layout.addWidget(self.draw_button)
        tool_layout.addWidget(self.erase_button)

        # 操作按钮
        action_layout = QHBoxLayout()
        self.clear_button = QPushButton("清除Mask (W)")
        self.save_button = QPushButton("保存 (Ctrl+S)")
        action_layout.addWidget(self.clear_button)
        action_layout.addWidget(self.save_button)

        # 导航按钮
        nav_layout = QHBoxLayout()
        self.prev_button = QPushButton("上一张 (A/←)")
        self.next_button = QPushButton("下一张 (D/→)")
        nav_layout.addWidget(self.prev_button)
        nav_layout.addWidget(self.next_button)

        # 组装功能区布局
        function_layout.addLayout(mask_options_layout)
        function_layout.addLayout(mask_style_layout)
        function_layout.addLayout(auto_options_layout)
        function_layout.addStretch()
        function_layout.addLayout(tool_layout)
        function_layout.addLayout(action_layout)
        function_layout.addStretch()
        function_layout.addLayout(nav_layout)
        
        # --- 组装右侧 ---
        right_splitter.addWidget(self.preview_panel)
        right_splitter.addWidget(function_frame)
        right_splitter.setStretchFactor(0, 2)
        right_splitter.setStretchFactor(1, 1)

        # --- 组装整体 ---
        main_splitter.addWidget(canvas_area)
        main_splitter.addWidget(right_splitter)
        main_splitter.setStretchFactor(0, 4) # 画布区域占比大
        main_splitter.setStretchFactor(1, 1)

        main_layout.addWidget(main_splitter)
        
        # --- START: A4 - 灵活布局 ---
        # 使用垂直QSplitter，用户可以自由调整预览区和功能区的高度
        right_splitter.addWidget(self.preview_panel)
        right_splitter.addWidget(function_frame)
        right_splitter.setStretchFactor(0, 2) # 预览区占比大
        right_splitter.setStretchFactor(1, 1)

        main_splitter.addWidget(canvas_area)
        main_splitter.addWidget(right_splitter) # 将垂直分隔器加入水平分隔器
        main_splitter.setStretchFactor(0, 4) # 画布区域占比大
        main_splitter.setStretchFactor(1, 1)

        # --- 组装主布局 ---
        # 移除旧的main_layout.addWidget(path_frame)
        main_layout.addWidget(main_splitter)
    
    # --- START: A3 - 创建菜单栏 ---
    def _create_menu(self):
        self.menu_bar = self.menuBar()
        
        # 文件菜单
        file_menu = self.menu_bar.addMenu("文件(&F)")
        
        # 使用Action而不是直接用Button，便于统一管理
        import_action = QAction("加载/刷新图像 (I)", self)
        import_action.triggered.connect(self.import_images)
        file_menu.addAction(import_action)
        
        # 添加分隔符
        file_menu.addSeparator()
        
        exit_action = QAction("退出(&Q)", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 视图菜单
        view_menu = self.menu_bar.addMenu("视图(&V)")
        toggle_path_dock_action = self.path_dock_widget.toggleViewAction()
        toggle_path_dock_action.setText("显示/隐藏路径面板")
        view_menu.addAction(toggle_path_dock_action)

        # 设置菜单 (未来可扩展)
        settings_menu = self.menu_bar.addMenu("设置(&S)")
        # 示例: self.change_color_action = QAction("修改Mask颜色...", self)
        # settings_menu.addAction(self.change_color_action)
    # --- END: A3 ---

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
        
        # --- START: C1. 修复索引同步问题 ---
        # 1. UI -> Model
        self.progress_slider.slider.valueChanged.connect(self.model.set_current_index)
        self.prev_button.clicked.connect(self.model.decrement_index)
        self.next_button.clicked.connect(self.model.increment_index)

        # 2. Model -> UI (这是关键的解耦步骤)
        self.model.index_changed.connect(self.on_index_changed) # <--- 关键连接
        self.model.files_changed.connect(self.on_files_changed)
        # self.model.index_changed.connect(self.progress_slider.slider.setValue)
        
        # 移除旧的连接
        # self.model.index_changed.connect(self.canvas.load_image)
        # self.model.index_changed.connect(self.preview_panel.update_previews)
        
        self.model.files_changed.connect(self.on_files_changed)
        self.model.show_mask_changed.connect(self.canvas.set_mask_visibility)
        # self.model.show_mask_changed.connect(self.show_mask_checkbox.setChecked)
        
        # --- START: B. 连接新功能信号 ---
        # 工具按钮 -> 模型
        self.draw_button.clicked.connect(lambda: self.model.set_drawing_mode("draw"))
        self.erase_button.clicked.connect(lambda: self.model.set_drawing_mode("erase"))

        # Mask显示选项 -> 模型
        self.show_mask_checkbox.toggled.connect(self.model.toggle_show_mask)
        self.mask_invert_checkbox.toggled.connect(self.model.set_mask_invert)
        self.area_radio.toggled.connect(lambda checked: self.model.set_mask_display_style("area") if checked else None)
        self.contour_radio.toggled.connect(lambda checked: self.model.set_mask_display_style("contour") if checked else None)
        self.high_contrast_checkbox.toggled.connect(self.model.set_high_contrast)
        
        # 模型 -> 画布 (Canvas)
        self.model.mode_changed.connect(self.canvas.set_drawing_mode)
        self.model.show_mask_changed.connect(self.canvas.set_mask_visibility)
        self.model.mask_display_changed.connect(self.canvas.update_mask_item)
        self.model.high_contrast_changed.connect(self.canvas.set_high_contrast)
        self.model.mask_updated.connect(self.canvas.update_mask_item) # 每次绘制后也刷新
        # --- END: B ---
    
    @pyqtSlot(int)
    def on_index_changed(self, index):
        """模型索引变化时，统一更新所有相关UI。"""
        if index < 0:
            return
            
        # 1. 更新进度条 (临时阻塞信号避免循环)
        self.progress_slider.slider.blockSignals(True)
        self.progress_slider.set_value(index)
        self.progress_slider.slider.blockSignals(False)

        # 2. 更新主画布
        self.canvas.load_image(index)
        
        # 3. 更新预览区
        self.preview_panel.update_previews(index)

    @pyqtSlot(int)
    def on_files_changed(self, total_files):
        if total_files > 0:
            self.progress_slider.set_range(0, total_files - 1)
            # 主动触发一次索引更新来加载第一张图
            self.on_index_changed(self.model.current_index)
        else:
            self.progress_slider.set_range(0, -1) # 禁用
            self.preview_panel.clear_previews()
            self.canvas.load_image(-1) # 清空画布
            QMessageBox.information(self, "导入完成", "未在原图路径中找到任何图片。")

    def _load_initial_settings(self):
        # ... (加载原图、去噪图、二值化图路径)
        self.original_path_selector.set_path(self.model.get_path('original_path'))
        self.denoised_path_selector.set_path(self.model.get_path('denoised_path'))
        self.mask_path_selector.set_path(self.model.get_path('mask_path'))
        
        # --- START: A2 - 加载并设置保存路径 ---
        save_path = self.model.get_path('save_path')
        if not save_path: # 如果为空，则默认使用二值化图路径
            save_path = self.model.get_path('mask_path')
        self.save_path_selector.set_path(save_path)
        # --- END: A2 ---
        
        self.show_mask_checkbox.setChecked(self.model.show_mask)
        self.auto_save_checkbox.setChecked(self.model.auto_save)
    def closeEvent(self, event):
        # 关闭程序前保存当前路径到配置文件
        self.model.config['Paths']['original_path'] = self.original_path_selector.get_path()
        self.model.config['Paths']['denoised_path'] = self.denoised_path_selector.get_path()
        self.model.config['Paths']['mask_path'] = self.mask_path_selector.get_path()
        # --- START: A2 - 保存路径 ---
        self.model.config['Paths']['save_path'] = self.save_path_selector.get_path()
        # --- END: A2 ---
        with open(self.model.config_path, 'w', encoding='utf-8') as configfile: # 增加encoding
            self.model.config.write(configfile)
        
        super().closeEvent(event)

    def import_images(self):
        original_path = self.original_path_selector.get_path()
        save_path = self.save_path_selector.get_path() # <--- A2. 增加保存路径校验
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