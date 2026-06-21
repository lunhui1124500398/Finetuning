# Finetuning/core/app_model.py

import configparser
import os

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPainterPath, QTransform

from utils.helpers import get_base_path


class AppModel(QObject):
    """Central application state shared across the UI."""

    config_loaded = pyqtSignal()
    files_changed = pyqtSignal(int)
    index_changed = pyqtSignal(int)
    mask_updated = pyqtSignal()
    mask_saved = pyqtSignal(int)
    tool_changed = pyqtSignal(str)
    auto_save_changed = pyqtSignal(bool)
    eraser_size_changed = pyqtSignal(int)
    selection_add_mode_changed = pyqtSignal(bool)
    zoom_lock_changed = pyqtSignal(bool)
    display_mode_changed = pyqtSignal(str)
    image_source_changed = pyqtSignal()
    mask_source_changed = pyqtSignal(bool)
    effects_changed = pyqtSignal()
    preview_effects_changed = pyqtSignal()
    seed_visual_mode_changed = pyqtSignal(str)

    DEFAULT_KEYBINDINGS = {
        "next_image": "D; Right",
        "prev_image": "A; Left",
        "save": "Ctrl+S",
        "save_and_next": "S",
        "next_binary_dataset": "N",
        "previous_binary_dataset": "B",
        "skip_current_binary_dataset": "Ctrl+Shift+K",
        "draw_mode": "Q",
        "polygon_mode": "P",
        "erase_mode": "E",
        "clear_mask": "W",
        "toggle_mask": "H",
        "auto_save": "X",
        "high_contrast": "C",
        "open_effects_panel": "Shift+C",
        "import_files": "I",
        "toggle_image_source": "Space",
        "toggle_path_panel": "J",
        "toggle_mask_source": "T",
        "cycle_seed_visual_mode": "F6",
    }

    def __init__(self, config_path=None):
        super().__init__()

        if config_path is None:
            project_root = get_base_path()
            self.config_path = os.path.join(project_root, "config", "settings.ini")
        else:
            self.config_path = config_path

        self.config = configparser.ConfigParser()

        self._original_files = []
        self._denoised_files = []
        self._mask_files = []
        self._current_index = -1
        self._undo_stack = {}
        self._redo_stack = {}
        self.max_undo_steps = 128

        self._selection_tool = "lasso"
        self._auto_save = False
        self._eraser_size = 10
        self._selection_add_mode = False
        self._effect_settings = {
            "manual_enabled": False,
            "manual_min": 0,
            "manual_max": 255,
            "manual_brightness": 0,
            "manual_contrast": 0,
            "manual_gamma": 1.0,
            "algo_enabled": False,
            "algo_name": "clahe",
            "clahe_clip_limit": 2.0,
            "clahe_grid_size": 8,
        }
        self._mask_invert = False
        self._is_zoom_locked = False
        self._last_transform = None
        self._last_h_scroll = 0
        self._last_v_scroll = 0
        self._display_mode = "ants"
        self._show_denoised = False
        self._effects_bypassed = False
        self._load_from_save_path = True
        self.show_slider_seed_markers = True
        self.show_preview_seed_badges = True
        self.seed_visual_mode = "balanced"

        self.load_config()
        self._preview_effect_settings = self._effect_settings.copy()

    def load_config(self):
        read_files = self.config.read(self.config_path, encoding="utf-8")
        if not read_files:
            print(f"Warning: config file not found or empty: {self.config_path}")
        self._ensure_default_keybindings()
        self._ensure_preview_settings()
        self.config_loaded.emit()
        self._eraser_size = self.config.getint("Drawing", "eraser_size", fallback=10)
        self.seed_visual_mode = self.config.get("Preview", "seed_visual_mode", fallback="balanced")

    def _ensure_default_keybindings(self):
        """Backfill shortcut entries so older configs can edit new actions."""
        if not self.config.has_section("Keybindings"):
            self.config.add_section("Keybindings")
        for key, value in self.DEFAULT_KEYBINDINGS.items():
            if not self.config.has_option("Keybindings", key):
                self.config.set("Keybindings", key, value)

    def _ensure_preview_settings(self):
        if not self.config.has_section("Preview"):
            self.config.add_section("Preview")
        if not self.config.has_option("Preview", "seed_visual_mode"):
            self.config.set("Preview", "seed_visual_mode", "balanced")

    def push_undo_state(self, index, path: QPainterPath):
        if index not in self._undo_stack:
            self._undo_stack[index] = []
        if index in self._redo_stack:
            self._redo_stack[index].clear()
        self._undo_stack[index].append(QPainterPath(path))
        if len(self._undo_stack[index]) > self.max_undo_steps:
            self._undo_stack[index].pop(0)

    def pop_undo_state(self, index):
        if index in self._undo_stack and self._undo_stack[index]:
            return self._undo_stack[index].pop()
        return None

    @property
    def current_index(self):
        return self._current_index

    def set_current_index(self, index):
        if index == -1:
            if self._current_index != -1:
                self._current_index = -1
                self.index_changed.emit(-1)
            return
        if 0 <= index < len(self._original_files):
            if self._current_index != index:
                self._current_index = index
                self.index_changed.emit(index)

    def increment_index(self):
        if not self._original_files:
            self.set_current_index(-1)
            return
        next_index = 0 if self._current_index < 0 else self._current_index + 1
        self.set_current_index(min(next_index, len(self._original_files) - 1))

    def decrement_index(self):
        if not self._original_files:
            self.set_current_index(-1)
            return
        previous_index = 0 if self._current_index <= 0 else self._current_index - 1
        self.set_current_index(previous_index)

    def update_file_lists(self, original_path, denoised_path, mask_path):
        from core.image_manager import ImageManager

        self._original_files = ImageManager.get_image_files(original_path)
        self._denoised_files = ImageManager.get_image_files(denoised_path) if denoised_path else []
        self._mask_files = ImageManager.get_image_files(mask_path) if mask_path else []

        total_files = len(self._original_files)
        self._current_index = 0 if total_files > 0 else -1
        self._undo_stack.clear()
        self._redo_stack.clear()
        if not self._denoised_files:
            self._show_denoised = False
        self._effects_bypassed = False
        self.files_changed.emit(total_files)

    @property
    def selection_tool(self):
        return self._selection_tool

    def set_selection_tool(self, tool):
        valid_tools = ["lasso", "polygon", "erase", "lasso_subtract", "polygon_subtract"]
        if tool in valid_tools and self._selection_tool != tool:
            self._selection_tool = tool
            self.tool_changed.emit(tool)

    @property
    def selection_add_mode(self):
        return self._selection_add_mode

    def set_selection_add_mode(self, enabled: bool):
        if self._selection_add_mode != enabled:
            self._selection_add_mode = enabled
            self.selection_add_mode_changed.emit(enabled)

    @property
    def display_mode(self):
        return self._display_mode

    def set_display_mode(self, mode: str):
        valid_modes = ["hide", "area", "contour", "ants"]
        if mode in valid_modes and self._display_mode != mode:
            self._display_mode = mode
            self.display_mode_changed.emit(mode)

    def toggle_mask_visibility(self):
        """Quick-toggle between marching ants and hidden mask."""
        self.set_display_mode("hide" if self._display_mode == "ants" else "ants")

    @property
    def auto_save(self):
        return self._auto_save

    def set_auto_save(self, auto: bool):
        if self._auto_save != auto:
            self._auto_save = auto
            self.auto_save_changed.emit(self._auto_save)

    @property
    def eraser_size(self):
        return self._eraser_size

    def set_eraser_size(self, size: int):
        size = max(1, min(size, 200))
        if self._eraser_size != size:
            self._eraser_size = size
            self.eraser_size_changed.emit(size)

    @property
    def effect_settings(self):
        return self._effect_settings

    @staticmethod
    def settings_have_active_effects(settings: dict) -> bool:
        if not settings:
            return False
        if settings.get("algo_enabled", False):
            return True
        if not settings.get("manual_enabled", False):
            return False
        return any([
            settings.get("manual_min", 0) != 0,
            settings.get("manual_max", 255) != 255,
            settings.get("manual_brightness", 0) != 0,
            settings.get("manual_contrast", 0) != 0,
            abs(float(settings.get("manual_gamma", 1.0)) - 1.0) > 1e-6,
        ])

    def has_active_effects(self, include_preview: bool = True) -> bool:
        if self.settings_have_active_effects(self._effect_settings):
            return True
        return include_preview and self.settings_have_active_effects(self._preview_effect_settings)

    def update_effect_settings(self, settings: dict):
        self._effect_settings.update(settings)
        self._preview_effect_settings = self._effect_settings.copy()
        self._effects_bypassed = False
        print("Applied image effects:", self._effect_settings)
        self.effects_changed.emit()

    def toggle_quick_contrast(self):
        """Toggle CLAHE enhancement without opening the effects dialog."""
        enable_algo = not self._effect_settings.get("algo_enabled", False)
        self._effect_settings.update({
            "algo_enabled": enable_algo,
            "algo_name": "clahe",
            "clahe_clip_limit": self._effect_settings.get("clahe_clip_limit", 2.0),
            "clahe_grid_size": self._effect_settings.get("clahe_grid_size", 8),
        })
        self._preview_effect_settings = self._effect_settings.copy()
        self._effects_bypassed = False
        self.effects_changed.emit()
        return enable_algo

    @property
    def preview_effect_settings(self):
        return self._preview_effect_settings

    def update_preview_effect_settings(self, preview_settings: dict):
        self._preview_effect_settings.update(preview_settings)
        if not self.has_active_effects(include_preview=True):
            self._effects_bypassed = False
        self.preview_effects_changed.emit()

    def revert_preview_to_last_settings(self):
        self._preview_effect_settings = self._effect_settings.copy()
        if not self.has_active_effects(include_preview=True):
            self._effects_bypassed = False
        self.preview_effects_changed.emit()

    @property
    def mask_invert(self):
        return self._mask_invert

    def set_mask_invert(self, invert: bool):
        if self._mask_invert != invert:
            self._mask_invert = invert
            self.mask_updated.emit()

    @property
    def show_denoised(self):
        return self._show_denoised

    @property
    def effects_bypassed(self):
        return self._effects_bypassed

    def toggle_image_source(self):
        if self.has_active_effects(include_preview=True):
            self._effects_bypassed = not self._effects_bypassed
            state = "raw" if self._effects_bypassed else "adjusted"
            print(f"Image effects comparison toggled. Showing {state} image.")
            self.image_source_changed.emit()
            return
        if self._denoised_files:
            self._show_denoised = not self._show_denoised
            print(f"Image source toggled. show_denoised={self._show_denoised}")
            self.image_source_changed.emit()

    @property
    def load_from_save_path(self):
        return self._load_from_save_path

    def toggle_mask_source(self):
        self._load_from_save_path = not self._load_from_save_path
        source = "save_path" if self._load_from_save_path else "mask_path"
        print(f"Mask source toggled. Preferred source: {source}")
        self.mask_source_changed.emit(self._load_from_save_path)

    def get_path(self, key):
        return self.config["Paths"].get(key)

    def get_keybinding(self, key):
        return self.config["Keybindings"].get(key, "")

    def set_seed_visual_mode(self, mode: str):
        valid_modes = {"fast", "balanced", "info"}
        if mode not in valid_modes:
            return
        if self.seed_visual_mode != mode:
            self.seed_visual_mode = mode
            self.seed_visual_mode_changed.emit(mode)

    @property
    def is_zoom_locked(self):
        return self._is_zoom_locked

    def set_zoom_locked(self, locked: bool):
        if self._is_zoom_locked != locked:
            self._is_zoom_locked = locked
            self.zoom_lock_changed.emit(locked)
            if not locked:
                self.clear_zoom_state()

    def store_zoom_state(self, transform: QTransform, h_scroll: int, v_scroll: int):
        self._last_transform = transform
        self._last_h_scroll = h_scroll
        self._last_v_scroll = v_scroll

    def get_zoom_state(self):
        return self._last_transform, self._last_h_scroll, self._last_v_scroll

    def clear_zoom_state(self):
        self._last_transform = None
        self._last_h_scroll = 0
        self._last_v_scroll = 0
