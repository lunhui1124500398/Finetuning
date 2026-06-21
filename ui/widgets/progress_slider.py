from __future__ import annotations

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QSlider, QStyle, QStyleOptionSlider, QVBoxLayout, QWidget, QLabel


class MarkerSlider(QSlider):
    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._manual_seed_indices: set[int] = set()
        self._effective_seed_indices: set[int] = set()

    def set_seed_markers(self, manual_indices: set[int], effective_indices: set[int]) -> None:
        self._manual_seed_indices = set(manual_indices)
        self._effective_seed_indices = set(effective_indices)
        self.update()

    def clear_seed_markers(self) -> None:
        self._manual_seed_indices.clear()
        self._effective_seed_indices.clear()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.orientation() != Qt.Orientation.Horizontal:
            return
        maximum = self.maximum()
        minimum = self.minimum()
        if maximum <= minimum:
            return

        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        if groove.isNull():
            groove = QRect(10, self.height() // 2 - 2, max(1, self.width() - 20), 4)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        auto_color = QColor(64, 170, 255)
        manual_color = QColor(255, 170, 0)
        marker_top = groove.top() - 7
        marker_bottom = groove.bottom() + 7
        span = max(1, maximum - minimum)

        all_indices = sorted(self._effective_seed_indices | self._manual_seed_indices)
        for index in all_indices:
            if index < minimum or index > maximum:
                continue
            ratio = (index - minimum) / span
            x = groove.left() + int(ratio * max(1, groove.width() - 1))
            color = manual_color if index in self._manual_seed_indices else auto_color
            painter.setPen(QPen(color, 2))
            painter.drawLine(x, marker_top, x, marker_bottom)

        painter.end()


class ProgressSlider(QWidget):
    """A slider plus a progress label, now with optional seed markers."""

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(0)

        self.slider = MarkerSlider(orientation)
        self.progress_label = QLabel("0/0")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        legend = "滑条颜色标记: 橙色=手动指定 Seed, 蓝色=自动生效 Seed"
        self.slider.setToolTip(legend)
        self.progress_label.setToolTip(legend)

        layout.addWidget(self.slider)
        layout.addWidget(self.progress_label)

        self.slider.valueChanged.connect(self.update_label)

    def set_range(self, min_val, max_val):
        self.slider.setRange(min_val, max_val)
        self.update_label()

    def set_value(self, value):
        self.slider.setValue(value)

    def set_seed_markers(self, manual_indices: set[int], effective_indices: set[int]) -> None:
        self.slider.set_seed_markers(manual_indices, effective_indices)

    def clear_seed_markers(self) -> None:
        self.slider.clear_seed_markers()

    def update_label(self):
        current = self.slider.value() + 1
        total = self.slider.maximum() + 1
        if total == 0:
            current = 0
        self.progress_label.setText(f"{current}/{total}")
