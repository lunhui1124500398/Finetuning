# Finetuning/ui/widgets/settings_dialog.py

import configparser
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTabWidget, QWidget,
    QFormLayout, QLabel, QLineEdit, QColorDialog, QScrollArea, QFrame,
    QMessageBox, QFileDialog
)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt

from .key_sequence_edit import KeySequenceEdit

class SettingsDialog(QDialog):
    def __init__(self, config: configparser.ConfigParser, parent=None):
        # ... (构造函数上半部分无变化) ...
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("设置")
        self.setMinimumSize(600, 500)

        self.key_editors = {}
        self.color_buttons = {}
        self.color_labels = {}

        self.init_ui()
        self.load_settings()

    def init_ui(self):
        # ... (此函数内部无变化) ...
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
        self.ok_button = QPushButton("应用并保存")
        self.cancel_button = QPushButton("取消")
        
        button_layout.addWidget(self.import_button)
        button_layout.addWidget(self.export_button)
        button_layout.addWidget(self.restore_button)
        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        main_layout.addLayout(button_layout)

        self.ok_button.clicked.connect(self.save_and_accept)
        self.cancel_button.clicked.connect(self.reject)
        self.restore_button.clicked.connect(self.confirm_restore_defaults)
        self.import_button.clicked.connect(self.import_settings)
        self.export_button.clicked.connect(self.export_settings)
    
    def setup_keybindings_tab(self, parent_widget):
        # ... (此函数内部无变化) ...
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
        # ... (此函数内部无变化) ...
        scroll_area = QScrollArea(parent_widget)
        scroll_area.setWidgetResizable(True)
        container = QWidget()
        scroll_area.setWidget(container)
        
        main_layout = QVBoxLayout(container)
        
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

    # --- START: 修改 add_color_picker ---
    def add_color_picker(self, layout, key, section):
        label_text = key.replace('_', ' ').title()
        
        h_layout = QHBoxLayout()
        color_label = QLabel()
        color_label.setFixedSize(20, 20)
        # --- FIX: 不再需要 setAutoFillBackground 和 QPalette ---
        # --- 为色块添加一个边框，使其在任何背景下都清晰可见 ---
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

        button.clicked.connect(lambda _, s=section, k=key: self.open_color_dialog(s, k))
    # --- END: 修改 add_color_picker ---
    
    def open_color_dialog(self, section, key):
        # ... (此函数内部无变化) ...
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
            
    # --- START: 修改 update_color_preview ---
    def update_color_preview(self, section, key, value_str):
        """安全地更新颜色预览UI，使用样式表填充色块。"""
        widget_pair = self.color_labels.get((section, key))
        
        if not widget_pair:
            return
            
        color_label, line_edit = widget_pair
        line_edit.setText(value_str)
        
        color = QColor()
        color_qss_string = "transparent" # 默认透明
        
        if ',' in value_str: # RGBA
            try:
                r, g, b, a = map(int, value_str.split(','))
                color.setRgb(r, g, b, a)
                # QSS支持rgba格式，这对于显示透明度至关重要
                color_qss_string = f"rgba({r}, {g}, {b}, {a})"
            except (ValueError, TypeError): pass
        else: # Hex
            color.setNamedColor(value_str)
            color_qss_string = color.name()

        # --- FIX: 使用样式表动态设置背景色，比QPalette更可靠 ---
        color_label.setStyleSheet(f"background-color: {color_qss_string}; border: 1px solid #888;")
    # --- END: 修改 update_color_preview ---
    
    def load_settings(self):
        # ... (此函数内部无变化) ...
        for key, editor in self.key_editors.items():
            value = self.config.get('Keybindings', key, fallback='')
            editor.setText(value)
        
        sections_to_load = ['QSS_Colors', 'Colors']
        for section in sections_to_load:
            if self.config.has_section(section):
                for key, value in self.config.items(section):
                    self.update_color_preview(section, key, value)

    # ... (其余所有方法 save_settings, save_and_accept, confirm_restore_defaults, restore_defaults, export_settings, import_settings 均无变化) ...
    def save_settings(self):
        """将UI中的设置保存到config对象。"""
        for key, editor in self.key_editors.items():
            self.config.set('Keybindings', key, editor.text())
        for (section, key), (_, line_edit) in self.color_labels.items():
             self.config.set(section, key, line_edit.text())

    def save_and_accept(self):
        """保存设置并关闭对话框。"""
        self.save_settings()
        self.accept()

    def confirm_restore_defaults(self):
        reply = QMessageBox.question(self, '恢复默认设置',
                                     "您确定要将所有设置恢复为默认值吗？\n此操作不可撤销。",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.restore_defaults()

    def restore_defaults(self):
        defaults = {
            'Keybindings': {
                'next_image': "D; Right", 'prev_image': "A; Left", 'save': "Ctrl+S",
                'save_and_nect': "S", 'draw_mode': "Q", 'erase_mode': "E",
                'clear_mask': "W", 'toggle_mask': "Z", 'auto_save': "X",
                'high_contrast': "C", 'import_files': "I", 'toggle_image_source': "Space"
            },
            'Colors': {
                'mask_overlay_color': "255, 0, 0, 80",
                'contour_line_color': "0, 255, 0, 100",
                'inner_contour_color': "0, 255, 0, 100",
                'contour_thickness': "1"
            },
            'QSS_Colors': {
                'background-color-darkest': "#252627",
                'background-color-dark': "#2e2f30",
                'background-color-light': "#3a3b3c",
                'border-color': "#4a4b4c",
                'border-color-hover': "#5a5b5c",
                'text-color': "#e0e0e0"
            }
        }
        
        temp_config = configparser.ConfigParser()
        temp_config.read_dict(defaults)

        for section in temp_config.sections():
            for key, value in temp_config.items(section):
                if section == 'Keybindings':
                    if key in self.key_editors:
                        self.key_editors[key].setText(value)
                else:
                    self.update_color_preview(section, key, value)
        
        QMessageBox.information(self, "成功", "设置已恢复为默认值。请点击“应用并保存”以生效。")

    def export_settings(self):
        temp_config = configparser.ConfigParser()
        
        for section in self.config.sections():
            if not temp_config.has_section(section):
                temp_config.add_section(section)
            for key, value in self.config.items(section):
                temp_config.set(section, key, value)
        
        for key, editor in self.key_editors.items():
            temp_config.set('Keybindings', key, editor.text())
        for (section, key), (_, line_edit) in self.color_labels.items():
            if not temp_config.has_section(section):
                temp_config.add_section(section)
            temp_config.set(section, key, line_edit.text())

        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出配置", "", "配置文件 (*.ini);;所有文件 (*)"
        )

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as configfile:
                    temp_config.write(configfile)
                QMessageBox.information(self, "成功", f"配置已成功导出到:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导出配置失败: {e}")

    def import_settings(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入配置", "", "配置文件 (*.ini);;所有文件 (*)"
        )

        if file_path:
            try:
                imported_config = configparser.ConfigParser()
                imported_config.read(file_path, encoding='utf-8')

                if imported_config.has_section('Keybindings'):
                    for key, editor in self.key_editors.items():
                        value = imported_config.get('Keybindings', key, fallback=editor.text())
                        editor.setText(value)
                
                sections_to_load = ['QSS_Colors', 'Colors']
                for section in sections_to_load:
                    if imported_config.has_section(section):
                        for key, value in imported_config.items(section):
                            if (section, key) in self.color_labels:
                                self.update_color_preview(section, key, value)

                QMessageBox.information(self, "成功", "配置已成功加载。\n请检查设置，然后点击“应用并保存”使其生效。")

            except Exception as e:
                QMessageBox.critical(self, "错误", f"导入配置失败: {e}")