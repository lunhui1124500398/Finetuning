from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QGroupBox, QMessageBox, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QLineEdit, QFileDialog,
                             QCheckBox, QSpacerItem, QSizePolicy)
from PyQt6.QtCore import Qt
from typing import List, Dict, Tuple
from pathlib import Path

class RgCalculationDialog(QDialog):
    def __init__(self, exports_dir: str, rois: List[Dict], main_window=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量计算 Rg (质厚衬度)")
        self.setMinimumWidth(800)
        self.setMinimumHeight(600)
        
        self.exports_dir = exports_dir
        self.rois = rois
        self.main_window = main_window
        
        # Read from config if available. Default aligns with the pipeline standard
        # refined-mask suffix (_mask_refined); the writeback step produces that name.
        self.default_suffix = '_mask_refined'
        if self.main_window and hasattr(self.main_window, 'model'):
            self.default_suffix = self.main_window.model.config.get('Scripts', 'default_mask_suffix', fallback='_mask_refined')
        
        self.init_ui()
        self.populate_table()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Info Header
        info_label = QLabel(f"<b>来源目录:</b> {self.exports_dir}<br>"
                            f"检测到 {len(self.rois)} 个有效 ROI 目录。")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Config Area
        config_group = QGroupBox("全局配置")
        config_layout = QVBoxLayout(config_group)
        
        # Mask suffix selection
        suffix_layout = QHBoxLayout()
        suffix_layout.addWidget(QLabel("对应的 Mask 文件夹后缀: "))
        self.suffix_input = QLineEdit(self.default_suffix)
        self.suffix_input.setToolTip("程序将把源目录配置的具体后缀(如 _origin) 替换为此后缀来寻找对应 Mask。")
        suffix_layout.addWidget(self.suffix_input)
        suffix_layout.addStretch()
        config_layout.addLayout(suffix_layout)
        
        # CSV output
        csv_layout = QHBoxLayout()
        csv_layout.addWidget(QLabel("汇总 CSV 路径: "))
        self.csv_path_input = QLineEdit(str(Path(self.exports_dir) / "rg_results.csv"))
        btn_browse_csv = QPushButton("浏览...")
        btn_browse_csv.clicked.connect(self.browse_csv_path)
        csv_layout.addWidget(self.csv_path_input)
        csv_layout.addWidget(btn_browse_csv)
        config_layout.addLayout(csv_layout)
        
        # Single ROI CSV suffix
        indiv_csv_layout = QHBoxLayout()
        indiv_csv_layout.addWidget(QLabel("单 ROI 结果 CSV 后缀: "))
        self.indiv_csv_suffix_input = QLineEdit("")
        self.indiv_csv_suffix_input.setPlaceholderText("例如: _v2")
        self.indiv_csv_suffix_input.setToolTip("为每个 ROI 单独生成的 CSV 添加名称后缀，例如填写 _v2 将生成 Rg_Results_NP1_v2.csv")
        indiv_csv_layout.addWidget(self.indiv_csv_suffix_input)
        indiv_csv_layout.addStretch()
        config_layout.addLayout(indiv_csv_layout)
        
        layout.addWidget(config_group)
        
        # Table of ROIs
        self.table = QTableWidget(len(self.rois), 5)
        self.table.setHorizontalHeaderLabels([
            "选择", "ROI 名称", "源目录", "可用帧数", "计算前 N 帧"
        ])
        
        header = self.table.horizontalHeader()
        header.setMinimumHeight(40)
        header.setMinimumSectionSize(100)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 250)
        
        layout.addWidget(self.table)
        
        # Batch Edit Area
        batch_group = QGroupBox("批量设置")
        batch_layout = QHBoxLayout(batch_group)
        
        batch_layout.addWidget(QLabel("统一设置所有选中行的计算帧数为:"))
        self.batch_limit_input = QLineEdit()
        self.batch_limit_input.setPlaceholderText("例如: 100")
        self.batch_limit_input.setMaximumWidth(60)
        batch_layout.addWidget(self.batch_limit_input)
        
        btn_apply_batch = QPushButton("应用")
        btn_apply_batch.clicked.connect(self.apply_batch_limit)
        batch_layout.addWidget(btn_apply_batch)
        
        batch_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        
        btn_select_all = QPushButton("全选")
        btn_select_all.clicked.connect(lambda: self.toggle_all(True))
        btn_deselect_all = QPushButton("全不选")
        btn_deselect_all.clicked.connect(lambda: self.toggle_all(False))
        batch_layout.addWidget(btn_select_all)
        batch_layout.addWidget(btn_deselect_all)
        
        layout.addWidget(batch_group)
        
        # Dialog Buttons
        btn_layout = QHBoxLayout()
        self.btn_calc = QPushButton("开始计算")
        self.btn_calc.setDefault(True)
        self.btn_cancel = QPushButton("取消")
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_calc)
        btn_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(btn_layout)
        
        self.btn_calc.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        
    def browse_csv_path(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "选择 CSV 保存路径", self.csv_path_input.text(), "CSV Files (*.csv)"
        )
        if path:
            self.csv_path_input.setText(path)
            
    def populate_table(self):
        for row, roi in enumerate(self.rois):
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk_item.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, 0, chk_item)
            
            name_item = QTableWidgetItem(roi['original_name'])
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 1, name_item)
            
            src_item = QTableWidgetItem(roi['source_folder'])
            src_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            src_item.setToolTip(roi['source_folder'])
            self.table.setItem(row, 2, src_item)
            
            count_item = QTableWidgetItem(str(roi['total_frames']))
            count_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, count_item)
            
            limit_input = QLineEdit(str(roi['total_frames']))
            self.table.setCellWidget(row, 4, limit_input)
            
            chk_item.setData(Qt.ItemDataRole.UserRole, roi)

    def toggle_all(self, state: bool):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            item.setCheckState(Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)

    def apply_batch_limit(self):
        limit_text = self.batch_limit_input.text().strip()
        if not limit_text.isdigit():
            QMessageBox.warning(self, "输入无效", "请输入有效的数字作为计算限制。")
            return
            
        limit = int(limit_text)
        
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked:
                roi = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                actual_limit = min(limit, roi['total_frames'])
                limit_widget = self.table.cellWidget(row, 4)
                if isinstance(limit_widget, QLineEdit):
                    limit_widget.setText(str(actual_limit))
            
    def get_config(self) -> Tuple[List[Dict], str, str]:
        """
        Returns:
            (List of selected ROI dicts, mask_suffix, csv_path)
            The ROI dicts will contain 'max_frames'
        """
        selected = []
        mask_suffix = self.suffix_input.text().strip()
        csv_path = self.csv_path_input.text().strip()
        indiv_csv_suffix = self.indiv_csv_suffix_input.text().strip()
        
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item.checkState() == Qt.CheckState.Checked:
                roi = item.data(Qt.ItemDataRole.UserRole)
                limit_widget = self.table.cellWidget(row, 4)
                
                try:
                    limit = int(limit_widget.text().strip())
                except ValueError:
                    limit = roi['total_frames']
                    
                roi_copy = roi.copy()
                roi_copy['max_frames'] = limit
                roi_copy['csv_suffix'] = indiv_csv_suffix
                selected.append(roi_copy)
                
        return selected, mask_suffix, csv_path
