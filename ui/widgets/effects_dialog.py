# File: /ui/widgets/effects_dialog.py

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTabWidget, QWidget,
    QFormLayout, QLabel, QSlider, QCheckBox, QComboBox, QDialogButtonBox,
    QStackedWidget, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal

class EffectsDialog(QDialog):
    # 信号：当用户点击 Apply 或 OK 时发出，携带最终的设置
    settings_applied = pyqtSignal(dict)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("图像效果调整")
        self.setMinimumSize(450, 400)

        # 加载当前设置来初始化UI
        self.initial_settings = self.model.effect_settings.copy()

        self._init_ui()
        self._connect_signals()
        self._load_settings_to_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # 1. 算法增强 Tab
        algo_tab = QWidget()
        self._setup_algo_tab(algo_tab)
        self.tabs.addTab(algo_tab, "算法增强")

        # 2. 手动调整 Tab
        manual_tab = QWidget()
        self._setup_manual_tab(manual_tab)
        self.tabs.addTab(manual_tab, "手动调整")

        # 3. 对话框按钮
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | 
                                      QDialogButtonBox.StandardButton.Cancel | 
                                      QDialogButtonBox.StandardButton.Apply)
        main_layout.addWidget(button_box)

        self.apply_button = button_box.button(QDialogButtonBox.StandardButton.Apply)

        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        self.apply_button.clicked.connect(self._apply_changes)

    def _setup_algo_tab(self, parent_widget):
        layout = QVBoxLayout(parent_widget)
        
        self.algo_enabled_check = QCheckBox("启用算法增强")
        layout.addWidget(self.algo_enabled_check)

        self.algo_group = QGroupBox("算法设置")
        layout.addWidget(self.algo_group)
        
        form_layout = QFormLayout(self.algo_group)
        
        self.algo_combo = QComboBox()
        self.algo_combo.addItems(["CLAHE", "全局直方图均衡化"])
        form_layout.addRow("选择算法:", self.algo_combo)

        # --- CLAHE 参数 ---
        self.clahe_clip_limit_slider = self._create_slider(1, 100, 1) # 对应 0.1 - 10.0
        self.clahe_clip_limit_label = QLabel()
        form_layout.addRow("对比度限制 (Clip Limit):", self._create_slider_layout(self.clahe_clip_limit_slider, self.clahe_clip_limit_label))

        self.clahe_grid_size_slider = self._create_slider(2, 32, 1)
        self.clahe_grid_size_label = QLabel()
        form_layout.addRow("网格大小 (Grid Size):", self._create_slider_layout(self.clahe_grid_size_slider, self.clahe_grid_size_label))

        layout.addStretch()

    def _setup_manual_tab(self, parent_widget):
        layout = QVBoxLayout(parent_widget)

        self.manual_enabled_check = QCheckBox("启用手动调整")
        layout.addWidget(self.manual_enabled_check)

        self.manual_group = QGroupBox("参数调整")
        layout.addWidget(self.manual_group)
        
        form_layout = QFormLayout(self.manual_group)

        self.min_level_slider = self._create_slider(0, 254)
        self.min_level_label = QLabel()
        form_layout.addRow("暗部 (Min Level):", self._create_slider_layout(self.min_level_slider, self.min_level_label))

        self.max_level_slider = self._create_slider(1, 255)
        self.max_level_label = QLabel()
        form_layout.addRow("亮部 (Max Level):", self._create_slider_layout(self.max_level_slider, self.max_level_label))

        self.brightness_slider = self._create_slider(-100, 100)
        self.brightness_label = QLabel()
        form_layout.addRow("亮度 (Brightness):", self._create_slider_layout(self.brightness_slider, self.brightness_label))
        
        self.contrast_slider = self._create_slider(-100, 100)
        self.contrast_label = QLabel()
        form_layout.addRow("对比度 (Contrast):", self._create_slider_layout(self.contrast_slider, self.contrast_label))

        # Reset 按钮
        reset_button = QPushButton("重置为默认值")
        reset_button.clicked.connect(self._reset_manual_defaults)
        layout.addWidget(reset_button, 0, Qt.AlignmentFlag.AlignRight)
        
        layout.addStretch()

    def _create_slider(self, min_val, max_val, step=1):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_val, max_val)
        slider.setSingleStep(step)
        return slider

    def _create_slider_layout(self, slider, label):
        layout = QHBoxLayout()
        layout.addWidget(slider)
        label.setMinimumWidth(35)
        layout.addWidget(label)
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def _connect_signals(self):
        # 连接所有控件的信号到预览更新函数
        controls = [
            self.algo_enabled_check, self.algo_combo, self.clahe_clip_limit_slider,
            self.clahe_grid_size_slider, self.manual_enabled_check, self.min_level_slider,
            self.max_level_slider, self.brightness_slider, self.contrast_slider
        ]
        for control in controls:
            if isinstance(control, QCheckBox):
                control.toggled.connect(self._update_preview)
            elif isinstance(control, QComboBox):
                control.currentIndexChanged.connect(self._update_preview)
            elif isinstance(control, QSlider):
                control.valueChanged.connect(self._update_preview)

    def _load_settings_to_ui(self, settings=None):
        """用给定的设置字典更新UI界面"""
        if settings is None:
            settings = self.initial_settings

        # 禁用信号，防止加载时触发预览
        self.blockSignals(True)

        self.manual_enabled_check.setChecked(settings['manual_enabled'])
        self.min_level_slider.setValue(settings['manual_min'])
        self.max_level_slider.setValue(settings['manual_max'])
        self.brightness_slider.setValue(settings['manual_brightness'])
        self.contrast_slider.setValue(settings['manual_contrast'])

        self.algo_enabled_check.setChecked(settings['algo_enabled'])
        self.algo_combo.setCurrentText(settings['algo_name'])
        self.clahe_clip_limit_slider.setValue(int(settings['clahe_clip_limit'] * 10))
        self.clahe_grid_size_slider.setValue(settings['clahe_grid_size'])
        
        self._update_labels()
        self.blockSignals(False)

    def _update_labels(self):
        self.min_level_label.setText(str(self.min_level_slider.value()))
        self.max_level_label.setText(str(self.max_level_slider.value()))
        self.brightness_label.setText(str(self.brightness_slider.value()))
        self.contrast_label.setText(str(self.contrast_slider.value()))
        self.clahe_clip_limit_label.setText(f"{self.clahe_clip_limit_slider.value() / 10.0:.1f}")
        self.clahe_grid_size_label.setText(str(self.clahe_grid_size_slider.value()))

    def _get_settings_from_ui(self):
        """从UI控件收集当前设置，返回字典"""
        return {
            'manual_enabled': self.manual_enabled_check.isChecked(),
            'manual_min': self.min_level_slider.value(),
            'manual_max': self.max_level_slider.value(),
            'manual_brightness': self.brightness_slider.value(),
            'manual_contrast': self.contrast_slider.value(),
            
            'algo_enabled': self.algo_enabled_check.isChecked(),
            'algo_name': self.algo_combo.currentText().lower().replace(" ", "_"),
            'clahe_clip_limit': self.clahe_clip_limit_slider.value() / 10.0,
            'clahe_grid_size': self.clahe_grid_size_slider.value(),
        }

    def _reset_manual_defaults(self):
        defaults = {'manual_min': 0, 'manual_max': 255, 'manual_brightness': 0, 'manual_contrast': 0}
        self.min_level_slider.setValue(defaults['manual_min'])
        self.max_level_slider.setValue(defaults['manual_max'])
        self.brightness_slider.setValue(defaults['manual_brightness'])
        self.contrast_slider.setValue(defaults['manual_contrast'])
        self._update_preview() # 触发预览更新

    def _update_preview(self):
        """将当前UI设置发送给模型以进行实时预览"""
        if self.signalsBlocked():
            return
        self._update_labels()
        current_settings = self._get_settings_from_ui()
        self.model.update_preview_effect_settings(current_settings)

    def _apply_changes(self):
        """正式应用更改"""
        final_settings = self._get_settings_from_ui()
        self.settings_applied.emit(final_settings)
        # 更新对话框的初始状态，以便下次取消时能恢复到这次应用的状态
        self.initial_settings = final_settings

    def accept(self):
        """OK按钮被点击"""
        self._apply_changes()
        super().accept()

    def reject(self):
        """Cancel按钮被点击，或按ESC"""
        # 恢复到打开对话框时的状态
        self.model.revert_preview_to_last_settings()
        super().reject()