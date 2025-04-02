# app/logic/context_manager.py
# Handles scanning files, building, and formatting context.
import os
from pathlib import Path
import logging
import time

logger = logging.getLogger(__name__)

# --- Configuration Constants (from original gemini_logic.py) ---
ALLOWED_EXTENSIONS = {'.py', '.txt', '.md', '.json', '.yaml', '.yml', '.html', '.css', '.js', '.sh', '.bash', '.zsh', '.java', '.c', '.cpp', '.h', '.hpp', '.cs', '.go', '.rb', '.php', '.sql', '.rs', '.swift', '.kt', '.scala', '.pl', '.pm', '.lua', '.toml', '.ini', '.cfg', '.conf', '.dockerfile', 'docker-compose.yml', '.gitignore', '.gitattributes', '.csv', '.tsv', '.xml', '.rst', '.tex', '.R'}
EXCLUDE_DIRS = {'__pycache__', 'venv', '.venv', '.git', '.idea', '.vscode', 'node_modules', 'build', 'dist', 'target', 'logs', '.pytest_cache', '.mypy_cache', 'site-packages', 'migrations', '__MACOSX', '.DS_Store', 'env'}
EXCLUDE_EXTENSIONS = {'.pyc', '.pyo', '.log', '.tmp', '.temp', '.bak', '.swp', '.swo', '.dll', '.so', '.dylib', '.exe', '.o', '.a', '.obj', '.lib', '.class', '.jar', '.war', '.ear', '.lock', '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar', '.iso', '.img', '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.svg', '.mp3', '.wav', '.ogg', '.flac', '.mp4', '.avi', '.mov', '.wmv', '.mkv', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp'}
MAX_FILE_SIZE_MB = 5
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# --- Helper Functions (from original gemini_logic.py) ---
# is_file_allowed, safe_read_file, scan_directory_recursively
# build_context_from_added_paths, format_context
# (Function bodies omitted for brevity - they remain unchanged from the original input file)

def is_file_allowed(file_path: Path) -> tuple[bool, str]:
    """Checks if a file should be included based on extension, name, and size."""
    # IN: file_path: Path; OUT: (allowed: bool, reason: str) # Checks file filters.
    logger.debug(f"Checking allowance for: {file_path}")
    if not file_path.is_file(): return False, "Not a file"
    # ... (rest of the logic is identical to original gemini_logic.py)
    file_suffix_lower = file_path.suffix.lower()
    file_name = file_path.name
    if file_name in ALLOWED_EXTENSIONS or file_suffix_lower in ALLOWED_EXTENSIONS:
        try:
            file_size = file_path.stat().st_size
            if file_size > MAX_FILE_SIZE_BYTES:
                 return False, f"Exceeds size limit ({MAX_FILE_SIZE_MB}MB)"
            return True, "Allowed by extension/name"
        except OSError as e: return False, f"Cannot get file size ({e})"
    if file_suffix_lower in EXCLUDE_EXTENSIONS: return False, f"Excluded extension ({file_suffix_lower})"
    # Final check seems redundant if first checks cover includes/excludes
    if file_suffix_lower not in ALLOWED_EXTENSIONS and file_name not in ALLOWED_EXTENSIONS:
         return False, f"Extension/name not in allowed list"
    logger.warning(f"File allowance check reached unexpected fallback: {file_path}")
    return False, "Unknown reason" # Fallback

def safe_read_file(file_path: Path) -> tuple[str, str | None]:
    """Reads file content safely, handling potential encoding issues."""
    # IN: file_path: Path; OUT: (content: str, status_msg: Optional[str]) # Reads file text safely.
    logger.debug(f"Reading file: {file_path}")
    try:
        content = file_path.read_text(encoding='utf-8')
        return content, None # Success
    except UnicodeDecodeError:
        logger.warning(f"UTF-8 decode failed for {file_path}. Trying latin-1.")
        try:
            content = file_path.read_text(encoding='latin-1')
            return content, "Read with fallback encoding (latin-1)"
        except Exception as e_fallback:
            logger.error(f"Fallback read error for {file_path}: {e_fallback}", exc_info=True)
            return f"Error reading file: Could not decode content - {e_fallback}", "Read error (fallback failed)"
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}", exc_info=True)
        return f"Error reading file: {e}", "Read error"

def scan_directory_recursively(directory_path: Path) -> tuple[dict, list, int]:
    """Scans a directory, returning content of allowed files and scan details."""
    # IN: directory_path: Path; OUT: (contents: dict, details: list, count: int) # Scans dir recursively.
    logger.info(f"Scanning directory recursively: {directory_path}")
    # ... (rest of the logic is identical to original gemini_logic.py)
    file_contents = {}
    scanned_files_details = []
    processed_count = 0; included_file_count = 0; skipped_file_count = 0; error_file_count = 0; excluded_dir_count = 0
    for root, dirs, files in os.walk(directory_path, topdown=True):
        root_path = Path(root)
        original_dirs = list(dirs); dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]; excluded_dirs_in_pass = set(original_dirs) - set(dirs)
        excluded_dir_count += len(excluded_dirs_in_pass)
        for excluded_dir_name in excluded_dirs_in_pass: scanned_files_details.append((str((root_path / excluded_dir_name).relative_to(directory_path)), "Skipped", f"Excluded directory ({excluded_dir_name})"))
        for filename in files:
            item_path = root_path / filename; relative_path_str = str(item_path.relative_to(directory_path))
            allowed, reason = is_file_allowed(item_path)
            if allowed:
                content, read_status = safe_read_file(item_path)
                if read_status and "error" in read_status.lower(): scanned_files_details.append((relative_path_str, "Error Reading", read_status)); error_file_count += 1
                else:
                    abs_path_key = str(item_path.resolve()); file_contents[abs_path_key] = content; status = "Included" + (f" ({read_status})" if read_status else "")
                    try: detail=f"{item_path.stat().st_size / 1024:.1f} KB"
                    except Exception: detail="Size N/A"
                    scanned_files_details.append((relative_path_str, status, detail)); included_file_count += 1
            else: scanned_files_details.append((relative_path_str, "Skipped", reason)); skipped_file_count += 1
    logger.info(f"Scan results: {included_file_count} included, {skipped_file_count} skipped, {error_file_count} errors, {excluded_dir_count} excluded dirs.")
    return file_contents, scanned_files_details, processed_count # Processed count is approximate

