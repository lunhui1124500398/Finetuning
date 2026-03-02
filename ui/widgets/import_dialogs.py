from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QGroupBox, QMessageBox, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QLineEdit, QCheckBox,
                             QSpacerItem, QSizePolicy)
from PyQt6.QtCore import Qt
from typing import List, Dict

class ROIBatchImportDialog(QDialog):
    """
    Dialog for reviewing and configuring ROI import parameters.
    Allows user to select which ROIs to import and limit the number of frames.
    """
    def __init__(self, exports_dir: str, rois: List[Dict], main_window=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量导入 ROI")
        self.setMinimumWidth(800)
        self.setMinimumHeight(500)
        
        self.exports_dir = exports_dir
        self.rois = rois
        self.main_window = main_window
        
        # Read from config if available
        self.default_suffix = '_mask_new'
        if self.main_window and hasattr(self.main_window, 'model'):
            self.default_suffix = self.main_window.model.config.get('Scripts', 'default_mask_suffix', fallback='_mask_new')
        
        self.init_ui()
        self.populate_table()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Info Header
        info_label = QLabel(f"<b>来源目录:</b> <br>{self.exports_dir}<br>"
                            f"检测到 {len(self.rois)} 个有效 ROI 目录。")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Table of ROIs
        self.table = QTableWidget(len(self.rois), 5)
        self.table.setHorizontalHeaderLabels([
            "导入", "ROI 名称", "源路径", "可用帧数", "导入前 N 帧"
        ])
        
        # Adjust table columns to show content without truncating too much
        header = self.table.horizontalHeader()
        header.setMinimumHeight(40) # Fix vertical clipping
        header.setMinimumSectionSize(100) # Ensure headers don't get squished
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        
        self.table.setColumnWidth(1, 150) # minimum base width for Name
        self.table.setColumnWidth(2, 250) # minimum base width for source
        
        layout.addWidget(self.table)
        
        # Batch Edit Area
        batch_group = QGroupBox("批量设置")
        batch_layout = QHBoxLayout(batch_group)
        
        batch_layout.addWidget(QLabel("统一设置所有选中行的导入帧数为:"))
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
        
        # Target Suffix Config
        suffix_layout = QHBoxLayout()
        suffix_layout.addWidget(QLabel("后续发回时对应的 Mask 后缀命: "))
        self.suffix_input = QLineEdit(self.default_suffix)
        self.suffix_input.setToolTip("默认将使用这作为最终回写时的文件夹后缀标识，跟随 Settings 里的全局默认值。")
        suffix_layout.addWidget(self.suffix_input)
        suffix_layout.addStretch()
        layout.addLayout(suffix_layout)
        
        # Dialog Buttons
        btn_layout = QHBoxLayout()
        self.btn_import = QPushButton("开始导入并创建工作区")
        self.btn_import.setDefault(True)
        self.btn_cancel = QPushButton("取消")
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_import)
        btn_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(btn_layout)
        
        self.btn_import.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        
    def populate_table(self):
        for row, roi in enumerate(self.rois):
            # 1. 勾选框
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk_item.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, 0, chk_item)
            
            # 2. Name
            name_item = QTableWidgetItem(roi['original_name'])
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 1, name_item)
            
            # 3. Source
            src_item = QTableWidgetItem(roi['source_folder'])
            src_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            src_item.setToolTip(roi['source_folder'])
            self.table.setItem(row, 2, src_item)
            
            # 4. Total frames
            count_item = QTableWidgetItem(str(roi['total_frames']))
            count_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, count_item)
            
            # 5. Limit Input
            limit_input = QLineEdit(str(roi['total_frames']))
            self.table.setCellWidget(row, 4, limit_input)
            
            # Store roi data in the first column for easy retrieval
            chk_item.setData(Qt.ItemDataRole.UserRole, roi)

    def toggle_all(self, state: bool):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            item.setCheckState(Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)
            
    def apply_batch_limit(self):
        limit_text = self.batch_limit_input.text().strip()
        if not limit_text.isdigit():
            QMessageBox.warning(self, "输入无效", "请输入有效的数字作为导入限制。")
            return
            
        limit = int(limit_text)
        
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked:
                # 只有选中的才应用
                roi = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                actual_limit = min(limit, roi['total_frames'])
                limit_widget = self.table.cellWidget(row, 4)
                if isinstance(limit_widget, QLineEdit):
                    limit_widget.setText(str(actual_limit))
                    
    def get_selected_rois(self) -> List[Dict]:
        """
        Returns a list of dicts with selected ROIs, dynamically appending 'selected_frames'.
        """
        selected = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item.checkState() == Qt.CheckState.Checked:
                roi = item.data(Qt.ItemDataRole.UserRole)
                limit_widget = self.table.cellWidget(row, 4)
                
                try:
                    limit = int(limit_widget.text().strip())
                except ValueError:
                    limit = roi['total_frames']
                    
                # safeguard limit
                limit = max(1, min(limit, roi['total_frames']))
                
                # Copy the dict so we don't mutate the original if dialog is reused
                roi_copy = roi.copy()
                roi_copy['selected_frames'] = limit
                selected.append(roi_copy)
                
        return selected

    def get_mask_target_suffix(self) -> str:
        return self.suffix_input.text().strip()
