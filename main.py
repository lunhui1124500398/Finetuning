import sys
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # 应用样式表
    try:
        with open('ui/resources/styles.qss', 'r') as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print("Stylesheet not found, using default style.")

    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec())