import configparser
from PyQt6.QtCore import QObject, pyqtSignal

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
    # ... 其他需要的信号

    def __init__(self, config_path='config/settings.ini'):
        super().__init__()
        self.config_path = config_path
        self.config = configparser.ConfigParser()
        
        # 内部状态变量
        self._original_files = []
        self._denoised_files = []
        self._mask_files = []
        self._current_index = -1
        
        self._drawing_mode = "draw" # "draw" or "erase"
        self._show_mask = True
        self._auto_save = False

        self.load_config()

    def load_config(self):
        self.config.read(self.config_path)
        self.config_loaded.emit()

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
        from ..core.image_manager import ImageManager # 延迟导入避免循环依赖
        self._original_files = ImageManager.get_image_files(original_path)
        self._denoised_files = ImageManager.get_image_files(denoised_path) if denoised_path else []
        self._mask_files = ImageManager.get_image_files(mask_path) if mask_path else []
        
        total_files = len(self._original_files)
        self.files_changed.emit(total_files)
        if total_files > 0:
            self.set_current_index(0)
        else:
            self.set_current_index(-1)
            
    # 使用属性和setter来自动发射信号
    @property
    def drawing_mode(self):
        return self._drawing_mode

    def set_drawing_mode(self, mode):
        if mode in ["draw", "erase"]:
            self._drawing_mode = mode
            self.mode_changed.emit(mode)
            
    @property
    def show_mask(self):
        return self._show_mask

    def toggle_show_mask(self):
        self._show_mask = not self._show_mask
        self.show_mask_changed.emit(self._show_mask)

    @property
    def auto_save(self):
        return self._auto_save

    def toggle_auto_save(self):
        self._auto_save = not self._auto_save
        self.auto_save_changed.emit(self._auto_save)
        
    def get_path(self, key):
        return self.config['Paths'].get(key)
        
    def get_keybinding(self, key):
        return self.config['Keybindings'].get(key, '')