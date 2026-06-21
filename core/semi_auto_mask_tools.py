from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from utils.cv_image_io import cv_imread, cv_imwrite
from utils.path_utils import to_filesystem_path


ProgressCallback = Optional[Callable[[int, int], bool]]
AUTO_META_FILENAME = "_semi_auto_meta.json"
SOURCE_MANUAL = "manual"
SOURCE_AUTO = "auto_generated"


@dataclass
class FramePaths:
    index: int
    frame_name: str
    original_path: Path
    mask_path: Optional[Path]
    save_path: Path

    @property
    def has_original_mask(self) -> bool:
        return _path_exists(self.mask_path)

    @property
    def has_saved_mask(self) -> bool:
        return _path_exists(self.save_path)


@dataclass
class ComponentSample:
    frame_index: int
    frame_name: str
    label: int
    keep_ratio: float
    removed_ratio: float
    area_ratio: float
    width_ratio: float
    height_ratio: float
    aspect_ratio: float
    fill_ratio: float
    center_x_ratio: float
    center_y_ratio: float
    touch_left: float
    touch_right: float
    touch_top: float
    touch_bottom: float
    edge_touch_ratio: float

    def feature_vector(self) -> np.ndarray:
        aspect_feature = min(np.log1p(self.aspect_ratio) / np.log(21.0), 1.5)
        return np.asarray(
            [
                self.area_ratio,
                self.width_ratio,
                self.height_ratio,
                aspect_feature,
                self.fill_ratio,
                self.center_x_ratio,
                self.center_y_ratio,
                self.touch_left,
                self.touch_right,
                self.touch_top,
                self.touch_bottom,
                self.edge_touch_ratio,
            ],
            dtype=np.float32,
        )


@dataclass
class BoundaryCleanupModel:
    feature_mean: np.ndarray
    feature_std: np.ndarray
    positive_vectors: np.ndarray
    negative_vectors: np.ndarray
    threshold: float
    require_edge_touch: bool
    positive_count: int
    negative_count: int

    def score(self, feature_vector: np.ndarray) -> float:
        scaled = (feature_vector - self.feature_mean) / self.feature_std
        pos_distance = _nearest_distance(self.positive_vectors, scaled)
        if self.negative_vectors.size == 0:
            return -pos_distance
        neg_distance = _nearest_distance(self.negative_vectors, scaled)
        return neg_distance - pos_distance

    def predict(self, sample: ComponentSample) -> Tuple[bool, float]:
        if self.require_edge_touch and sample.edge_touch_ratio <= 0.0:
            return False, float("-inf")
        score = self.score(sample.feature_vector())
        return score >= self.threshold, score


@dataclass
class BoundaryCleanupResult:
    processed_frames: int
    skipped_frames: int
    removed_components: int
    removed_pixels: int
    training_frame_count: int
    positive_component_count: int
    negative_component_count: int


@dataclass
class PropagationResult:
    processed_frames: int
    skipped_frames: int
    seed_frame_count: int
    propagated_pixels: int
    average_match_score: float
    reused_generated_reference_count: int


@dataclass
class ComponentRemovalResult:
    processed_frames: int
    skipped_frames: int
    removed_components: int
    removed_pixels: int


@dataclass
class MaskInitializationResult:
    copied_frames: int
    overwritten_frames: int
    skipped_existing_frames: int
    missing_source_frames: int


def build_frame_paths(
    original_files: Sequence[str],
    mask_files: Sequence[str],
    save_dir: str,
) -> List[FramePaths]:
    save_root = Path(save_dir)
    mask_map = {Path(path).name: Path(path) for path in mask_files}
    mask_stem_map: Dict[str, Path] = {}
    for path in mask_files:
        mask_path = Path(path)
        mask_stem_map.setdefault(mask_path.stem, mask_path)

    frames: List[FramePaths] = []
    for index, original in enumerate(original_files):
        original_path = Path(original)
        frame_name = original_path.with_suffix(".png").name
        mask_path = (
            mask_map.get(original_path.name)
            or mask_map.get(frame_name)
            or mask_stem_map.get(original_path.stem)
        )
        frames.append(
            FramePaths(
                index=index,
                frame_name=frame_name,
                original_path=original_path,
                mask_path=mask_path,
                save_path=save_root / frame_name,
            )
        )
    return frames


def saved_frame_indices(frames: Sequence[FramePaths]) -> List[int]:
    metadata = _load_auto_metadata_for_frames(frames)
    return [frame.index for frame in frames if frame.has_saved_mask and not _is_current_file_still_auto_generated(frame, metadata)]


