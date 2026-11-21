"""
Core utilities and shared state for the MEX API backend.
"""

from .config import (
    PROJECT_ROOT, RESOURCES_DIR, BASE_PATH, BACKEND_DIR,
    MEXCLI_PATH, HSDRAW_EXE, MEX_PROJECT_PATH,
    STORAGE_PATH, OUTPUT_PATH, LOGS_PATH,
    VANILLA_ASSETS_DIR, PROCESSOR_DIR, SERVICES_DIR,
    get_subprocess_args
)
from .state import (
    get_mex_manager, set_project_path, reload_mex_manager, get_project_files_dir,
    get_socketio, set_socketio, get_current_project_path
)
from .constants import (
    CHAR_PREFIXES, VANILLA_COSTUME_COUNT, VANILLA_ISO_MD5, STAGE_NAMES,
    VANILLA_CSS_COLOR_ORDER,
)
from .helpers import (
    calculate_auto_compression, cleanup_output_folder, get_folder_size,
    migrate_legacy_character_names, convert_windows_to_wsl_path
)

__all__ = [
    # config
    'PROJECT_ROOT', 'RESOURCES_DIR', 'BASE_PATH', 'BACKEND_DIR',
    'MEXCLI_PATH', 'HSDRAW_EXE', 'MEX_PROJECT_PATH',
    'STORAGE_PATH', 'OUTPUT_PATH', 'LOGS_PATH',
    'VANILLA_ASSETS_DIR', 'PROCESSOR_DIR', 'SERVICES_DIR',
    'get_subprocess_args',
    # state
    'get_mex_manager', 'set_project_path', 'reload_mex_manager', 'get_project_files_dir',
    'get_socketio', 'set_socketio', 'get_current_project_path',
    # constants
    'CHAR_PREFIXES', 'VANILLA_COSTUME_COUNT', 'VANILLA_ISO_MD5', 'STAGE_NAMES',
    'VANILLA_CSS_COLOR_ORDER',
    # helpers
    'calculate_auto_compression', 'cleanup_output_folder', 'get_folder_size',
    'migrate_legacy_character_names', 'convert_windows_to_wsl_path',
]
