# Finetuning/main.py

import sys
import os # 确保导入了 os
from PyQt6.QtWidgets import QApplication
from .ui.main_window import MainWindow

if __name__ == '__main__':
    app = QApplication(sys.argv)

    # --- START: 确认这部分代码是正确的 ---
    # 获取 main.py 文件所在的目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # 构造样式表文件的正确、绝对路径
    stylesheet_path = os.path.join(script_dir, 'ui', 'resources', 'style.qss')
    
    try:
        # 使用构造好的绝对路径来打开文件
        with open(stylesheet_path, 'r', encoding='utf-8') as f: # 加上 encoding
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print(f"Stylesheet not found at '{stylesheet_path}', using default style.")
    # --- END: 确认这部分代码是正确的 ---

    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec())