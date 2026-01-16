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
