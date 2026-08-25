# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config', 'config'),             # <--- 添加 (源文件夹, 目标文件夹)
        ('ui/resources', 'ui/resources'),  # <--- 添加 (源文件夹, 目标文件夹)
        ('Useful_script', 'Useful_script')  # <--- 添加脚本目录，解决打包后无可用脚本问题
    ],
    hiddenimports=[
        'PyQt6.sip',    # PyQt6 经常需要显式导入
        'cv2',
        'numpy',
        'PIL',
        'ui.widgets.import_dialogs',
        'core.rg_workflow_core',
        'ui.widgets.rg_calc_dialogs'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 项目代码从未 import torch; 它是被 scipy._lib.array_api_compat 的条件导入
    # 牵连进来的, 会让 dist 从 ~400MB 膨胀到 4GB。显式排除。
    excludes=['torch', 'torchgen'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FinetuningV9.6.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='ui/resources/icons/app_icon.png',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FinetuningV9.6.0',
)
