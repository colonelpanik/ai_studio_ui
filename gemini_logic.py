# gemini_logic.py
# Version: 2.1.1 - Added logging
import google.generativeai as genai
import google.ai.generativelanguage as glm
from google.generativeai.types import GenerationConfig, Model
import os
from pathlib import Path
import json
import time
import datetime
import database as db  # Import database helper (ensure it's v2.1+)
import logging # Import logging

# Get a logger instance for this module
logger = logging.getLogger(__name__)

# --- Configuration (Copied for reference, single source of truth preferred) ---
# Consider moving these constants to a dedicated config.py if complexity grows
APP_VERSION = "2.1.1" # Updated version
TITLE_MAX_LENGTH = 50
ALLOWED_EXTENSIONS = {'.py', '.txt', '.md', '.json', '.yaml', '.yml', '.html', '.css', '.js', '.sh', '.bash', '.zsh', '.java', '.c', '.cpp', '.h', '.hpp', '.cs', '.go', '.rb', '.php', '.sql', '.rs', '.swift', '.kt', '.scala', '.pl', '.pm', '.lua', '.toml', '.ini', '.cfg', '.conf', '.dockerfile', 'docker-compose.yml', '.gitignore', '.gitattributes', '.csv', '.tsv', '.xml', '.rst', '.tex', '.R'}
EXCLUDE_DIRS = {'__pycache__', 'venv', '.venv', '.git', '.idea', '.vscode', 'node_modules', 'build', 'dist', 'target', 'logs', '.pytest_cache', '.mypy_cache', 'site-packages', 'migrations', '__MACOSX', '.DS_Store', 'env'}
EXCLUDE_EXTENSIONS = {'.pyc', '.pyo', '.log', '.tmp', '.temp', '.bak', '.swp', '.swo', '.dll', '.so', '.dylib', '.exe', '.o', '.a', '.obj', '.lib', '.class', '.jar', '.war', '.ear', '.lock', '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar', '.iso', '.img', '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.svg', '.mp3', '.wav', '.ogg', '.flac', '.mp4', '.avi', '.mov', '.wmv', '.mkv', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp'}
MAX_FILE_SIZE_MB = 5
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
DEFAULT_MODEL = "models/gemini-1.5-flash-latest"
DEFAULT_MAX_OUTPUT_TOKENS_SLIDER = 4096
FALLBACK_MODEL_MAX_OUTPUT_TOKENS = 65536
MAX_HISTORY_PAIRS = 15

# --- Helper Functions ---
def is_file_allowed(file_path: Path):
    """Checks if a file should be included based on extension, name, and size."""
    logger.debug(f"Checking file allowance for: {file_path}")
    if not file_path.is_file():
        logger.debug(f"Skipped (not a file): {file_path}")
        return False, "Not a file"

    file_suffix_lower = file_path.suffix.lower()
    file_name = file_path.name

    # Check explicit allows first
    if file_name in ALLOWED_EXTENSIONS or file_suffix_lower in ALLOWED_EXTENSIONS:
         # Size check still applies even if extension is allowed
        try:
            file_size = file_path.stat().st_size
            if file_size > MAX_FILE_SIZE_BYTES:
                logger.warning(f"Skipped (exceeds size limit {MAX_FILE_SIZE_MB}MB): {file_path} ({file_size / 1024 / 1024:.2f}MB)")
                return False, f"Exceeds size limit ({MAX_FILE_SIZE_MB}MB)"
            logger.debug(f"Allowed by extension/name: {file_path}")
            return True, "Allowed by extension/name"
        except OSError as e:
            logger.error(f"Cannot get file size for {file_path}: {e}", exc_info=True)
            return False, f"Cannot get file size ({e})"

    # Check excludes
    if file_suffix_lower in EXCLUDE_EXTENSIONS:
        logger.debug(f"Skipped (excluded extension '{file_suffix_lower}'): {file_path}")
        return False, f"Excluded extension ({file_suffix_lower})"

    # Final check against allowed list (if not explicitly excluded)
    # This logic seems redundant if the first check covers allowed extensions/names.
    # Let's keep it for now as per original logic but log if it triggers.
    if file_suffix_lower not in ALLOWED_EXTENSIONS and file_name not in ALLOWED_EXTENSIONS:
        logger.debug(f"Skipped (extension/name not in allowed list): {file_path}")
        return False, f"Extension/name not in allowed list"

    # Fallback - should theoretically not be reached if logic above is sound
    logger.warning(f"File allowance check reached unexpected fallback state for: {file_path}")
    return False, "Unknown reason"


def safe_read_file(file_path: Path):
    """Reads file content safely, handling potential encoding issues."""
    logger.debug(f"Attempting to read file: {file_path}")
    try:
        content = file_path.read_text(encoding='utf-8')
        logger.debug(f"Successfully read {file_path} with UTF-8.")
        return content, None
    except UnicodeDecodeError:
        logger.warning(f"UTF-8 decoding failed for {file_path}. Trying latin-1.")
        try:
            content = file_path.read_text(encoding='latin-1')
            logger.info(f"Successfully read {file_path} with fallback encoding (latin-1).")
            return content, "Read with fallback encoding (latin-1)"
        except Exception as e_fallback:
            logger.error(f"Error reading {file_path} with fallback encoding: {e_fallback}", exc_info=True)
            return f"Error reading file: Could not decode content - {e_fallback}", "Read error (fallback failed)"
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}", exc_info=True)
        return f"Error reading file: {e}", "Read error"

