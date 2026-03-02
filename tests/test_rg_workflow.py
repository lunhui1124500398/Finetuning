import os
import shutil
import json
import numpy as np
import cv2
from pathlib import Path
import sys

# Add Finetuning path to sys.path
sys.path.append(str(Path(__file__).parent.parent))
from core.rg_workflow_core import RgWorkflowDataCore

def setup_dummy_exports_dir(tmp_path):
    """
    Creates a dummy MagicImageJ exports directory for testing. 
    Returns the path to the exports directory.
    """
    exports_dir = tmp_path / "20260301_Dataset3_CRY2_Exports"
    exports_dir.mkdir()
    
    # Create ROI 1
    roi1_dir = exports_dir / "20260301_Dataset3_CRY2_NP1_origin"
    roi1_dir.mkdir()
    (roi1_dir / "000000.png").touch()
    (roi1_dir / "000001.png").touch()
    (roi1_dir / "000002.png").touch()
    
    # Create ROI 2 (different structure but ends with _origin)
    roi2_dir = exports_dir / "NP2_Another_origin"
    roi2_dir.mkdir()
    (roi2_dir / "000000.png").touch()
    
    # Create noise directory
    noise_dir = exports_dir / "NP3_ignored"
    noise_dir.mkdir()
    
    # Create log
    (exports_dir / "processing_log.json").touch()
    
    return str(exports_dir)

def test_identify_rois(dummy_exports_dir):
    rois = RgWorkflowDataCore.identify_rois(dummy_exports_dir)
    assert len(rois) == 2
    
    roi1 = next(r for r in rois if r["source_folder"] == "20260301_Dataset3_CRY2_NP1_origin")
    assert roi1["roi_id"] == "ROI01"
    assert roi1["original_name"] == "NP1"
    assert roi1["total_frames"] == 3
    assert len(roi1["available_files"]) == 3
    assert "000000.png" in roi1["available_files"]
    
    roi2 = next(r for r in rois if r["source_folder"] == "NP2_Another_origin")
    assert roi2["roi_id"] == "ROI02"
    assert roi2["original_name"] == "NP2"
    assert roi2["total_frames"] == 1

def test_staging_and_writeback(dummy_exports_dir):
    rois = RgWorkflowDataCore.identify_rois(dummy_exports_dir)
    
    # Simulate user selection
    roi1 = next(r for r in rois if r["roi_id"] == "ROI01")
    roi1["selected_frames"] = 2 # Only copy 2 frames
    
    roi2 = next(r for r in rois if r["roi_id"] == "ROI02")
    roi2["selected_frames"] = 1
    
    selected_rois = [roi1, roi2]
    
    # 1. Create Staging Environment
    staging_dir = RgWorkflowDataCore.create_staging_environment(dummy_exports_dir, selected_rois)
    
    assert Path(staging_dir).exists()
    assert RgWorkflowDataCore.is_staging_directory(staging_dir)
    
    # Check manifest
    manifest = RgWorkflowDataCore.read_manifest(staging_dir)
    assert len(manifest["rois"]) == 2
    assert manifest["mask_target_suffix"] == "_mask_new"
    
    # Check copied files inside staging_dir/origin
    # ROI1 selected 2 frames
    origin_dir = Path(staging_dir) / "origin"
    assert (origin_dir / "ROI01_000000.png").exists()
    assert (origin_dir / "ROI01_000001.png").exists()
    assert not (origin_dir / "ROI01_000002.png").exists()
    # ROI2 selected 1 frame
    assert (origin_dir / "ROI02_000000.png").exists()
    
    # 2. Simulate User Drawing Masks
    # Create fake masks in the staging dir
    mask_source_dir = Path(staging_dir) / "PS_NP1_mask_new" # Simulate model save path
    mask_source_dir.mkdir()
    (mask_source_dir / "ROI01_000000.png").write_text("mask data 1")
    (mask_source_dir / "ROI02_000000.png").write_text("mask data 2")
    
    # 3. Writeback Masks
    summary = RgWorkflowDataCore.execute_mask_writeback(staging_dir, str(mask_source_dir))
    
    assert summary["rois_processed"] == 2
    assert summary["files_written"] == 2
    assert len(summary["errors"]) == 0
    
    # Check target directories
    exports_path = Path(dummy_exports_dir)
    roi1_mask_dir = exports_path / "20260301_Dataset3_CRY2_NP1_mask_new"
    roi2_mask_dir = exports_path / "NP2_Another_mask_new"
    
    assert roi1_mask_dir.exists()
    assert roi2_mask_dir.exists()
    
    # Check recovered files
    assert (roi1_mask_dir / "000000.png").exists()
    assert (roi1_mask_dir / "000000.png").read_text() == "mask data 1"
    assert (roi2_mask_dir / "000000.png").exists()
    assert (roi2_mask_dir / "000000.png").read_text() == "mask data 2"