def differing_saved_frame_indices(
    frames: Sequence[FramePaths],
    min_changed_pixels: int = 1,
) -> List[int]:
    metadata = _load_auto_metadata_for_frames(frames)
    indices: List[int] = []
    for frame in frames:
        if not frame.has_saved_mask:
            continue
        if _is_current_file_still_auto_generated(frame, metadata):
            continue
        source_mask = _load_binary_mask(frame.mask_path)
        saved_mask = _load_binary_mask(frame.save_path)
        if source_mask is None or saved_mask is None:
            continue
        if int(np.count_nonzero(source_mask != saved_mask)) >= min_changed_pixels:
            indices.append(frame.index)
    return indices


def explicit_seed_indices(frames: Sequence[FramePaths]) -> List[int]:
    metadata = _load_auto_metadata_for_frames(frames)
    indices: List[int] = []
    for frame in frames:
        if not frame.has_saved_mask:
            continue
        if _is_current_file_still_auto_generated(frame, metadata):
            continue
        entry = metadata.get(frame.frame_name, {})
        if bool(entry.get("explicit_seed")):
            indices.append(frame.index)
    return indices


def resolve_seed_indices(
    frames: Sequence[FramePaths],
    min_changed_pixels: int = 1,
) -> Tuple[List[int], str]:
    explicit = explicit_seed_indices(frames)
    if explicit:
        return explicit, "explicit"
    differing = differing_saved_frame_indices(frames, min_changed_pixels=min_changed_pixels)
    if differing:
        return differing, "edited"
    saved = saved_frame_indices(frames)
    return saved, "saved"


def list_seed_candidates(
    frames: Sequence[FramePaths],
    min_changed_pixels: int = 1,
) -> List[Dict[str, object]]:
    metadata = _load_auto_metadata_for_frames(frames)
    rows: List[Dict[str, object]] = []
    for frame in frames:
        if not frame.has_saved_mask:
            continue
        if _is_current_file_still_auto_generated(frame, metadata):
            continue
        entry = metadata.get(frame.frame_name, {})
        changed_pixels = 0
        source_mask = _load_binary_mask(frame.mask_path)
        saved_mask = _load_binary_mask(frame.save_path)
        if source_mask is not None and saved_mask is not None:
            changed_pixels = int(np.count_nonzero(source_mask != saved_mask))
        rows.append(
            {
                "index": frame.index,
                "frame_name": frame.frame_name,
                "explicit_seed": bool(entry.get("explicit_seed")),
                "source": str(entry.get("source", SOURCE_MANUAL)),
                "method": str(entry.get("method", "")),
                "changed_pixels": changed_pixels,
                "is_changed": changed_pixels >= min_changed_pixels,
            }
        )
    return rows


def describe_frame_seed_state(
    frames: Sequence[FramePaths],
    frame_index: int,
    min_changed_pixels: int = 1,
) -> Dict[str, object]:
    if frame_index < 0 or frame_index >= len(frames):
        return {
            "has_saved_mask": False,
            "is_manual_seed": False,
            "is_effective_seed": False,
            "is_auto_generated": False,
            "is_changed": False,
            "mode": "none",
            "label": "Seed: 否",
        }

    frame = frames[frame_index]
    if not frame.has_saved_mask:
        return {
            "has_saved_mask": False,
            "is_manual_seed": False,
            "is_effective_seed": False,
            "is_auto_generated": False,
            "is_changed": False,
            "mode": "none",
            "label": "Seed: 否",
        }

    metadata = _load_auto_metadata_for_frames(frames)
    if _is_current_file_still_auto_generated(frame, metadata):
        return {
            "has_saved_mask": True,
            "is_manual_seed": False,
            "is_effective_seed": False,
            "is_auto_generated": True,
            "is_changed": False,
            "mode": "auto_generated",
            "label": "Seed: 自动结果",
        }

    entry = metadata.get(frame.frame_name, {})
    is_manual_seed = bool(entry.get("explicit_seed"))
    source_mask = _load_binary_mask(frame.mask_path)
    saved_mask = _load_binary_mask(frame.save_path)
    changed_pixels = 0
    if source_mask is not None and saved_mask is not None:
        changed_pixels = int(np.count_nonzero(source_mask != saved_mask))
    is_changed = changed_pixels >= min_changed_pixels
    effective_indices, mode = resolve_seed_indices(frames, min_changed_pixels=min_changed_pixels)
    is_effective_seed = frame_index in set(effective_indices)

    if is_manual_seed:
        label = "Seed: 手动指定"
    elif is_effective_seed and mode == "edited":
        label = "Seed: 自动使用"
    elif is_effective_seed and mode == "saved":
        label = "Seed: 自动候选"
    elif frame.has_saved_mask:
        label = "Seed: 已保存"
    else:
        label = "Seed: 否"

    return {
        "has_saved_mask": True,
        "is_manual_seed": is_manual_seed,
        "is_effective_seed": is_effective_seed,
        "is_auto_generated": False,
        "is_changed": is_changed,
        "changed_pixels": changed_pixels,
        "mode": mode,
        "label": label,
    }


