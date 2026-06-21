from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.semi_auto_mask_tools import (
    build_frame_paths,
    clear_all_explicit_seeds,
    list_seed_candidates,
    resolve_seed_indices,
    set_explicit_seed,
)


SCRIPT_NAME = "Seed 管理..."
SCRIPT_DESCRIPTION = "查看、手动指定、取消当前数据集的 seed。"


def _refresh_views(main_window) -> None:
    if hasattr(main_window, "refresh_seed_cache"):
        main_window.refresh_seed_cache()
    model = main_window.model
    if model.current_index >= 0:
        main_window.canvas.load_image(model.current_index)
        main_window.preview_panel.update_previews(model.current_index)
    if hasattr(main_window, "update_seed_status_label"):
        main_window.update_seed_status_label()


class SeedManagerDialog(QDialog):
    def __init__(self, main_window, frames, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.frames = frames

        self.setWindowTitle("Seed 管理")
        self.setMinimumSize(900, 700)
        self.setModal(False)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setMinimumHeight(96)
        self.summary_label.setStyleSheet("padding: 10px 12px;")

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["手动指定", "帧号", "文件名", "改动像素", "来源"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.horizontalHeader().setMinimumHeight(44)
        self.table.itemDoubleClicked.connect(self._jump_to_selected_row)

        self.btn_mark_current = QPushButton("当前帧设为 Seed")
        self.btn_unmark_current = QPushButton("当前帧取消 Seed")
        self.btn_mark_selected = QPushButton("选中行设为 Seed")
        self.btn_unmark_selected = QPushButton("选中行取消 Seed")
        self.btn_jump = QPushButton("跳转到选中帧")
        self.btn_refresh = QPushButton("刷新列表")
        self.btn_clear_all = QPushButton("清空所有手动指定 Seed")
        self.btn_close = QPushButton("关闭")

        self.range_start_spin = QSpinBox()
        self.range_start_spin.setRange(1, max(1, len(frames)))
        self.range_start_spin.setValue(1)
        self.range_end_spin = QSpinBox()
        self.range_end_spin.setRange(1, max(1, len(frames)))
        self.range_end_spin.setValue(max(1, len(frames)))
        self.range_step_spin = QSpinBox()
        self.range_step_spin.setRange(1, 9999)
        self.range_step_spin.setValue(1)
        self.btn_mark_range = QPushButton("范围设为 Seed")
        self.btn_unmark_range = QPushButton("范围取消 Seed")

        self.btn_mark_current.clicked.connect(self._mark_current)
        self.btn_unmark_current.clicked.connect(self._unmark_current)
        self.btn_mark_selected.clicked.connect(lambda: self._mark_selected(True))
        self.btn_unmark_selected.clicked.connect(lambda: self._mark_selected(False))
        self.btn_jump.clicked.connect(self._jump_to_selected_row)
        self.btn_refresh.clicked.connect(self.refresh_table)
        self.btn_clear_all.clicked.connect(self._clear_all)
        self.btn_close.clicked.connect(self.close)
        self.btn_mark_range.clicked.connect(lambda: self._mark_range(True))
        self.btn_unmark_range.clicked.connect(lambda: self._mark_range(False))

        quick_buttons = QHBoxLayout()
        quick_buttons.addWidget(self.btn_mark_current)
        quick_buttons.addWidget(self.btn_unmark_current)
        quick_buttons.addWidget(self.btn_mark_selected)
        quick_buttons.addWidget(self.btn_unmark_selected)

        range_group = QGroupBox("批量设 Seed")
        range_form = QFormLayout()
        range_form.addRow("起始帧:", self.range_start_spin)
        range_form.addRow("结束帧:", self.range_end_spin)
        range_form.addRow("步长:", self.range_step_spin)
        range_actions = QHBoxLayout()
        range_actions.addWidget(self.btn_mark_range)
        range_actions.addWidget(self.btn_unmark_range)
        range_layout = QVBoxLayout(range_group)
        range_layout.addLayout(range_form)
        range_layout.addLayout(range_actions)

        tools_layout = QHBoxLayout()
        tools_layout.addWidget(range_group, 2)

        bottom_buttons = QHBoxLayout()
        bottom_buttons.addWidget(self.btn_jump)
        bottom_buttons.addWidget(self.btn_refresh)
        bottom_buttons.addWidget(self.btn_clear_all)
        bottom_buttons.addStretch()
        bottom_buttons.addWidget(self.btn_close)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addLayout(quick_buttons)
        layout.addLayout(tools_layout)
        layout.addWidget(self.table)
        layout.addLayout(bottom_buttons)

        self.refresh_table()

    def _current_frame(self):
        index = self.main_window.model.current_index
        if index < 0 or index >= len(self.frames):
            return None
        return self.frames[index]

    def _save_current_if_needed(self) -> bool:
        model = self.main_window.model
        if model.current_index < 0:
            return False
        return self.main_window.canvas.save_current_mask()

    def _mark_current(self) -> None:
        frame = self._current_frame()
        if frame is None:
            QMessageBox.warning(self, "没有当前帧", "请先加载一个数据集并定位到需要设置的帧。")
            return
        if not self._save_current_if_needed():
            return
        set_explicit_seed(frame.save_path, True)
        self.refresh_table(select_index=frame.index)

    def _unmark_current(self) -> None:
        frame = self._current_frame()
        if frame is None or not frame.has_saved_mask:
            QMessageBox.warning(self, "没有可取消的 Seed", "当前帧还没有保存到 mask_new。")
            return
        set_explicit_seed(frame.save_path, False)
        self.refresh_table(select_index=frame.index)

    def _selected_frame_indices(self) -> list[int]:
        rows = sorted({item.row() for item in self.table.selectedItems()})
        indices: list[int] = []
        for row in rows:
            item = self.table.item(row, 1)
            if item is None:
                continue
            indices.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return indices

    def _mark_selected(self, enabled: bool) -> None:
        indices = self._selected_frame_indices()
        if not indices:
            QMessageBox.information(self, "未选中帧", "请先在列表中选中至少一行。支持按 Ctrl 或 Shift 多选。")
            return
        changed = 0
        for index in indices:
            frame = self.frames[index]
            if frame.has_saved_mask:
                set_explicit_seed(frame.save_path, enabled)
                changed += 1
        self.refresh_table(select_index=indices[0])
        action = "设为" if enabled else "取消"
        QMessageBox.information(self, "批量完成", f"已对 {changed} 张已保存帧执行“{action} Seed”。")

    def _mark_range(self, enabled: bool) -> None:
        start_index = self.range_start_spin.value() - 1
        end_index = self.range_end_spin.value() - 1
        step = self.range_step_spin.value()
        if start_index > end_index:
            QMessageBox.warning(self, "范围错误", "起始帧不能大于结束帧。")
            return
        changed = 0
        first_changed = None
        for index in range(start_index, end_index + 1, step):
            frame = self.frames[index]
            if frame.has_saved_mask:
                set_explicit_seed(frame.save_path, enabled)
                changed += 1
                if first_changed is None:
                    first_changed = index
        self.refresh_table(select_index=first_changed)
        action = "设为" if enabled else "取消"
        QMessageBox.information(
            self,
            "范围处理完成",
            f"范围 {start_index + 1}-{end_index + 1}，步长 {step}。\n已对 {changed} 张已保存帧执行“{action} Seed”。",
        )

    def _jump_to_selected_row(self) -> None:
        indices = self._selected_frame_indices()
        if not indices:
            return
        self.main_window.canvas.save_current_mask()
        target_index = indices[0]
        self.main_window.model.set_current_index(target_index)
        _refresh_views(self.main_window)
        self.refresh_table(select_index=target_index)

    def _clear_all(self) -> None:
        if QMessageBox.question(self, "确认清空", "要清空当前数据集里所有手动指定的 Seed 吗？") != QMessageBox.StandardButton.Yes:
            return
        cleared = clear_all_explicit_seeds(self.frames[0].save_path.parent)
        self.refresh_table()
        QMessageBox.information(self, "清空完成", f"已清空 {cleared} 个手动指定 Seed。")

    def refresh_table(self, select_index: int | None = None) -> None:
        if hasattr(self.main_window, "refresh_seed_cache"):
            self.main_window.refresh_seed_cache()
        if hasattr(self.main_window, "update_seed_status_label"):
            self.main_window.update_seed_status_label()
        if self.main_window.model.current_index >= 0:
            self.main_window.preview_panel.update_previews(self.main_window.model.current_index)
        rows = list_seed_candidates(self.frames, min_changed_pixels=1)
        resolved_indices, seed_mode = resolve_seed_indices(self.frames, min_changed_pixels=1)
        manual_count = sum(1 for row in rows if row["explicit_seed"])
        mode_text = {
            "explicit": "当前脚本会优先使用你手动指定的 Seed。",
            "edited": "当前没有手动指定 Seed，脚本会自动使用你手修并保存、且与原 mask 有差异的帧。",
            "saved": "当前没有手动指定 Seed，也没有明显改动帧，脚本会自动使用已保存帧。",
        }.get(seed_mode, "当前脚本会自动选择 Seed。")

        current_index = self.main_window.model.current_index
        filename_text = "N/A"
        if 0 <= current_index < len(self.frames):
            filename_text = self.frames[current_index].frame_name

        self.summary_label.setText(
            f"当前帧: {current_index + 1 if current_index >= 0 else 'N/A'}    "
            f"候选帧数: {len(rows)}    手动指定 Seed 数: {manual_count}    实际生效 Seed 数: {len(resolved_indices)}"
            f"\n{mode_text}"
            "\n说明: 不手动指定也可以，脚本默认仍会自动使用你手修并保存过的帧。手动指定只是为了让你明确告诉脚本“优先就用这些”。"
            f"\n当前文件: {filename_text}"
        )

        self.table.setRowCount(len(rows))
        self.table.clearContents()
        for row_index, row in enumerate(rows):
            manual_item = QTableWidgetItem("是" if row["explicit_seed"] else "")
            manual_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            index_item = QTableWidgetItem(str(int(row["index"]) + 1))
            index_item.setData(Qt.ItemDataRole.UserRole, int(row["index"]))
            name_item = QTableWidgetItem(str(row["frame_name"]))
            changed_item = QTableWidgetItem(str(int(row["changed_pixels"])))
            source_item = QTableWidgetItem("手工已修")

            for item in (manual_item, index_item, name_item, changed_item, source_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.table.setItem(row_index, 0, manual_item)
            self.table.setItem(row_index, 1, index_item)
            self.table.setItem(row_index, 2, name_item)
            self.table.setItem(row_index, 3, changed_item)
            self.table.setItem(row_index, 4, source_item)

            if select_index is not None and int(row["index"]) == select_index:
                self.table.selectRow(row_index)

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)


def run(main_window):
    model = main_window.model
    save_dir = model.get_path("save_path")
    if not save_dir:
        QMessageBox.warning(main_window, "缺少保存路径", "请先加载当前数据集，并确保 save_path 指向 mask_new。")
        return

    if model.current_index >= 0:
        main_window.canvas.save_current_mask()

    frames = build_frame_paths(model._original_files, model._mask_files, save_dir)
    if not frames:
        QMessageBox.warning(main_window, "没有图像", "当前数据集没有可处理的帧。")
        return

    dialog = SeedManagerDialog(main_window=main_window, frames=frames, parent=main_window)
    main_window._seed_manager_dialog = dialog
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