def build_context_from_added_paths(added_paths_set: set[str]) -> tuple[dict, list]:
    """Builds file content dictionary and display details from a set of added paths."""
    # IN: added_paths_set: set; OUT: (contents: dict, details: list) # Builds context dict from paths.
    logger.info(f"Building context from {len(added_paths_set)} added path(s).")
    # ... (rest of the logic is identical to original gemini_logic.py)
    all_file_contents = {}; all_found_files_display = []; total_items_processed = 0
    if not added_paths_set: return {}, []
    sorted_paths = sorted(list(added_paths_set))
    for path_str in sorted_paths:
        try:
            path_obj = Path(path_str).resolve()
            if path_obj.is_file():
                allowed, reason = is_file_allowed(path_obj)
                if allowed:
                    content, read_status = safe_read_file(path_obj); unique_key = str(path_obj); all_file_contents[unique_key] = content
                    try: detail=f"{path_obj.stat().st_size / 1024:.1f} KB" + (f" ({read_status})" if read_status else "")
                    except Exception: detail = "Size N/A" + (f" ({read_status})" if read_status else "")
                    all_found_files_display.append((str(path_obj), "Included", detail))
                else: all_found_files_display.append((str(path_obj), "Skipped", reason))
            elif path_obj.is_dir():
                dir_contents, dir_scan_details, processed_count = scan_directory_recursively(path_obj); total_items_processed += processed_count
                all_file_contents.update(dir_contents)
                for rel_path, status, detail in dir_scan_details: all_found_files_display.append((str(path_obj / rel_path), status, detail))
            else: all_found_files_display.append((path_str, "Error", "Path does not exist or is not file/dir"))
        except Exception as e: all_found_files_display.append((path_str, "Error", f"Processing failed: {e}"))
    all_found_files_display.sort(key=lambda x: x[0])
    logger.info(f"Context build complete. Found {len(all_file_contents)} files for context.")
    return all_file_contents, all_found_files_display

def format_context(file_contents_dict: dict, added_paths_set: set[str]) -> str:
    """Formats the collected file contents into a string for the prompt."""
    # IN: file_contents_dict, added_paths_set; OUT: str # Formats context dict to string.
    logger.debug(f"Formatting context string from {len(file_contents_dict)} files.")
    # ... (rest of the logic is identical to original gemini_logic.py)
    if not file_contents_dict: return "" # Return empty string instead of message
    context_str = "--- Local File Context ---\n\n"
    sorted_abs_paths = sorted(file_contents_dict.keys()); resolved_added_roots = {}
    for added_root in added_paths_set:
        try: resolved_added_roots[added_root] = Path(added_root).resolve()
        except Exception: pass # Ignore unresolvable paths for display formatting
    for abs_path_key in sorted_abs_paths:
        content = file_contents_dict[abs_path_key]; display_path = abs_path_key
        try:
            abs_path_obj = Path(abs_path_key)
            for added_root_str, added_root_path in resolved_added_roots.items():
                if abs_path_obj.is_relative_to(added_root_path):
                    if added_root_path.is_dir(): display_path = str(abs_path_obj.relative_to(added_root_path)); break
                    elif added_root_path.is_file() and abs_path_obj == added_root_path: display_path = abs_path_obj.name; break
            if display_path == abs_path_key: # Fallback attempt
                 for added_root_str, added_root_path in resolved_added_roots.items():
                      if abs_path_key.startswith(str(added_root_path)) and str(added_root_path) != abs_path_key:
                           orig_added_is_file = Path(added_root_str).is_file() if Path(added_root_str).exists() else False
                           if orig_added_is_file: display_path = Path(abs_path_key).name
                           else:
                                try: display_path = os.path.relpath(abs_path_key, str(added_root_path))
                                except ValueError: display_path = abs_path_key
                           break
        except Exception: display_path = abs_path_key # Fallback on error
        context_str += f"--- File: {display_path} ---\n```\n{content}\n```\n\n"
    context_str += "--- End Local File Context ---\n\n"
    return context_str

def reconstruct_gemini_history(messages: list[dict]) -> list[dict]:
    """Converts the simple message list to the Gemini API's history format."""
    # IN: messages: list[dict]; OUT: list[dict] # Converts simple chat list to API history format.
    logger.debug(f"Reconstructing Gemini history from {len(messages)} messages.")
    # ... (rest of the logic is identical to original gemini_logic.py)
    history = []; valid_roles = {"user", "assistant"}
    for i, msg in enumerate(messages):
        role = msg.get("role"); content = msg.get("content")
        if role in valid_roles and isinstance(content, str):
             api_role = "model" if role == "assistant" else "user"
             history.append({"role": api_role, "parts": [{"text": content}]})
        else: logger.warning(f"Skipping invalid message index {i} during history reconstruction.")
    return history
