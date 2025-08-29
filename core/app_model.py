# Finetuning/core/app_model.py

import configparser
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPainterPath
import os

class AppModel(QObject):
    """应用程序的核心数据模型，负责管理所有状态。"""
    config_loaded = pyqtSignal()
    files_changed = pyqtSignal(int)
    index_changed = pyqtSignal(int)
    mask_updated = pyqtSignal()
    tool_changed = pyqtSignal(str)
    auto_save_changed = pyqtSignal(bool)
    high_contrast_changed = pyqtSignal(bool)
    
    # --- START: 核心状态重构 ---
    # 新增信号，用于通知UI显示模式已改变
    display_mode_changed = pyqtSignal(str) 
    # 废弃: show_mask_changed, mask_display_changed
    # --- END: 核心状态重构 ---

    def __init__(self, config_path=None):
        super().__init__()
        
        if config_path is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(current_dir)
            self.config_path = os.path.join(project_root, 'config', 'settings.ini')
        else:
            self.config_path = config_path

        self.config = configparser.ConfigParser()
        
        # 内部状态变量
        self._original_files = []
        self._denoised_files = []
        self._mask_files = []
        self._current_index = -1
        self._undo_stack = {}
        self._redo_stack = {}
        self.max_undo_steps = 128
        
        # 功能状态
        self._selection_tool = "lasso"  
        self._auto_save = False
        self._high_contrast = False
        self._mask_invert = False

        # --- START: 核心状态重构 ---
        # 使用单一状态 self._display_mode 替换 self._show_mask 和 self._mask_display_style
        # 可选值: "hide", "area", "contour", "ants"
        self._display_mode = "contour"  # 默认以绿色轮廓模式启动
        # --- END: 核心状态重构 ---
        
        self.load_config()

    def load_config(self):
        read_files = self.config.read(self.config_path, encoding='utf-8')
        if not read_files:
            print(f"警告: 配置文件未找到或为空: {self.config_path}")
        self.config_loaded.emit()
    
    # --- 栈方法 (无变动) ---
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
    
    # --- 文件与索引 (无变动) ---
    @property
    def current_index(self):
        return self._current_index

    def set_current_index(self, index):
        if 0 <= index < len(self._original_files):
            if self._current_index != index:
                self._current_index = index
                self.index_changed.emit(index)

    def increment_index(self):
        self.set_current_index(self._current_index + 1)

    def decrement_index(self):
        self.set_current_index(self._current_index - 1)

    def update_file_lists(self, original_path, denoised_path, mask_path):
        from ..core.image_manager import ImageManager
        self._original_files = ImageManager.get_image_files(original_path)
        self._denoised_files = ImageManager.get_image_files(denoised_path) if denoised_path else []
        self._mask_files = ImageManager.get_image_files(mask_path) if mask_path else []
        
        total_files = len(self._original_files)
        self.files_changed.emit(total_files)
        if total_files > 0:
            self.set_current_index(0)
        else:
            self.set_current_index(-1)
            
    # --- 状态属性与方法 ---
    @property
    def selection_tool(self):
        return self._selection_tool

    def set_selection_tool(self, tool):
        if tool in ["lasso", "polygon", "erase"] and self._selection_tool != tool:
            self._selection_tool = tool
            self.tool_changed.emit(tool)
    
    # --- START: 核心状态重构 ---
    @property
    def display_mode(self):
        return self._display_mode

    def set_display_mode(self, mode: str):
        """设置新的显示模式"""
        valid_modes = ["hide", "area", "contour", "ants"]
        if mode in valid_modes and self._display_mode != mode:
            self._display_mode = mode
            self.display_mode_changed.emit(mode)
    # --- END: 核心状态重构 ---
            
    @property
    def auto_save(self):
        return self._auto_save

    def set_auto_save(self, auto: bool):
        if self._auto_save != auto:
            self._auto_save = auto
            self.auto_save_changed.emit(self._auto_save)
            
    @property
    def high_contrast(self):
        return self._high_contrast

    def set_high_contrast(self, enabled: bool):
        if self._high_contrast != enabled:
            self._high_contrast = enabled
            self.high_contrast_changed.emit(enabled)

    @property
    def mask_invert(self):
        return self._mask_invert

    def set_mask_invert(self, invert: bool):
        if self._mask_invert != invert:
            self._mask_invert = invert
            # 任何显示相关的都通过 mask_updated 触发刷新
            self.mask_updated.emit()
    
    def get_path(self, key):
        return self.config['Paths'].get(key)
        
    def get_keybinding(self, key):
        return self.config['Keybindings'].get(key, '')