def scan_directory_recursively(directory_path: Path):
    """Scans a directory, returning content of allowed files and scan details."""
    logger.info(f"Scanning directory recursively: {directory_path}")
    file_contents = {}
    scanned_files_details = []
    processed_count = 0
    excluded_dir_count = 0
    included_file_count = 0
    skipped_file_count = 0
    error_file_count = 0

    for root, dirs, files in os.walk(directory_path, topdown=True):
        root_path = Path(root)
        logger.debug(f"Scanning in: {root_path}")
        processed_count += 1 + len(dirs) + len(files) # Count root dir, subdirs, files in this pass

        # Filter excluded directories before recursing into them
        original_dirs = list(dirs) # Copy before modifying
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        excluded_dirs_in_pass = set(original_dirs) - set(dirs)
        if excluded_dirs_in_pass:
            excluded_dir_count += len(excluded_dirs_in_pass)
            for excluded_dir_name in excluded_dirs_in_pass:
                 rel_path = (root_path / excluded_dir_name).relative_to(directory_path)
                 logger.debug(f"Skipping excluded directory: {rel_path}")
                 scanned_files_details.append((str(rel_path), "Skipped", f"Excluded directory ({excluded_dir_name})"))

        # Process files in the current directory
        for filename in files:
            item_path = root_path / filename
            relative_path_str = str(item_path.relative_to(directory_path))
            logger.debug(f"Processing item: {relative_path_str}")

            allowed, reason = is_file_allowed(item_path)
            if allowed:
                content, read_status = safe_read_file(item_path)
                if read_status and "error" in read_status.lower():
                    logger.error(f"Error reading file included in scan: {relative_path_str} - {read_status}")
                    scanned_files_details.append((relative_path_str, "Error Reading", read_status))
                    error_file_count += 1
                else:
                    abs_path_key = str(item_path.resolve())
                    file_contents[abs_path_key] = content
                    status = "Included" + (f" ({read_status})" if read_status else "")
                    try:
                        detail=f"{item_path.stat().st_size / 1024:.1f} KB"
                    except Exception as stat_err:
                        logger.warning(f"Could not get size for {item_path}: {stat_err}")
                        detail="Size N/A"
                    scanned_files_details.append((relative_path_str, status, detail))
                    included_file_count += 1
                    logger.debug(f"Included file: {relative_path_str}")
            else:
                scanned_files_details.append((relative_path_str, "Skipped", reason))
                skipped_file_count += 1
                logger.debug(f"Skipped file: {relative_path_str} ({reason})")

    logger.info(f"Directory scan complete: {directory_path}. Processed ~{processed_count} items.")
    logger.info(f"Scan results: {included_file_count} included, {skipped_file_count} skipped, {error_file_count} errors, {excluded_dir_count} excluded dirs.")
    return file_contents, scanned_files_details, processed_count

