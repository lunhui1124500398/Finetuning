# Finetuning/ui/main_window.py

import os
import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QCheckBox, QFrame, QSplitter, QMessageBox, QDockWidget,
    QButtonGroup, QRadioButton, QLabel, QGroupBox, QDialog
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QAction, QKeySequence, QIcon

from core.app_model import AppModel
from core.image_manager import ImageManager
from .widgets.path_selector import PathSelector
from .widgets.image_canvas import ImageCanvas
from .widgets.preview_panel import PreviewPanel
from .widgets.progress_slider import ProgressSlider
from .widgets.settings_dialog import SettingsDialog
from .widgets.effects_dialog import EffectsDialog
from PyQt6.QtWidgets import QMessageBox # 确保已导入

class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.model = AppModel()
        self.image_manager = ImageManager()
        
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
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(script_dir, 'resources', 'icons', 'app_icon.png')

        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            print("Application icon set successfully.")
        else:
            print(f"Warning: Application icon not found at '{icon_path}'")

    def init_ui(self):
        self.setWindowTitle("手动抠图工具 V7.4(全新自定义))")
        self.setGeometry(100, 100, 1800, 1000)

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
        other_options_layout.addWidget(self.lock_zoom_checkbox)
        other_options_layout.addWidget(self.mask_invert_checkbox)

        auto_save_layout = QHBoxLayout()
        self.auto_save_checkbox = QCheckBox("自动保存 (X)")
        auto_save_layout.addWidget(self.auto_save_checkbox)

        display_layout.addLayout(display_mode_layout)
        display_layout.addLayout(other_options_layout)
        display_layout.addLayout(auto_save_layout)

        effects_group = QGroupBox("效果设置")
        effects_layout = QHBoxLayout(effects_group)
        self.effects_button = QPushButton("图像效果调整 (C)") # 使用 QPushButton 更符合语义
        effects_layout.addWidget(self.effects_button)
        effects_layout.addStretch()

        tools_group = QGroupBox("编辑工具")
        tools_layout = QVBoxLayout(tools_group)
        tool_buttons_layout = QHBoxLayout()
        self.lasso_button = QPushButton("套索 (Q)")
        self.polygon_button = QPushButton("多边形 (P)")
        self.erase_selection_button = QPushButton("橡皮擦(E)")
        self.lasso_button.setCheckable(True)
        self.polygon_button.setCheckable(True)
        self.erase_selection_button.setCheckable(True)
        self.tool_button_group = QButtonGroup(self)
        self.tool_button_group.addButton(self.lasso_button)
        self.tool_button_group.addButton(self.polygon_button)
        self.tool_button_group.addButton(self.erase_selection_button)
        self.lasso_button.setChecked(True)
        tool_buttons_layout.addWidget(self.lasso_button)
        tool_buttons_layout.addWidget(self.polygon_button)
        tool_buttons_layout.addWidget(self.erase_selection_button)
        action_buttons_layout = QVBoxLayout()
        self.clear_button = QPushButton("清除Mask (W)")
        self.save_button = QPushButton("保存 (Ctrl+S)")
        self.save_and_next_button = QPushButton("保存并下一张 (S or 双击)")
        action_buttons_layout.addWidget(self.clear_button)
        action_buttons_layout.addWidget(self.save_button)
        action_buttons_layout.addWidget(self.save_and_next_button)
        tools_layout.addLayout(tool_buttons_layout)
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
        self.settings_action = QAction("打开设置...", self)
        self.settings_action.triggered.connect(self.open_settings_dialog)
        settings_menu.addAction(self.settings_action)

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
            'toggle_image_source': self.model.toggle_image_source
        }
        
        for key, func in key_map.items():
            create_shortcut(key, func)

    def _connect_signals(self):
        self.import_button.clicked.connect(self.import_images)
        self.prev_button.clicked.connect(self.model.decrement_index)
        self.next_button.clicked.connect(self.model.increment_index)
        self.progress_slider.slider.valueChanged.connect(self.model.set_current_index)
        
        self.clear_button.clicked.connect(self.canvas.clear_current_selection)
        self.save_button.clicked.connect(self.canvas.save_current_mask)
        self.save_and_next_button.clicked.connect(self.save_and_next)
        
        self.canvas.save_and_next_requested.connect(self.save_and_next)

        self.lasso_button.toggled.connect(lambda checked: self.model.set_selection_tool("lasso") if checked else None)
        self.polygon_button.toggled.connect(lambda checked: self.model.set_selection_tool("polygon") if checked else None)
        self.erase_selection_button.toggled.connect(lambda checked: self.model.set_selection_tool("erase") if checked else None)
        
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

        self.model.image_source_changed.connect(self.canvas.on_image_source_changed)

        self.model.mask_updated.connect(lambda: self.preview_panel.update_previews(self.model.current_index))

    @pyqtSlot(str)
    def on_tool_changed(self, tool):
        self.canvas.set_tool(tool)
        if tool == 'lasso':
            self.lasso_button.setChecked(True)
        elif tool == 'polygon':
            self.polygon_button.setChecked(True)
        elif tool == 'erase':
            self.erase_selection_button.setChecked(True)

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
        if index < 0: return
        self.progress_slider.slider.blockSignals(True)
        self.progress_slider.set_value(index)
        self.progress_slider.slider.blockSignals(False)
        self.progress_slider.update_label()
        self.canvas.load_image(index)
        self.preview_panel.update_previews(index)

    @pyqtSlot(int)
    def on_files_changed(self, total_files):
        if total_files > 0:
            self.progress_slider.set_range(0, total_files - 1)
            self.on_display_mode_changed(self.model.display_mode)
            self.on_index_changed(self.model.current_index)
        else:
            self.progress_slider.set_range(0, -1)
            self.preview_panel.clear_previews()
            self.canvas.load_image(-1)
            QMessageBox.information(self, "提示", "在指定路径下未找到图像文件。")
    
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
        """
        以非模态方式打开效果对话框，以实现实时预览和交互。
        """
        if self.model.current_index < 0:
            QMessageBox.warning(self, "提示", "请先加载图像。")
            return

        # 【修改 2】检查对话框是否已创建并可见，防止重复打开
        if self.effects_dialog is None or not self.effects_dialog.isVisible():
            # 将对话框实例存储在 self.effects_dialog 中，防止其被垃圾回收
            self.effects_dialog = EffectsDialog(self.model, self)

            def apply_new_settings(settings):
                self.canvas.push_undo_state_for_effects()
                self.model.update_effect_settings(settings)
            
            self.effects_dialog.settings_applied.connect(apply_new_settings)
            self.effects_dialog.finished.connect(self.on_effects_dialog_finished)

            # 【修改 3】使用 .show() 以非模态方式显示对话框
            self.effects_dialog.show()
        else:
            self.effects_dialog.raise_()
            self.effects_dialog.activateWindow()

    def on_effects_dialog_finished(self, result):
        """
        【新增方法】当效果对话框关闭时（通过“确定”、“取消”或“X”按钮），此槽函数被调用。
        """
        if result != QDialog.DialogCode.Accepted:
            self.model.revert_preview_to_last_settings()
        
        if self.effects_dialog:
            try:
                self.effects_dialog.disconnect()
            except TypeError:
                pass