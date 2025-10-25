# Finetuning/core/app_model.py

import configparser
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPainterPath, QTransform
import os

class AppModel(QObject):
    """应用程序的核心数据模型，负责管理所有状态。"""
    config_loaded = pyqtSignal()
    files_changed = pyqtSignal(int)
    index_changed = pyqtSignal(int)
    mask_updated = pyqtSignal()
    tool_changed = pyqtSignal(str)
    auto_save_changed = pyqtSignal(bool)
    eraser_size_changed = pyqtSignal(int) #新增：橡皮擦大小
    # high_contrast_changed = pyqtSignal(bool)

    zoom_lock_changed = pyqtSignal(bool) # 缩放锁定状态
    
    # --- START: 核心状态重构 ---
    # 新增信号，用于通知UI显示模式已改变
    display_mode_changed = pyqtSignal(str) 
    # 废弃: show_mask_changed, mask_display_changed
    # --- END: 核心状态重构 ---

    # 底图信号
    image_source_changed = pyqtSignal()
    mask_source_changed = pyqtSignal(bool) #新增：用于切换mask
    effects_changed = pyqtSignal() # 新的信号，通知UI参数改变
    preview_effects_changed = pyqtSignal() # 预览参数改变信号

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
        self._eraser_size = 10 # 默认值
        # 废除self._high_contrast = False
        # 新增: 统一的效果参数字典
        self._effect_settings = {
            'manual_enabled': False,
            'manual_min': 0,
            'manual_max': 255,
            'manual_brightness': 0,  # 范围可设为 -100 到 100
            'manual_contrast': 0,    # 范围可设为 -100 到 100

            'algo_enabled': False,
            'algo_name': 'clahe',  # 默认算法, 可选 'clahe', 'equalize_hist' 等
            'clahe_clip_limit': 2.0,
            'clahe_grid_size': 8
        }
        self._mask_invert = False

        self._is_zoom_locked = False
        self._last_transform = None
        self._last_h_scroll = 0
        self._last_v_scroll = 0

        # --- START: 核心状态重构 ---
        # 使用单一状态 self._display_mode 替换 self._show_mask 和 self._mask_display_style
        # 可选值: "hide", "area", "contour", "ants"
        self._display_mode = "ants"  # 默认以蚂蚁线模式启动
        # --- END: 核心状态重构 ---

        self._show_denoised = False # false显示原图
        # 默认优先加载已经保存的mask
        self._load_from_save_path = True

        self.load_config()
        # 用于实时预览的临时设置，不影响最终状态和撤销栈
        self._preview_effect_settings = self._effect_settings.copy()

    def load_config(self):
        read_files = self.config.read(self.config_path, encoding='utf-8')
        if not read_files:
            print(f"警告: 配置文件未找到或为空: {self.config_path}")
        self.config_loaded.emit()
        # 从配置文件初始化橡皮擦大小
        self._eraser_size = self.config.getint("Drawing", 'eraser_size', fallback=10)
    
    # --- 栈方法 ---
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
    
    # --- 文件与索引 ---
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
        from core.image_manager import ImageManager
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
    def eraser_size(self):
        return self._eraser_size

    def set_eraser_size(self, size: int):
        """设置橡皮擦大小并发出信号"""
        size = max(1, min(size, 200)) # 限制大小在 1-200
        if self._eraser_size != size:
            self._eraser_size = size
            self.eraser_size_changed.emit(size)
            
    # @property
    # def high_contrast(self):
    #     return self._high_contrast

    # def set_high_contrast(self, enabled: bool):
    #     if self._high_contrast != enabled:
    #         self._high_contrast = enabled
    #         self.high_contrast_changed.emit(enabled)

    @property
    def effect_settings(self):
        """获取当前正式的效果设置"""
        return self._effect_settings

    def update_effect_settings(self, settings: dict):
        """
        正式更新效果参数，并触发重绘和撤销记录。
        """
        # 在修改前，将当前状态推入撤销栈（这一步在 canvas 中完成）
        self._effect_settings.update(settings)
        # 将预览状态与正式状态同步
        self._preview_effect_settings = self._effect_settings.copy()
        print("正式应用效果: ", self._effect_settings)
        self.effects_changed.emit()

    @property
    def preview_effect_settings(self):
        """获取用于实时预览的效果设置"""
        return self._preview_effect_settings

    def update_preview_effect_settings(self, preview_settings: dict):
        """
        仅更新预览效果参数，触发实时预览重绘，不影响正式状态。
        """
        self._preview_effect_settings.update(preview_settings)
        self.preview_effects_changed.emit()

    def revert_preview_to_last_settings(self):
        """当用户取消对话框时，将预览恢复到上一个正式状态"""
        self._preview_effect_settings = self._effect_settings.copy()
        self.preview_effects_changed.emit() # 触发一次刷新以清除预览效果

    @property
    def mask_invert(self):
        return self._mask_invert

    def set_mask_invert(self, invert: bool):
        if self._mask_invert != invert:
            self._mask_invert = invert
            # 任何显示相关的都通过 mask_updated 触发刷新
            self.mask_updated.emit()
    
    @property
    def show_denoised(self):
        """返回是否应显示去噪图"""
        return self._show_denoised

    def toggle_image_source(self):
        """切换底图显示（原图/去噪图）"""
        # 仅当存在去噪图文件时才执行切换
        if self._denoised_files:
            self._show_denoised = not self._show_denoised
            print(f"切换底图，当前显示去噪图: {self._show_denoised}")
            self.image_source_changed.emit()
    
    @property
    def load_from_save_path(self):
        """
        返回是否应该优先从save_path加载mask
        """
        return self._load_from_save_path
    
    def toggle_mask_source(self):
        """
        切换mask的加载源。
        True:优先加载save_path
        False:优先加载mask_path
        """
        self._load_from_save_path = not self._load_from_save_path
        source = "'Save Path' (已存效果)" if self._load_from_save_path else "'Mask Path' (二值化图)"
        print(f"Mask 加载源已切换，优先加载: {source}")
        self.mask_source_changed.emit(self._load_from_save_path)

    def get_path(self, key):
        return self.config['Paths'].get(key)
        
    def get_keybinding(self, key):
        return self.config['Keybindings'].get(key, '')
    
    # 视图显示相关代码
    @property
    def is_zoom_locked(self):
        return self._is_zoom_locked

    def set_zoom_locked(self, locked: bool):
        if self._is_zoom_locked != locked:
            self._is_zoom_locked = locked
            self.zoom_lock_changed.emit(locked)
            # 如果解锁，则清除已保存的状态
            if not locked:
                self.clear_zoom_state()
    
    def store_zoom_state(self, transform: QTransform, h_scroll: int, v_scroll: int):
        """存储视图状态"""
        self._last_transform = transform
        self._last_h_scroll = h_scroll
        self._last_v_scroll = v_scroll

    def get_zoom_state(self):
        """获取存储的视图状态"""
        return self._last_transform, self._last_h_scroll, self._last_v_scroll

    def clear_zoom_state(self):
        """清除存储的视图状态"""
        self._last_transform = None
        self._last_h_scroll = 0
        self._last_v_scroll = 0

    # 对比度调整相关
    # File: /core/app_model.py
    def update_effect_settings(self, settings: dict):
        """更新效果参数并通知UI刷新"""
        self._effect_settings.update(settings)
        self.effects_changed.emit()

    @property
    def effect_settings(self):
        return self._effect_settings