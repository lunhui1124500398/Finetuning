# File: ui/widgets/effects_dialog.py

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTabWidget, QWidget,
    QFormLayout, QLabel, QSlider, QCheckBox, QComboBox, QDialogButtonBox,
    QStackedWidget, QGroupBox, QSpinBox, QDoubleSpinBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from core.image_manager import ImageManager

class EffectsDialog(QDialog):
    # 信号：当用户点击 Apply 或 OK 时发出，携带最终的设置
    settings_applied = pyqtSignal(dict)

    def __init__(self, model, parent=None, current_pixmap=None):
        super().__init__(parent)
        self.model = model
        self.current_pixmap = current_pixmap  # 保存当前图像引用用于 Auto 计算
        self.setWindowTitle("图像效果调整")
        self.setMinimumSize(500, 450) # 稍微加大高度以容纳新控件

        # 加载当前设置来初始化UI
        self.initial_settings = self.model.effect_settings.copy()

        self._init_ui()
        self._connect_signals()
        self._load_settings_to_ui()
    
    def set_current_pixmap(self, pixmap):
        """[NEW] 更新当前用于 Auto 计算的图像引用"""
        self.current_pixmap = pixmap

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # 1. 手动调整 Tab (新风格，模仿 ImageJ)
        manual_tab = QWidget()
        self._setup_manual_tab(manual_tab)
        self.tabs.addTab(manual_tab, "手动调整")
        
        # 2. 算法增强 Tab (保持旧风格，使用旧辅助函数)
        algo_tab = QWidget()
        self._setup_algo_tab(algo_tab)
        self.tabs.addTab(algo_tab, "算法增强")

        # 3. 对话框按钮
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | 
                                      QDialogButtonBox.StandardButton.Cancel | 
                                      QDialogButtonBox.StandardButton.Apply)
        main_layout.addWidget(button_box)

        self.apply_button = button_box.button(QDialogButtonBox.StandardButton.Apply)

        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        self.apply_button.clicked.connect(self._apply_changes)
    
    def _on_auto_clicked(self):
        """
        Auto 按钮逻辑：
        1. 基于图像内容计算 Percentile Min/Max。
        2. 如果当前设置已经是全范围(0-255)，直接应用计算结果。
        3. 如果当前设置已经接近计算结果，或者用户再次点击，则在当前基础上向内“收缩”，增强对比度。
        """
        if not self.current_pixmap:
            return
            
        # 1. 获取当前 UI 上的 min/max
        current_min = self.min_level_slider.value()
        current_max = self.max_level_slider.value()
        
        # 2. 计算基于图像统计学的理论最佳值 (0.5% 饱和度)
        auto_min_stat, auto_max_stat = ImageManager.calculate_auto_levels(self.current_pixmap, saturation_percentage=0.5)
        
        # 调试打印，看看算出来是多少
        print(f"Auto Calc: Stat=({auto_min_stat}, {auto_max_stat}), Current=({current_min}, {current_max})")

        new_min, new_max = 0, 255

        # 3. 决策逻辑
        is_default = (current_min == 0 and current_max == 255)
        
        # 检查当前值是否比统计值“更宽” (意味着还有增强空间)
        # 例如: 统计是(20, 200)，当前是(0, 255)，则应用 (20, 200)
        range_is_wider_than_stat = (current_min < auto_min_stat) or (current_max > auto_max_stat)

        if is_default or range_is_wider_than_stat:
            # 第一阶段：应用统计学计算结果
            new_min = auto_min_stat
            new_max = auto_max_stat
            
            # 极端情况：如果统计结果依然是 0-255 (说明图像直方图本身就铺满了)，
            # 强制收缩一点点，让用户看到“有反应”
            if new_min == 0 and new_max == 255:
                new_min = 10
                new_max = 245
        else:
            # 第二阶段：用户觉得不够，再次点击 -> 在当前基础上强制收缩 (ImageJ 风格)
            # 每次向内收缩当前范围的 5%
            current_range = current_max - current_min
            step = max(2, int(current_range * 0.05)) 
            
            new_min = min(current_min + step, 120) # 限制暗部最大只到 120
            new_max = max(current_max - step, 135) # 限制亮部最小只到 135
            
            if new_min >= new_max: # 防止交叉
                 new_min = current_min
                 new_max = current_max

        # 4. 更新 UI 并强制刷新
        # 阻断信号防止 setValue 触发两次 update，最后手动调一次
        self.blockSignals(True) 
        self.manual_enabled_check.setChecked(True)
        self.min_level_slider.setValue(new_min)
        self.max_level_slider.setValue(new_max)
        
        # 记得同步 SpinBox (虽然 Slider 绑定了，但 blockSignals 后可能不同步，保险起见)
        self.min_level_spin.setValue(new_min)
        self.max_level_spin.setValue(new_max)
        self.blockSignals(False)

        print(f"Auto Applied: ({new_min}, {new_max})")
        self._update_preview() # 显式触发预览更新

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

        # --- CLAHE 参数 (继续使用旧的 slider 辅助函数) ---
        self.clahe_clip_limit_slider = self._create_slider(1, 100, 1) # 对应 0.1 - 10.0
        self.clahe_clip_limit_label = QLabel()
        form_layout.addRow("对比度限制 (Clip Limit):", self._create_slider_layout(self.clahe_clip_limit_slider, self.clahe_clip_limit_label))

        self.clahe_grid_size_slider = self._create_slider(2, 32, 1)
        self.clahe_grid_size_label = QLabel()
        form_layout.addRow("网格大小 (Grid Size):", self._create_slider_layout(self.clahe_grid_size_slider, self.clahe_grid_size_label))

        layout.addStretch()

    def _setup_manual_tab(self, parent_widget):
        """
        重构的手动调整页面，模仿 ImageJ 风格：
        - 包含 Auto, Reset, Set 按钮
        - 滑块旁边增加数字输入框 (SpinBox)
        """
        layout = QVBoxLayout(parent_widget)

        self.manual_enabled_check = QCheckBox("启用手动调整")
        layout.addWidget(self.manual_enabled_check)

        self.manual_group = QGroupBox("Level & Contrast")
        layout.addWidget(self.manual_group)
        
        # 使用 FormLayout 排列控件
        control_layout = QFormLayout(self.manual_group)

        # 定义一个内部辅助函数来创建 "滑块 + 数字框" 的组合
        def create_control(min_v, max_v, default_v, label_txt):
            row_layout = QHBoxLayout()
            
            # 滑块
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(min_v, max_v)
            slider.setValue(default_v)
            
            # 数字框
            spin = QSpinBox()
            spin.setRange(min_v, max_v)
            spin.setValue(default_v)
            
            # 双向绑定
            slider.valueChanged.connect(lambda v: spin.blockSignals(True) or spin.setValue(v) or spin.blockSignals(False))
            slider.valueChanged.connect(self._update_preview) # Slider 拖动直接触发预览
            spin.valueChanged.connect(lambda v: slider.setValue(v)) # Spin 变动会触发 Slider 的 valueChanged -> _update_preview

            row_layout.addWidget(slider)
            row_layout.addWidget(spin)
            
            control_layout.addRow(label_txt, row_layout)
            return slider, spin

        # 创建四个主要的控制项
        self.min_level_slider, self.min_level_spin = create_control(0, 255, 0, "Min Level:")
        self.max_level_slider, self.max_level_spin = create_control(0, 255, 255, "Max Level:")
        self.brightness_slider, self.brightness_spin = create_control(-100, 100, 0, "Brightness:")
        self.contrast_slider, self.contrast_spin = create_control(-100, 100, 0, "Contrast:")

        # 按钮区
        btn_layout = QHBoxLayout()
        self.auto_btn = QPushButton("Auto")
        self.auto_btn.setToolTip("自动计算最佳 Min/Max 值 (点击多次逐步增强)")
        
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setToolTip("重置为当前未修改状态")

        self.set_btn = QPushButton("Set Defaults")
        self.set_btn.setToolTip("重置为默认值 (0-255, 无增强)")

        btn_layout.addWidget(self.auto_btn)
        btn_layout.addWidget(self.reset_btn)
        btn_layout.addWidget(self.set_btn)
        
        layout.addLayout(btn_layout)
        layout.addStretch()

        # 连接按钮信号
        self.auto_btn.clicked.connect(self._on_auto_clicked)
        self.reset_btn.clicked.connect(self._revert_to_initial) # Reset 恢复到打开对话框时的状态
        self.set_btn.clicked.connect(self._reset_manual_defaults) # Set Defaults 恢复到 0-255

    # --- 保留旧的辅助函数供 Algo Tab 使用 ---
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
    # ------------------------------------

    def _connect_signals(self):
        # 仅连接 Algo 相关的，Manual 相关的在 create_control 中已经连接了
        controls = [
            self.algo_enabled_check, self.algo_combo, 
            self.clahe_clip_limit_slider, self.clahe_grid_size_slider, 
            self.manual_enabled_check
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

        # [FIXED] 分别设置 slider 和 spinbox，避免触发联动信号
        def set_val(slider, spin, val):
            slider.blockSignals(True)
            spin.blockSignals(True)
            slider.setValue(val)
            spin.setValue(val)
            slider.blockSignals(False)
            spin.blockSignals(False)

        set_val(self.min_level_slider, self.min_level_spin, settings['manual_min'])
        set_val(self.max_level_slider, self.max_level_spin, settings['manual_max'])
        set_val(self.brightness_slider, self.brightness_spin, settings['manual_brightness'])
        set_val(self.contrast_slider, self.contrast_spin, settings['manual_contrast'])

        self.algo_enabled_check.setChecked(settings['algo_enabled'])
        self.algo_combo.setCurrentText(settings['algo_name'])
        self.clahe_clip_limit_slider.setValue(int(settings['clahe_clip_limit'] * 10))
        self.clahe_grid_size_slider.setValue(settings['clahe_grid_size'])
        
        self._update_labels() # 更新 Algo Tab 的标签
        self.blockSignals(False)
        self._update_preview() # 手动触发一次预览以同步状态

    def _update_labels(self):
        # 仅更新 Algo Tab 的标签，Manual Tab 由 SpinBox 负责显示
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

    def _on_auto_clicked(self):
        """Auto 按钮逻辑：计算自动对比度"""
        if not self.current_pixmap:
            print("Auto Failed: No current_pixmap set.")
            return
            
        # 1. 获取当前的 min/max
        current_min = self.min_level_slider.value()
        current_max = self.max_level_slider.value()
        auto_min_stat, auto_max_stat = ImageManager.calculate_auto_levels(self.current_pixmap, saturation_percentage=0.5)
        new_min, new_max = 0, 255
        is_default = (current_min == 0 and current_max == 255)
        range_is_wider_than_stat = (current_min < auto_min_stat) or (current_max > auto_max_stat)

        # 2. 如果是第一次点击 (还是默认值 0-255)，进行全局直方图计算
        if is_default or range_is_wider_than_stat:
            new_min = auto_min_stat
            new_max = auto_max_stat
            if new_min == 0 and new_max == 255:
                new_min = 10
                new_max = 245
        else:
            # 3. 用户希望“逐级提高”，我们在当前基础上向内收缩 5%
            current_range = current_max - current_min
            step = max(1, int(current_range * 0.05)) # 每次收缩 5%
            new_min = min(current_min + step, 120) # 限制暗部不要收缩得太离谱
            new_max = max(current_max - step, 135) # 限制亮部
            if new_min >= new_max: 
                 new_min = current_min
                 new_max = current_max
        
        # [CRITICAL FIXED] 只阻塞控件信号，不阻塞 Dialog 信号
        self.manual_enabled_check.setChecked(True) # 这会触发一次 update
        
        def safe_set(slider, spin, val):
            slider.blockSignals(True) # 防止触发 update
            spin.blockSignals(True)
            slider.setValue(val)
            spin.setValue(val)
            slider.blockSignals(False)
            spin.blockSignals(False)
            
        safe_set(self.min_level_slider, self.min_level_spin, new_min)
        safe_set(self.max_level_slider, self.max_level_spin, new_max)
        
        print(f"Auto Applied: {new_min}-{new_max}")
        self._update_preview() # 显式触发一次

    def _reset_manual_defaults(self):
        """Set Defaults: 恢复到标准的 0-255"""
        self.min_level_slider.setValue(0)
        self.max_level_slider.setValue(255)
        self.brightness_slider.setValue(0)
        self.contrast_slider.setValue(0)

    def _revert_to_initial(self):
        """Reset: 恢复到打开对话框时的状态"""
        self._load_settings_to_ui(self.initial_settings)

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
    
    def force_preview_update(self):
        self._update_preview()