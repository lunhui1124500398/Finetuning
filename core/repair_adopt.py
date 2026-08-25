# -*- coding: utf-8 -*-
"""采纳修复结果 —— 三道防线里的后两道。

用户的原话是: "先跑了推理之后才知道哪些有问题, 后续再跑的时候如何确保不会覆盖?"

    ① 版本化      每次修复写进新的 _repair/<particle>/v{N}/, 旧数据物理上碰不到
                  (在 core/repair_runner.py)
    ② 采纳是独立步骤  重推结果停在 v{N}/result/, 逐帧勾选后才落地。跑完 ≠ 生效
    ③ 跳过人工帧   本模块

## 第三道防线怎么判"这帧是不是人工的"

`_semi_auto_meta.json` 里每帧记了 `source` 和 **`sha1`**。现成的
`_is_current_file_still_auto_generated` 会**重新哈希文件比对** —— 所以"自动生成之后
又被用户手改过"的帧, 哈希对不上, 会被正确识别成人工。这比只看 `source` 字段强得多。

分类:
    absent  文件不存在        -> 随便写
    auto    仍是纯自动生成     -> 可覆盖
    manual  人工存过 / 手改过 / 没有元数据 -> **默认保护, 不采纳**

没有元数据也算 manual 是刻意的保守选择: 宁可让用户多点一次, 不可默默盖掉手工劳动。

## 目标只有一个

只写 `save_dir` (即 `_mask_refined/`)。**绝不碰 `_masks/<particle>_mask/`** ——
那是第一次推理的原始输出, 永久保留作对照。下面有一道硬拦截。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from core.semi_auto_mask_tools import (
    FramePaths,
    _is_current_file_still_auto_generated,
    _load_auto_metadata,
    mark_auto_generated_mask,
)

STATUS_ABSENT = "absent"
STATUS_AUTO = "auto"
STATUS_MANUAL = "manual"
STATUS_MISSING_RESULT = "missing_result"

STATUS_LABELS = {
    STATUS_ABSENT: "尚无结果，可直接写入",
    STATUS_AUTO: "自动生成，可覆盖",
    STATUS_MANUAL: "已人工精修，默认跳过",
    STATUS_MISSING_RESULT: "重推没有产出这一帧",
}


class AdoptError(RuntimeError):
    pass


@dataclass
class AdoptionItem:
    frame_name: str
    result_path: Path
    target_path: Path
    status: str

    @property
    def protected(self) -> bool:
        """默认不采纳。人工帧要保护, 没有重推结果的帧无从采纳。"""
        return self.status in (STATUS_MANUAL, STATUS_MISSING_RESULT)

    @property
    def adoptable(self) -> bool:
        return self.status != STATUS_MISSING_RESULT

    @property
    def label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


def _guard_target_dir(save_dir: Path) -> None:
    """硬拦截: 不许把采纳目标指向原始推理输出目录。

    `_mask` 是第一次推理的结果, 是唯一的对照基准。一旦被覆盖就再也回不去了。
    """
    name = save_dir.name
    if name.endswith("_mask"):
        raise AdoptError(
            f"拒绝写入 {name}/ —— 这是第一次推理的原始输出, 必须保留作对照。\n"
            "采纳的目标应该是 _mask_refined/。"
        )


def classify_frame(save_dir: Path, frame_name: str, metadata: Dict) -> str:
    target = save_dir / frame_name
    if not target.exists():
        return STATUS_ABSENT
    frame = FramePaths(
        index=0,
        frame_name=frame_name,
        original_path=target,
        mask_path=None,
        save_path=target,
    )
    return STATUS_AUTO if _is_current_file_still_auto_generated(frame, metadata) else STATUS_MANUAL


def plan_adoption(result_dir, save_dir, frame_names: Sequence[str]) -> List[AdoptionItem]:
    """列出每帧会发生什么。**只读, 不动任何文件。**"""
    result_dir = Path(result_dir)
    save_dir = Path(save_dir)
    _guard_target_dir(save_dir)

    metadata = _load_auto_metadata(save_dir)
    items: List[AdoptionItem] = []
    for raw_name in frame_names:
        frame_name = Path(raw_name).with_suffix(".png").name
        result_path = result_dir / frame_name
        target_path = save_dir / frame_name
        if not result_path.exists():
            status = STATUS_MISSING_RESULT
        else:
            status = classify_frame(save_dir, frame_name, metadata)
        items.append(AdoptionItem(frame_name, result_path, target_path, status))
    return items


def summarize_plan(items: Iterable[AdoptionItem]) -> Dict[str, object]:
    items = list(items)
    by_status: Dict[str, List[str]] = {}
    for item in items:
        by_status.setdefault(item.status, []).append(item.frame_name)
    return {
        "total": len(items),
        "default_adopt": [i.frame_name for i in items if not i.protected],
        "protected": [i.frame_name for i in items if i.protected],
        "by_status": by_status,
        "manual_frames": by_status.get(STATUS_MANUAL, []),
    }


def apply_adoption(
    items: Sequence[AdoptionItem],
    selected: Optional[Iterable[str]] = None,
    method: str = "repair",
) -> Dict[str, object]:
    """把选中的帧从 result/ 复制进 save_dir。

    `selected=None` 表示"只采纳默认可采纳的帧"(即跳过全部人工帧)。
    要覆盖人工帧, 必须把帧名显式列进 `selected` —— 这个显式动作就是用户的确认。
    """
    lookup = {item.frame_name: item for item in items}
    if selected is None:
        chosen = [item.frame_name for item in items if not item.protected]
    else:
        chosen = [Path(n).with_suffix(".png").name for n in selected]

    written: List[str] = []
    skipped: List[str] = []
    overwritten_manual: List[str] = []

    for frame_name in chosen:
        item = lookup.get(frame_name)
        if item is None or not item.adoptable:
            skipped.append(frame_name)
            continue
        item.target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item.result_path, item.target_path)
        # 打上可追溯的来源标记, 同时把这帧标回"自动生成" ——
        # 它确实是模型产物, 后续再修复时不该被当成人工劳动保护起来。
        mark_auto_generated_mask(item.target_path, method)
        written.append(frame_name)
        if item.status == STATUS_MANUAL:
            overwritten_manual.append(frame_name)

    for item in items:
        if item.frame_name not in chosen:
            skipped.append(item.frame_name)

    return {
        "written": written,
        "skipped": skipped,
        "overwritten_manual": overwritten_manual,
        "written_count": len(written),
        "skipped_count": len(skipped),
    }
