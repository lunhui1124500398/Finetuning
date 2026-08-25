# -*- coding: utf-8 -*-
"""镜像填充重推 —— 三段跨环境流水线。

## 为什么是三段

分割器吃的是 **3 通道: origin + IVAN-hrtem + IVAN-lrtem**, 而且靠 **sibling 文件夹配对**
去发现它们 (不是文件名后缀)。所以只把 origin 镜像填充、复用旧的 hrtem/lrtem 是没用的 ——
黑边仍然存在于 3 个通道中的 2 个。**必须重跑 IVAN。**

    ① 镜像填充   (本进程, numpy/cv2)
    ② IVAN 去噪   D:\\bushu_binary_model\\.venv        ivan_local_runner.py --model both
    ③ 分割        D:\\PythonEnvs\\liquid-tem-seg\\.venv  infer_new_xz_swinbottleneck_ws7p.py

## 两个静默失败陷阱 (必须主动检测)

1. **分割器找不到配对模态时是 `continue` + 退出码 0。** 零序列的运行和成功用退出码
   **无法区分**。所以真跑之前先 `--dry-run`, 断言 `n_sequences > 0`。
2. **IVAN runner 单图失败只打 `[ERROR]` 不改退出码。** 必须扫 stdout, 不能只看 returncode。

## 永不覆盖

每次修复写进一个新的 `_repair/<particle>/v{N}/`, 原始推理 `_masks/<particle>_mask/`
和历史版本物理上碰不到。重推结果停在 `v{N}/result/`, **采纳是另一个显式步骤**
(见 core/repair_adopt.py) —— 跑完 ≠ 生效。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import cv2
import numpy as np

from core.exclusion_region import ExclusionRegionConfig, effective_region_mask
from core.mirror_fill import mirror_fill

# 解释器与脚本路径。与 launchers/inference_gui.py 保持一致, 允许环境变量覆盖
# (换机器/换环境时不用改代码)。
IVAN_PYTHON = os.environ.get("IVAN_PY", r"D:\bushu_binary_model\.venv\Scripts\python.exe")
IVAN_RUNNER = os.environ.get("IVAN_RUNNER", r"D:\bushu_binary_model\ivan_local_runner.py")
SEG_PYTHON = os.environ.get("LIQUID_TEM_PY", r"D:\PythonEnvs\liquid-tem-seg\.venv\Scripts\python.exe")
SEG_SCRIPT = os.environ.get(
    "LIQUID_TEM_INFER",
    r"D:\Unet++_retrain\phase_scripts\PhaseB_swin_bottleneck\infer_new_xz_swinbottleneck_ws7p.py",
)
SEG_CHECKPOINT = os.environ.get(
    "LIQUID_TEM_SEG_CKPT",
    r"D:\Unet++_retrain\runs\unetpp_clean_v1\UPP-SwinBottleneck-WS7P\best_epoch_038_iou_0.855752.pth",
)
LOC_CHECKPOINT = os.environ.get(
    "LIQUID_TEM_LOC_CKPT",
    r"D:\WS7_4channel_model_after_clean\runs\locator_clean_v1\best_locator.pt",
)

# 填充后 origin 文件夹的名字。**必须含 "contrasted"** —— 分割器默认
# `--input-folder-keywords contrasted` 会把不含该词的文件夹过滤掉。
PADDED_STEM = "padded"
PADDED_ORIGIN_DIRNAME = f"{PADDED_STEM}_contrasted"

ProgressCallback = Optional[Callable[[int, int, str], bool]]
LineCallback = Optional[Callable[[str], None]]


class RepairError(RuntimeError):
    """带用户可读中文说明的失败。"""


@dataclass(frozen=True)
class RepairLayout:
    """一次修复运行的全部落地路径。

    `root` 自身就是一个合法的 session dir (含 padded_contrasted/ 和
    _denoise/padded_{hrtem,lrtem}/), 所以 `--input-root` 直接指向它即可,
    走分割器的 `_is_session_dir` 快路径。
    """
    root: Path
    version: int
    particle: str

    @property
    def padded_dir(self) -> Path:
        return self.root / PADDED_ORIGIN_DIRNAME

    @property
    def ivan_out_dir(self) -> Path:
        return self.root / "_ivan_out"

    @property
    def denoise_dir(self) -> Path:
        return self.root / "_denoise"

    @property
    def hrtem_dir(self) -> Path:
        return self.denoise_dir / f"{PADDED_STEM}_hrtem"

    @property
    def lrtem_dir(self) -> Path:
        return self.denoise_dir / f"{PADDED_STEM}_lrtem"

    @property
    def masks_dir(self) -> Path:
        return self.root / "_masks"

    @property
    def result_dir(self) -> Path:
        return self.root / "result"

    @property
    def region_json(self) -> Path:
        return self.root / "region.json"

    @property
    def log_path(self) -> Path:
        return self.root / "run.log"

    def make_dirs(self) -> None:
        for path in (self.padded_dir, self.ivan_out_dir, self.denoise_dir,
                     self.masks_dir, self.result_dir):
            path.mkdir(parents=True, exist_ok=True)


def repair_root_for(exports_dir, particle: str) -> Path:
    # 放在 _masks/ 下 (而非 exports 根) —— 用户在文件浏览器里好找, 和 mask 相关的
    # 东西都收在一起。安全性: binary_queue 只扫 exports 根下 *_contrasted 的直接子目录
    # + 精确拼 _masks/<particle>_mask, 不 iterdir 遍历 _masks/; 分割器跳过 _ 开头目录。
    # 所以 _masks/_repair 不会被任何扫描误抓。
    return Path(exports_dir) / "_masks" / "_repair" / particle


def existing_versions(exports_dir, particle: str) -> List[int]:
    root = repair_root_for(exports_dir, particle)
    if not root.exists():
        return []
    versions = []
    for child in root.iterdir():
        match = re.fullmatch(r"v(\d+)", child.name)
        if match and child.is_dir():
            versions.append(int(match.group(1)))
    return sorted(versions)


def allocate_repair_version(exports_dir, particle: str) -> RepairLayout:
    """分配一个**全新**的 v{N}。绝不复用已有版本 —— 这是"永不覆盖"的第一道防线。"""
    versions = existing_versions(exports_dir, particle)
    version = (versions[-1] + 1) if versions else 1
    root = repair_root_for(exports_dir, particle) / f"v{version}"
    layout = RepairLayout(root=root, version=version, particle=particle)
    layout.make_dirs()
    return layout


# ----------------------------------------------------------------------
# 阶段 ① 镜像填充
# ----------------------------------------------------------------------

def prepare_padded_frames(
    frame_paths: Sequence[str],
    frame_indices: Sequence[int],
    layout: RepairLayout,
    config: ExclusionRegionConfig,
    feather: float = 0.0,
    method: str = "directional",
    direction: str = "auto",
    progress_callback: ProgressCallback = None,
) -> Dict[str, object]:
    """把选中帧镜像填充后写进 padded_contrasted/。**文件名逐字保留** ——
    IVAN 和分割器靠文件名在三个文件夹之间做交集配对。

    method/direction 见 core/mirror_fill.mirror_fill (默认定向倒映+自动方向)。
    """
    if len(frame_paths) != len(frame_indices):
        raise ValueError("frame_paths 与 frame_indices 长度不一致")
    if not frame_paths:
        raise RepairError("没有选中任何帧。")

    layout.padded_dir.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    empty_region_frames: List[int] = []
    total = len(frame_paths)

    for offset, (src, index) in enumerate(zip(frame_paths, frame_indices)):
        if progress_callback and progress_callback(offset, total, f"镜像填充 {Path(src).name}") is False:
            raise RepairError("已取消。")

        image = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise RepairError(f"读不出图像: {src}")

        region = effective_region_mask(config, index, image)
        if not region.any():
            empty_region_frames.append(index)

        filled = mirror_fill(image, region, feather=feather, method=method, direction=direction)
        target = layout.padded_dir / Path(src).name
        if not cv2.imwrite(str(target), filled):
            raise RepairError(f"写不出填充图: {target}")
        written.append(target.name)

    return {
        "written": written,
        "count": len(written),
        "empty_region_frames": empty_region_frames,
    }


# ----------------------------------------------------------------------
# 阶段 ② / ③ 命令构造
# ----------------------------------------------------------------------

def build_ivan_command(layout: RepairLayout, batch_size: int = 128,
                       patch_size: int = 128, stride: int = 64) -> List[str]:
    """`--model both` 一次同时出 hrtem + lrtem: 模型只载一次, I/O 只付一次。"""
    return [
        IVAN_PYTHON, IVAN_RUNNER,
        "--model", "both",
        "--input", str(layout.padded_dir),
        "--output", str(layout.ivan_out_dir),
        "--batch_size", str(batch_size),
        "--patch_size", str(patch_size),
        "--stride", str(stride),
    ]


def build_seg_command(layout: RepairLayout, threshold: float = 0.50,
                      batch_size: int = 64, amp: str = "bf16",
                      dry_run: bool = False) -> List[str]:
    cmd = [
        SEG_PYTHON, SEG_SCRIPT,
        "--input-root", str(layout.root),
        "--origin-source", "contrasted",
        "--segmenter-checkpoint", SEG_CHECKPOINT,
        "--locator-checkpoint", LOC_CHECKPOINT,
        "--threshold", str(threshold),
        "--batch-size", str(batch_size),
        "--amp", amp,
        "--enhance-locator-prior",
    ]
    if dry_run:
        cmd.append("--dry-run")
    else:
        # 输出目录是全新的 v{N}, 不存在"已有文件"问题; 显式 --overwrite 避免
        # 脚本因目录非空而 raise (它在既不给 --overwrite 也不给 --skip-existing 时会报错)。
        cmd.append("--overwrite")
    return cmd


def promote_ivan_output(layout: RepairLayout) -> None:
    """把 _ivan_out/output_{hrtem,lrtem}/ 挪到分割器要求的 _denoise/padded_{hrtem,lrtem}/。"""
    layout.denoise_dir.mkdir(parents=True, exist_ok=True)
    for modality in ("hrtem", "lrtem"):
        src = layout.ivan_out_dir / f"output_{modality}"
        dst = layout.denoise_dir / f"{PADDED_STEM}_{modality}"
        if not src.exists():
            raise RepairError(
                f"IVAN 没有产出 {src.name}/。去噪这一步很可能失败了 —— 请看 run.log。"
            )
        if dst.exists():
            for item in src.iterdir():
                target = dst / item.name
                if target.exists():
                    target.unlink()
                item.replace(target)
        else:
            src.replace(dst)


# ----------------------------------------------------------------------
# 输出解析 —— 两个静默失败陷阱的探针
# ----------------------------------------------------------------------

def parse_dry_run(stdout: str) -> Dict[str, object]:
    """从 --dry-run 输出里抠出发现结果 JSON。"""
    depth = 0
    start = -1
    for pos, char in enumerate(stdout):
        if char == "{":
            if depth == 0:
                start = pos
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        payload = json.loads(stdout[start:pos + 1])
                    except json.JSONDecodeError:
                        start = -1
                        continue
                    if isinstance(payload, dict) and "n_sequences" in payload:
                        return payload
                    start = -1
    return {}


def assert_discovery_ok(info: Dict[str, object]) -> None:
    """零序列的运行和成功用退出码无法区分, 只能在这里拦。"""
    if not info:
        raise RepairError(
            "分割器的 --dry-run 没有给出可解析的发现结果。\n"
            "多半是脚本路径或环境不对, 请看 run.log。"
        )
    n_sequences = int(info.get("n_sequences") or 0)
    if n_sequences <= 0:
        raise RepairError(
            "分割器没有发现任何可处理的序列 (n_sequences=0)。\n\n"
            "最常见的原因是 IVAN 去噪没有产出配对的 hrtem/lrtem 文件夹, "
            "或者三个文件夹里的文件名对不上。\n"
            "注意: 这种情况下分割器**退出码仍然是 0**, 所以必须靠这一步拦住。\n\n"
            f"发现结果: {json.dumps(info, ensure_ascii=False)[:400]}"
        )


def parse_result_line(stdout: str) -> Dict[str, int]:
    """抓机器可读的结尾行 `__RESULT__:written=N,skipped=M`。"""
    match = re.search(r"__RESULT__:written=(\d+),skipped=(\d+)", stdout)
    if not match:
        return {}
    return {"written": int(match.group(1)), "skipped": int(match.group(2))}


def collect_error_lines(stdout: str) -> List[str]:
    """IVAN 单图失败只打 [ERROR] 不改退出码, 必须扫 stdout。"""
    return [line.strip() for line in stdout.splitlines() if "[ERROR]" in line]


def find_mask_output_dir(layout: RepairLayout) -> Path:
    """分割器的输出目录名由它自己拼, 与其猜不如扫。"""
    if not layout.masks_dir.exists():
        raise RepairError("分割器没有建立 _masks/ 目录 —— 这一步很可能没跑起来。")
    candidates = [d for d in layout.masks_dir.iterdir() if d.is_dir() and any(d.iterdir())]
    if not candidates:
        raise RepairError("分割器建了 _masks/ 但里面没有任何输出。请看 run.log。")
    return sorted(candidates, key=lambda d: len(list(d.iterdir())), reverse=True)[0]


# ----------------------------------------------------------------------
# 阶段 ④ 按区域裁掉预测
# ----------------------------------------------------------------------

def crop_masks_by_region(
    mask_dir,
    frame_paths: Sequence[str],
    frame_indices: Sequence[int],
    config: ExclusionRegionConfig,
    result_dir,
    progress_callback: ProgressCallback = None,
) -> Dict[str, int]:
    """把排除区内的预测抹掉, 结果写进 result_dir。

    这一步是必须的: 镜像填充只是让 locator 不再被黑边带偏, 填充区里**照样**可能
    长出预测 (那是假内容上长出来的), 必须整片删掉。
    """
    mask_dir = Path(mask_dir)
    result_dir = Path(result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)

    processed = 0
    missing = 0
    removed_pixels = 0
    total = len(frame_paths)

    for offset, (src, index) in enumerate(zip(frame_paths, frame_indices)):
        if progress_callback and progress_callback(offset, total, f"按区域裁剪 {Path(src).name}") is False:
            raise RepairError("已取消。")

        name = Path(src).with_suffix(".png").name
        mask_path = mask_dir / name
        if not mask_path.exists():
            missing += 1
            continue

        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            missing += 1
            continue

        origin = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
        region = effective_region_mask(config, index, origin if origin is not None else mask)
        if region.shape != mask.shape:
            region = cv2.resize(region, (mask.shape[1], mask.shape[0]), interpolation=cv2.INTER_NEAREST)

        binary = (mask > 127).astype(np.uint8)
        removed_pixels += int((binary & (region > 0)).sum())
        binary[region > 0] = 0

        if not cv2.imwrite(str(result_dir / name), (binary * 255).astype(np.uint8)):
            raise RepairError(f"写不出裁剪结果: {result_dir / name}")
        processed += 1

    return {"processed": processed, "missing": missing, "removed_pixels": removed_pixels}


# ----------------------------------------------------------------------
# 子进程
# ----------------------------------------------------------------------

def run_command(cmd: Sequence[str], on_line: LineCallback = None,
                log_path: Optional[Path] = None) -> Dict[str, object]:
    """跑一段子进程, 逐行回调, 全量收集 stdout。

    环境刻意**净化 PYTHONPATH** —— 继承下去会让 bushu_binary_model\\utils.py 顶掉
    Finetuning 的 utils 命名空间包 (inference_gui.py:894 记过这个坑)。
    """
    executable = cmd[0]
    if not os.path.exists(executable):
        raise RepairError(f"找不到解释器:\n{executable}\n\n请确认对应环境还在。")
    script = cmd[1] if len(cmd) > 1 else ""
    if script and not os.path.exists(script):
        raise RepairError(f"找不到脚本:\n{script}")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONPATH", None)

    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(
        list(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        env=env, creationflags=creationflags,
    )

    lines: List[str] = []
    handle = open(log_path, "a", encoding="utf-8") if log_path else None
    try:
        if handle:
            handle.write(f"\n$ {' '.join(cmd)}\n")
        for line in process.stdout:
            line = line.rstrip("\n")
            lines.append(line)
            if handle:
                handle.write(line + "\n")
            if on_line:
                on_line(line)
    finally:
        process.wait()
        if handle:
            handle.close()

    stdout = "\n".join(lines)
    return {"returncode": process.returncode, "stdout": stdout,
            "errors": collect_error_lines(stdout)}
