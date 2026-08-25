# -*- coding: utf-8 -*-
"""排除区域 (exclusion region) —— 与 mask 完全独立的第二个绘制通道。

## 为什么存在

历史上 `Useful_script/filter_components_by_region.py` 把 `canvas._selection_path`
(也就是**真 mask 本身**) 征用成草稿纸来记录"区域"。由此派生出一串症状:
必须先关自动保存、结束后不帮你开回来、画的时候看不见蚂蚁线、异常后卡在绘制模式,
以及最危险的一条 —— 捕获对话框开着时若有人按 X 开自动保存, 切帧会把临时区域
覆盖写进真 mask。

这个模块给"区域"一个自己的家。`ImageCanvas._region_path` 与 `_selection_path` 平级
但完全独立, 而 `save_mask_for_index` / `get_pixmap_from_path` 只序列化后者 ——
**因此自动保存不需要关, 上述症状是从根上消失, 不是被绕过。**

## 两种区域, 取并集

- **手动区域**: 用户画的多边形, 套用一个帧范围。管石墨烯液池边界这类基本不动的东西。
- **自动黑边**: 每帧独立检测漂移矫正 padding。黑角随漂移逐帧移动, 手画盖不住。

    effective_region(frame) = manual(该帧所在范围) ∪ auto_black(frame)

## 设计取舍

多边形按**原始平滑顶点**存, 不走 `ImageManager.process_selection_path` 的像素吸附。
那个吸附是为 mask 精度做的 (`_extract_pixel_boundaries` 会把边界拆成纯水平/垂直
线段, 顶点数暴涨), 区域不需要这种精度 —— 保留平滑多边形换来小体积、可读的 JSON,
栅格化时再离散即可。

本模块刻意保持 **Qt 无关**, 只依赖 numpy/cv2, 以便脱离 GUI 测试。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple

import cv2
import numpy as np

try:
    from utils.path_utils import to_filesystem_path
except Exception:  # pragma: no cover - 允许脱离仓库单独 import
    def to_filesystem_path(path):
        return str(path)


REGION_FILENAME = "_exclusion_region.json"
REGION_FORMAT_VERSION = 1

Polygon = List[Tuple[float, float]]


# ----------------------------------------------------------------------
# 数据结构
# ----------------------------------------------------------------------

@dataclass
class ManualRegion:
    """一组多边形 + 它生效的帧范围 (两端闭区间)。

    闭区间是刻意与 `semi_auto_mask_tools.apply_region_component_filter`
    的 `start_index <= frame.index <= end_index` 对齐, 避免两处语义打架。
    """
    start: int = 0
    end: int = 0
    polygons: List[Polygon] = field(default_factory=list)
    created_at: str = ""

    def contains_frame(self, frame_index: int) -> bool:
        return self.start <= frame_index <= self.end


@dataclass
class AutoBlackSettings:
    """漂移 padding 自动检测参数。

    border_only 是关键防线: 只保留触碰画面边界的连通分量, 粒子内部的暗区
    不接触边界, 因此不会被误吞。默认开启。
    """
    enabled: bool = True
    threshold: int = 2
    dilate: int = 3
    border_only: bool = True


@dataclass
class ExclusionRegionConfig:
    manual: List[ManualRegion] = field(default_factory=list)
    auto_black: AutoBlackSettings = field(default_factory=AutoBlackSettings)


# ----------------------------------------------------------------------
# 序列化
# ----------------------------------------------------------------------

def _compact(value) -> Any:
    """整数值就存成整数。

    区域经过像素吸附后坐标本就是整数, 存成 20 而不是 20.0 让 JSON 小一截也更可读。
    """
    number = float(value)
    return int(number) if number.is_integer() else number


def config_to_dict(config: ExclusionRegionConfig) -> Dict[str, Any]:
    return {
        "version": REGION_FORMAT_VERSION,
        "manual": [
            {
                "start": int(region.start),
                "end": int(region.end),
                "polygons": [[[_compact(x), _compact(y)] for x, y in poly] for poly in region.polygons],
                "created_at": region.created_at,
            }
            for region in config.manual
        ],
        "auto_black": {
            "enabled": bool(config.auto_black.enabled),
            "threshold": int(config.auto_black.threshold),
            "dilate": int(config.auto_black.dilate),
            "border_only": bool(config.auto_black.border_only),
        },
    }


def config_from_dict(payload: Any) -> ExclusionRegionConfig:
    """从 dict 还原。**任何字段缺失/类型不对都回落到默认值, 绝不抛异常。**

    这个文件躺在用户数据目录里, 可能被手改、被半截写坏。让它把 canvas 拖垮
    是不可接受的 —— 最坏情况是"区域丢了重画一次", 不能是"工具起不来"。
    """
    if not isinstance(payload, dict):
        return ExclusionRegionConfig()

    manual: List[ManualRegion] = []
    for raw in payload.get("manual") or []:
        if not isinstance(raw, dict):
            continue
        polygons: List[Polygon] = []
        for poly in raw.get("polygons") or []:
            points: Polygon = []
            for point in poly or []:
                try:
                    points.append((float(point[0]), float(point[1])))
                except (TypeError, ValueError, IndexError):
                    continue
            if points:
                polygons.append(points)
        try:
            start = int(raw.get("start", 0))
            end = int(raw.get("end", 0))
        except (TypeError, ValueError):
            continue
        manual.append(ManualRegion(
            start=start,
            end=end,
            polygons=polygons,
            created_at=str(raw.get("created_at", "") or ""),
        ))

    defaults = AutoBlackSettings()
    raw_auto = payload.get("auto_black")
    if not isinstance(raw_auto, dict):
        raw_auto = {}

    def _pick(key, caster, fallback):
        try:
            return caster(raw_auto[key])
        except (KeyError, TypeError, ValueError):
            return fallback

    auto_black = AutoBlackSettings(
        enabled=_pick("enabled", bool, defaults.enabled),
        threshold=_pick("threshold", int, defaults.threshold),
        dilate=_pick("dilate", int, defaults.dilate),
        border_only=_pick("border_only", bool, defaults.border_only),
    )
    return ExclusionRegionConfig(manual=manual, auto_black=auto_black)


def region_config_path(save_dir) -> str:
    return os.path.join(str(save_dir), REGION_FILENAME)


def load_region_config(save_dir) -> ExclusionRegionConfig:
    path = to_filesystem_path(region_config_path(save_dir))
    if not os.path.exists(path):
        return ExclusionRegionConfig()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return config_from_dict(json.load(fh))
    except Exception:
        # 坏文件当没有, 见 config_from_dict 的说明
        return ExclusionRegionConfig()


def save_region_config(save_dir, config: ExclusionRegionConfig) -> str:
    """原子写: 先写 .tmp 再 os.replace, 避免半截文件。

    与 `_semi_auto_meta.json` 同目录同级。
    """
    target = to_filesystem_path(region_config_path(save_dir))
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)

    tmp = target + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(config_to_dict(config), fh, ensure_ascii=False, indent=2)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return target


# ----------------------------------------------------------------------
# 查询与栅格化
# ----------------------------------------------------------------------

def apply_auto_black_settings(
    save_dir,
    enabled=None,
    threshold=None,
    dilate=None,
    border_only=None,
) -> ExclusionRegionConfig:
    """只改 auto_black 参数并落盘, **手动区域原样保留**。

    给重推面板的开关/阈值/余量控件用: 读当前配置 → 覆盖指定字段 → 存回。
    传 None 的字段沿用原值。返回更新后的配置。
    """
    config = load_region_config(save_dir)
    current = config.auto_black
    config.auto_black = AutoBlackSettings(
        enabled=current.enabled if enabled is None else bool(enabled),
        threshold=current.threshold if threshold is None else int(threshold),
        dilate=current.dilate if dilate is None else int(dilate),
        border_only=current.border_only if border_only is None else bool(border_only),
    )
    save_region_config(save_dir, config)
    return config


def manual_polygons_for_frame(config: ExclusionRegionConfig, frame_index: int) -> List[Polygon]:
    """该帧命中的所有手动区域多边形 (多个范围重叠时取并集)。"""
    polygons: List[Polygon] = []
    for region in config.manual:
        if region.contains_frame(frame_index):
            polygons.extend(region.polygons)
    return polygons


def rasterize_polygons(polygons: Sequence[Polygon], shape: Tuple[int, int]) -> np.ndarray:
    """多边形 -> uint8 0/1 掩码。少于 3 个点的退化多边形直接跳过, 不报错。

    用户手抖点一下就松手是常态, 不该弹窗打断。
    """
    height, width = int(shape[0]), int(shape[1])
    mask = np.zeros((height, width), dtype=np.uint8)
    contours = []
    for poly in polygons or []:
        if poly is None or len(poly) < 3:
            continue
        contours.append(np.asarray(poly, dtype=np.float64).round().astype(np.int32))
    if contours:
        cv2.fillPoly(mask, contours, 1)
    return mask


def _to_gray(image: np.ndarray) -> np.ndarray:
    arr = np.asarray(image)
    if arr.ndim == 3:
        channels = arr.shape[2]
        if channels == 4:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2GRAY)
        elif channels == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        else:
            arr = arr[:, :, 0]
    return arr


def detect_black_border(
    image: np.ndarray,
    threshold: int = 2,
    dilate: int = 3,
    border_only: bool = True,
    close_ksize: int = 3,
) -> np.ndarray:
    """检测漂移矫正留下的纯黑 padding, 返回 uint8 0/1 掩码。

    步骤: 阈值 -> (只留触边连通分量) -> 闭运算填噪点小孔 -> 膨胀留余量。

    `threshold` 是**闭区间** (`<= threshold`)。膨胀的默认 3px 是为了盖住黑边与
    有效区之间的抗锯齿过渡带 —— 那一圈灰边同样会把 locator 带偏。
    """
    gray = _to_gray(image)
    dark = (gray <= threshold).astype(np.uint8)
    if not dark.any():
        return dark

    if border_only:
        num, labels = cv2.connectedComponents(dark, connectivity=8)
        if num > 1:
            edge_labels = np.concatenate([
                labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1],
            ])
            keep = np.unique(edge_labels)
            keep = keep[keep != 0]
            if keep.size == 0:
                return np.zeros_like(dark)
            lut = np.zeros(num, dtype=np.uint8)
            lut[keep] = 1
            dark = lut[labels]

    if close_ksize and close_ksize > 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_ksize, close_ksize))
        dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, kernel)

    if dilate and dilate > 0:
        size = int(dilate) * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        dark = cv2.dilate(dark, kernel, iterations=1)

    return (dark > 0).astype(np.uint8)


def effective_region_mask(
    config: ExclusionRegionConfig,
    frame_index: int,
    image: np.ndarray,
) -> np.ndarray:
    """该帧真正生效的排除区域 = 手动区域 ∪ 自动黑边。

    返回 uint8 0/1, 尺寸跟随 `image`。永不返回 None —— 调用方拿到的最坏情况
    是一张全零掩码, 不用到处写 `if mask is not None`。
    """
    gray = _to_gray(image)
    shape = (gray.shape[0], gray.shape[1])

    mask = rasterize_polygons(manual_polygons_for_frame(config, frame_index), shape)

    if config.auto_black.enabled:
        auto = detect_black_border(
            gray,
            threshold=config.auto_black.threshold,
            dilate=config.auto_black.dilate,
            border_only=config.auto_black.border_only,
        )
        # 用 | 而不是 + , 重叠处不能出现 2
        mask = (mask | auto).astype(np.uint8)

    return mask
