"""
Script Loader
--------------
Dynamically loads scripts from the Useful_script directory.
Each script should define:
  - SCRIPT_NAME: str - Display name for the menu
  - run(main_window): callable - Entry point function
"""

import os
import importlib.util
import traceback


def get_smart_mask_files(model, save_dir: str):
    """
    智能获取输入 Mask 文件列表。
    
    策略（自动智能检测）：
    - 如果 save_path 中有文件，优先使用 save_path 的文件（允许脚本链式执行）
    - 否则，回退到使用 mask_path 的文件
    
    Args:
        model: AppModel 实例
        save_dir: 脚本保存结果的目录路径
        
    Returns:
        tuple: (file_list, source_name, source_path)
            - file_list: 输入文件路径列表
            - source_name: 来源名称 ("save_path" 或 "mask_path")
            - source_path: 来源目录路径
    """
    from core.image_manager import ImageManager
    
    # 检查 save_path 中是否有已保存的文件
    save_files = ImageManager.get_image_files(save_dir) if save_dir and os.path.isdir(save_dir) else []
    
    if save_files:
        # save_path 有文件，使用它们（允许在上一个脚本结果上继续处理）
        return save_files, "save_path (已处理)", save_dir
    elif model._mask_files:
        # 回退到 mask_path
        mask_path = model.get_path('mask_path')
        return model._mask_files, "mask_path (原始)", mask_path
    else:
        return [], "无", ""

def load_scripts(scripts_dir: str) -> list:
    """
    Scans the scripts_dir for .py files and loads them as modules.
    
    Args:
        scripts_dir: Absolute path to the Useful_script directory.
        
    Returns:
        A list of dicts: [{'name': str, 'description': str, 'run': callable, 'module': module}, ...]
    """
    scripts = []
    
    if not os.path.isdir(scripts_dir):
        print(f"[ScriptLoader] Warning: Directory not found: {scripts_dir}")
        return scripts
    
    # Files to skip
    skip_files = {'__init__.py', 'script_loader.py'}
    
    for filename in sorted(os.listdir(scripts_dir)):
        if not filename.endswith('.py'):
            continue
        if filename in skip_files or filename.startswith('_'):
            continue
        
        filepath = os.path.join(scripts_dir, filename)
        module_name = filename[:-3]  # Remove .py extension
        
        try:
            # Dynamic import
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                print(f"[ScriptLoader] Failed to load spec for: {filename}")
                continue
                
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Check for required attributes
            if not hasattr(module, 'SCRIPT_NAME'):
                print(f"[ScriptLoader] Warning: {filename} has no SCRIPT_NAME, skipping.")
                continue
            if not hasattr(module, 'run') or not callable(module.run):
                print(f"[ScriptLoader] Warning: {filename} has no run() function, skipping.")
                continue
            
            script_info = {
                'name': module.SCRIPT_NAME,
                'description': getattr(module, 'SCRIPT_DESCRIPTION', ''),
                'run': module.run,
                'module': module,
                'filename': filename
            }
            scripts.append(script_info)
            print(f"[ScriptLoader] Loaded: {module.SCRIPT_NAME} ({filename})")
            
        except Exception as e:
            print(f"[ScriptLoader] Error loading {filename}: {e}")
            import traceback
            traceback.print_exc()
    
    return scripts
