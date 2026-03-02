"""
派发 Mask (回写源目录)
----------------------
将当前工作区画好的 Mask 图像，根据清单自动分发回最初的 ROI 原始目录中。
这是批量扣图工作流的最后一步。
"""

import os
from PyQt6.QtWidgets import QMessageBox, QProgressDialog, QApplication, QInputDialog
from PyQt6.QtCore import Qt

# --- Script Metadata ---
SCRIPT_NAME = "2. 派发 Mask (写回原目录)..."
SCRIPT_DESCRIPTION = "读取当前临时工作区的清单，将处理好的 Mask 写回各个 ROI 的原目录"

def run(main_window):
    """
    Entry point for the script.
    
    Args:
        main_window: MainWindow instance.
    """
    from core.rg_workflow_core import RgWorkflowDataCore
    from PyQt6.QtWidgets import QFileDialog
    
    model = main_window.model
    current_dir = model.get_path('original_path')
    save_dir = model.get_path('save_path')
    mask_dir = model.get_path('mask_path')
    
    default_source = save_dir if (save_dir and os.path.exists(save_dir)) else (mask_dir or current_dir)
    
    if not current_dir or not os.path.exists(current_dir):
        QMessageBox.warning(main_window, "工作区无效", "当前没有设置有效的工作区路径。")
        return
        
    # In newer versions, original_path points to staging_dir/origin
    from pathlib import Path
    p_current = Path(current_dir)
    if p_current.name == "origin":
        staging_dir = str(p_current.parent)
    else:
        staging_dir = current_dir
        
    if not RgWorkflowDataCore.is_staging_directory(staging_dir):
        QMessageBox.warning(
            main_window, 
            "非 Staging 目录", 
            "当前 original_path 目录不存在 manifest.json 清单文件。\n请确认当前是在使用【导入 ROI】功能创建的工作区中！"
        )
        return
        
    try:
        manifest = RgWorkflowDataCore.read_manifest(staging_dir)
    except Exception as e:
        QMessageBox.critical(main_window, "读取清单失败", f"无法解析清单文件: {e}")
        return
        
    rois_count = len(manifest.get('rois', []))
    config_suffix = model.config.get('Scripts', 'default_mask_suffix', fallback='_mask_new')
    default_suffix = manifest.get('mask_target_suffix', config_suffix)
    
    # Let user confirm or change the target suffix
    reply, ok = QInputDialog.getText(
        main_window,
        "确认回写目标后缀",
        f"即将根据清单分发给 {rois_count} 个 ROI。\n\n"
        f"请确认回写到各 ROI 文件夹的后缀（如果是新路径将自动创建）:",
        text=default_suffix
    )
    
    if not ok:
        return
        
    target_suffix = reply.strip()
    if not target_suffix:
        QMessageBox.warning(main_window, "输入无效", "目标后缀不能为空！")
        return
        
    source_dir = QFileDialog.getExistingDirectory(
        main_window,
        "选择包含全量 Mask 的子目录 (例如 mask_new)",
        default_source
    )
    if not source_dir:
        return
        
    # Execute writeback
    progress = QProgressDialog("正在将 Mask 图像分发回源目录...", "取消", 0, 0, main_window)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setValue(0)
    QApplication.processEvents()
    
    try:
        summary = RgWorkflowDataCore.execute_mask_writeback(
            staging_dir=staging_dir, 
            mask_dir=source_dir, 
            target_suffix_override=target_suffix
        )
        progress.close()
    except Exception as e:
        progress.close()
        QMessageBox.critical(main_window, "执行失败", f"回写过程中发生错误:\n{e}")
        return
        
    # Show summary
    if summary["errors"]:
        error_msg = "\n".join(summary["errors"][:5])
        if len(summary["errors"]) > 5:
            error_msg += f"\n... 以及其他 {len(summary['errors']) - 5} 个错误"
            
        QMessageBox.warning(
            main_window,
            "部分完成",
            f"回写完成，但发生了一些错误：\n"
            f"已写入文件数: {summary['files_written']}\n"
            f"错误详情:\n{error_msg}"
        )
    else:
        QMessageBox.information(
            main_window,
            "回写成功",
            f"成功将 Mask 图像写回！\n\n"
            f"目标 ROI 数: {summary['rois_processed']}\n"
            f"共计复制文件数: {summary['files_written']}"
        )
