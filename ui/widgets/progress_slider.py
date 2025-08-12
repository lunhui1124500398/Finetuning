from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSlider, QLabel
from PyQt6.QtCore import Qt

class ProgressSlider(QWidget):
    """一个封装了滑块和进度标签(例如 '10/100')的组合控件。"""
    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5) # 上下留些边距
        layout.setSpacing(0)

        self.slider = QSlider(orientation)
        self.progress_label = QLabel("0/0")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(self.slider)
        layout.addWidget(self.progress_label)
        
        self.slider.valueChanged.connect(self.update_label)

    def set_range(self, min_val, max_val):
        self.slider.setRange(min_val, max_val)
        self.update_label()
    
    def set_value(self, value):
        self.slider.setValue(value)

    def update_label(self):
        current = self.slider.value() + 1
        total = self.slider.maximum() + 1
        if total == 0:
            current = 0
        self.progress_label.setText(f"{current}/{total}")