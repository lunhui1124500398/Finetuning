import os
import json
import shutil
import csv
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import numpy as np
import cv2

class RgWorkflowDataCore:
    """
    Core data logic for the Rg workflow integration between MagicImageJ and Finetuning.
    Handles the creation of staging directories, manifest files, and mask writeback.
    """
    
    @staticmethod
    def identify_rois(exports_dir: str, target_suffix: str = '_origin') -> List[Dict]:
        """
        Scans an Exports directory and identifies all ROI folders ending with the target_suffix.
        Returns a list of dicts with ROI information.
        """
        exports_path = Path(exports_dir)
        rois = []
        
        if not exports_path.is_dir():
            return rois
            
        roi_dirs = sorted([d for d in exports_path.iterdir() if d.is_dir() and d.name.endswith(target_suffix)])
        
        for i, roi_dir in enumerate(roi_dirs):
            # Try to extract the NP suffix or just use a fallback name
            original_name = f"NP{i+1}"
            if "_NP" in roi_dir.name:
                parts = roi_dir.name.split("_NP")
                if len(parts) > 1:
                    num_part = parts[1].split("_")[0]
                    original_name = f"NP{num_part}"
                    
            files = sorted([f.name for f in roi_dir.iterdir() if f.is_file() and f.suffix.lower() in ['.png', '.tif', '.tiff', '.jpg']])
            
            rois.append({
                "roi_id": f"ROI{i+1:02d}",
                "source_folder": roi_dir.name,
                "original_name": original_name,
                "total_frames": len(files),
                "available_files": files
            })
            
        return rois

    @staticmethod
    def create_staging_environment(exports_dir: str, selected_rois: List[Dict], mask_target_suffix: str = "_mask_new") -> str:
        """
        Creates a staging environment from the selected ROIs and their frame counts.
        selected_rois should be a list of dicts, each containing:
        - roi_id: str
        - source_folder: str
        - original_name: str
        - selected_frames: int (how many frames to copy, starting from 0)
        - available_files: list of str (all valid image filenames)
        """
        exports_path = Path(exports_dir)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        staging_dir_name = f"_staging_{timestamp}"
        staging_path = exports_path / staging_dir_name
        
        origin_path = staging_path / "origin"
        mask_path = staging_path / "mask"
        mask_new_path = staging_path / "mask_new"
        
        # Create staging subdirs
        origin_path.mkdir(parents=True, exist_ok=True)
        mask_path.mkdir(parents=True, exist_ok=True)
        mask_new_path.mkdir(parents=True, exist_ok=True)
        
        manifest_rois = []
        
        for roi in selected_rois:
            source_dir = exports_path / roi['source_folder']
            files_to_copy = roi['available_files'][:roi['selected_frames']]
            
            staged_files = []
            
            for i, filename in enumerate(files_to_copy):
                # source file
                src_file = source_dir / filename
                
                # generate staged filename: ROIxx_yyyyyy.ext
                ext = src_file.suffix
                staged_filename = f"{roi['roi_id']}_{i:06d}{ext}"
                staged_file = origin_path / staged_filename
                
                # Copy file
                shutil.copy2(src_file, staged_file)
                
                staged_files.append({
                    "staged_name": staged_filename,
                    "original_name": filename
                })
                
            manifest_rois.append({
                "roi_id": roi['roi_id'],
                "source_folder": roi['source_folder'],
                "original_name": roi['original_name'],
                "frame_count": len(files_to_copy),
                "files": staged_files
            })
            
        manifest = {
            "source_dir": str(exports_path.absolute()),
            "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mask_target_suffix": mask_target_suffix,
            "rois": manifest_rois
        }
        
        manifest_path = staging_path / "manifest.json"
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            
        return str(staging_path)

    @staticmethod
    def is_staging_directory(dir_path: str) -> bool:
        """Checks if a directory is a valid staging directory."""
        manifest_path = Path(dir_path) / "manifest.json"
        return manifest_path.is_file()

    @staticmethod
    def read_manifest(dir_path: str) -> Dict:
        """Reads the manifest file from a staging directory."""
        manifest_path = Path(dir_path) / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Manifest not found in {dir_path}")
            
        with open(manifest_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def execute_mask_writeback(staging_dir: str, mask_dir: str = None, target_suffix_override: str = None) -> Dict:
        """
        Reads the manifest and copies masks back to their original ROI folders.
        If mask_dir is None, assumes masks are in staging_dir/save_path (from model).
        Returns a dict summarizing the operation.
        """
        staging_path = Path(staging_dir)
        manifest = RgWorkflowDataCore.read_manifest(staging_dir)
        
        # Determine source dir for masks (where user drew them)
        mask_source_dir = Path(mask_dir) if mask_dir else staging_path
        
        exports_dir = Path(manifest["source_dir"])
        target_suffix = target_suffix_override if target_suffix_override else manifest.get("mask_target_suffix", "_mask_new")
        
        summary = {
            "total_rois": len(manifest["rois"]),
            "rois_processed": 0,
            "files_written": 0,
            "errors": []
        }
        
        for roi in manifest["rois"]:
            
            # The original target dir name e.g., 20260301_Dataset3_CRY2_NP1_origin
            # We replace '_origin' with the target_suffix
            source_folder = roi["source_folder"]
            if source_folder.endswith("_origin"):
                target_folder_name = source_folder[:-7] + target_suffix
            else:
                target_folder_name = source_folder + target_suffix
                
            target_dir = exports_dir / target_folder_name
            
            # Ensure target directory exists
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                summary["errors"].append(f"Failed to create directory {target_dir}: {str(e)}")
                continue
                
            summary["rois_processed"] += 1
            
            for file_mapping in roi["files"]:
                staged_name = file_mapping["staged_name"]
                original_name = file_mapping["original_name"]
                
                # Check if mask exists in source
                mask_file = mask_source_dir / staged_name
                if mask_file.is_file():
                    target_file = target_dir / original_name
                    try:
                        shutil.copy2(mask_file, target_file)
                        summary["files_written"] += 1
                    except Exception as e:
                        summary["errors"].append(f"Failed to copy {staged_name} to {target_file}: {str(e)}")
                        
        return summary

    @staticmethod
    def calculate_rg_for_rois(rois_to_calculate: List[Dict], output_csv: str) -> List[Dict]:
        """
        Calculates the Mass-weighted Rg for a list of ROIs.
        rois_to_calculate is a list of dicts, each containing:
        - roi_name: str (e.g. NP1)
        - origin_dir: str
        - mask_dir: str
        - max_frames: Optional[int]
        
        Returns a list of calculated results and writes them to the specified CSV.
        """
        all_results = []
        
        for roi in rois_to_calculate:
            roi_name = roi["roi_name"]
            origin_dir = Path(roi["origin_dir"])
            mask_dir = Path(roi["mask_dir"])
            max_frames = roi.get("max_frames")
            
            roi_results = []
            
            if not origin_dir.is_dir() or not mask_dir.is_dir():
                all_results.append({"Image_Name": f"ERROR: Missing folders for {roi_name}", "Rg_Value": np.nan})
                continue
                
            origin_files = sorted([f.name for f in origin_dir.iterdir() if f.is_file() and f.suffix.lower() in ['.png', '.jpg', '.tif'] and not f.name.startswith('.')])
            mask_files = sorted([f.name for f in mask_dir.iterdir() if f.is_file() and f.suffix.lower() in ['.png', '.jpg', '.tif'] and not f.name.startswith('.')])
            
            count = min(len(origin_files), len(mask_files))
            if max_frames is not None:
                count = min(count, max_frames)
                
            if count == 0:
                all_results.append({"Image_Name": f"ERROR: No valid images for {roi_name}", "Rg_Value": np.nan})
                continue
                
            for i in range(count):
                f_org = origin_files[i]
                f_msk = mask_files[i]
                
                path_org = str(origin_dir / f_org)
                path_msk = str(mask_dir / f_msk)
                
                rg = RgWorkflowDataCore._calculate_single_rg(path_org, path_msk)
                
                if rg is not None:
                    res_dict = {"Image_Name": f"{roi_name}_{f_org}", "Rg_Value": rg}
                    all_results.append(res_dict)
                    roi_results.append({"Image_Name": f_org, "Rg_Value": rg})
                else:
                    res_dict = {"Image_Name": f"{roi_name}_{f_org}", "Rg_Value": np.nan}
                    all_results.append(res_dict)
                    roi_results.append({"Image_Name": f_org, "Rg_Value": np.nan})
                    
            # 顺便在该 ROI 的 origin 目录的上一级(Exports)生成该单独 ROI 结果
            if roi_results and output_csv:
                output_path = Path(output_csv)
                # output_csv e.g. /path/to/Exports/rg_results.csv
                # Individual csv e.g. /path/to/Exports/Rg_Results_NP1.csv
                csv_suffix = roi.get("csv_suffix", "")
                indiv_csv = output_path.parent / f"Rg_Results_{roi_name}{csv_suffix}.csv"
                with open(indiv_csv, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=["Image_Name", "Rg_Value"])
                    writer.writeheader()
                    writer.writerows(roi_results)
                    
        # Write the combined master CSV
        if all_results and output_csv:
            with open(output_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=["Image_Name", "Rg_Value"])
                writer.writeheader()
                writer.writerows(all_results)
                
        return all_results

    @staticmethod
    def _calculate_single_rg(origin_path: str, mask_path: str) -> Optional[float]:
        """核心Rg计算逻辑 (Mass-weighted) - adapted from Rg_Calc_GUI.py"""
        try:
            # 读取 Mask
            binary_img = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
            if binary_img is None: return None
            # 自动阈值化，确保非0即255
            _, binary_thresh = cv2.threshold(binary_img, 127, 255, cv2.THRESH_BINARY)

            # 获取粒子坐标
            y_idx, x_idx = np.where(binary_thresh == 255)
            if len(x_idx) == 0: return None # Mask是全黑的

            # 计算几何中心
            x_centroid = np.mean(x_idx)
            y_centroid = np.mean(y_idx)

            # 读取 Origin
            origin_img = cv2.imread(origin_path, cv2.IMREAD_GRAYSCALE)
            if origin_img is None: return None

            # 检查尺寸是否匹配
            if origin_img.shape != binary_img.shape:
                return None

            # --- 物理参数计算 ---
            # 1. 计算背景底噪 (利用Mask的黑色区域)
            background_mask = (binary_thresh == 0)
            background_pixels = origin_img[background_mask]
            
            # 如果背景像素太少，就取整张图的某个特定值（防止除零等极端情况），这里沿用逻辑
            bg_mean = np.mean(background_pixels) if background_pixels.size > 0 else 0

            # 2. 提取粒子区域并计算"质量"
            # 质量 = 255 - (原始灰度 - 背景均值)
            # 也就是：越黑的地方(灰度低)，质量越大
            particle_mask = (binary_thresh == 255)
            particle_pixels = origin_img[particle_mask]
            
            # 转换为 float 计算以防溢出
            real_grays = particle_pixels.astype(float) - bg_mean
            masses = 255 - real_grays
            
            # 简单校验质量是否有效 (避免全白图导致总质量为负或0)
            total_mass = np.sum(masses)
            if total_mass <= 0:
                return None

            # 3. 计算 Rg
            # 对应像素的坐标
            ys, xs = np.where(particle_mask)
            dx = xs - x_centroid
            dy = ys - y_centroid
            
            # Rg 公式: sqrt( sum(m*r^2) / sum(m) )
            sum_numerator = np.sum(masses * (dx ** 2 + dy ** 2))
            rg = np.sqrt(sum_numerator / total_mass)

            return round(rg, 2)

        except Exception as e:
            print(f"Error processing {os.path.basename(origin_path)}: {e}")
            return None
