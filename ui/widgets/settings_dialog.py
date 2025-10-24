# Finetuning/ui/widgets/settings_dialog.py

import configparser
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTabWidget, QWidget,
    QFormLayout, QLabel, QLineEdit, QColorDialog, QScrollArea, QFrame,
    QMessageBox, QFileDialog, QComboBox, QGroupBox
)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt, pyqtSignal

from .key_sequence_edit import KeySequenceEdit

class SettingsDialog(QDialog):
    settings_applied = pyqtSignal()

    def __init__(self, config: configparser.ConfigParser, parent=None):
        super().__init__(parent)
        self.config = config
        # 3. 从父窗口获取配置文件路径，以便保存
        self.config_path = parent.model.config_path if parent and hasattr(parent, 'model') else None

        self.setWindowTitle("设置")
        self.setMinimumSize(600, 500)

        self.key_editors = {}
        self.color_buttons = {}
        self.color_labels = {}
        self.theme_combo = None 
        self._loading_theme = False

        self.init_ui()
        self.load_settings()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        keybindings_tab = QWidget()
        self.tabs.addTab(keybindings_tab, "快捷键")
        self.setup_keybindings_tab(keybindings_tab)

        appearance_tab = QWidget()
        self.tabs.addTab(appearance_tab, "外观")
        self.setup_appearance_tab(appearance_tab)

        button_layout = QHBoxLayout()
        self.import_button = QPushButton("导入配置...")
        self.export_button = QPushButton("导出配置...")
        self.restore_button = QPushButton("恢复默认")
        # 创建新的功能按钮
        self.apply_button = QPushButton("应用")
        self.save_button = QPushButton("保存")
        self.close_button = QPushButton("关闭")
        
        button_layout.addWidget(self.import_button)
        button_layout.addWidget(self.export_button)
        button_layout.addWidget(self.restore_button)
        button_layout.addStretch()
        button_layout.addWidget(self.apply_button)
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.close_button)
        main_layout.addLayout(button_layout)

        self.apply_button.clicked.connect(self.apply_changes)
        self.save_button.clicked.connect(self.save_changes_to_file)
        self.close_button.clicked.connect(self.accept) # accept() 会关闭对话框

        # 连接其他按钮
        self.restore_button.clicked.connect(self.confirm_restore_defaults)
        self.import_button.clicked.connect(self.import_settings)
        self.export_button.clicked.connect(self.export_settings)

        self.generate_theme_button.clicked.connect(self._on_generate_theme_clicked)

    def setup_keybindings_tab(self, parent_widget):
        scroll_area = QScrollArea(parent_widget)
        scroll_area.setWidgetResizable(True)
        
        container = QWidget()
        scroll_area.setWidget(container)

        layout = QFormLayout(container)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        
        if self.config.has_section('Keybindings'):
            for key, value in self.config.items('Keybindings'):
                label_text = key.replace('_', ' ').title()
                key_edit = KeySequenceEdit()
                layout.addRow(QLabel(f"{label_text}:"), key_edit)
                self.key_editors[key] = key_edit
        
        parent_layout = QVBoxLayout(parent_widget)
        parent_layout.addWidget(scroll_area)
        
    def setup_appearance_tab(self, parent_widget):
        scroll_area = QScrollArea(parent_widget)
        scroll_area.setWidgetResizable(True)
        container = QWidget()
        scroll_area.setWidget(container)
        
        main_layout = QVBoxLayout(container)
        
        # --- START: 新增主题选择部分 ---
        theme_group = QGroupBox("界面主题")
        theme_layout = QVBoxLayout(theme_group) # 改为QVBoxLayout以容纳更多控件
        
        # 原有的主题下拉框
        top_theme_layout = QHBoxLayout()
        self.theme_combo = QComboBox()
        theme_names = [s.split('_', 1)[1] for s in self.config.sections() if s.startswith('Theme_')]
        self.theme_combo.addItems(theme_names)
        self.theme_combo.addItem("Custom")
        top_theme_layout.addWidget(QLabel("选择预设主题:"))
        top_theme_layout.addWidget(self.theme_combo)

        # 新增的“根据主色调生成”按钮
        self.generate_theme_button = QPushButton("🎨 根据主色调生成...")
        
        theme_layout.addLayout(top_theme_layout)
        theme_layout.addWidget(self.generate_theme_button)
        
        main_layout.addWidget(theme_group)

        # --- END: 新增主题选择部分 ---

        qss_group = QFrame()
        qss_group.setFrameShape(QFrame.Shape.StyledPanel)
        qss_layout = QFormLayout(qss_group)
        qss_layout.addRow(QLabel("<b>界面主题颜色 (QSS)</b>"))
        
        if self.config.has_section('QSS_Colors'):
            for key, value in self.config.items('QSS_Colors'):
                self.add_color_picker(qss_layout, key, 'QSS_Colors')

        overlay_group = QFrame()
        overlay_group.setFrameShape(QFrame.Shape.StyledPanel)
        overlay_layout = QFormLayout(overlay_group)
        overlay_layout.addRow(QLabel("<b>图像叠加颜色 (RGBA)</b>"))

        if self.config.has_section('Colors'):
            for key, value in self.config.items('Colors'):
                if key in ['contour_thickness']: continue
                self.add_color_picker(overlay_layout, key, 'Colors')

        main_layout.addWidget(qss_group)
        main_layout.addWidget(overlay_group)
        
        parent_layout = QVBoxLayout(parent_widget)
        parent_layout.addWidget(scroll_area)

        # 连接信号
        self.theme_combo.currentTextChanged.connect(self._on_theme_selected)
    
    def apply_changes(self):
        """将UI上的设置保存到内存中的config对象，并发出信号通知主窗口刷新。"""
        self.save_settings()
        self.settings_applied.emit()
        print("Settings applied to current session.")
    
    def save_changes_to_file(self):
        """先应用更改，然后将内存中的config对象写入到 .ini 文件。"""
        # 首先，确保当前UI上的修改被应用
        self.apply_changes()

        # 然后，写入文件
        if not self.config_path:
            QMessageBox.critical(self, "错误", "配置文件路径未设置，无法保存。")
            return
            
        try:
            with open(self.config_path, 'w', encoding='utf-8') as configfile:
                self.config.write(configfile)
            QMessageBox.information(self, "成功", "设置已成功保存到文件。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")

    def add_color_picker(self, layout, key, section):
        label_text = key.replace('_', ' ').title()
        
        h_layout = QHBoxLayout()
        color_label = QLabel()
        color_label.setFixedSize(20, 20)
        color_label.setStyleSheet("border: 1px solid #888;")
        
        line_edit = QLineEdit()
        line_edit.setReadOnly(True)

        button = QPushButton("选择...")
        
        h_layout.addWidget(color_label)
        h_layout.addWidget(line_edit)
        h_layout.addWidget(button)
        
        layout.addRow(QLabel(f"{label_text}:"), h_layout)

        self.color_buttons[(section, key)] = button
        self.color_labels[(section, key)] = (color_label, line_edit)

        # 当用户点击颜色选择按钮时，我们认为他们可能要自定义，于是切换到 Custom
        button.clicked.connect(lambda: self.theme_combo.setCurrentText("Custom"))
        button.clicked.connect(lambda _, s=section, k=key: self.open_color_dialog(s, k))
    
    def open_color_dialog(self, section, key):
        _, line_edit = self.color_labels[(section, key)]
        current_value = line_edit.text()
        
        initial_color = QColor()
        
        is_rgba = ',' in current_value
        if is_rgba:
            try:
                r, g, b, a = map(int, current_value.split(','))
                initial_color.setRgb(r, g, b, a)
            except (ValueError, TypeError):
                initial_color.setNamedColor("#000000")
        else:
            initial_color.setNamedColor(current_value)

        options = QColorDialog.ColorDialogOption.ShowAlphaChannel if is_rgba else QColorDialog.ColorDialogOption(0)
        color = QColorDialog.getColor(initial_color, self, "选择颜色", options)

        if color.isValid():
            if is_rgba:
                new_value = f"{color.red()},{color.green()},{color.blue()},{color.alpha()}"
            else:
                new_value = color.name() # #RRGGBB format
            
            self.update_color_preview(section, key, new_value)
            
    def update_color_preview(self, section, key, value_str):
        widget_pair = self.color_labels.get((section, key))
        if not widget_pair: return
            
        color_label, line_edit = widget_pair
        line_edit.setText(value_str)
        
        color_qss_string = "transparent"
        
        if ',' in value_str: # RGBA
            try:
                r, g, b, a = map(int, value_str.split(','))
                color_qss_string = f"rgba({r}, {g}, {b}, {a})"
            except (ValueError, TypeError): pass
        else: # Hex
            color_qss_string = value_str

        color_label.setStyleSheet(f"background-color: {color_qss_string}; border: 1px solid #888;")
    
    def load_settings(self):
        # 加载快捷键
        for key, editor in self.key_editors.items():
            value = self.config.get('Keybindings', key, fallback='')
            editor.setText(value)
        
        # 加载颜色
        sections_to_load = ['QSS_Colors', 'Colors']
        for section in sections_to_load:
            if self.config.has_section(section):
                for key, value in self.config.items(section):
                    self.update_color_preview(section, key, value)
        
        # --- START: 加载主题设置 ---
        self._loading_theme = True
        last_theme = self.config.get('Theme', 'current_theme', fallback='Dark')
        
        # 检查当前 QSS_Colors 是否与 last_theme 的预设匹配
        is_custom = False
        theme_section_name = f"Theme_{last_theme}"
        if self.config.has_section(theme_section_name):
            for key, value in self.config.items('QSS_Colors'):
                preset_value = self.config.get(theme_section_name, key, fallback=None)
                if preset_value is None or value != preset_value:
                    is_custom = True
                    break
        else:
            # 如果上次保存的主题不存在，也标记为自定义
            is_custom = True

        if is_custom:
            self.theme_combo.setCurrentText("Custom")
        else:
            self.theme_combo.setCurrentText(last_theme)
        
        self._loading_theme = False
        # --- END: 加载主题设置 ---

    def save_settings(self):
        # 保存快捷键
        for key, editor in self.key_editors.items():
            self.config.set('Keybindings', key, editor.text())
            
        # 保存颜色到 QSS_Colors (当前激活的颜色)
        for (section, key), (_, line_edit) in self.color_labels.items():
             self.config.set(section, key, line_edit.text())

        # --- START: 保存主题设置 ---
        # 【修复】在写入之前，确保 'Theme' 部分一定存在
        if not self.config.has_section('Theme'):
            self.config.add_section('Theme')

        current_theme_selection = self.theme_combo.currentText()
        if current_theme_selection != "Custom":
             # 现在可以安全地写入了
             self.config.set('Theme', 'current_theme', current_theme_selection)
        # --- END: 保存主题设置 ---

    def confirm_restore_defaults(self):
        reply = QMessageBox.question(self, '恢复默认设置',
                                     "您确定要将所有设置恢复为默认值吗？\n此操作不可撤销。",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.restore_defaults()

    def restore_defaults(self):
        # 从 Dark 主题预设中恢复颜色
        if self.config.has_section('Theme_Dark'):
             self._on_theme_selected('Dark')

        # 恢复默认快捷键
        defaults_keys = {
            'next_image': "D; Right", 'prev_image': "A; Left", 'save': "Ctrl+S",
            'save_and_next': "S", 'draw_mode': "Q", 'erase_mode': "E", 'polygon_mode': "P",
            'clear_mask': "W", 'toggle_mask': "Z", 'auto_save': "X",
            'high_contrast': "C", 'import_files': "I", 'toggle_image_source': "Space",
            'toggle_path_panel':"J"
        }
        for key, value in defaults_keys.items():
             if key in self.key_editors:
                 self.key_editors[key].setText(value)
        
        QMessageBox.information(self, "成功", "设置已恢复为默认值。请点击“应用并保存”以生效。")

    def export_settings(self):
        # 导出前先将当前UI上的设置暂存
        self.save_settings()
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出配置", "", "配置文件 (*.ini);;所有文件 (*)"
        )

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as configfile:
                    self.config.write(configfile)
                QMessageBox.information(self, "成功", f"配置已成功导出到:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导出配置失败: {e}")

    def import_settings(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入配置", "", "配置文件 (*.ini);;所有文件 (*)"
        )

        if file_path:
            try:
                # 导入配置并直接更新UI
                imported_config = configparser.ConfigParser()
                imported_config.read(file_path, encoding='utf-8')
                
                # 创建一个新的 config 对象来更新，以免污染原始的
                temp_config = configparser.ConfigParser()
                temp_config.read_dict(self.config) # 复制现有配置
                
                # 用导入的配置覆盖
                for section in imported_config.sections():
                    if not temp_config.has_section(section):
                        temp_config.add_section(section)
                    for key, value in imported_config.items(section):
                        temp_config.set(section, key, value)
                
                # 将这个临时的配置对象加载到UI上
                self.config = imported_config
                self.load_settings()

                QMessageBox.information(self, "成功", "配置已成功加载。\n请检查设置，然后点击“应用并保存”使其生效。")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导入配置失败: {e}")

    def _on_theme_selected(self, theme_name):
        """当用户在下拉框中选择一个主题时调用"""
        if self._loading_theme or theme_name == "Custom":
            return
        
        theme_section_name = f"Theme_{theme_name}"
        if not self.config.has_section(theme_section_name):
            print(f"警告: 未在配置文件中找到主题节: {theme_section_name}")
            return
            
        # 将选定主题的颜色加载到UI的颜色选择器中
        for key, value in self.config.items(theme_section_name):
            self.update_color_preview('QSS_Colors', key, value)
    
    def _on_generate_theme_clicked(self):
        """
        当用户点击“根据主色调生成”按钮时触发。
        """
        # 1. 弹出颜色选择对话框
        initial_color = QColor(self.config.get('QSS_Colors', 'background-color-dark', fallback='#34495e'))
        base_color = QColorDialog.getColor(initial_color, self, "请选择一个主色调")

        if not base_color.isValid():
            return # 用户取消了选择

        # 2. 调用颜色派生逻辑
        color_theme = self._calculate_color_theme(base_color)

        # 3. 更新UI上的颜色选择器
        for key, value in color_theme.items():
            self.update_color_preview('QSS_Colors', key, value)
        
        # 4. 自动将主题设置为 "Custom"
        self.theme_combo.setCurrentText("Custom")

    def _calculate_color_theme(self, base_color: QColor) -> dict:
        """
        根据一个基础颜色，计算出一整套UI主题颜色。
        返回一个包含 QSS_Colors 键和新颜色值的字典。
        """
        # 使用 HSL 颜色空间进行计算
        base_h = base_color.hslHueF()
        base_s = base_color.hslSaturationF()
        base_l = base_color.lightnessF()

        # 定义派生规则 (这些百分比可以根据喜好调整)
        darkest_l = max(0, base_l * 0.85)
        dark_l = base_l
        light_l = min(1, base_l * 1.25)
        border_l = min(1, base_l * 1.5)
        border_hover_l = min(1, base_l * 1.7)

        # 创建新的 QColor 对象
        darkest_color = QColor.fromHslF(base_h, base_s * 0.9, darkest_l)
        dark_color = QColor.fromHslF(base_h, base_s, dark_l)
        light_color = QColor.fromHslF(base_h, base_s, light_l)
        border_color = QColor.fromHslF(base_h, base_s * 0.95, border_l)
        border_hover_color = QColor.fromHslF(base_h, base_s, border_hover_l)
        
        # 判断文字颜色
        # 感知亮度公式: Y = 0.299*R + 0.587*G + 0.114*B
        luminance = (0.299 * base_color.red() + 0.587 * base_color.green() + 0.114 * base_color.blue())
        text_color = QColor("#e0e0e0") if luminance < 128 else QColor("#1a1a1a")

        return {
            'background-color-darkest': darkest_color.name(),
            'background-color-dark': dark_color.name(),
            'background-color-light': light_color.name(),
            'border-color': border_color.name(),
            'border-color-hover': border_hover_color.name(),
            'text-color': text_color.name()
        }