def learn_boundary_cleanup_model(
    frames: Sequence[FramePaths],
    training_indices: Sequence[int],
    min_component_area: int = 6,
    removed_keep_ratio: float = 0.25,
    kept_keep_ratio: float = 0.75,
) -> Tuple[BoundaryCleanupModel, List[ComponentSample]]:
    frame_map = {frame.index: frame for frame in frames}
    positive_samples: List[ComponentSample] = []
    negative_samples: List[ComponentSample] = []
    all_samples: List[ComponentSample] = []

    for index in training_indices:
        frame = frame_map.get(index)
        if frame is None or not frame.has_saved_mask or not frame.has_original_mask:
            continue
        source_mask = _load_binary_mask(frame.mask_path)
        saved_mask = _load_binary_mask(frame.save_path)
        if source_mask is None or saved_mask is None:
            continue
        samples = _extract_component_samples(
            source_mask,
            saved_mask,
            frame.index,
            frame.frame_name,
            min_component_area=min_component_area,
        )
        for sample in samples:
            all_samples.append(sample)
            if sample.keep_ratio <= removed_keep_ratio and sample.edge_touch_ratio > 0.0:
                positive_samples.append(sample)
            elif sample.keep_ratio >= kept_keep_ratio:
                negative_samples.append(sample)

    if not positive_samples:
        raise RuntimeError("没有学到可删掉的边界阳性组件。请先手动修几张明显删边界的帧。")

    all_vectors = np.vstack([sample.feature_vector() for sample in positive_samples + negative_samples])
    feature_mean = all_vectors.mean(axis=0)
    feature_std = all_vectors.std(axis=0)
    feature_std[feature_std < 1e-6] = 1.0

    positive_vectors = np.vstack(
        [((sample.feature_vector() - feature_mean) / feature_std) for sample in positive_samples]
    )
    negative_vectors = (
        np.vstack([((sample.feature_vector() - feature_mean) / feature_std) for sample in negative_samples])
        if negative_samples
        else np.empty((0, positive_vectors.shape[1]), dtype=np.float32)
    )

    model = BoundaryCleanupModel(
        feature_mean=feature_mean.astype(np.float32),
        feature_std=feature_std.astype(np.float32),
        positive_vectors=positive_vectors.astype(np.float32),
        negative_vectors=negative_vectors.astype(np.float32),
        threshold=0.0,
        require_edge_touch=(sum(sample.edge_touch_ratio > 0.0 for sample in positive_samples) / len(positive_samples)) >= 0.8,
        positive_count=len(positive_samples),
        negative_count=len(negative_samples),
    )

    positive_scores = np.asarray([model.score(sample.feature_vector()) for sample in positive_samples], dtype=np.float32)
    negative_scores = (
        np.asarray([model.score(sample.feature_vector()) for sample in negative_samples], dtype=np.float32)
        if negative_samples
        else np.empty((0,), dtype=np.float32)
    )

    if negative_scores.size > 0:
        threshold = (float(negative_scores.max()) + float(positive_scores.min())) * 0.5
        if float(negative_scores.max()) >= float(positive_scores.min()):
            threshold = float(np.percentile(positive_scores, 25))
    else:
        threshold = float(np.percentile(positive_scores, 30))
    model.threshold = threshold
    return model, all_samples


def apply_boundary_cleanup(
    frames: Sequence[FramePaths],
    model: BoundaryCleanupModel,
    start_index: int,
    end_index: int,
    training_indices: Sequence[int],
    min_component_area: int = 6,
    skip_existing_saves: bool = True,
    progress_callback: ProgressCallback = None,
) -> BoundaryCleanupResult:
    metadata = _load_auto_metadata_for_frames(frames)
    target_frames = [frame for frame in frames if start_index <= frame.index <= end_index]
    skipped_frames = 0
    processed_frames = 0
    removed_components = 0
    removed_pixels = 0
    training_set = set(training_indices)

    for offset, frame in enumerate(target_frames):
        if progress_callback and progress_callback(offset, len(target_frames)) is False:
            break
        if frame.index in training_set:
            skipped_frames += 1
            continue
        if skip_existing_saves and frame.has_saved_mask and not _is_current_file_still_auto_generated(frame, metadata):
            skipped_frames += 1
            continue

        base_mask_path = frame.save_path if frame.has_saved_mask else frame.mask_path
        base_mask = _load_binary_mask(base_mask_path)
        if base_mask is None:
            skipped_frames += 1
            continue

        num_labels, label_map, stats, _ = cv2.connectedComponentsWithStats(base_mask, connectivity=8)
        output_mask = base_mask.copy()
        frame_removed_components = 0
        frame_removed_pixels = 0
        image_height, image_width = base_mask.shape
        for label in range(1, num_labels):
            area = int(stats[label, cv2.CC_STAT_AREA])
            if area < min_component_area:
                continue
            component_mask = label_map == label
            sample = _component_sample_from_mask(component_mask, image_height, image_width, frame.index, frame.frame_name, label)
            should_remove, _ = model.predict(sample)
            if should_remove:
                output_mask[component_mask] = 0
                frame_removed_components += 1
                frame_removed_pixels += int(np.count_nonzero(component_mask))

        _save_binary_mask(frame.save_path, output_mask)
        _record_auto_generated_mask(frame.save_path, method="boundary_cleanup")
        removed_components += frame_removed_components
        removed_pixels += frame_removed_pixels
        processed_frames += 1

    return BoundaryCleanupResult(
        processed_frames=processed_frames,
        skipped_frames=skipped_frames,
        removed_components=removed_components,
        removed_pixels=removed_pixels,
        training_frame_count=len(training_set),
        positive_component_count=model.positive_count,
        negative_component_count=model.negative_count,
    )