def test_writeback_custom_suffix(dummy_exports_dir):
    rois = RgWorkflowDataCore.identify_rois(dummy_exports_dir)
    
    # Select only 1 ROI
    roi1 = next(r for r in rois if r["roi_id"] == "ROI01")
    roi1["selected_frames"] = 1
    
    staging_dir = RgWorkflowDataCore.create_staging_environment(dummy_exports_dir, [roi1], mask_target_suffix="_custom_mask")
    
    mask_source_dir = Path(staging_dir) / "PS_NP1_custom"
    mask_source_dir.mkdir()
    (mask_source_dir / "ROI01_000000.png").write_text("custom mask data")
    
    # Writeback using an override
    summary = RgWorkflowDataCore.execute_mask_writeback(
        staging_dir=staging_dir, 
        mask_dir=str(mask_source_dir),
        target_suffix_override="_my_override"
    )
    
    assert summary["rois_processed"] == 1
    assert summary["files_written"] == 1
    
    exports_path = Path(dummy_exports_dir)
    roi1_mask_dir = exports_path / "20260301_Dataset3_CRY2_NP1_my_override"
    
    assert roi1_mask_dir.exists()
    assert (roi1_mask_dir / "000000.png").exists()
    assert (roi1_mask_dir / "000000.png").read_text() == "custom mask data"

def test_rg_calculation(tmp_path):
    # Create fake origin and mask images
    origin_dir = tmp_path / "origin"
    origin_dir.mkdir()
    mask_dir = tmp_path / "mask"
    mask_dir.mkdir()
    
    # create a simple 10x10 origin image (grayscale)
    origin_img = np.ones((10, 10), dtype=np.uint8) * 200 # Background is 200 light gray
    origin_img[3:7, 3:7] = 50 # Particle is 50 dark gray
    cv2.imwrite(str(origin_dir / "000000.png"), origin_img)
    
    # Create mask image
    mask_img = np.zeros((10, 10), dtype=np.uint8)
    mask_img[3:7, 3:7] = 255
    cv2.imwrite(str(mask_dir / "000000.png"), mask_img)
    
    rois = [{
        "roi_name": "NP1",
        "origin_dir": str(origin_dir),
        "mask_dir": str(mask_dir)
    }]
    
    output_csv = str(tmp_path / "test_out.csv")
    
    results = RgWorkflowDataCore.calculate_rg_for_rois(rois, output_csv)
    
    assert len(results) == 1
    assert results[0]["Image_Name"] == "NP1_000000.png"
    assert not np.isnan(results[0]["Rg_Value"])
    assert results[0]["Rg_Value"] > 0
    
    assert Path(output_csv).exists()

if __name__ == "__main__":
    import tempfile
    
    d = Path(tempfile.mkdtemp())
    try:
        dummy_dir = setup_dummy_exports_dir(d)
        test_identify_rois(dummy_dir)
        test_staging_and_writeback(dummy_dir)
        test_writeback_custom_suffix(dummy_dir)
        test_rg_calculation(d)
        print("ALL TESTS PASSED")
    finally:
        shutil.rmtree(d)

