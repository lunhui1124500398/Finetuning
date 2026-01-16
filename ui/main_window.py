# Finetuning/ui/main_window.py

import os
import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QCheckBox, QFrame, QSplitter, QMessageBox, QDockWidget,
    QButtonGroup, QRadioButton, QLabel, QGroupBox, QDialog, QSlider, QSizePolicy,
    QProgressDialog
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QAction, QKeySequence, QIcon, QGuiApplication

from core.app_model import AppModel
from core.image_manager import ImageManager
from .widgets.path_selector import PathSelector
from .widgets.image_canvas import ImageCanvas
from .widgets.preview_panel import PreviewPanel
from .widgets.progress_slider import ProgressSlider
from .widgets.settings_dialog import SettingsDialog
from .widgets.effects_dialog import EffectsDialog
from PyQt6.QtWidgets import QMessageBox # 确保已导入
from utils.helpers import get_base_path
from core.batch_processor import BatchProcessor
from ui.widgets.script_dialogs import ApplyMaskScriptDialog


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.model = AppModel()
        self.image_manager = ImageManager()
        self.batch_processor = BatchProcessor()
        
        # 【修改 1】初始化一个属性来持有效果对话框的实例
        self.effects_dialog = None

        self.active_actions = []

        self.set_application_icon()

        self.init_ui()
        self._create_menu()
        self._create_actions_and_shortcuts()
        self._connect_signals()
        
        self.initial_layout_states = {
            'main_window': self.saveState(),
            'main_splitter': self.main_splitter.saveState(),
            'right_splitter': self.right_splitter.saveState()
        }

        self._load_initial_settings()
        self.initial_state = self.saveState()  

    def set_application_icon(self):
        """加载并设置应用程序的图标。"""
        # script_dir = os.path.dirname(os.path.abspath(__file__))
        # icon_path = os.path.join(script_dir, 'resources', 'icons', 'app_icon.png')
        base_path = get_base_path()
        # 1. 根据操作系统平台确定图标文件名
        if sys.platform == 'darwin':
            # 'darwin' 是 macOS 的内部名称
            icon_filename = 'app_icon.icns'
            print("Detected macOS, attempting to load .icns icon.")
        else:
            # 适用于 Windows ('win32'), Linux ('linux') 等
            icon_filename = 'app_icon.png'
            print(f"Detected non-macOS ({sys.platform}), attempting to load .png icon.")

        # 2. 构建完整的图标路径
        icon_path = os.path.join(base_path, 'ui', 'resources', 'icons', icon_filename)
        
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            print("Application icon set successfully.")
        else:
            print(f"Warning: Application icon not found at '{icon_path}'")

    def init_ui(self):
        self.setWindowTitle("手动抠图工具 V9.3(全新自定义+内置脚本)")
        # 获取主屏幕的可用几何尺寸（排除任务栏/Dock等）
        screen = QGuiApplication.primaryScreen()
        available_geometry = screen.availableGeometry()
        
        # 设置窗口为屏幕可用区域的90%
        window_width = int(available_geometry.width() * 0.9)
        window_height = int(available_geometry.height() * 0.9)
        
        # 计算居中位置
        x = available_geometry.x() + (available_geometry.width() - window_width) // 2
        y = available_geometry.y() + (available_geometry.height() - window_height) // 2
        
        self.setGeometry(x, y, window_width, window_height)
        # --- 修改结束 ---
        
        # 可选：设置最小尺寸以防止窗口过小
        self.setMinimumSize(500, 500)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        self.path_dock_widget = QDockWidget("路径设置 (可拖拽)", self)
        self.path_dock_widget.setObjectName("PathDockWidget")
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
        
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        canvas_area = QFrame()
        canvas_area.setFrameShape(QFrame.Shape.StyledPanel)
        canvas_layout = QVBoxLayout(canvas_area)
        self.canvas = ImageCanvas(self.model, self.image_manager)
        self.progress_slider = ProgressSlider()
        canvas_layout.addWidget(self.canvas)
        canvas_layout.addWidget(self.progress_slider)
        
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.preview_panel = PreviewPanel(self.model, self.image_manager, canvas_widget=self.canvas)
        
        function_frame = QFrame()
        function_frame.setFrameShape(QFrame.Shape.StyledPanel)
        function_layout = QVBoxLayout(function_frame)

        display_group = QGroupBox("显示选项")
        display_layout = QVBoxLayout(display_group)
        
        display_mode_layout = QHBoxLayout()
        self.hide_radio = QRadioButton("隐藏")
        self.area_radio = QRadioButton("面积")
        self.contour_radio = QRadioButton("轮廓")
        self.ants_radio = QRadioButton("蚂蚁线")
        
        self.display_mode_group = QButtonGroup(self)
        self.display_mode_group.addButton(self.hide_radio)
        self.display_mode_group.addButton(self.area_radio)
        self.display_mode_group.addButton(self.contour_radio)
        self.display_mode_group.addButton(self.ants_radio)

        display_mode_layout.addWidget(QLabel("查看模式:"))
        display_mode_layout.addWidget(self.hide_radio)
        display_mode_layout.addWidget(self.area_radio)
        display_mode_layout.addWidget(self.contour_radio)
        display_mode_layout.addWidget(self.ants_radio)

        other_options_layout = QHBoxLayout()
        self.mask_invert_checkbox = QCheckBox("反相显示")
        
        self.lock_zoom_checkbox = QCheckBox("固定缩放")
        # --- START: 1. 新增 Mask 来源标签 ---
        # 默认文本会在加载文件时设置
        self.mask_source_label = QLabel("来源: N/A")
        self.mask_source_label.setObjectName("MaskSourceLabel")
        self.mask_source_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        other_options_layout.addWidget(self.lock_zoom_checkbox)
        other_options_layout.addWidget(self.mask_invert_checkbox)
        other_options_layout.addStretch() #将标签推到右侧
        other_options_layout.addWidget(self.mask_source_label)

        self.filename_display_layout = QHBoxLayout()
        self.filename_label_title = QLabel("当前文件:")
        self.filename_label_value = QLabel("N/A")
        
        # 策略：让value-label水平扩展，并将其内部文本推到右侧
        # QLabel 默认会使用 ElideRight (末尾...) 来处理溢出文本
        self.filename_label_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.filename_label_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.filename_label_value.setToolTip("当前正在编辑的图像文件名")
        
        self.filename_display_layout.addWidget(self.filename_label_title)
        self.filename_display_layout.addWidget(self.filename_label_value)

        auto_save_layout = QHBoxLayout()
        self.auto_save_checkbox = QCheckBox("自动保存 (X)")
        auto_save_layout.addWidget(self.auto_save_checkbox)

        display_layout.addLayout(display_mode_layout)
        display_layout.addLayout(other_options_layout)
        display_layout.addLayout(self.filename_display_layout)
        display_layout.addLayout(auto_save_layout)

        effects_group = QGroupBox("效果设置")
        effects_layout = QHBoxLayout(effects_group)
        self.effects_button = QPushButton("图像效果调整 (C)") # 使用 QPushButton 更符合语义
        effects_layout.addWidget(self.effects_button)
        effects_layout.addStretch()

        tools_group = QGroupBox("编辑工具")
        tools_layout = QVBoxLayout(tools_group)
        tool_buttons_layout = QHBoxLayout()
        self.lasso_button = QPushButton("套索 (+/Q)")
        self.lasso_subtract_button = QPushButton("套索 (-)")
        self.polygon_button = QPushButton("多边形 (+/P)")
        self.polygon_subtract_button = QPushButton("多边形 (-)")
        self.erase_selection_button = QPushButton("橡皮擦(E)")

        self.lasso_button.setCheckable(True)
        self.lasso_subtract_button.setCheckable(True)
        self.polygon_button.setCheckable(True)
        self.polygon_subtract_button.setCheckable(True)
        self.erase_selection_button.setCheckable(True)

        self.tool_button_group = QButtonGroup(self)
        self.tool_button_group.addButton(self.lasso_button)
        self.tool_button_group.addButton(self.lasso_subtract_button)
        self.tool_button_group.addButton(self.polygon_button)
        self.tool_button_group.addButton(self.polygon_subtract_button)
        self.tool_button_group.addButton(self.erase_selection_button)

        self.lasso_button.setChecked(True)
        tool_buttons_layout.addWidget(self.lasso_button)
        tool_buttons_layout.addWidget(self.lasso_subtract_button)
        tool_buttons_layout.addWidget(self.polygon_button)
        tool_buttons_layout.addWidget(self.polygon_subtract_button)
        tool_buttons_layout.addWidget(self.erase_selection_button)
        
        # --- START: 新增橡皮擦大小滑块 ---
        tool_options_layout = QHBoxLayout()
        # eraser_size_layout = QHBoxLayout()
        self.eraser_size_label = QLabel(f"橡皮擦: {self.model.eraser_size}px")
        self.eraser_size_label.setMinimumWidth(80) # 防止标签跳动
        self.eraser_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.eraser_size_slider.setRange(1, 200) # 设置橡皮擦大小范围
        self.eraser_size_slider.setValue(self.model.eraser_size)
        tool_options_layout.addWidget(self.eraser_size_label)
        tool_options_layout.addWidget(self.eraser_size_slider)
        tool_options_layout.addSpacing(20) # 添加一点间距
        # 新增的 "添加模式" 复选框
        self.selection_add_mode_checkbox = QCheckBox("添加模式")
        self.selection_add_mode_checkbox.setToolTip("勾选后，套索和多边形工具将默认用于添加选区（无需按Shift）")
        tool_options_layout.addWidget(self.selection_add_mode_checkbox)

        
        action_buttons_layout = QVBoxLayout()
        
        self.toggle_mask_source_button = QPushButton("切换Mask来源 (T)")
        self.clear_button = QPushButton("清除Mask (W)")
        self.save_button = QPushButton("保存 (Ctrl+S)")
        self.save_and_next_button = QPushButton("保存并下一张 (S or 双击)")
        
        action_buttons_layout.addWidget(self.toggle_mask_source_button)
        action_buttons_layout.addWidget(self.clear_button)
        action_buttons_layout.addWidget(self.save_button)
        action_buttons_layout.addWidget(self.save_and_next_button)
        tools_layout.addLayout(tool_buttons_layout)
        tools_layout.addLayout(tool_options_layout) # 将滑块工具添加到工具布局中
        tools_layout.addLayout(action_buttons_layout)

        nav_layout = QHBoxLayout()
        self.prev_button = QPushButton("上一张 (A/←)")
        self.next_button = QPushButton("下一张 (D/→)")
        nav_layout.addWidget(self.prev_button)
        nav_layout.addWidget(self.next_button)

        function_layout.addWidget(display_group)
        function_layout.addWidget(effects_group)
        function_layout.addWidget(tools_group)
        function_layout.addStretch()
        function_layout.addLayout(nav_layout)
        function_frame.setLayout(function_layout)
        self.right_splitter.addWidget(self.preview_panel)
        self.right_splitter.addWidget(function_frame)
        self.right_splitter.setSizes([600, 200])
        self.main_splitter.addWidget(canvas_area)
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setSizes([1200, 600])
        main_layout.addWidget(self.main_splitter)
    
    def _create_menu(self):
        self.menu_bar = self.menuBar()
        file_menu = self.menu_bar.addMenu("文件(&F)")

        self.import_action = QAction("加载/刷新图像 (I)", self)
        self.import_action.triggered.connect(self.import_images)
        file_menu.addAction(self.import_action)
        
        file_menu.addSeparator()
        self.exit_action = QAction("退出(&Q)", self)
        self.exit_action.triggered.connect(self.close)
        file_menu.addAction(self.exit_action)

        edit_menu = self.menu_bar.addMenu("编辑(&E)")
        self.undo_action = QAction("撤销", self)
        self.undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self.undo_action.triggered.connect(self.canvas.undo)
        edit_menu.addAction(self.undo_action)

        # --- [MODIFIED] 动态加载脚本菜单 ---
        scripts_menu = self.menu_bar.addMenu("脚本(&Scripts)")
        self._populate_scripts_menu(scripts_menu)
        
        view_menu = self.menu_bar.addMenu("视图(&V)")
        self.toggle_path_dock_action = self.path_dock_widget.toggleViewAction()
        self.toggle_path_dock_action.setText("显示/隐藏路径面板")
        view_menu.addAction(self.toggle_path_dock_action)
        
        view_menu.addSeparator()
        self.restore_layout_action = QAction("恢复默认布局", self)
        self.restore_layout_action.triggered.connect(self.restore_layout)
        view_menu.addAction(self.restore_layout_action)  
        settings_menu = self.menu_bar.addMenu("设置(&S)")
        self.settings_action = QAction("打开设置...", self)
        self.settings_action.triggered.connect(self.open_settings_dialog)
        settings_menu.addAction(self.settings_action)

    def _populate_scripts_menu(self, menu):
        """动态加载 Useful_script/ 目录中的脚本并添加到菜单"""
        from Useful_script.script_loader import load_scripts
        
        # 获取 Useful_script 目录的绝对路径
        base_path = get_base_path()
        scripts_dir = os.path.join(base_path, 'Useful_script')
        
        scripts = load_scripts(scripts_dir)
        
        if not scripts:
            no_script_action = QAction("(无可用脚本)", self)
            no_script_action.setEnabled(False)
            menu.addAction(no_script_action)
            return
        
        for script in scripts:
            action = QAction(script['name'], self)
            if script['description']:
                action.setToolTip(script['description'])
            
            # 使用 lambda 捕获当前的 run 函数
            run_func = script['run']
            action.triggered.connect(lambda checked, f=run_func: f(self))
            menu.addAction(action)

    def _create_actions_and_shortcuts(self):
        for action in self.active_actions:
            self.removeAction(action)
        self.active_actions.clear()

        def create_shortcut(key_name, function):
            shortcut_str = self.model.get_keybinding(key_name)
            if not shortcut_str: return
            action = QAction(self)
            shortcuts = [QKeySequence(key.strip()) for key in shortcut_str.replace(';', ',').split(',')]
            action.setShortcuts(shortcuts)
            action.triggered.connect(function)
            self.addAction(action)
            self.active_actions.append(action)
        
        key_map = {
            'next_image': self.model.increment_index,
            'prev_image': self.model.decrement_index,
            'save': self.canvas.save_current_mask,
            'draw_mode': lambda: self.model.set_selection_tool("lasso"),
            'polygon_mode': lambda: self.model.set_selection_tool("polygon"),
            'erase_mode': lambda: self.model.set_selection_tool("erase"),
            'clear_mask': self.canvas.clear_current_selection,
            'import_files': self.import_images,
            'save_and_next': self.save_and_next,
            'auto_save': lambda: self.model.set_auto_save(not self.model.auto_save),
            'high_contrast': self.open_effects_chooser,
            'toggle_image_source': self.model.toggle_image_source,
            'toggle_path_panel':self.toggle_path_dock_action.trigger,
            'toggle_mask_source':self.model.toggle_mask_source
        }
        
        for key, func in key_map.items():
            create_shortcut(key, func)
        
        # 1. 更新“加载/刷新图像”菜单
        shortcut_str = self.model.get_keybinding('import_files')
        menu_text = "加载/刷新图像"
        if shortcut_str:
            display_shortcut = shortcut_str.split(';')[0].split(',')[0].strip()
            menu_text += f" ({display_shortcut})"
        self.import_action.setText(menu_text)

        # 2. 更新“显示/隐藏路径面板”菜单
        shortcut_str = self.model.get_keybinding('toggle_path_panel')
        menu_text = "显示/隐藏路径面板"
        if shortcut_str:
            display_shortcut = shortcut_str.split(';')[0].split(',')[0].strip()
            menu_text += f" ({display_shortcut})"
        self.toggle_path_dock_action.setText(menu_text)

    @pyqtSlot(str, str)
    def _update_model_path(self, key, new_path):
        """一个专门用来更新模型中路径配置的槽函数"""
        # 使用 self.model.config.set 来更新内存中的配置
        self.model.config.set('Paths', key, new_path)
        print(f"Model path '{key}' updated to: {new_path}")

    def _connect_signals(self):
        self.import_button.clicked.connect(self.import_images)
        self.prev_button.clicked.connect(self.model.decrement_index)
        self.next_button.clicked.connect(self.model.increment_index)
        self.progress_slider.slider.valueChanged.connect(self.model.set_current_index)
        
        self.clear_button.clicked.connect(self.canvas.clear_current_selection)
        self.save_button.clicked.connect(self.canvas.save_current_mask)
        self.save_and_next_button.clicked.connect(self.save_and_next)

        self.toggle_mask_source_button.clicked.connect(self.model.toggle_mask_source)
        
        self.canvas.save_and_next_requested.connect(self.save_and_next)

        self.lasso_button.toggled.connect(lambda checked: self.model.set_selection_tool("lasso") if checked else None)
        self.lasso_subtract_button.toggled.connect(lambda checked: self.model.set_selection_tool("lasso_subtract") if checked else None)
        self.polygon_button.toggled.connect(lambda checked: self.model.set_selection_tool("polygon") if checked else None)
        self.polygon_subtract_button.toggled.connect(lambda checked: self.model.set_selection_tool("polygon_subtract") if checked else None)
        self.erase_selection_button.toggled.connect(lambda checked: self.model.set_selection_tool("erase") if checked else None)
        
        # --- START: 连接橡皮擦滑块 ---
        self.eraser_size_slider.valueChanged.connect(self.model.set_eraser_size)
        self.model.eraser_size_changed.connect(self.on_eraser_size_changed)
        self.selection_add_mode_checkbox.toggled.connect(self.model.set_selection_add_mode)
        self.model.selection_add_mode_changed.connect(self.selection_add_mode_checkbox.setChecked)

        self.hide_radio.toggled.connect(lambda checked: self.model.set_display_mode("hide") if checked else None)
        self.area_radio.toggled.connect(lambda checked: self.model.set_display_mode("area") if checked else None)
        self.contour_radio.toggled.connect(lambda checked: self.model.set_display_mode("contour") if checked else None)
        self.ants_radio.toggled.connect(lambda checked: self.model.set_display_mode("ants") if checked else None)

        self.auto_save_checkbox.toggled.connect(self.model.set_auto_save)
        self.effects_button.clicked.connect(self.open_effects_chooser)
        self.mask_invert_checkbox.toggled.connect(self.model.set_mask_invert)
        self.lock_zoom_checkbox.toggled.connect(self.model.set_zoom_locked)

        self.model.index_changed.connect(self.on_index_changed)
        self.model.files_changed.connect(self.on_files_changed)
        self.model.tool_changed.connect(self.on_tool_changed)
        
        self.model.auto_save_changed.connect(self.auto_save_checkbox.setChecked)
        self.model.effects_changed.connect(self.canvas.on_effects_changed)
        self.model.display_mode_changed.connect(self.on_display_mode_changed)
        
        self.model.zoom_lock_changed.connect(self.lock_zoom_checkbox.setChecked)

        self.model.mask_updated.connect(self.canvas.update_selection_display)
        self.model.preview_effects_changed.connect(self.canvas.on_preview_effects_changed)
        self.model.display_mode_changed.connect(self.canvas.update_selection_display)

        # 新增：当Mask加载源切换时，强制重载当前图像
        self.model.mask_source_changed.connect(
            lambda:self.canvas.load_image(self.model.current_index)
            )
        # 更换加载源时，更新标签文本
        self.model.mask_source_changed.connect(self.update_mask_source_label)

        self.model.image_source_changed.connect(self.canvas.on_image_source_changed)
        self.model.mask_updated.connect(lambda: self.preview_panel.update_previews(self.model.current_index))
        
        # 当用户通过UI选择新路径时，立即更新AppModel
        self.original_path_selector.path_selected.connect(
            lambda path: self._update_model_path('original_path', path)
        )
        self.denoised_path_selector.path_selected.connect(
            lambda path: self._update_model_path('denoised_path', path)
        )
        self.mask_path_selector.path_selected.connect(
            lambda path: self._update_model_path('mask_path', path)
        )
        self.save_path_selector.path_selected.connect(
            lambda path: self._update_model_path('save_path', path)
        )

    def run_script_clean_mask(self):
        """调用 BatchProcessor 执行清洗逻辑"""
        mask_files = self.model._mask_files
        save_dir = self.model.get_path('save_path')

        if not mask_files or not save_dir:
            QMessageBox.warning(self, "路径未设置", "请确保已加载 Mask 路径且设置了 Save Path。")
            return

        count = len(mask_files)
        reply = QMessageBox.question(self, "批量处理确认", 
                                     f"即将处理 {count} 张图像，结果将覆盖保存路径中的文件。\n是否继续？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return

        # 进度条
        progress = QProgressDialog("正在清洗 Mask...", "取消", 0, count, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        # 定义回调更新进度
        def progress_cb(current, total):
            if progress.wasCanceled(): return False
            progress.setValue(current + 1)
            QApplication.processEvents() # 保持界面响应
            return True

        # [CALL] 调用核心逻辑
        processed = self.batch_processor.run_clean_masks(mask_files, save_dir, progress_cb)
        
        progress.setValue(count)
        
        # 刷新界面
        if self.model.load_from_save_path:
             self.canvas.load_image(self.model.current_index)
             self.preview_panel.update_previews(self.model.current_index)

        QMessageBox.information(self, "完成", f"已清洗 {processed} 张 Mask。")

    def run_script_apply_mask(self):
        """
        弹出对话框配置路径，然后调用 BatchProcessor 执行抠图。
        """
        # 1. 准备默认路径 (为了方便用户，预填当前项目的路径)
        # 注意：用户可能想用已保存的 Cleaned Mask，所以 Mask 默认路径优先设为 Save Path
        default_mask = self.model.get_path('save_path') or self.model.get_path('mask_path')
        default_img = self.model.get_path('original_path')
        # 结果路径默认设为原图路径下的 "masked_output" 文件夹
        default_save = os.path.join(default_img, "masked_output") if default_img else ""

        # 2. 弹出配置对话框
        dialog = ApplyMaskScriptDialog(default_mask, default_img, default_save, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # 3. 获取配置
        mask_path, img_path, save_path = dialog.get_paths()
        
        # 确保保存目录存在
        if not os.path.exists(save_path):
            try:
                os.makedirs(save_path)
            except OSError as e:
                QMessageBox.critical(self, "错误", f"无法创建保存目录:\n{e}")
                return

        # 4. 准备进度条
        # 我们需要先统计一下文件数量来设置进度条最大值，但 batch_processor 里会再算一次。
        # 为了简单，我们先大概估算或让 batch_processor 处理。
        # 这里为了 UI 响应，我们在 BatchProcessor 里并没有计算 total 的逻辑暴露出来。
        # 简单起见，我们先获取一下 Mask 数量用于进度条显示。
        from core.image_manager import ImageManager # 临时导入
        total_files = len(ImageManager.get_image_files(mask_path))
        
        progress = QProgressDialog("正在批量抠图...", "取消", 0, total_files, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        
        def progress_cb(current, total):
            if progress.wasCanceled(): return False
            progress.setValue(current + 1)
            QApplication.processEvents()
            return True

        # 5. [CALL] 调用核心逻辑
        processed = self.batch_processor.run_apply_mask_to_images(
            mask_path, img_path, save_path, progress_cb
        )
        
        progress.setValue(total_files)
        QMessageBox.information(self, "完成", f"处理完成！\n共生成 {processed} 张抠图结果。\n保存在: {save_path}")

    # --- [MODIFIED] 打开效果对话框时传递 Pixmap ---
    def open_effects_chooser(self):
        if self.model.current_index < 0:
            QMessageBox.warning(self, "提示", "请先加载图像。")
            return

        # 获取当前正在显示的底图 (可能是原图，也可能是去噪图)
        current_base_pixmap = self.canvas._denoised_pixmap if (self.model.show_denoised and self.canvas._denoised_pixmap) else self.canvas._original_pixmap

        if self.effects_dialog is None or not self.effects_dialog.isVisible():
            # [CHANGE] 传递 current_base_pixmap 给 Dialog
            self.effects_dialog = EffectsDialog(self.model, self, current_pixmap=current_base_pixmap)

            def apply_new_settings(settings):
                self.canvas.push_undo_state_for_effects()
                self.model.update_effect_settings(settings)
            
            self.effects_dialog.settings_applied.connect(apply_new_settings)
            self.effects_dialog.finished.connect(self.on_effects_dialog_finished)

            self.effects_dialog.show()
        else:
            # 如果对话框已经打开，更新它内部引用的图片（防止用户换图了但对话框还在用旧图计算Auto）
            self.effects_dialog.current_pixmap = current_base_pixmap
            self.effects_dialog.raise_()
            self.effects_dialog.activateWindow()

    # --- START: 新增橡皮擦滑块的槽函数 ---
    @pyqtSlot(int)
    def on_eraser_size_changed(self, size):
        # 更新标签
        self.eraser_size_label.setText(f"橡皮擦: {size}px")
        # 更新滑块位置（防止循环触发，先阻断信号）
        self.eraser_size_slider.blockSignals(True)
        self.eraser_size_slider.setValue(size)
        self.eraser_size_slider.blockSignals(False)


    @pyqtSlot(str)
    def on_tool_changed(self, tool):
        self.canvas.set_tool(tool)
        if tool == 'lasso':
            self.lasso_button.setChecked(True)
        elif tool == 'polygon':
            self.polygon_button.setChecked(True)
        elif tool == 'erase':
            self.erase_selection_button.setChecked(True)
        elif tool == 'lasso_subtract':
            self.lasso_subtract_button.setChecked(True)
        elif tool == 'polygon_subtract':
            self.polygon_subtract_button.setChecked(True)

    @pyqtSlot(str)
    def on_display_mode_changed(self, mode):
        if mode == "hide":
            self.hide_radio.setChecked(True)
        elif mode == "area":
            self.area_radio.setChecked(True)
        elif mode == "contour":
            self.contour_radio.setChecked(True)
        elif mode == "ants":
            self.ants_radio.setChecked(True)

    @pyqtSlot(int)
    def on_index_changed(self, index):
        if index < 0: 
            # 如果索引无效 (例如没有文件)，清空标签并返回
            self.filename_label_value.setText("N/A")
            self.filename_label_value.setToolTip("")
            # 确保滑块标签也更新
            self.progress_slider.set_value(index)
            self.progress_slider.update_label()
            return
        self.progress_slider.slider.blockSignals(True)
        self.progress_slider.set_value(index)
        self.progress_slider.slider.blockSignals(False)
        self.progress_slider.update_label()
        
        try:
            # 从 model 中获取文件名
            filepath = self.model._original_files[index]
            filename = os.path.basename(filepath)
            self.filename_label_value.setText(filename)
            self.filename_label_value.setToolTip(filepath) # 完整路径作为提示
        
        except (IndexError, AttributeError) as e:
            print(f"Error updating filename: {e}")
            self.filename_label_value.setText("N/A")
            self.filename_label_value.setToolTip("")
        
        self.canvas.load_image(index)
        # [CRITICAL FIX] 如果效果对话框是打开的，必须把新图片传给它，并强制应用当前的滑块值
        if self.effects_dialog and self.effects_dialog.isVisible():
            # 获取当前底图 (原图或去噪图)
            current_base_pixmap = self.canvas._denoised_pixmap if (self.model.show_denoised and self.canvas._denoised_pixmap) else self.canvas._original_pixmap
            
            # 更新对话框的引用图 (用于 Auto 计算)
            self.effects_dialog.set_current_pixmap(current_base_pixmap)
            
            # 强制对话框重新发射一次 preview 信号
            # 这样 ImageCanvas 就会收到 preview_effects_changed 信号，并用当前滑块的值渲染新图
            self.effects_dialog.force_preview_update()
        self.preview_panel.update_previews(index)

    @pyqtSlot(int)
    def on_files_changed(self, total_files):
        if total_files > 0:
            self.progress_slider.set_range(0, total_files - 1)
            self.on_display_mode_changed(self.model.display_mode)
            self.update_mask_source_label(self.model.load_from_save_path) #首次加载时设置标签初始状态
            self.on_index_changed(self.model.current_index)
        else:
            self.progress_slider.set_range(0, -1)
            self.preview_panel.clear_previews()
            self.canvas.load_image(-1)
            self.mask_source_label.setText("来源: N/A") # 清空标签
            
            self.filename_label_value.setText("N/A")
            self.filename_label_value.setToolTip("")
            
            QMessageBox.information(self, "提示", "在指定路径下未找到图像文件。")
    
    # --- START: 新增槽函数 ---
    @pyqtSlot(bool)
    def update_mask_source_label(self, load_from_save):
        """仅更新Mask来源标签的文本"""
        if load_from_save:
            self.mask_source_label.setText("来源: 已存 (Save)")
            self.mask_source_label.setToolTip("当前优先加载 'Save Path' (按 T 键切换)")
        else:
            self.mask_source_label.setText("来源: 二值 (Mask)")
            self.mask_source_label.setToolTip("当前优先加载 'Mask Path' (按 T 键切换)")
    
    def save_and_next(self):
        if self.model.current_index < 0:
            return
        if self.canvas.save_current_mask():
            self.model.increment_index()
    
    def apply_stylesheet(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(script_dir, 'resources', 'style.qss.template')
        
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
            
            if self.model.config.has_section('QSS_Colors'):
                color_items = self.model.config.items('QSS_Colors')
                sorted_color_items = sorted(color_items, key=lambda item: len(item[0]), reverse=True)
                for key, value in sorted_color_items:
                    template_content = template_content.replace(f"@{key}", value)
            
            QApplication.instance().setStyleSheet(template_content)
            print("Stylesheet applied successfully.")

        except FileNotFoundError:
            print(f"Stylesheet template not found at '{template_path}', using default style.")
        except Exception as e:
            print(f"Error applying stylesheet: {e}")

    def open_settings_dialog(self):
        dialog = SettingsDialog(self.model.config, self)
        dialog.settings_applied.connect(self.apply_settings_from_dialog)
        dialog.exec()

    @pyqtSlot()
    def apply_settings_from_dialog(self):
        print("Applying settings changes from dialog...")
        self.apply_stylesheet()
        self._create_actions_and_shortcuts()
        self.canvas.update_selection_display()
        self.preview_panel.update_previews(self.model.current_index)

    def _load_initial_settings(self):
        self.apply_stylesheet()
        self.original_path_selector.set_path(self.model.get_path('original_path'))
        self.denoised_path_selector.set_path(self.model.get_path('denoised_path'))
        self.mask_path_selector.set_path(self.model.get_path('mask_path'))
        save_path = self.model.get_path('save_path') or self.model.get_path('mask_path')
        self.save_path_selector.set_path(save_path)
        self.import_images()

    def import_images(self):
        original_path = self.original_path_selector.get_path()
        save_path = self.save_path_selector.get_path()

        # 检查路径是否为空或者目录不存在
        if not original_path or not os.path.isdir(original_path):
            QMessageBox.warning(self, "路径错误", "“原图路径”为空或无效，可能是第一次打开没有配置，请继续。")
            # 可以选择性地弹出文件选择对话框，引导用户操作
            # self.original_path_selector.select_directory() 
            return

        if not save_path or not os.path.isdir(save_path):
            # 如果保存路径不存在，可以询问用户是否创建
            if save_path: # 路径不为空但目录不存在
                reply = QMessageBox.question(self, "创建目录？", f"路径 “{save_path}” 不存在。\n是否要创建它？",
                                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    try:
                        os.makedirs(save_path, exist_ok=True)
                    except Exception as e:
                        QMessageBox.critical(self, "创建失败", f"无法创建目录：{e}")
                        return
                else:
                    QMessageBox.warning(self, "路径错误", "请选择一个有效的“保存路径”！")
                    return
            else: # 路径为空
                QMessageBox.warning(self, "路径错误", "请先选择“保存路径”！")
                return
        
        self.model.update_file_lists(
            original_path,  
            self.denoised_path_selector.get_path(),  
            self.mask_path_selector.get_path()
        )

    def restore_layout(self):
        if hasattr(self, 'initial_state'):
            self.restoreState(self.initial_layout_states['main_window'])
            self.main_splitter.restoreState(self.initial_layout_states['main_splitter'])
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
    
    def open_effects_chooser(self):
        if self.model.current_index < 0:
            QMessageBox.warning(self, "提示", "请先加载图像。")
            return

        # 获取当前图
        current_base_pixmap = self.canvas._denoised_pixmap if (self.model.show_denoised and self.canvas._denoised_pixmap) else self.canvas._original_pixmap

        # 如果对话框还不存在，创建它
        if self.effects_dialog is None:
            self.effects_dialog = EffectsDialog(self.model, self, current_pixmap=current_base_pixmap)
            
            # 定义 Apply 回调
            def apply_new_settings(settings):
                self.canvas.push_undo_state_for_effects()
                self.model.update_effect_settings(settings)
            
            # 连接信号 (只连一次)
            self.effects_dialog.settings_applied.connect(apply_new_settings)
            self.effects_dialog.finished.connect(self.on_effects_dialog_finished)
        
        else:
            # 如果已存在，更新图片引用
            self.effects_dialog.set_current_pixmap(current_base_pixmap)
            # 恢复到上一次的正式设置 (或者保持当前状态，看需求。通常打开时应该显示当前生效的设置)
            # self.effects_dialog._load_settings_to_ui(self.model.effect_settings) 

        # 显示对话框 (非模态)
        self.effects_dialog.show()
        self.effects_dialog.raise_()
        self.effects_dialog.activateWindow()

    def on_effects_dialog_finished(self, result):
        """当效果对话框关闭时调用"""
        if result != QDialog.DialogCode.Accepted:
            # 如果是取消或关闭，恢复预览前的状态
            self.model.revert_preview_to_last_settings()
        
        # [FIXED] 不要在这里 disconnect！因为我们复用了 self.effects_dialog 实例。
        # 如果 disconnect 了，下次再打开，settings_applied 信号就断了，Apply 按钮会失效。
        pass

    # def on_effects_dialog_finished(self, result):
    #     """
    #     【新增方法】当效果对话框关闭时（通过“确定”、“取消”或“X”按钮），此槽函数被调用。
    #     """
    #     if result != QDialog.DialogCode.Accepted:
    #         self.model.revert_preview_to_last_settings()
        
    #     if self.effects_dialog:
    #         try:
    #             self.effects_dialog.disconnect()
    #         except TypeError:
    #             pass