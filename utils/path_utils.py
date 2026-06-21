from __future__ import annotations

import os
from pathlib import Path
from typing import Union


PathLike = Union[str, os.PathLike]


def to_display_path(path: PathLike) -> str:
    """Return a user-facing Windows path without the extended-length prefix."""
    text = str(path)
    if os.name != "nt":
        return text
    if text.startswith("\\\\?\\UNC\\"):
        return "\\\\" + text[8:]
    if text.startswith("\\\\?\\"):
        return text[4:]
    return text


def to_filesystem_path(path: PathLike) -> str:
    """
    Convert a path to a form that bypasses Windows MAX_PATH for Python file I/O.

    The returned path should be used only for filesystem calls. Store and show
    `to_display_path(path)` instead so configs remain readable.
    """
    text = to_display_path(path)
    if os.name != "nt" or not text:
        return text
    if text.startswith("\\\\?\\"):
        return text
    absolute = os.path.abspath(text)
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute.lstrip("\\")
    return "\\\\?\\" + absolute


def filesystem_path(path: PathLike) -> Path:
    return Path(to_filesystem_path(path))


def absolute_display_path(path: PathLike) -> str:
    text = to_display_path(path)
    if not text:
        return ""
    return to_display_path(os.path.abspath(text))
