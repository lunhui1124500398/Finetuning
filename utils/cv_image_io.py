from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Sequence

import cv2
import numpy as np

from utils.path_utils import to_filesystem_path


def cv_imread(path: str | os.PathLike, flags: int = cv2.IMREAD_UNCHANGED) -> Optional[np.ndarray]:
    """Read an image through Python file I/O so Windows unicode/long paths work."""
    if not path:
        return None
    fs_path = to_filesystem_path(path)
    try:
        if not os.path.exists(fs_path):
            return None
        with open(fs_path, "rb") as handle:
            encoded = np.frombuffer(handle.read(), dtype=np.uint8)
    except OSError:
        return None
    if encoded.size == 0:
        return None
    return cv2.imdecode(encoded, flags)


def cv_imwrite(
    path: str | os.PathLike,
    image: np.ndarray,
    params: Sequence[int] | None = None,
) -> bool:
    """Write an image through Python file I/O so Windows unicode/long paths work."""
    if image is None:
        return False
    target = Path(path)
    extension = target.suffix or ".png"
    try:
        ok, encoded = cv2.imencode(extension, image, list(params or []))
        if not ok:
            return False
        os.makedirs(to_filesystem_path(target.parent), exist_ok=True)
        with open(to_filesystem_path(target), "wb") as handle:
            handle.write(encoded.tobytes())
    except OSError:
        return False
    return True


def load_grayscale(path: str | os.PathLike) -> Optional[np.ndarray]:
    return cv_imread(path, cv2.IMREAD_GRAYSCALE)


def load_binary_mask(path: str | os.PathLike, threshold: int = 127) -> Optional[np.ndarray]:
    image = load_grayscale(path)
    if image is None:
        return None
    return (image > threshold).astype(np.uint8)


def save_binary_mask(path: str | os.PathLike, mask: np.ndarray) -> bool:
    return cv_imwrite(path, (mask > 0).astype(np.uint8) * 255)
