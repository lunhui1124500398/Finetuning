"""
批量计算 Rg (质厚衬度)
----------------------
读取 MagicImageJ 导出的目录，针对有 Origin 和对应 Mask 文件夹的 ROI，
自动按名字匹配图像，利用质厚衬度法（Mass-weighted）计算 Rg 值，并输出为 CSV。
"""

import os
from PyQt6.QtWidgets import QMessageBox, QProgressDialog, QApplication, QFileDialog, QDialog
from PyQt6.QtCore import Qt
from pathlib import Path

# --- Script Metadata ---
SCRIPT_NAME = "3. 批量计算 Rg (质厚衬度)..."
SCRIPT_DESCRIPTION = "选择包含源数据和Mask的Exports目录，批量计算每张图片的 Rg 并输出为 CSV。"

def run(main_window):
    """
    Entry point for the script.
    
    Args:
        main_window: MainWindow instance.
    """
    from core.rg_workflow_core import RgWorkflowDataCore
    from ui.widgets.rg_calc_dialogs import RgCalculationDialog
    
    # 1. 询问用户选择 Exports 目录
    last_path = main_window.model.get_path('original_path') or ""
    start_dir = os.path.dirname(last_path) if last_path else ""
    
    exports_dir = QFileDialog.getExistingDirectory(
        main_window,
        "选择进行 Rg 计算的 Exports 总目录",
        start_dir
    )
    
    if not exports_dir:
        return
        
    # 2. 扫描目录寻找 origin 文件夹
    origin_suffix = main_window.model.config.get('Scripts', 'default_origin_suffix', fallback='_origin')
    rois = RgWorkflowDataCore.identify_rois(exports_dir, target_suffix=origin_suffix)
    
    if not rois:
        QMessageBox.warning(main_window, "未发现源数据", f"选定目录下没有发现以 '{origin_suffix}' 结尾的 ROI 文件夹。")
        return
        
    # 3. 弹出窗口选择和配置
    dialog = RgCalculationDialog(exports_dir, rois, main_window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
        
    selected_rois, mask_suffix, csv_path = dialog.get_config()
    
    if not selected_rois:
        QMessageBox.warning(main_window, "未选择", "你没有勾选任何需要计算的 ROI。")
        return
        
    # 4. 构建用于计算的数据结构
    exports_path = Path(exports_dir)
    rois_to_calculate = []
    
    for roi in selected_rois:
        source_folder = roi['source_folder']
        origin_dir = exports_path / source_folder
        
        # Determine mask dir
        if source_folder.endswith(origin_suffix):
            target_folder_name = source_folder[:-len(origin_suffix)] + mask_suffix
        else:
            target_folder_name = source_folder + mask_suffix
            
        mask_dir = exports_path / target_folder_name
        
        rois_to_calculate.append({
            "roi_name": roi['original_name'],
            "origin_dir": str(origin_dir),
            "mask_dir": str(mask_dir),
            "max_frames": roi['max_frames'],
            "csv_suffix": roi.get('csv_suffix', '')
        })
        
    # 5. 执行计算
    total_files = sum(r['max_frames'] for r in rois_to_calculate)
    # This is a bit fake progress because calculate_rg_for_rois is monolithic, 
    # but we display a dialog to inform the user it's working.
    progress = QProgressDialog("正在计算 Rg 值，请稍候...", "取消", 0, 0, main_window)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.show()
    QApplication.processEvents()
    
    try:
        results = RgWorkflowDataCore.calculate_rg_for_rois(rois_to_calculate, csv_path)
        progress.close()
    except Exception as e:
        progress.close()
        QMessageBox.critical(main_window, "计算失败", f"计算 Rg 过程中发生错误:\n{e}")
        return
        
    # Show summary
    success_count = sum(1 for r in results if str(r["Rg_Value"]) != "nan" and not str(r["Image_Name"]).startswith("ERROR"))
    error_count = len(results) - success_count
    
    QMessageBox.information(
        main_window,
        "计算完成",
        f"Rg 计算已完成！\n\n"
        f"成功计算: {success_count} 张\n"
        f"失败/缺失: {error_count} 张\n\n"
        f"结果已保存至:\n{csv_path}"
    )