def build_context_from_added_paths(added_paths_set):
    """Builds file content dictionary and display details from a set of added paths."""
    logger.info(f"Building context from {len(added_paths_set)} added path(s).")
    all_file_contents = {}
    all_found_files_display = []
    total_items_processed = 0 # Approximate count from scans

    if not added_paths_set:
        logger.info("No paths provided, context will be empty.")
        return {}, []

    # Sort paths for consistent processing order
    sorted_paths = sorted(list(added_paths_set))
    logger.debug(f"Processing paths: {sorted_paths}")

    for path_str in sorted_paths:
        try:
            path_obj = Path(path_str).resolve()
            logger.debug(f"Processing resolved path: {path_obj}")
            if path_obj.is_file():
                logger.debug(f"{path_obj} is a file.")
                allowed, reason = is_file_allowed(path_obj)
                if allowed:
                    content, read_status = safe_read_file(path_obj)
                    unique_key = str(path_obj) # Use resolved absolute path as key
                    all_file_contents[unique_key] = content
                    try:
                        detail=f"{path_obj.stat().st_size / 1024:.1f} KB" + (f" ({read_status})" if read_status else "")
                    except Exception as stat_err:
                         logger.warning(f"Could not get size for {path_obj}: {stat_err}")
                         detail = "Size N/A" + (f" ({read_status})" if read_status else "")
                    all_found_files_display.append((str(path_obj), "Included", detail)) # Use absolute path for display list key
                    logger.debug(f"Included single file: {path_obj}")
                else:
                    all_found_files_display.append((str(path_obj), "Skipped", reason))
                    logger.debug(f"Skipped single file: {path_obj} ({reason})")
            elif path_obj.is_dir():
                logger.debug(f"{path_obj} is a directory, starting recursive scan.")
                dir_contents, dir_scan_details, processed_count = scan_directory_recursively(path_obj)
                total_items_processed += processed_count
                all_file_contents.update(dir_contents)
                # Update display details with absolute paths for consistency
                for rel_path, status, detail in dir_scan_details:
                    abs_p_str = str(path_obj / rel_path) # Construct absolute path for display list key
                    all_found_files_display.append((abs_p_str, status, detail))
                logger.debug(f"Finished scanning directory: {path_obj}")
            else:
                logger.warning(f"Provided path does not exist or is not a file/directory: {path_str}")
                all_found_files_display.append((path_str, "Error", "Path does not exist or is not file/dir"))
        except Exception as e:
            logger.error(f"Failed to process path '{path_str}': {e}", exc_info=True)
            all_found_files_display.append((path_str, "Error", f"Processing failed: {e}"))

    # Sort final display list by absolute path string
    all_found_files_display.sort(key=lambda x: x[0])
    logger.info(f"Context build complete. Found {len(all_file_contents)} files for context.")
    return all_file_contents, all_found_files_display

def format_context(file_contents_dict, added_paths_set):
    """Formats the collected file contents into a string for the prompt."""
    logger.debug(f"Formatting context string from {len(file_contents_dict)} files.")
    if not file_contents_dict:
        logger.debug("File content dictionary is empty, returning no context message.")
        return "No local file context provided or found."

    context_str = "--- Local File Context ---\n\n"
    sorted_abs_paths = sorted(file_contents_dict.keys())

    # Resolve added paths once for efficiency
    resolved_added_roots = {}
    for added_root in added_paths_set:
        try:
            resolved_added_roots[added_root] = Path(added_root).resolve()
        except Exception as e:
            logger.warning(f"Could not resolve added path '{added_root}' for display formatting: {e}")

    for abs_path_key in sorted_abs_paths:
        content = file_contents_dict[abs_path_key]
        display_path = abs_path_key # Default to absolute path
        try:
            abs_path_obj = Path(abs_path_key)
            # Attempt to find the relative path based on the originally added roots
            for added_root_str, added_root_path in resolved_added_roots.items():
                if abs_path_obj.is_relative_to(added_root_path):
                    # Use relative path if it's inside a *directory* added path
                    if added_root_path.is_dir():
                         display_path = str(abs_path_obj.relative_to(added_root_path))
                         break
                    # Use filename if it's relative to a *file* added path (should be the file itself)
                    elif added_root_path.is_file() and abs_path_obj == added_root_path:
                         display_path = abs_path_obj.name
                         break
            # Fallback check using startswith for edge cases (less robust)
            if display_path == abs_path_key:
                 for added_root_str, added_root_path in resolved_added_roots.items():
                     if abs_path_key.startswith(str(added_root_path)) and str(added_root_path) != abs_path_key:
                         # Check if added_root_path was originally a file path
                         orig_added_is_file = Path(added_root_str).is_file() if Path(added_root_str).exists() else False

                         if orig_added_is_file:
                              display_path = Path(abs_path_key).name
                         else:
                              try:
                                   display_path = os.path.relpath(abs_path_key, str(added_root_path))
                              except ValueError: # e.g., on Windows if paths are on different drives
                                   display_path = abs_path_key # Keep absolute path
                         break

        except Exception as path_err:
            logger.warning(f"Error determining relative display path for {abs_path_key}: {path_err}")
            display_path = abs_path_key # Fallback to absolute path on error

        context_str += f"--- File: {display_path} ---\n"
        context_str += f"```\n{content}\n```\n\n"
        logger.debug(f"Added file to context string: {display_path}")

    context_str += "--- End Local File Context ---\n\n"
    logger.debug("Finished formatting context string.")
    return context_str

