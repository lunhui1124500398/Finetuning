# Finetuning/ui/widgets/key_sequence_edit.py

from PyQt6.QtWidgets import QLineEdit
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QFocusEvent

class KeySequenceEdit(QLineEdit):
    """
    一个专门用于录制快捷键的输入框。
    它会捕获键盘事件并将其转换成标准的快捷键字符串，
    并在获得焦点时高亮显示。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self._key_sequence = []

        # --- START: 新增样式定义 ---
        # 定义两种样式：默认和高亮
        self.DEFAULT_STYLE = """
            QLineEdit {
                background-color: #3a3b3c;
                border: 1px solid #5a5b5c;
                border-radius: 4px;
                padding: 5px;
            }
        """
        self.FOCUSED_STYLE = """
            QLineEdit {
                background-color: #4f5153;
                border: 2px solid #78a2c2; /* 使用蓝色边框高亮 */
                color: #ffffff;
                border-radius: 4px;
                padding: 4px; /* 内边距-1以适应边框+1 */
            }
        """
        self.setStyleSheet(self.DEFAULT_STYLE)
        # --- END: 新增样式定义 ---

    # --- START: 新增焦点事件处理 ---
    def focusInEvent(self, event: QFocusEvent):
        """当控件获得焦点时调用。"""
        super().focusInEvent(event)
        self.setStyleSheet(self.FOCUSED_STYLE)
        self.setPlaceholderText("请按下快捷键...")
        super().clear() # 清空之前的内容以便输入新的

    def focusOutEvent(self, event: QFocusEvent):
        """当控件失去焦点时调用。"""
        super().focusOutEvent(event)
        self.setStyleSheet(self.DEFAULT_STYLE)
        self.setPlaceholderText("")
        # 如果用户没输入任何东西就移开了焦点，恢复显示原来的值
        if not self.text() and self._key_sequence:
             self.setText(self._key_sequence[0])

    # --- END: 新增焦点事件处理 ---

    def keyPressEvent(self, event):
        """
        重写键盘按下事件。
        """
        key = event.key()
        modifiers = event.modifiers()

        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return
        
        # 格式化快捷键
        sequence_str = self._format_sequence(key, modifiers)
        self.setText(sequence_str)
        # 更新内部状态，以便失去焦点时可以恢复
        self._key_sequence = [sequence_str]
        
        event.accept()

    def _format_sequence(self, key, modifiers):
        """
        将按键和修饰符格式化为字符串, 例如 "Ctrl+S"。
        """
        parts = []
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            parts.append("Ctrl")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            parts.append("Shift")
        if modifiers & Qt.KeyboardModifier.AltModifier:
            parts.append("Alt") # Alt在某些系统下可能显示为Meta
        
        key_name = QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)
        if key_name:
             parts.append(key_name)

        return "+".join(parts)

    def clear(self):
        """
        重写 clear 方法以同时清空内部状态。
        """
        super().clear()
        self._key_sequence = []

    def setText(self, text: str):
        """重写 setText 以更新内部状态"""
        super().setText(text)
        self._key_sequence = [text]