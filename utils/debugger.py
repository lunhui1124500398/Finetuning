# /utils/debugger.py

import configparser
import os
import cv2
import numpy as np
from datetime import datetime
from PyQt6.QtGui import QPixmap, QImage

class Debugger:
    def __init__(self, config_path=None):
        if config_path is None:
            # 自动定位到项目根目录下的 config/settings.ini
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(current_dir)
            config_path = os.path.join(project_root, 'config', 'settings.ini')

        config = configparser.ConfigParser()
        config.read(config_path, encoding='utf-8')

        # 从配置文件读取调试设置
        self.is_enabled = config.getboolean('Debug', 'enabled', fallback=False)
        self.save_path = config.get('Debug', 'save_path', fallback='./debug_images')

        if self.is_enabled:
            # 如果调试模式开启，确保保存目录存在
            os.makedirs(self.save_path, exist_ok=True)
            print("--- DEBUG MODE IS ON ---")
            print(f"Debug images will be saved to: {os.path.abspath(self.save_path)}")

    def log(self, message):
        """仅在调试模式开启时打印信息"""
        if not self.is_enabled:
            return
        print(f"[DEBUG] {message}")

    def save_image(self, image_data, filename_suffix):
        """
        仅在调试模式开启时保存图像 (支持 QPixmap, QImage 和 Numpy Array)。
        文件名会自动包含时间戳以避免覆盖。
        """
        if not self.is_enabled:
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{timestamp}_{filename_suffix}.png"
        full_path = os.path.join(self.save_path, filename)

        try:
            if isinstance(image_data, QPixmap):
                image_data.save(full_path, "PNG")
                self.log(f"Saved QPixmap to '{full_path}'")
            elif isinstance(image_data, QImage):
                image_data.save(full_path, "PNG")
                self.log(f"Saved QImage to '{full_path}'")
            elif isinstance(image_data, np.ndarray):
                cv2.imwrite(full_path, image_data)
                self.log(f"Saved Numpy array to '{full_path}'")
            else:
                self.log(f"Error: Unsupported type for saving: {type(image_data)}")
        except Exception as e:
            self.log(f"Failed to save image '{full_path}'. Error: {e}")

# 创建一个全局的调试器实例，这样整个应用都可以共享它
debugger = Debugger()