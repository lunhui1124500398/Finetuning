# File: ui/widgets/effects_dialog.py

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTabWidget, QWidget,
    QFormLayout, QLabel, QSlider, QCheckBox, QComboBox, QDialogButtonBox,
    QStackedWidget, QGroupBox, QSpinBox, QDoubleSpinBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from core.image_manager import ImageManager
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

class EffectsDialog(QDialog):
    # 信号：当用户点击 Apply 或 OK 时发出，携带最终的设置
    settings_applied = pyqtSignal(dict)

    def __init__(self, model, parent=None, current_pixmap=None):
        super().__init__(parent)
        self.model = model
        self.current_pixmap = None # Initialize to None first
        self.hist_sample = None # Cache for histogram data
        self.current_pixmap = current_pixmap  # 保存当前图像引用用于 Auto 计算
        if self.current_pixmap:
             self._update_histogram_data()
        
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
        self._update_histogram_data() # Pre-calculate histogram data when image changes
        self._update_histogram_lines() # Refresh plot


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

        # --- [NEW] Histogram ---
        self.hist_figure = Figure(figsize=(4, 2), dpi=100)
        self.hist_figure.patch.set_facecolor('#f0f0f0') # Match groupbox background roughly
        self.hist_canvas = FigureCanvasQTAgg(self.hist_figure)
        self.hist_ax = self.hist_figure.add_subplot(111)
        self.hist_figure.subplots_adjust(left=0.05, right=0.95, top=0.95, bottom=0.15)
        self.hist_ax.axis('off')
        
        # Add histogram to the top of the manual tab
        layout.insertWidget(1, self.hist_canvas) # Insert below checkbox, above controls


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
            slider.valueChanged.connect(self._update_preview_with_hist) # Slider 拖动直接触发预览和直方图更新
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
        
        # [NEW] Gamma slider (使用 QDoubleSpinBox，范围 0.1-3.0)
        gamma_row = QHBoxLayout()
        self.gamma_slider = QSlider(Qt.Orientation.Horizontal)
        self.gamma_slider.setRange(10, 300)  # 代表 0.1 - 3.0 (值/100)
        self.gamma_slider.setValue(100)  # 默认 1.0
        
        self.gamma_spin = QDoubleSpinBox()
        self.gamma_spin.setRange(0.1, 3.0)
        self.gamma_spin.setSingleStep(0.1)
        self.gamma_spin.setDecimals(2)
        self.gamma_spin.setValue(1.0)
        
        # 双向绑定 (slider is int *100, spin is float)
        self.gamma_slider.valueChanged.connect(lambda v: (
            self.gamma_spin.blockSignals(True),
            self.gamma_spin.setValue(v / 100.0),
            self.gamma_spin.blockSignals(False)
        ))
        self.gamma_slider.valueChanged.connect(self._update_preview_with_hist)
        self.gamma_spin.valueChanged.connect(lambda v: self.gamma_slider.setValue(int(v * 100)))
        
        gamma_row.addWidget(self.gamma_slider)
        gamma_row.addWidget(self.gamma_spin)
        control_layout.addRow("Gamma:", gamma_row)

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
                control.valueChanged.connect(self._update_preview_with_hist)

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
        
        # [NEW] Gamma
        gamma_val = settings.get('manual_gamma', 1.0)
        self.gamma_slider.blockSignals(True)
        self.gamma_spin.blockSignals(True)
        self.gamma_slider.setValue(int(gamma_val * 100))
        self.gamma_spin.setValue(gamma_val)
        self.gamma_slider.blockSignals(False)
        self.gamma_spin.blockSignals(False)

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
            'manual_gamma': self.gamma_spin.value(),  # [NEW]
            
            'algo_enabled': self.algo_enabled_check.isChecked(),
            'algo_name': self.algo_combo.currentText().lower().replace(" ", "_"),
            'clahe_clip_limit': self.clahe_clip_limit_slider.value() / 10.0,
            'clahe_grid_size': self.clahe_grid_size_slider.value(),
        }

    def _on_auto_clicked(self):
        """
        Auto 按钮逻辑 (仿 ImageJ)：
        1. 计算基于 Percentile 的建议范围 (Auto Levels)
        2. 如果当前范围明显宽于建议范围，则应用建议范围。
        3. 如果当前范围已经接近建议范围，则在当前基础上收缩 (Shrink)，增强对比度。
        """
        if not self.current_pixmap:
            print("Auto Failed: No current_pixmap set.")
            return

        # 1. 获取当前状态
        current_min = self.min_level_slider.value()
        current_max = self.max_level_slider.value()
        current_range_width = current_max - current_min

        # 2. 计算统计学最佳范围 (0.04% - 99.96%)
        auto_min, auto_max = ImageManager.calculate_auto_levels(self.current_pixmap)
        auto_range_width = auto_max - auto_min
        
        # 3. 决策逻辑
        # 判断条件：当前范围是否显著宽于自动范围 (宽松一点，1.1倍)
        # 如果是默认状态 (0-255) 或者 当前范围很大，则直接跳转到 Auto Levels
        is_default = (current_min == 0 and current_max == 255)
        range_is_wider = current_range_width > (auto_range_width * 1.1)

        new_min, new_max = current_min, current_max

        if is_default or range_is_wider:
            # Mode A: Apply Auto Levels
            new_min = auto_min
            new_max = auto_max
        else:
            # Mode B: Shrink (增强对比度)
            # 在当前范围基础上收缩，而不是使用硬编码的限制
            # 每次收缩当前宽度的 5% (左右各 5%) -> 总共 10%
            # 参考 enhance_from_another_project.py 的逻辑
            
            shrink_factor = 0.05
            margin = int(current_range_width * shrink_factor)
            if margin < 1: margin = 1 # 至少收缩 1 个单位
            
            new_min = current_min + margin
            new_max = current_max - margin
            
            # 安全检查：防止交叉
            if new_min >= new_max:
                 mid = (current_min + current_max) // 2
                 new_min = mid - 1
                 new_max = mid + 1
            
            # 钳位到 0-255
            new_min = max(0, new_min)
            new_max = min(255, new_max)

        # 4. 应用设置
        self.manual_enabled_check.setChecked(True)
        
        def safe_set(slider, spin, val):
            slider.blockSignals(True)
            spin.blockSignals(True)
            slider.setValue(val)
            spin.setValue(val)
            slider.blockSignals(False)
            spin.blockSignals(False)

        safe_set(self.min_level_slider, self.min_level_spin, new_min)
        safe_set(self.max_level_slider, self.max_level_spin, new_max)
        
        # [NEW] 重置额外的亮度、对比度和 Gamma 滑块，确保纯粹的 Level 调整
        safe_set(self.brightness_slider, self.brightness_spin, 0)
        safe_set(self.contrast_slider, self.contrast_spin, 0)
        
        # Reset Gamma to 1.0
        self.gamma_slider.blockSignals(True)
        self.gamma_spin.blockSignals(True)
        self.gamma_slider.setValue(100)
        self.gamma_spin.setValue(1.0)
        self.gamma_slider.blockSignals(False)
        self.gamma_spin.blockSignals(False)
        
        print(f"Auto Applied: {new_min}-{new_max} (Original Auto: {auto_min}-{auto_max})")
        self._update_preview()
        self._update_histogram_lines() # [NEW] Update histogram lines immediately

    def _reset_manual_defaults(self):
        """Set Defaults: 恢复到标准的 0-255, Gamma 1.0"""
        self.min_level_slider.setValue(0)
        self.max_level_slider.setValue(255)
        self.brightness_slider.setValue(0)
        self.contrast_slider.setValue(0)
        self.gamma_slider.setValue(100)  # [NEW] gamma = 1.0
        self.gamma_spin.setValue(1.0)

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

    # --- Histogram Logic ---
    def _update_histogram_data(self):
        """Calculates histogram data from current_pixmap (cached)"""
        if not self.current_pixmap or self.current_pixmap.isNull():
            self.hist_sample = None
            return

        # QPixmap -> Grayscale Numpy
        qimage = self.current_pixmap.toImage().convertToFormat(self.current_pixmap.toImage().Format.Format_Grayscale8)
        ptr = qimage.bits()
        ptr.setsize(qimage.sizeInBytes())
        h, w = qimage.height(), qimage.width()
        bpl = qimage.bytesPerLine()
        arr = np.array(ptr).reshape(h, bpl)[:, :w]
        
        # Downsample for performance (similar to learn/enhance_from_another_project.py)
        if arr.size > 1000000:
            self.hist_sample = arr.ravel()[::100]
        else:
            self.hist_sample = arr.ravel()

    def _update_histogram_lines(self):
        """Redraws histogram with current Min/Max lines"""
        self.hist_ax.clear()
        self.hist_ax.axis('off')
        
        if self.hist_sample is None:
            self.hist_ax.text(0.5, 0.5, "No Image", ha='center')
            self.hist_canvas.draw()
            return

        # Plot Histogram
        self.hist_ax.hist(self.hist_sample, bins=64, color='#888888', alpha=0.6, density=True)
        
        # Plot Lines
        min_v = self.min_level_slider.value()
        max_v = self.max_level_slider.value()
        
        self.hist_ax.axvline(min_v, color='blue', linestyle='--', linewidth=1)
        self.hist_ax.axvline(max_v, color='red', linestyle='--', linewidth=1)
        
        # Ensure x-axis covers 0-255
        self.hist_ax.set_xlim(-5, 260)
        
        self.hist_canvas.draw()

    def _update_preview_with_hist(self):
        self._update_preview()
        self._update_histogram_lines() # Refresh lines when sliders move