def propagate_masks_by_template(
    frames: Sequence[FramePaths],
    start_index: int,
    end_index: int,
    seed_indices: Sequence[int],
    target_indices: Optional[Sequence[int]] = None,
    search_radius: int = 24,
    template_margin: int = 8,
    skip_existing_saves: bool = True,
    allow_generated_masks_as_references: bool = False,
    progress_callback: ProgressCallback = None,
) -> PropagationResult:
    metadata = _load_auto_metadata_for_frames(frames)
    if not seed_indices:
        raise RuntimeError("没有找到可用的已修帧。请先保存几张 mask_new 再追踪。")

    frame_map = {frame.index: frame for frame in frames}
    known_masks: Dict[int, np.ndarray] = {}
    for seed_index in seed_indices:
        frame = frame_map.get(seed_index)
        if frame is None:
            continue
        seed_mask = _load_binary_mask(frame.save_path if frame.has_saved_mask else frame.mask_path)
        if seed_mask is not None:
            known_masks[seed_index] = seed_mask
            if frame.has_saved_mask:
                _save_binary_mask(frame.save_path, seed_mask)

    if not known_masks:
        raise RuntimeError("已找到种子帧，但没有读到有效的二值 mask。")

    if target_indices is None:
        candidate_indices = [index for index in range(start_index, end_index + 1) if index not in set(seed_indices)]
    else:
        candidate_indices = [index for index in target_indices if start_index <= index <= end_index and index not in set(seed_indices)]
    order = sorted(candidate_indices, key=lambda idx: min(abs(idx - seed) for seed in known_masks))

    processed_frames = 0
    skipped_frames = 0
    propagated_pixels = 0
    match_scores: List[float] = []
    reused_generated_reference_count = 0

    for offset, target_index in enumerate(order):
        if progress_callback and progress_callback(offset, len(order)) is False:
            break
        frame = frame_map.get(target_index)
        if frame is None:
            skipped_frames += 1
            continue
        if skip_existing_saves and frame.has_saved_mask and not _is_current_file_still_auto_generated(frame, metadata):
            skipped_frames += 1
            continue

        target_image = _load_grayscale(frame.original_path)
        if target_image is None:
            skipped_frames += 1
            continue

        ref_index = min(known_masks, key=lambda seed: abs(seed - target_index))
        ref_frame = frame_map[ref_index]
        ref_image = _load_grayscale(ref_frame.original_path)
        ref_mask = known_masks[ref_index]
        if ref_image is None:
            skipped_frames += 1
            continue

        dynamic_radius = int(search_radius * max(1, min(4, abs(target_index - ref_index))))
        predicted_mask, match_score = _propagate_single_mask(
            ref_image=ref_image,
            ref_mask=ref_mask,
            target_image=target_image,
            search_radius=dynamic_radius,
            template_margin=template_margin,
        )
        _save_binary_mask(frame.save_path, predicted_mask)
        _record_auto_generated_mask(frame.save_path, method="mask_tracking")
        if allow_generated_masks_as_references:
            known_masks[target_index] = predicted_mask
            reused_generated_reference_count += 1
        propagated_pixels += int(np.count_nonzero(predicted_mask))
        match_scores.append(match_score)
        processed_frames += 1

    average_match_score = float(np.mean(match_scores)) if match_scores else 0.0
    return PropagationResult(
        processed_frames=processed_frames,
        skipped_frames=skipped_frames,
        seed_frame_count=len(seed_indices),
        propagated_pixels=propagated_pixels,
        average_match_score=average_match_score,
        reused_generated_reference_count=reused_generated_reference_count,
    )


