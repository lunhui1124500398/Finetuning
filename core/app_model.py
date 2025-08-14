# Finetuning/core/app_model.py

import configparser
from PyQt6.QtCore import QObject, pyqtSignal
import os

class AppModel(QObject):
    """应用程序的核心数据模型，负责管理所有状态。"""
    # 定义信号，当状态改变时发射，通知UI更新
    config_loaded = pyqtSignal()
    files_changed = pyqtSignal(int)  # int: total number of files
    index_changed = pyqtSignal(int)  # int: current index
    mask_updated = pyqtSignal()      # 当Mask被修改时
    mode_changed = pyqtSignal(str)   # str: "draw" or "erase"
    show_mask_changed = pyqtSignal(bool)
    auto_save_changed = pyqtSignal(bool)
    mask_display_changed = pyqtSignal()
    high_contrast_changed = pyqtSignal(bool)

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

        # 栈状态初始化
        self._undo_stack = {} # key: index, value: list of QPixmaps
        self._redo_stack = {} # 同上
        self.max_undo_steps = 128
                
        # 功能状态
        self._drawing_mode = "draw" 
        self._show_mask = True
        self._auto_save = False
        self._high_contrast = False
        self._mask_display_style = "area"
        self._mask_invert = False

        self.load_config()

    def load_config(self):
        read_files = self.config.read(self.config_path, encoding='utf-8')
        if not read_files:
            print(f"警告: 配置文件未找到或为空: {self.config_path}")
        self.config_loaded.emit()
    
    # --- 栈方法 (省略未修改部分) ---
    def push_undo_state(self, index, mask_pixmap):
        if index not in self._undo_stack:
            self._undo_stack[index] = []
        if index in self._redo_stack:
            self._redo_stack[index].clear()
        self._undo_stack[index].append(mask_pixmap.copy())
        if len(self._undo_stack[index]) > self.max_undo_steps:
            self._undo_stack[index].pop(0)

    def pop_undo_state(self, index):
        if index in self._undo_stack and self._undo_stack[index]:
            return self._undo_stack[index].pop()
        return None
    
    # --- 文件与索引 (省略未修改部分) ---
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
            
    # --- START: 核心修正 - 使用带状态检查的 set 方法 ---
    
    @property
    def drawing_mode(self):
        return self._drawing_mode

    def set_drawing_mode(self, mode):
        if mode in ["draw", "erase"] and self._drawing_mode != mode:
            self._drawing_mode = mode
            self.mode_changed.emit(mode)
            # 联动逻辑：进入绘图/橡皮模式时，自动切换到轮廓视图以便观察
            if self.mask_display_style != "contour":
                self.set_mask_display_style("contour")
            
    @property
    def show_mask(self):
        return self._show_mask

    def set_show_mask(self, show: bool):
        """【修正】明确设置显示状态，而不是翻转"""
        if self._show_mask != show:
            self._show_mask = show
            self.show_mask_changed.emit(self._show_mask)

    @property
    def auto_save(self):
        return self._auto_save

    def set_auto_save(self, auto: bool):
        """【修正】明确设置自动保存状态，而不是翻转"""
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
    def mask_display_style(self):
        return self._mask_display_style

    def set_mask_display_style(self, style):
        if style in ["area", "contour"] and self._mask_display_style != style:
            self._mask_display_style = style
            self.mask_display_changed.emit()

    @property
    def mask_invert(self):
        return self._mask_invert

    def set_mask_invert(self, invert: bool):
        if self._mask_invert != invert:
            self._mask_invert = invert
            self.mask_display_changed.emit()

    # --- END: 核心修正 ---
    
    def get_path(self, key):
        return self.config['Paths'].get(key)
        
    def get_keybinding(self, key):
        return self.config['Keybindings'].get(key, '')