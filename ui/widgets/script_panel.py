from typing import List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)


class ScriptPanelDialog(QDialog):
    """Non-modal script launcher grouped by workflow."""

    run_script_requested = pyqtSignal(object)

    def __init__(self, scripts: List[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("脚本面板")
        self.setMinimumWidth(960)
        self.setMinimumHeight(520)
        self.setWindowModality(Qt.WindowModality.NonModal)

        self.scripts = scripts
        self.category_items = []

        layout = QVBoxLayout(self)

        header = QLabel("按工作流分类显示 Useful_script。面板保持打开，不会阻塞主窗口操作。")
        header.setWordWrap(True)
        header.setStyleSheet("color: gray;")
        layout.addWidget(header)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("搜索:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入脚本名、说明或文件名")
        self.search_input.textChanged.connect(self.apply_filter)
        search_row.addWidget(self.search_input)
        layout.addLayout(search_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["脚本名称", "说明"])
        self.tree.setIndentation(24)
        self.tree.setAlternatingRowColors(True)
        tree_header = self.tree.header()
        tree_header.setMinimumHeight(46)
        tree_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        tree_header.setMinimumSectionSize(180)
        tree_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        tree_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(0, 460)
        self.tree.setStyleSheet(
            "QHeaderView::section {"
            "  min-height: 36px;"
            "  padding: 8px 12px;"
            "  font-weight: 600;"
            "}"
            "QTreeWidget::item {"
            "  min-height: 30px;"
            "  padding: 2px 6px;"
            "}"
        )
        self.tree.itemDoubleClicked.connect(lambda _item, _column: self.run_selected_script())
        layout.addWidget(self.tree)

        button_row = QHBoxLayout()
        self.run_button = QPushButton("运行选中脚本")
        self.close_button = QPushButton("关闭面板")
        self.run_button.clicked.connect(self.run_selected_script)
        self.close_button.clicked.connect(self.close)
        button_row.addStretch()
        button_row.addWidget(self.run_button)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

        self.set_scripts(scripts)

    def set_scripts(self, scripts: List[dict]):
        from Useful_script.script_loader import group_scripts_by_category

        self.scripts = scripts
        self.category_items = []
        self.tree.clear()

        for category, items in group_scripts_by_category(scripts):
            category_item = QTreeWidgetItem([category, f"{len(items)} 个脚本"])
            category_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(category_item)
            self.category_items.append(category_item)

            for script in items:
                item = QTreeWidgetItem(
                    [
                        script.get("name", script.get("filename", "")),
                        script.get("description", ""),
                    ]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, script)
                item.setToolTip(0, script.get("filename", ""))
                item.setToolTip(1, script.get("description", ""))
                category_item.addChild(item)
            category_item.setExpanded(True)

        self.apply_filter(self.search_input.text())

    def apply_filter(self, text: str):
        query = text.strip().lower()
        for category_item in self.category_items:
            visible_children = 0
            for index in range(category_item.childCount()):
                child = category_item.child(index)
                script = child.data(0, Qt.ItemDataRole.UserRole) or {}
                haystack = " ".join(
                    [
                        script.get("name", ""),
                        script.get("description", ""),
                        script.get("filename", ""),
                        script.get("category", ""),
                    ]
                ).lower()
                visible = not query or query in haystack
                child.setHidden(not visible)
                if visible:
                    visible_children += 1
            category_item.setHidden(visible_children == 0)

    def run_selected_script(self):
        item = self.tree.currentItem()
        if item is None:
            return
        script = item.data(0, Qt.ItemDataRole.UserRole)
        if not script:
            if item.childCount() > 0:
                self.tree.setCurrentItem(item.child(0))
                script = item.child(0).data(0, Qt.ItemDataRole.UserRole)
            if not script:
                return
        self.run_script_requested.emit(script)
