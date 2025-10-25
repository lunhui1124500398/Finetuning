# utils/helpers.py

"""
这个文件用于存放通用的辅助函数。
例如，可以在这里添加复杂的数学计算、数据转换等与核心逻辑或UI不直接相关的函数。
"""

# Finetuning/utils/helpers.py
import sys
import os

def get_base_path():
    """
    获取资源文件的基础路径。
    - 在开发环境中，返回项目根目录 (Finetuning 文件夹)。
    - 在 PyInstaller 打包的 'onefile' 模式下，返回解压后的临时目录 (sys._MEIPASS)。
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # 运行在 PyInstaller 打包后的 .exe 中 (onefile 模式)
        # sys._MEIPASS 是 PyInstaller 创建的临时文件夹
        return sys._MEIPASS
    else:
        # 运行在普通的 Python 环境中 (开发模式)
        # 我们假设 main.py 在项目根目录
        return os.path.dirname(os.path.abspath(sys.argv[0])) 
        ##### 注意：如果 main.py 不在根目录，这里可能需要调整
        
        # 鉴于你的 main.py 在根目录，这个方法是可行的。
        #
        # 另一种更健壮的开发模式路径（如果 helpers.py 在 utils/ 下）:
        # return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))