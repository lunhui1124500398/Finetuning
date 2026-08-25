# -*- coding: utf-8 -*-
"""镜像填充 —— 把排除区域用它周围的真实内容"反射"填掉。

## 为什么要填, 而不是直接涂黑或涂平均值

分割管线是 locator 先定位、再把 prior 交给 segmenter。漂移矫正留下的黑角是一条
又直又硬的高对比边界, locator 会锁死在上面, segmenter 于是拿到错误的 prior ——
结果是 mask 里只有那条边, 真粒子整个漏掉。

涂成常数会**造出一条新的硬边**, 同样能把 locator 带偏。镜像填充让排除区里长出
和邻域统计一致的纹理, 那条边就不存在了。

## 算法

对任意形状的区域, 用**距离变换标签图**做"反射到最近有效像素的对面":

    对区域内每个像素 p:
        n = 离 p 最近的有效像素
        src = 2n - p                 # 以 n 为中点把 p 反射出去
        若 src 越界或仍落在区域内 -> 回落到 n

`cv2.distanceTransformWithLabels` 一次就给出"每个像素最近的零像素是谁", 于是整张
索引图是纯 numpy 运算, 没有逐像素 Python 循环。

**索引图只取决于区域形状, 与帧内容无关** —— 所以手动区域 (全程不变) 只需算一次,
之后每帧就是一次花式索引; 自动黑边逐帧变化才需要逐帧重算。这就是 `build_mirror_map`
和 `apply_mirror_map` 分开的理由。

## 三种填充方式 (method)

- **directional** (默认): 沿单一轴整体翻折 —— 用户想的"直接倒映"。底部黑条 → 垂直
  把上方内容翻下来; 左右黑边 → 水平。方向 auto 时按区域从哪条图像边侵入自动判断,
  对角三角黑角(顶边+左边都显著接触)没有单一方向 → 退回 distance。**不产生对角接缝。**
- **distance**: 逐像素找欧氏距离最近的有效像素反射。任意形状通用, 但矩形等多边形状
  会在到多条边等距的中轴处出现方向突变, 形成对角接缝(一个视觉伪影)。
- **inpaint**: cv2.inpaint 邻域插值。无接缝最平滑, 对分割最安全(不造假结构),
  但大区域会糊、丢纹理。

## 一个刻意的取舍

反射可能把边界附近的真粒子镜像成一个"假粒子"。但它落在**排除区内部**, 而排除区里的
预测最后本来就要整片删掉, 所以无害。真正要防的是假粒子透过感受野把检测**拽过边界**,
`feather` 参数就是为此准备的 —— 且羽化**只作用于区域内部**, 区域外一个像素都不动
(那里要保留真实预测)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


@dataclass(frozen=True)
class MirrorMap:
    """区域形状决定的采样索引图。可跨帧复用。"""
    src_y: np.ndarray          # (H, W) int32
    src_x: np.ndarray          # (H, W) int32
    region: np.ndarray         # (H, W) uint8 0/1
    trivial: bool = False      # 区域为空或占满整幅 —— 填充退化为原样返回

    @property
    def shape(self):
        return self.region.shape


def _as_binary_region(region: np.ndarray, shape) -> np.ndarray:
    region = np.asarray(region)
    if region.ndim != 2:
        raise ValueError(f"region 必须是二维掩码, 收到 shape={region.shape}")
    if region.shape != tuple(shape[:2]):
        raise ValueError(f"region 尺寸 {region.shape} 与图像 {tuple(shape[:2])} 不一致")
    return (region > 0).astype(np.uint8)


def build_mirror_map(region: np.ndarray) -> MirrorMap:
    """由区域形状算出采样索引图。同一区域只需算一次。"""
    region_u8 = np.asarray(region)
    if region_u8.ndim != 2:
        raise ValueError(f"region 必须是二维掩码, 收到 shape={region_u8.shape}")
    region_u8 = (region_u8 > 0).astype(np.uint8)
    height, width = region_u8.shape

    grid_y, grid_x = np.mgrid[0:height, 0:width]

    # 空区域 / 占满整幅: 前者无事可做, 后者没有任何有效像素可供镜像
    if not region_u8.any() or region_u8.all():
        return MirrorMap(
            src_y=grid_y.astype(np.int32),
            src_x=grid_x.astype(np.int32),
            region=region_u8,
            trivial=True,
        )

    # distanceTransform 算的是"到最近零像素的距离"。传入 region (区域=1, 有效=0),
    # 于是对区域内每个像素拿到最近的**有效**像素。
    _, labels = cv2.distanceTransformWithLabels(
        region_u8, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL
    )

    # labels 给每个零像素一个唯一编号, 非零像素带的是"最近零像素"的编号。
    # 反查一张 编号 -> 坐标 的表, 就能把编号还原成坐标。
    zero_y, zero_x = np.nonzero(region_u8 == 0)
    lut = np.zeros((int(labels.max()) + 1, 2), dtype=np.int32)
    lut[labels[zero_y, zero_x]] = np.stack([zero_y, zero_x], axis=1)
    nearest = lut[labels]                       # (H, W, 2)

    src_y = 2 * nearest[..., 0] - grid_y
    src_x = 2 * nearest[..., 1] - grid_x
    np.clip(src_y, 0, height - 1, out=src_y)
    np.clip(src_x, 0, width - 1, out=src_x)

    # 反射点仍落在区域内 -> 回落到最近有效像素。
    # 少了这一步, 宽条带形状的区域会把自己的黑像素抄进来, 等于白填。
    still_inside = region_u8[src_y, src_x] > 0
    src_y = np.where(still_inside, nearest[..., 0], src_y).astype(np.int32)
    src_x = np.where(still_inside, nearest[..., 1], src_x).astype(np.int32)

    return MirrorMap(src_y=src_y, src_x=src_x, region=region_u8, trivial=False)


def _nearest_valid_along_axis(region_u8: np.ndarray, axis: int) -> np.ndarray:
    """每个位置沿指定轴最近的有效像素的坐标值。

    axis=0 → 同列里最近的有效行号; axis=1 → 同行里最近的有效列号。
    整行/整列都无有效像素的位置返回自身坐标(等于不动)。
    """
    if axis == 1:
        return _nearest_valid_along_axis(region_u8.T, 0).T

    height, width = region_u8.shape
    valid = region_u8 == 0
    rows = np.broadcast_to(np.arange(height)[:, None], (height, width))
    big = height * 2

    # 向下扫: 每个位置"上方(含自身)最近的有效行号", 无则 -1
    up = np.where(valid, rows, -1)
    up = np.maximum.accumulate(up, axis=0)
    # 向上扫: "下方(含自身)最近的有效行号", 无则 big
    down = np.where(valid, rows, big)
    down = np.minimum.accumulate(down[::-1], axis=0)[::-1]

    dist_up = np.where(up >= 0, rows - up, big)
    dist_down = np.where(down < big, down - rows, big)
    nearest = np.where(dist_up <= dist_down, up, down)

    no_valid = (up < 0) & (down >= big)
    nearest = np.where(no_valid, rows, nearest)
    return nearest.astype(np.int32)


def resolve_fill_direction(region: np.ndarray) -> str:
    """自动判断定向反射的方向: 'vertical' / 'horizontal' / 'distance'。

    用区域 bounding box 的长宽比, 沿**长轴**方向翻折 (宽>高的横条 → 垂直把上方内容
    翻下来; 高>宽的竖条 → 水平)。

    为什么不用"接触哪条边": 横贯全宽的条带两侧都连着左右边缘, 按接触边会误判成水平,
    可那样同一行里根本没有有效像素可反射。bbox 长宽比稳健得多。

    近方形 (对角三角、角块) 没有明确长轴, 或区域根本不接触任何图像边 (无侵入语义),
    返回 'distance' 让调用方退回各向距离反射。
    """
    region_u8 = (np.asarray(region) > 0).astype(np.uint8)
    if not region_u8.any():
        return "vertical"

    ys, xs = np.nonzero(region_u8)
    height, width = region_u8.shape
    touches_edge = (ys.min() == 0 or ys.max() == height - 1
                    or xs.min() == 0 or xs.max() == width - 1)
    if not touches_edge:
        return "distance"          # 不接触任何边 → 没有侵入方向

    box_h = int(ys.max() - ys.min() + 1)
    box_w = int(xs.max() - xs.min() + 1)
    ratio = min(box_h, box_w) / max(box_h, box_w)
    if ratio > 0.62:
        return "distance"          # 近方形 → 无明确长轴 (对角三角/角块)
    return "vertical" if box_w >= box_h else "horizontal"


def build_directional_map(region: np.ndarray, direction: str) -> MirrorMap:
    """沿单一轴的定向反射索引图。direction ∈ {'vertical','horizontal'}。"""
    region_u8 = (np.asarray(region) > 0).astype(np.uint8)
    if region_u8.ndim != 2:
        raise ValueError(f"region 必须是二维掩码, 收到 shape={region_u8.shape}")
    height, width = region_u8.shape
    grid_y, grid_x = np.mgrid[0:height, 0:width]

    if not region_u8.any() or region_u8.all():
        return MirrorMap(grid_y.astype(np.int32), grid_x.astype(np.int32), region_u8, trivial=True)

    if direction == "vertical":
        nearest = _nearest_valid_along_axis(region_u8, axis=0)
        # 不重复边界 (REFLECT_101): 镜面在有效区边缘, 紧邻的有效像素直接翻进来 ——
        # filled[y0]=img[y0-1], 这才是"直接倒映"。sign 修正保证向上/向下都对。
        sgn = np.sign(nearest - grid_y).astype(np.int32)
        src = 2 * nearest - grid_y - sgn
        np.clip(src, 0, height - 1, out=src)
        still_inside = region_u8[src, grid_x] > 0
        src_y = np.where(still_inside, nearest, src).astype(np.int32)
        src_x = grid_x.astype(np.int32)
    elif direction == "horizontal":
        nearest = _nearest_valid_along_axis(region_u8, axis=1)
        sgn = np.sign(nearest - grid_x).astype(np.int32)
        src = 2 * nearest - grid_x - sgn
        np.clip(src, 0, width - 1, out=src)
        still_inside = region_u8[grid_y, src] > 0
        src_x = np.where(still_inside, nearest, src).astype(np.int32)
        src_y = grid_y.astype(np.int32)
    else:
        raise ValueError(f"direction 必须是 'vertical' 或 'horizontal', 收到 {direction!r}")

    return MirrorMap(src_y=src_y, src_x=src_x, region=region_u8, trivial=False)


def _inpaint_fill(image: np.ndarray, region_u8: np.ndarray, feather: float) -> np.ndarray:
    """cv2.inpaint (Telea)。区域外逐字节还原, 保证真实预测区不被动。"""
    image = np.asarray(image)
    mask = (region_u8 > 0).astype(np.uint8) * 255
    src8 = image if image.dtype == np.uint8 else cv2.normalize(
        image, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    radius = max(3, int(round(feather))) if feather else 3
    painted = cv2.inpaint(src8, mask, radius, cv2.INPAINT_TELEA)
    out = image.copy()
    inside = region_u8 > 0
    out[inside] = painted.astype(image.dtype)[inside]
    return out


def apply_mirror_map(image: np.ndarray, mirror_map: MirrorMap, feather: float = 0.0) -> np.ndarray:
    """按预先算好的索引图填充一帧。**永不就地修改入参。**"""
    image = np.asarray(image)
    if image.shape[:2] != mirror_map.shape:
        raise ValueError(f"图像尺寸 {image.shape[:2]} 与索引图 {mirror_map.shape} 不一致")

    out = image.copy()
    if mirror_map.trivial:
        return out

    inside = mirror_map.region > 0
    out[inside] = image[mirror_map.src_y[inside], mirror_map.src_x[inside]]

    if feather and feather > 0:
        ksize = max(3, int(round(feather * 3)) | 1)     # 保证是奇数
        blurred = cv2.GaussianBlur(out, (ksize, ksize), float(feather))
        # 只覆盖区域内部。区域外正是"要保留真实预测"的地方, 一个像素都不能动。
        out[inside] = blurred[inside]

    return out


def build_fill_map(region: np.ndarray, method: str = "directional",
                   direction: str = "auto") -> Optional[MirrorMap]:
    """按 method/direction 造出采样索引图。inpaint 无索引图 → 返回 None。

    索引图只取决于区域形状, 与帧内容无关, 所以手动区域(全程不变)可以算一次跨帧复用。
    """
    region_u8 = (np.asarray(region) > 0).astype(np.uint8)
    if method == "inpaint":
        return None
    if method == "distance":
        return build_mirror_map(region_u8)
    if method == "directional":
        resolved = resolve_fill_direction(region_u8) if direction == "auto" else direction
        if resolved == "distance":          # 对角/内部 → 退回距离反射
            return build_mirror_map(region_u8)
        return build_directional_map(region_u8, resolved)
    raise ValueError(f"未知的填充方式: {method!r}")


def mirror_fill(
    image: np.ndarray,
    region: np.ndarray,
    feather: float = 0.0,
    mirror_map: Optional[MirrorMap] = None,
    method: str = "directional",
    direction: str = "auto",
) -> np.ndarray:
    """一步到位版本。逐帧区域各不相同时用它; 区域固定时请复用 build_fill_map。

    method: 'directional'(默认, 定向倒映) / 'distance'(各向反射) / 'inpaint'。
    direction: 仅 directional 用, 'auto'/'vertical'/'horizontal'。
    传了 mirror_map 时直接用它(视为已按需要的 method 构建好), method/direction 忽略。
    """
    image = np.asarray(image)
    region_u8 = _as_binary_region(region, image.shape)

    if mirror_map is not None:
        return apply_mirror_map(image, mirror_map, feather=feather)

    if method == "inpaint":
        if not region_u8.any():
            return image.copy()
        return _inpaint_fill(image, region_u8, feather)

    mirror_map = build_fill_map(region_u8, method=method, direction=direction)
    return apply_mirror_map(image, mirror_map, feather=feather)
