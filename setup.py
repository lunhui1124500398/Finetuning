from setuptools import setup

APP = ['main.py']
DATA_FILES = [
    'config',      # 包含整个config文件夹
    'ui/resources' # 包含整个resources文件夹
]
OPTIONS = {
    'argv_emulation': True,
    'iconfile': 'ui/resources/icons/app_icon.png', # 指定应用图标
    'packages': ['cv2', 'PyQt6', 'numpy'], # 显式包含一些可能被遗漏的库
    'includes': [],
    'plist': {
        'CFBundleName': 'Finetuning',
        'CFBundleDisplayName': 'Finetuning',
        'CFBundleVersion': '1.0.0',
        'CFBundleIdentifier': 'com.yourcompany.finetuning', # 建议使用唯一标识
        'NSHumanReadableCopyright': 'Copyright © 2025, Your Name'
    }
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)