def _extract_component_samples(
    source_mask: np.ndarray,
    edited_mask: np.ndarray,
    frame_index: int,
    frame_name: str,
    min_component_area: int,
) -> List[ComponentSample]:
    num_labels, label_map, stats, _ = cv2.connectedComponentsWithStats(source_mask, connectivity=8)
    image_height, image_width = source_mask.shape
    samples: List[ComponentSample] = []
    for label in range(1, num_labels):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < min_component_area:
            continue
        component_mask = label_map == label
        keep_ratio = float(np.count_nonzero(component_mask & (edited_mask > 0)) / max(1, area))
        sample = _component_sample_from_mask(component_mask, image_height, image_width, frame_index, frame_name, label)
        sample.keep_ratio = keep_ratio
        sample.removed_ratio = 1.0 - keep_ratio
        samples.append(sample)
    return samples


def _component_sample_from_mask(
    component_mask: np.ndarray,
    image_height: int,
    image_width: int,
    frame_index: int,
    frame_name: str,
    label: int,
) -> ComponentSample:
    ys, xs = np.where(component_mask)
    x1, x2 = int(xs.min()), int(xs.max())
    y1, y2 = int(ys.min()), int(ys.max())
    width = x2 - x1 + 1
    height = y2 - y1 + 1
    area = int(component_mask.sum())
    area_ratio = area / float(max(1, image_height * image_width))
    fill_ratio = area / float(max(1, width * height))
    touch_left = float(x1 <= 0)
    touch_right = float(x2 >= image_width - 1)
    touch_top = float(y1 <= 0)
    touch_bottom = float(y2 >= image_height - 1)
    edge_touch_ratio = (touch_left + touch_right + touch_top + touch_bottom) / 4.0
    return ComponentSample(
        frame_index=frame_index,
        frame_name=frame_name,
        label=label,
        keep_ratio=0.0,
        removed_ratio=0.0,
        area_ratio=float(area_ratio),
        width_ratio=float(width / max(1, image_width)),
        height_ratio=float(height / max(1, image_height)),
        aspect_ratio=float(width / max(1, height)),
        fill_ratio=float(fill_ratio),
        center_x_ratio=float((x1 + x2 + 1) * 0.5 / max(1, image_width)),
        center_y_ratio=float((y1 + y2 + 1) * 0.5 / max(1, image_height)),
        touch_left=touch_left,
        touch_right=touch_right,
        touch_top=touch_top,
        touch_bottom=touch_bottom,
        edge_touch_ratio=float(edge_touch_ratio),
    )


def _nearest_distance(vectors: np.ndarray, sample: np.ndarray) -> float:
    if vectors.size == 0:
        return float("inf")
    distances = np.linalg.norm(vectors - sample[None, :], axis=1)
    return float(np.min(distances))


def _path_exists(path: Optional[Path | str]) -> bool:
    if path is None:
        return False
    try:
        return os.path.exists(to_filesystem_path(path))
    except OSError:
        return False


def _ensure_parent_dir(path: Path | str) -> None:
    parent = Path(path).parent
    os.makedirs(to_filesystem_path(parent), exist_ok=True)


def _read_image(path: Optional[Path | str], flags: int) -> Optional[np.ndarray]:
    return cv_imread(path, flags) if path is not None else None


def _write_image(path: Path | str, image: np.ndarray) -> None:
    if not cv_imwrite(path, image):
        raise RuntimeError(f"Failed to write image: {path}")


