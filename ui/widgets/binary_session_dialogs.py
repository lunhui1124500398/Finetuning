from pathlib import Path
from typing import Dict, List, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHeaderView,
)

from utils.path_utils import filesystem_path


JOINABLE_ROLE = Qt.ItemDataRole.UserRole.value + 1
SELECTED_ROLE = Qt.ItemDataRole.UserRole.value + 2


class BinaryExportsSessionDialog(QDialog):
    """Review and select Exports folders for a direct Binary queue session."""

    def __init__(
        self,
        exports_dir: str,
        origin_suffix: str = "_contrasted",
        mask_suffix: str = "_mask",
        save_suffix: str = "_mask_refined",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("从 Exports 创建 Binary 会话")
        self.setMinimumWidth(1100)
        self.setMinimumHeight(650)

        self.exports_dir = exports_dir
        self.datasets: List[Dict] = []
        self.scan_config: Tuple[str, str, str] = ("", "", "")

        layout = QVBoxLayout(self)

        header = QLabel(f"<b>Exports 目录:</b><br>{exports_dir}")
        header.setWordWrap(True)
        layout.addWidget(header)

        config_group = QGroupBox("文件夹后缀")
        config_layout = QVBoxLayout(config_group)

        suffix_row = QHBoxLayout()
        self.origin_suffix_input = QLineEdit(origin_suffix)
        self.mask_suffix_input = QLineEdit(mask_suffix)
        self.save_suffix_input = QLineEdit(save_suffix)
        self.origin_suffix_input.setToolTip("作为原图加载的文件夹后缀，例如 _contrasted")
        self.mask_suffix_input.setToolTip("作为初始二值 mask 读取的文件夹后缀")
        self.save_suffix_input.setToolTip("精修结果保存文件夹后缀。建议与初始 mask 后缀不同，以免覆盖原始结果。")

        suffix_row.addWidget(QLabel("原图后缀:"))
        suffix_row.addWidget(self.origin_suffix_input)
        suffix_row.addWidget(QLabel("初始 Mask 后缀:"))
        suffix_row.addWidget(self.mask_suffix_input)
        suffix_row.addWidget(QLabel("保存后缀:"))
        suffix_row.addWidget(self.save_suffix_input)
        self.refresh_button = QPushButton("刷新扫描")
        self.refresh_button.clicked.connect(self.refresh_candidates)
        suffix_row.addWidget(self.refresh_button)
        config_layout.addLayout(suffix_row)

        note = QLabel(
            "默认会勾选所有 contrasted 文件夹；初始 Mask 和保存后缀对应的文件夹不存在时，会在创建会话时自动建立为空文件夹。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        config_layout.addWidget(note)
        layout.addWidget(config_group)

        self.summary_label = QLabel("")
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["加入", "数据集", "原图帧", "Mask帧", "已有保存", "源文件夹", "Mask文件夹", "保存文件夹"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        header_view = self.table.horizontalHeader()
        header_view.setMinimumHeight(48)
        header_view.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        header_view.setMinimumSectionSize(90)
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setColumnWidth(0, 120)
        self.table.setColumnWidth(1, 250)
        self.table.setColumnWidth(2, 95)
        self.table.setColumnWidth(3, 105)
        self.table.setColumnWidth(4, 105)
        layout.addWidget(self.table)

        select_row = QHBoxLayout()
        select_all_button = QPushButton("全选可用")
        select_none_button = QPushButton("全不选")
        select_all_button.clicked.connect(lambda: self.set_all_valid_checked(True))
        select_none_button.clicked.connect(lambda: self.set_all_valid_checked(False))
        select_row.addWidget(select_all_button)
        select_row.addWidget(select_none_button)
        select_row.addStretch()
        layout.addLayout(select_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("创建并启动会话")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.refresh_candidates()

    def current_suffixes(self) -> Tuple[str, str, str]:
        return (
            self.origin_suffix_input.text().strip() or "_contrasted",
            self.mask_suffix_input.text().strip() or "_origin_mask_new",
            self.save_suffix_input.text().strip() or "_origin_mask_refined",
        )

    def refresh_candidates(self):
        from core.binary_queue_core import BinaryQueueCore

        origin_suffix, mask_suffix, save_suffix = self.current_suffixes()
        self.scan_config = (origin_suffix, mask_suffix, save_suffix)
        self.datasets = BinaryQueueCore.discover_exports_binary_datasets(
            self.exports_dir,
            origin_suffix=origin_suffix,
            mask_suffix=mask_suffix,
            save_suffix=save_suffix,
            require_mask_dir=False,
        )
        self.populate_table()

    def populate_table(self):
        self.table.setRowCount(len(self.datasets))

        joinable_count = 0
        missing_mask_dir_count = 0
        selected_count = 0
        for row, dataset in enumerate(self.datasets):
            origin_count = int(dataset.get("origin_count", 0))
            mask_count = int(dataset.get("mask_count", 0))
            save_count = int(dataset.get("save_count", 0))
            mask_dir_exists = filesystem_path(dataset.get("mask_dir", "")).is_dir()
            joinable = origin_count > 0
            if joinable:
                joinable_count += 1
                selected_count += 1
            if joinable and not mask_dir_exists:
                missing_mask_dir_count += 1

            check_item = QTableWidgetItem("已加入" if joinable else "不可用")
            check_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            check_item.setData(Qt.ItemDataRole.UserRole, dataset)
            check_item.setData(JOINABLE_ROLE, joinable)
            check_item.setData(SELECTED_ROLE, joinable)
            check_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, check_item)
            checkbox = QCheckBox("已加入")
            checkbox.setChecked(joinable)
            checkbox.setEnabled(joinable)
            checkbox.setStyleSheet(
                "QCheckBox { padding-left: 8px; font-weight: 600; }"
                "QCheckBox::indicator { width: 22px; height: 22px; }"
                "QCheckBox::indicator:checked { background-color: #4caf50; border: 2px solid #b7f7bf; }"
                "QCheckBox::indicator:unchecked { background-color: #2e2f30; border: 2px solid #8a8f94; }"
                "QCheckBox::indicator:disabled { background-color: #444; border: 2px solid #666; }"
            )
            checkbox.toggled.connect(lambda checked, r=row: self.on_join_toggled(r, checked))
            self.table.setCellWidget(row, 0, checkbox)

            mask_folder_text = dataset.get("mask_folder", Path(dataset.get("mask_dir", "")).name)
            if joinable and not mask_dir_exists:
                mask_folder_text += "（将创建）"
            values = [
                dataset.get("dataset_name", ""),
                str(origin_count),
                str(mask_count),
                str(save_count),
                dataset.get("source_folder", Path(dataset.get("origin_dir", "")).name),
                mask_folder_text,
                dataset.get("save_folder", Path(dataset.get("save_dir", "")).name),
            ]
            for col, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if col in (2, 3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if joinable and not mask_dir_exists:
                    item.setToolTip("初始 Mask 文件夹不存在，创建会话时会自动创建空文件夹。")
                if not joinable:
                    item.setToolTip("该文件夹没有可加载的原图帧，不能加入会话。")
                    item.setForeground(Qt.GlobalColor.gray)
                self.table.setItem(row, col, item)

        self.summary_label.setText(
            f"检测到 {len(self.datasets)} 个原图文件夹；可加入 {joinable_count} 个；"
            f"当前默认选择 {selected_count} 个；缺初始 Mask 文件夹 {missing_mask_dir_count} 个（会自动创建空文件夹）。"
        )

    def on_join_toggled(self, row: int, checked: bool):
        item = self.table.item(row, 0)
        if item is None:
            return
        item.setData(SELECTED_ROLE, checked)
        item.setText("已加入" if checked else "未加入")
        widget = self.table.cellWidget(row, 0)
        if isinstance(widget, QCheckBox):
            widget.setText("已加入" if checked else "未加入")

    def set_all_valid_checked(self, checked: bool):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            dataset = item.data(Qt.ItemDataRole.UserRole)
            joinable = int(dataset.get("origin_count", 0)) > 0
            if joinable:
                widget = self.table.cellWidget(row, 0)
                if isinstance(widget, QCheckBox):
                    widget.setChecked(checked)
                else:
                    self.on_join_toggled(row, checked)

    def selected_datasets(self) -> List[Dict]:
        selected = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(SELECTED_ROLE):
                selected.append(item.data(Qt.ItemDataRole.UserRole).copy())
        return selected

    def on_accept(self):
        if self.current_suffixes() != self.scan_config:
            QMessageBox.warning(self, "需要刷新扫描", "后缀设置已修改，请先点击“刷新扫描”再创建会话。")
            return

        selected = self.selected_datasets()
        if not selected:
            QMessageBox.warning(self, "未选择文件夹", "请至少勾选一个可用的 Binary 文件夹。")
            return

        _, mask_suffix, save_suffix = self.current_suffixes()
        if mask_suffix == save_suffix:
            reply = QMessageBox.question(
                self,
                "确认覆盖式会话",
                "初始 Mask 后缀和保存后缀相同，精修会直接写回原 binary 文件夹。\n是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.accept()

    def get_config(self) -> Tuple[List[Dict], str, str, str]:
        origin_suffix, mask_suffix, save_suffix = self.current_suffixes()
        return self.selected_datasets(), origin_suffix, mask_suffix, save_suffix
