"""
批量导入 ROI (Batch ROI Import)
-------------------------------
从 MagicImageJ 导出的包含多个 ROI 的总目录中批量导入图像。
此脚本将自动提取符合条件的 Origin 图像，重命名并放入一个 staging 文件夹，供 Finetuning 集中处理。
"""

import os
from PyQt6.QtWidgets import QMessageBox, QProgressDialog, QApplication, QDialog
from PyQt6.QtCore import Qt

# --- Script Metadata ---
SCRIPT_NAME = "1. 批量导入 ROI (创建 Staging)..."
SCRIPT_DESCRIPTION = "从 MagicImageJ 导出目录批量抽取多ROI图像用于二值化"

def run(main_window):
    """
    Entry point for the script.
    
    Args:
        main_window: MainWindow instance.
    """
    from ui.widgets.import_dialogs import ROIBatchImportDialog
    from core.rg_workflow_core import RgWorkflowDataCore
    from PyQt6.QtWidgets import QFileDialog
    
    # 1. 询问用户选择 Exports 目录
    last_path = main_window.model.get_path('original_path') or ""
    start_dir = os.path.dirname(last_path) if last_path else ""
    
    # 获取用户配置的 origin_suffix
    origin_suffix = main_window.model.config.get('Scripts', 'default_origin_suffix', fallback='_origin')
    
    exports_dir = QFileDialog.getExistingDirectory(
        main_window,
        f"选择包含多个 ROI ({origin_suffix}) 的 Exports 总目录",
        start_dir
    )
    
    if not exports_dir:
        return
        
    # 2. 扫描目录
    rois = RgWorkflowDataCore.identify_rois(exports_dir, target_suffix=origin_suffix)
    
    if not rois:
        QMessageBox.warning(main_window, "未发现源数据", f"选定目录下没有发现以 '{origin_suffix}' 结尾的 ROI 文件夹。")
        return
        
    # 3. 弹出窗口选择和配置帧数
    dialog = ROIBatchImportDialog(exports_dir, rois, main_window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
        
    selected_rois = dialog.get_selected_rois()
    mask_target_suffix = dialog.get_mask_target_suffix()
    
    if not selected_rois:
        QMessageBox.warning(main_window, "未选择", "你没有勾选任何需要导入的 ROI。")
        return
        
    # 4. 执行创建 Staging
    total_files = sum(r['selected_frames'] for r in selected_rois)
    progress = QProgressDialog("正在整合所选图像创建临时工作区...", "取消", 0, total_files, main_window)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    
    # Hook into create_staging_environment isn't easily progress-callable 
    # without changing the core method, so we will just show Indeterminate 
    # or a fake progress for now if it's too fast. 
    # Given the core logic is synchronous, we'll just run it.
    progress.setValue(0)
    QApplication.processEvents()
    
    try:
        staging_dir = RgWorkflowDataCore.create_staging_environment(exports_dir, selected_rois, mask_target_suffix)
        progress.setValue(total_files)
    except Exception as e:
        progress.close()
        QMessageBox.critical(main_window, "错误", f"创建临时工作区失败: {e}")
        return
        
    # 5. 更新 Finetuning 工作区
    model = main_window.model
    origin_dir = os.path.join(staging_dir, "origin")
    mask_dir = os.path.join(staging_dir, "mask")
    save_dir = os.path.join(staging_dir, "mask_new")
    
    # Set the new paths in the config
    model.config.set('Paths', 'original_path', origin_dir)
    model.config.set('Paths', 'denoised_path', "")
    model.config.set('Paths', 'mask_path', mask_dir)
    model.config.set('Paths', 'save_path', save_dir)
    
    # Also set default input to original for tools
    model.config.set('Scripts', 'default_input_source', 'mask_path')
    
    # Save config
    with open(model.config_path, 'w', encoding='utf-8') as f:
        model.config.write(f)
        
    # **FIX**: Actually update the file lists in model so images are loaded
    # Instead of calling import_images which relies on UI selectors, use the model directly
    model.update_file_lists(
        original_path=origin_dir,
        denoised_path="",
        mask_path=mask_dir
    )
    
    # Update UI selectors to match the new paths
    main_window.original_path_selector.set_path(origin_dir)
    main_window.denoised_path_selector.set_path("")
    main_window.mask_path_selector.set_path(mask_dir)
    main_window.save_path_selector.set_path(save_dir)
    
    QMessageBox.information(
        main_window,
        "合并导入成功",
        f"成功导入 {len(selected_rois)} 个 ROI，共计 {total_files} 张图像。\n"
        f"当前工作区已自动切换到新建的临时文件夹：\n{os.path.basename(staging_dir)}\n\n"
        "请使用【套索/多边形】工具直接在此处绘制 Mask。\n"
        "完成后，可调用【派发 Mask】脚本写回源目录。"
    )