def update_context_and_tokens(model_instance, added_paths_set, system_instruction):
    """Builds context, calculates token count, and returns updated state info."""
    logger.info("Updating context and calculating tokens...")
    token_count = 0
    token_count_str = "Token Count: N/A"
    context_content_dict = {}
    context_files_details = []

    # 1. Build Context
    logger.debug("Building context from added paths...")
    start_build = time.time()
    content_dict, display_details = build_context_from_added_paths(added_paths_set)
    build_time = time.time() - start_build
    logger.debug(f"Context build finished in {build_time:.2f}s. {len(content_dict)} files found.")
    context_files_details = display_details
    context_content_dict = content_dict

    # 2. Calculate Tokens
    if model_instance:
        logger.debug(f"Calculating tokens using model: {model_instance.model_name}")
        try:
            current_instruction = system_instruction.strip()
            instruction_prefix = f"--- System Instruction ---\n{current_instruction}\n--- End System Instruction ---\n\n" if current_instruction else ""
            if current_instruction:
                logger.debug(f"Including system instruction (length {len(current_instruction)}) in token count.")
            else:
                 logger.debug("No system instruction provided for token count.")

            logger.debug("Formatting context content for token counting...")
            current_context = format_context(context_content_dict, added_paths_set) # Use the content dict just built

            text_for_token_count = instruction_prefix + current_context
            # Avoid counting tokens for empty/default context message
            if text_for_token_count.strip() and text_for_token_count != "No local file context provided or found.":
                logger.debug(f"Calling count_tokens API for text length: {len(text_for_token_count)}")
                start_count = time.time()
                # Potential API call
                count_response = model_instance.count_tokens(text_for_token_count)
                count_time = time.time() - start_count
                token_count = count_response.total_tokens
                token_count_str = f"Token Count (Instr + Context): {token_count:,}"
                logger.info(f"Token count successful: {token_count} tokens ({count_time:.2f}s).")
            else:
                token_count_str = "Token Count: 0"
                token_count = 0
                logger.debug("No effective text for token counting (Instruction/Context empty).")
        except Exception as e:
            logger.error(f"Error counting tokens: {e}", exc_info=True)
            token_count_str = f"Token Count: Error" # Simplified error message for UI
            token_count = -1 # Indicate error state
    else:
        logger.warning("Cannot calculate tokens: Model instance not available.")
        token_count_str = "Token Count: N/A (Add API Key & Model)"
        token_count = -1 # Indicate N/A state

    logger.info(f"Context/Token update complete. Token string: '{token_count_str}'")
    return token_count, token_count_str, context_files_details, context_content_dict

def get_model_output_limit(model_name):
    """Gets the output token limit for the specified model."""
    logger.info(f"Fetching output token limit for model: {model_name}")
    try:
        # Potential API call
        model_info = genai.get_model(model_name)
        logger.debug(f"Received model info for {model_name}")
        if hasattr(model_info, 'output_token_limit'):
            limit = model_info.output_token_limit
            logger.info(f"Output token limit for {model_name}: {limit}")
            return limit
        else:
            logger.warning(f"'output_token_limit' attribute not found for model {model_name}. Using fallback: {FALLBACK_MODEL_MAX_OUTPUT_TOKENS}")
            return FALLBACK_MODEL_MAX_OUTPUT_TOKENS
    except Exception as e:
        logger.error(f"Error getting model info for {model_name}: {e}. Using fallback: {FALLBACK_MODEL_MAX_OUTPUT_TOKENS}", exc_info=True)
        return FALLBACK_MODEL_MAX_OUTPUT_TOKENS

def reconstruct_gemini_history(messages):
    """Converts the simple message list to the Gemini API's history format."""
    logger.debug(f"Reconstructing Gemini history from {len(messages)} messages.")
    history = []
    valid_roles = {"user", "assistant"}
    for i, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content")
        if role in valid_roles and isinstance(content, str):
             # Map 'assistant' to 'model' for the API
            api_role = "model" if role == "assistant" else "user"
            history.append({"role": api_role, "parts": [{"text": content}]})
        else:
             logger.warning(f"Skipping invalid message at index {i} during history reconstruction: Role='{role}', Content type='{type(content)}'")
    logger.debug(f"Reconstructed history length: {len(history)}")
    return history

# --- API Key Functions ---
def load_api_key():
    """Loads API key from database settings."""
    logger.debug("Attempting to load API key from DB settings.")
    loaded_api_key = db.load_setting('api_key')
    if loaded_api_key:
        logger.info("API key loaded from database.")
    else:
        logger.info("API key not found in database settings.")
    return loaded_api_key

def save_api_key(api_key):
    """Saves API key to database settings."""
    # Avoid logging the key itself, maybe just the length or last chars if needed
    logger.info(f"Attempting to save API key (length {len(api_key)}) to DB.")
    if not api_key: # Basic validation
         logger.error("Attempted to save an empty API key.")
         return False
    success = db.save_setting('api_key', api_key)
    if success:
        logger.info("API Key saved successfully to database.")
        return True
    else:
        logger.error("Failed to save API key to database.") # db function should log specifics
        return False

def clear_api_key():
    """Deletes the API key from database settings."""
    logger.warning("Attempting to delete API key setting from database.")
    success = db.delete_setting('api_key')
    if success:
        logger.info("API Key setting deleted successfully from database.")
        return True
    else:
        logger.error("Failed to delete API key setting from database.") # db function logs specifics
        return False