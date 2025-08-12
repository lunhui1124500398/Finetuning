from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog
from PyQt6.QtCore import pyqtSignal

class PathSelector(QWidget):
    """一个封装了标签、只读文本框和选择按钮的路径选择控件。"""
    path_selected = pyqtSignal(str)  # 定义一个信号，当路径被选择时发射

    def __init__(self, label_text, parent=None):
        super().__init__(parent)
        self.label_text = label_text
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel(self.label_text)
        self.line_edit = QLineEdit()
        self.line_edit.setReadOnly(True)
        self.button = QPushButton("选择文件夹...")

        layout.addWidget(self.label)
        layout.addWidget(self.line_edit)
        layout.addWidget(self.button)

        self.button.clicked.connect(self.select_directory)

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, f"请选择{self.label_text}")
        if directory:
            self.line_edit.setText(directory)
            self.path_selected.emit(directory)

    def get_path(self):
        return self.line_edit.text()

    def set_path(self, path):
        self.line_edit.setText(path)