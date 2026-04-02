from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget


class PathSelector(QWidget):
    """Path input with both manual editing and directory browsing."""

    path_selected = pyqtSignal(str)

    def __init__(self, label_text, parent=None):
        super().__init__(parent)
        self.label_text = label_text
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel(self.label_text)
        self.line_edit = QLineEdit()
        self.line_edit.setPlaceholderText("\u53ef\u624b\u52a8\u8f93\u5165\u6216\u70b9\u51fb\u53f3\u4fa7\u9009\u62e9\u6587\u4ef6\u5939")
        self.button = QPushButton("\u9009\u62e9\u6587\u4ef6\u5939...")

        layout.addWidget(self.label)
        layout.addWidget(self.line_edit)
        layout.addWidget(self.button)

        self.button.clicked.connect(self.select_directory)
        self.line_edit.editingFinished.connect(self._emit_current_path)

    def _emit_current_path(self):
        self.path_selected.emit(self.line_edit.text().strip())

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            f"\u8bf7\u9009\u62e9{self.label_text}",
            self.line_edit.text().strip(),
        )
        if directory:
            self.line_edit.setText(directory)
            self.path_selected.emit(directory)

    def get_path(self):
        return self.line_edit.text().strip()

    def set_path(self, path):
        self.line_edit.setText(path)