def _load_binary_mask(path: Optional[Path]) -> Optional[np.ndarray]:
    image = _read_image(path, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    return (image > 127).astype(np.uint8)


def _load_grayscale(path: Path) -> Optional[np.ndarray]:
    return _read_image(path, cv2.IMREAD_GRAYSCALE)


def _save_binary_mask(path: Path, mask: np.ndarray) -> None:
    _write_image(path, (mask > 0).astype(np.uint8) * 255)


def _auto_meta_path(save_dir: Path) -> Path:
    return save_dir / AUTO_META_FILENAME


def _load_auto_metadata(save_dir: Path) -> Dict[str, Dict[str, str]]:
    meta_path = _auto_meta_path(save_dir)
    if not _path_exists(meta_path):
        return {}
    try:
        with open(to_filesystem_path(meta_path), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {}
    frames = payload.get("frames", {})
    return frames if isinstance(frames, dict) else {}


def _write_auto_metadata(save_dir: Path, frames_payload: Dict[str, Dict[str, str]]) -> None:
    meta_path = _auto_meta_path(save_dir)
    payload = {"frames": frames_payload}
    _ensure_parent_dir(meta_path)
    with open(to_filesystem_path(meta_path), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def mark_manual_saved_mask(path: Path | str) -> None:
    path = Path(path)
    if not _path_exists(path):
        return
    save_dir = path.parent
    frames_payload = _load_auto_metadata(save_dir)
    existing = frames_payload.get(path.name, {})
    frames_payload[path.name] = {
        "source": SOURCE_MANUAL,
        "method": "manual_save",
        "sha1": _file_sha1(path),
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "explicit_seed": bool(existing.get("explicit_seed")),
    }
    _write_auto_metadata(save_dir, frames_payload)


def set_explicit_seed(path: Path | str, enabled: bool) -> None:
    path = Path(path)
    if not _path_exists(path):
        raise FileNotFoundError(str(path))
    save_dir = path.parent
    frames_payload = _load_auto_metadata(save_dir)
    existing = dict(frames_payload.get(path.name, {}))
    if not existing:
        existing = {
            "source": SOURCE_MANUAL,
            "method": "manual_save",
            "sha1": _file_sha1(path),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
    else:
        existing["sha1"] = _file_sha1(path)
        existing["saved_at"] = datetime.now(timezone.utc).isoformat()
    existing["explicit_seed"] = bool(enabled)
    frames_payload[path.name] = existing
    _write_auto_metadata(save_dir, frames_payload)


def clear_all_explicit_seeds(save_dir: Path | str) -> int:
    save_dir = Path(save_dir)
    frames_payload = _load_auto_metadata(save_dir)
    cleared = 0
    for frame_name, entry in frames_payload.items():
        if bool(entry.get("explicit_seed")):
            entry["explicit_seed"] = False
            cleared += 1
    if cleared:
        _write_auto_metadata(save_dir, frames_payload)
    return cleared


def mark_auto_generated_mask(path: Path | str, method: str) -> None:
    _record_auto_generated_mask(Path(path), method=method)


def initialize_saved_masks_from_sources(
    frames: Sequence[FramePaths],
    overwrite_existing: bool = False,
    progress_callback: ProgressCallback = None,
) -> MaskInitializationResult:
    copied_frames = 0
    overwritten_frames = 0
    skipped_existing_frames = 0
    missing_source_frames = 0

    total = len(frames)
    for position, frame in enumerate(frames):
        if progress_callback and not progress_callback(position, total):
            break

        source_path = frame.mask_path
        if source_path is None or not _path_exists(source_path):
            missing_source_frames += 1
            continue

        if _path_exists(frame.save_path) and not overwrite_existing:
            skipped_existing_frames += 1
            continue

        existed_before_copy = _path_exists(frame.save_path)
        _ensure_parent_dir(frame.save_path)
        shutil.copy2(to_filesystem_path(source_path), to_filesystem_path(frame.save_path))
        mark_manual_saved_mask(frame.save_path)
        copied_frames += 1
        if existed_before_copy and overwrite_existing:
            overwritten_frames += 1

    return MaskInitializationResult(
        copied_frames=copied_frames,
        overwritten_frames=overwritten_frames,
        skipped_existing_frames=skipped_existing_frames,
        missing_source_frames=missing_source_frames,
    )


def remove_small_connected_components(
    mask: np.ndarray,
    max_component_area: int,
) -> Tuple[np.ndarray, int, int]:
    binary_mask = (mask > 0).astype(np.uint8)
    num_labels, label_map, stats, _ = cv2.connectedComponentsWithStats(binary_mask, connectivity=8)
    output_mask = binary_mask.copy()
    removed_components = 0
    removed_pixels = 0

    for label in range(1, num_labels):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area <= max_component_area:
            component_mask = label_map == label
            output_mask[component_mask] = 0
            removed_components += 1
            removed_pixels += int(np.count_nonzero(component_mask))

    return output_mask, removed_components, removed_pixels


def batch_remove_small_components(
    mask_files: Sequence[str],
    output_dir: str,
    max_component_area: int,
    progress_callback: ProgressCallback = None,
    auto_method: str = "remove_small_components",
) -> ComponentRemovalResult:
    output_root = Path(output_dir)
    os.makedirs(to_filesystem_path(output_root), exist_ok=True)

    processed_frames = 0
    skipped_frames = 0
    removed_components = 0
    removed_pixels = 0

    for index, mask_path in enumerate(mask_files):
        if progress_callback and progress_callback(index, len(mask_files)) is False:
            break

        input_path = Path(mask_path)
        base_mask = _load_binary_mask(input_path)
        if base_mask is None:
            skipped_frames += 1
            continue

        filtered_mask, frame_removed_components, frame_removed_pixels = remove_small_connected_components(
            base_mask,
            max_component_area=max_component_area,
        )
        output_path = output_root / input_path.name
        _save_binary_mask(output_path, filtered_mask)
        mark_auto_generated_mask(output_path, method=auto_method)

        processed_frames += 1
        removed_components += frame_removed_components
        removed_pixels += frame_removed_pixels

    return ComponentRemovalResult(
        processed_frames=processed_frames,
        skipped_frames=skipped_frames,
        removed_components=removed_components,
        removed_pixels=removed_pixels,
    )


def apply_region_component_filter(
    frames: Sequence[FramePaths],
    region_mask: np.ndarray,
    start_index: int,
    end_index: int,
    remove_mode: str,
    component_mode: str = "whole_component",
    region_match_mode: str = "overlap",
    progress_callback: ProgressCallback = None,
) -> ComponentRemovalResult:
    if remove_mode not in {"inside", "outside"}:
        raise ValueError(f"Unsupported remove_mode: {remove_mode}")
    if component_mode not in {"whole_component", "partial"}:
        raise ValueError(f"Unsupported component_mode: {component_mode}")
    if region_match_mode not in {"overlap", "centroid"}:
        raise ValueError(f"Unsupported region_match_mode: {region_match_mode}")

    processed_frames = 0
    skipped_frames = 0
    removed_components = 0
    removed_pixels = 0
    target_frames = [frame for frame in frames if start_index <= frame.index <= end_index]

    for offset, frame in enumerate(target_frames):
        if progress_callback and progress_callback(offset, len(target_frames)) is False:
            break

        base_mask_path = frame.save_path if frame.has_saved_mask else frame.mask_path
        base_mask = _load_binary_mask(base_mask_path)
        if base_mask is None:
            skipped_frames += 1
            continue

        normalized_region = _normalize_region_mask(region_mask, base_mask.shape)
        num_labels, label_map, stats, centroids = cv2.connectedComponentsWithStats(base_mask, connectivity=8)
        output_mask = base_mask.copy()
        frame_removed_components = 0
        frame_removed_pixels = 0

        if component_mode == "partial":
            pixels_to_remove = normalized_region > 0 if remove_mode == "inside" else normalized_region == 0
            removed_pixel_mask = (output_mask > 0) & pixels_to_remove
            if np.any(removed_pixel_mask):
                output_mask[removed_pixel_mask] = 0
                frame_removed_pixels = int(np.count_nonzero(removed_pixel_mask))
                for label in range(1, num_labels):
                    component_mask = label_map == label
                    if np.any(removed_pixel_mask & component_mask):
                        frame_removed_components += 1
            _save_binary_mask(frame.save_path, output_mask)
            mark_auto_generated_mask(
                frame.save_path,
                method=f"region_component_filter_{remove_mode}_{component_mode}",
            )

            processed_frames += 1
            removed_components += frame_removed_components
            removed_pixels += frame_removed_pixels
            continue

        for label in range(1, num_labels):
            component_mask = label_map == label
            if region_match_mode == "centroid":
                centroid_x, centroid_y = centroids[label]
                x = int(np.clip(round(float(centroid_x)), 0, normalized_region.shape[1] - 1))
                y = int(np.clip(round(float(centroid_y)), 0, normalized_region.shape[0] - 1))
                is_inside = bool(normalized_region[y, x] > 0)
            else:
                is_inside = bool(np.any(normalized_region[component_mask] > 0))
            should_remove = is_inside if remove_mode == "inside" else not is_inside
            if not should_remove:
                continue

            output_mask[component_mask] = 0
            frame_removed_components += 1
            frame_removed_pixels += int(np.count_nonzero(component_mask))

        _save_binary_mask(frame.save_path, output_mask)
        mark_auto_generated_mask(
            frame.save_path,
            method=f"region_component_filter_{remove_mode}_{component_mode}_{region_match_mode}",
        )

        processed_frames += 1
        removed_components += frame_removed_components
        removed_pixels += frame_removed_pixels

    return ComponentRemovalResult(
        processed_frames=processed_frames,
        skipped_frames=skipped_frames,
        removed_components=removed_components,
        removed_pixels=removed_pixels,
    )


def clear_saved_results_after_index(
    frames: Sequence[FramePaths],
    anchor_index: int,
    include_anchor: bool = False,
) -> Dict[str, int]:
    if not frames:
        return {"cleared_files": 0, "updated_metadata": 0, "skipped_frames": 0}
    threshold = anchor_index if include_anchor else anchor_index + 1
    save_dir = frames[0].save_path.parent
    frames_payload = _load_auto_metadata(save_dir)
    cleared_files = 0
    updated_metadata = 0
    skipped_frames = 0
    for frame in frames:
        if frame.index < threshold:
            continue

        base_mask = _load_binary_mask(frame.save_path if frame.has_saved_mask else frame.mask_path)
        if base_mask is None:
            base_image = _load_grayscale(frame.original_path)
            if base_image is None:
                skipped_frames += 1
                continue
            empty_mask = np.zeros(base_image.shape[:2], dtype=np.uint8)
        else:
            empty_mask = np.zeros(base_mask.shape, dtype=np.uint8)

        _save_binary_mask(frame.save_path, empty_mask)
        frames_payload[frame.frame_name] = {
            "source": SOURCE_MANUAL,
            "method": "clear_after_frame",
            "sha1": _file_sha1(frame.save_path),
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "explicit_seed": False,
        }
        cleared_files += 1
        updated_metadata += 1

    _write_auto_metadata(save_dir, frames_payload)
    return {"cleared_files": cleared_files, "updated_metadata": updated_metadata, "skipped_frames": skipped_frames}


def _load_auto_metadata_for_frames(frames: Sequence[FramePaths]) -> Dict[str, Dict[str, str]]:
    if not frames:
        return {}
    return _load_auto_metadata(frames[0].save_path.parent)


def _file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with open(to_filesystem_path(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record_auto_generated_mask(path: Path, method: str) -> None:
    if not _path_exists(path):
        return
    save_dir = path.parent
    frames_payload = _load_auto_metadata(save_dir)
    frames_payload[path.name] = {
        "source": SOURCE_AUTO,
        "method": method,
        "sha1": _file_sha1(path),
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "explicit_seed": False,
    }
    _write_auto_metadata(save_dir, frames_payload)


def _is_current_file_still_auto_generated(frame: FramePaths, metadata: Dict[str, Dict[str, str]]) -> bool:
    if not frame.has_saved_mask:
        return False
    entry = metadata.get(frame.frame_name)
    if not entry:
        return False
    source = entry.get("source", "")
    method = entry.get("method", "")
    if source and source != SOURCE_AUTO:
        return False
    if not source and not method:
        return False
    expected_sha1 = entry.get("sha1", "")
    if not expected_sha1:
        return False
    try:
        current_sha1 = _file_sha1(frame.save_path)
    except Exception:
        return False
    return current_sha1 == expected_sha1


def _normalize_region_mask(region_mask: np.ndarray, target_shape: Tuple[int, int]) -> np.ndarray:
    binary_region = (region_mask > 0).astype(np.uint8)
    if binary_region.shape == target_shape:
        return binary_region
    resized = cv2.resize(
        binary_region,
        (target_shape[1], target_shape[0]),
        interpolation=cv2.INTER_NEAREST,
    )
    return (resized > 0).astype(np.uint8)


def _mask_bbox(mask: np.ndarray, margin: int = 0) -> Optional[Tuple[int, int, int, int]]:
    ys, xs = np.where(mask > 0)
    if ys.size == 0 or xs.size == 0:
        return None
    y1 = max(0, int(ys.min()) - margin)
    y2 = min(mask.shape[0], int(ys.max()) + 1 + margin)
    x1 = max(0, int(xs.min()) - margin)
    x2 = min(mask.shape[1], int(xs.max()) + 1 + margin)
    return x1, y1, x2, y2


def _translate_binary_mask(mask: np.ndarray, dx: int, dy: int) -> np.ndarray:
    output = np.zeros_like(mask)
    height, width = mask.shape
    src_x1 = max(0, -dx)
    src_y1 = max(0, -dy)
    dst_x1 = max(0, dx)
    dst_y1 = max(0, dy)
    copy_width = min(width - src_x1, width - dst_x1)
    copy_height = min(height - src_y1, height - dst_y1)
    if copy_width <= 0 or copy_height <= 0:
        return output
    output[dst_y1 : dst_y1 + copy_height, dst_x1 : dst_x1 + copy_width] = mask[
        src_y1 : src_y1 + copy_height,
        src_x1 : src_x1 + copy_width,
    ]
    return output


def _propagate_single_mask(
    ref_image: np.ndarray,
    ref_mask: np.ndarray,
    target_image: np.ndarray,
    search_radius: int,
    template_margin: int,
) -> Tuple[np.ndarray, float]:
    bbox = _mask_bbox(ref_mask, margin=template_margin)
    if bbox is None:
        return np.zeros_like(ref_mask), 0.0
    x1, y1, x2, y2 = bbox
    template = ref_image[y1:y2, x1:x2]
    if template.size == 0:
        return ref_mask.copy(), 0.0

    template_height, template_width = template.shape
    pad = max(search_radius + max(template_width, template_height), template_margin + 4)
    padded_target = cv2.copyMakeBorder(
        target_image,
        pad,
        pad,
        pad,
        pad,
        borderType=cv2.BORDER_REFLECT_101,
    )

    search_x1 = x1 + pad - search_radius
    search_y1 = y1 + pad - search_radius
    search_x2 = x2 + pad + search_radius
    search_y2 = y2 + pad + search_radius
    search_region = padded_target[search_y1:search_y2, search_x1:search_x2]

    if search_region.shape[0] < template_height or search_region.shape[1] < template_width:
        return ref_mask.copy(), 0.0

    method = cv2.TM_CCOEFF_NORMED
    template_f32 = template.astype(np.float32)
    search_f32 = search_region.astype(np.float32)
    result = cv2.matchTemplate(search_f32, template_f32, method)
    if result.size == 0:
        return ref_mask.copy(), 0.0

    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    best_x = search_x1 + max_loc[0] - pad
    best_y = search_y1 + max_loc[1] - pad
    dx = int(best_x - x1)
    dy = int(best_y - y1)
    translated = _translate_binary_mask(ref_mask, dx, dy)
    return translated, float(max_val)
