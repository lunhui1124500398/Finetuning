# Finetuning/main.py

import argparse
import sys
import os
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Finetuning - Mask 精修工具")
    parser.add_argument("--session", type=str, default="",
                        help="Binary queue session JSON 文件路径，启动后自动加载")
    args, remaining = parser.parse_known_args()

    app = QApplication(remaining)

    main_win = MainWindow(session_path=args.session)
    main_win.show()
    sys.exit(app.exec())
