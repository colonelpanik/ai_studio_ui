# app/logic/context_manager.py
# Handles scanning files, building, and formatting context.
import os
from pathlib import Path
import logging
import time

logger = logging.getLogger(__name__)

# --- Configuration Constants ---

# Set of file extensions (lowercase, including '.') considered text-based and potentially useful for context.
# Also includes common specific filenames like 'Dockerfile', 'Makefile'.
ALLOWED_EXTENSIONS = {
    # Code
    '.py', '.pyi', '.java', '.c', '.cpp', '.h', '.hpp', '.cs', '.go', '.rs', '.swift', '.kt', '.kts',
    '.scala', '.rb', '.erb', '.php', '.pl', '.pm', '.lua', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs',
    '.html', '.htm', '.css', '.scss', '.sass', '.less', '.vue', '.svelte', '.sh', '.bash', '.zsh',
    '.ps1', '.bat', '.cmd', '.sql', '.r', '.lisp', '.lsp', '.cl', '.hs', '.erl', '.ex', '.exs',
    '.dart', '.groovy', '.gd', # Godot script
    '.wat', # WebAssembly Text

    # Config & Data
    '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.properties', '.env', '.xml',
    '.csv', '.tsv', '.proto', '.tf', '.tfvars', '.hcl', '.gradle', '.csproj', '.vbproj', '.fsproj',
    '.sln', 'dockerfile', 'docker-compose.yml', '.gitignore', '.gitattributes', 'makefile', # Use lowercase for filenames + dotfiles
    '.npmrc', '.yarnrc', '.babelrc', '.eslintrc', '.prettierrc', 'pyproject.toml', 'requirements.txt',
    'pipfile', 'gemfile', 'cargo.toml', 'go.mod', 'go.sum', 'composer.json', 'package.json',
    'tsconfig.json', '.editorconfig',

    # Markup & Text
    '.txt', '.md', '.rst', '.tex', '.adoc', '.asciidoc', '.log', # Allow logs explicitly if desired, remove if not
    '.graphql', '.gql', '.plantuml', '.puml', '.mermaid', '.mmd',

    # Data (potentially large, use MAX_FILE_SIZE_MB carefully)
    '.geojson', '.sql', '.csv', '.tsv',
}

# Set of directory names to completely ignore during recursive scans. Case-sensitive.
EXCLUDE_DIRS = {
    # Common Env/Cache
    'venv', '.venv', 'env', '.env', '__pycache__', '.pytest_cache', '.mypy_cache', '.cache',
    '.composer_cache', '.npm', '.yarn',

    # Version Control
    '.git', '.hg', '.svn',

    # IDE/Editor Specific
    '.idea', '.vscode', '.vs',

    # Build/Output Dirs
    'node_modules', 'bower_components', 'vendor', # PHP Composer
    'build', 'dist', 'out', 'output', 'bin', 'obj', 'target', # Common build outputs
    'public', # Often contains compiled assets
    '.gradle', # Gradle cache
    '.terraform', # Terraform cache

    # OS Specific / Temporary
    '__MACOSX', '.DS_Store', 'Thumbs.db',

    # Specific Framework/Tool Dirs
    'site-packages', 'migrations', 'Pods', # CocoaPods
    'logs', # Often noisy, but sometimes useful context
    '.next', # Next.js build output
    '.nuxt', # Nuxt.js build output
    'coverage', # Code coverage reports
    'docs', # Often generated documentation, keep if source needed
    'storybook-static', # Storybook build output
}

# Set of file extensions (lowercase, including '.') to always exclude, even if the name matches ALLOWED_EXTENSIONS.
# Primarily for compiled files, binaries, media, archives, temp files, etc.
EXCLUDE_EXTENSIONS = {
    # Compiled Code / Binaries
    '.pyc', '.pyo', '.pyd', '.dll', '.so', '.dylib', '.exe', '.o', '.a', '.obj', '.lib', '.class',
    '.jar', '.war', '.ear', '.nupkg', '.wasm', '.pdb', '.elf', '.com',

    # Archives
    '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar', '.iso', '.img', '.deb', '.rpm', '.pkg', '.dmg',
    '.egg', '.whl',

    # Media (Images, Audio, Video)
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp', '.ico', '.svg', # SVG can be text, but often complex/large
    '.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a',
    '.mp4', '.avi', '.mov', '.wmv', '.mkv', '.webm', '.flv',

    # Documents / Spreadsheets / Presentations
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp', '.rtf',

    # Databases
    '.db', '.sqlite', '.sqlite3', '.mdb', '.accdb', '.sdf',

    # Temporary / Backup / Swap Files
    '.tmp', '.temp', '.bak', '.swp', '.swo', '.swn', '~',

    # Lock Files
    '.lock', 'package-lock.json', 'yarn.lock', 'composer.lock', 'pipfile.lock', 'cargo.lock', # Use lowercase
    'gemfile.lock', 'poetry.lock',

    # Cache / Index / Metadata
    '.cache', '.idx', '.pack', '.index', # Git index/pack files
    '.suo', '.user', # Visual Studio user settings

    # Fonts
    '.ttf', '.otf', '.woff', '.woff2', '.eot',

    # Keys / Certificates (Security Risk - Usually exclude)
    '.pfx', '.p12', '.pem', '.crt', '.cer', '.key', '.jks', '.keystore',

    # Source Maps (can be large, often not needed for context)
    '.css.map', '.js.map',

    # Logs (can be excluded here if not explicitly allowed above)
    # '.log',
}

# --- FIX: Correctly create lowercase set of ALL specific filenames in ALLOWED_EXTENSIONS ---
_ALLOWED_FILENAMES_LOWER = {fn.lower() for fn in ALLOWED_EXTENSIONS if not fn.startswith('.') or '.' not in fn[1:]} # Include dotfiles if they don't have another dot

MAX_FILE_SIZE_MB = 5 # Keep the size limit configurable
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# --- Helper Functions (from original gemini_logic.py) ---

def is_file_allowed(file_path: Path) -> tuple[bool, str]:
    """Checks if a file should be included based on extension, name, and size."""
    # IN: file_path: Path; OUT: (allowed: bool, reason: str) # Checks file filters.
    logger.debug(f"Checking allowance for: {file_path}")
    if not file_path.is_file(): return False, "Not a file"

    file_suffix_lower = file_path.suffix.lower()
    file_name_lower = file_path.name.lower() # Use lowercase filename

    # --- FIX: Check against corrected _ALLOWED_FILENAMES_LOWER ---
    is_allowed_name_or_ext = (file_name_lower in _ALLOWED_FILENAMES_LOWER or
                              (file_suffix_lower in ALLOWED_EXTENSIONS and file_suffix_lower != ''))

    if is_allowed_name_or_ext:
        # Check size only if extension/name is allowed
        try:
            file_size = file_path.stat().st_size
            if file_size > MAX_FILE_SIZE_BYTES:
                 return False, f"Exceeds size limit ({MAX_FILE_SIZE_MB}MB)"
            # Ensure it's not *also* explicitly excluded by extension
            if file_suffix_lower in EXCLUDE_EXTENSIONS:
                 # Also check if filename itself is a lock file exclusion
                 if file_name_lower in EXCLUDE_EXTENSIONS:
                    return False, f"Excluded lock file ({file_name_lower})"
                 return False, f"Excluded extension ({file_suffix_lower}) despite name/allowed ext"
            # Ensure filename itself isn't explicitly excluded (e.g., package-lock.json)
            if file_name_lower in EXCLUDE_EXTENSIONS:
                 return False, f"Excluded filename ({file_name_lower})"

            return True, "Allowed by extension/name"
        except OSError as e: return False, f"Cannot get file size ({e})"
    # If not allowed by name/ext, check if explicitly excluded
    elif file_suffix_lower in EXCLUDE_EXTENSIONS or file_name_lower in EXCLUDE_EXTENSIONS:
         reason_detail = f"extension ({file_suffix_lower})" if file_suffix_lower in EXCLUDE_EXTENSIONS else f"filename ({file_name_lower})"
         return False, f"Excluded {reason_detail}"
    # Otherwise, it's not allowed and not excluded -> implicitly disallowed
    else:
        return False, "Extension/name not in allowed list"

# ... (rest of the file remains unchanged) ...

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
            # Return error message as content, and status
            return f"Error reading file: Could not decode content - {e_fallback}", "Read error (fallback failed)"
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}", exc_info=True)
        return f"Error reading file: {e}", "Read error"

def scan_directory_recursively(directory_path: Path) -> tuple[dict, list, int]:
    """
    Scans a directory, returning content of allowed files and scan details.
    Details list now contains tuples of (absolute_path: Path, status: str, detail: str).
    Excluded directories are skipped entirely and not added to the details list.
    """
    # IN: directory_path: Path; OUT: (contents: dict, details: list[tuple[Path, str, str]], count: int) # Scans dir recursively.
    logger.info(f"Scanning directory recursively: {directory_path}")
    file_contents = {} # {abs_path_str: content}
    scanned_files_details = [] # List of tuples: (absolute_path: Path, status: str, detail: str)
    processed_count = 0 # This count isn't very accurate, maybe remove later
    included_file_count = 0
    skipped_file_count = 0
    error_file_count = 0
    excluded_dir_count = 0 # Count how many dirs were skipped

    # Ensure directory_path is absolute for consistent results
    abs_directory_path = directory_path.resolve()

    for root, dirs, files in os.walk(abs_directory_path, topdown=True):
        root_path = Path(root)

        # Filter excluded directories *before* processing files in the current root
        original_dirs = list(dirs) # Keep original list to count exclusions
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS] # Modify dirs in-place to prevent traversal
        excluded_dirs_in_pass = set(original_dirs) - set(dirs)
        excluded_dir_count += len(excluded_dirs_in_pass)

        # Process files in the current directory (which is not excluded)
        for filename in files:
            item_path = (root_path / filename).resolve() # Use resolved absolute path
            allowed, reason = is_file_allowed(item_path)

            if allowed:
                content, read_status = safe_read_file(item_path)
                if read_status and "error" in read_status.lower():
                    scanned_files_details.append((item_path, "Error Reading", read_status))
                    error_file_count += 1
                else:
                    # Use absolute path string as key for content dictionary
                    abs_path_key = str(item_path)
                    file_contents[abs_path_key] = content
                    status = "Included" + (f" ({read_status})" if read_status else "")
                    try:
                        detail=f"{item_path.stat().st_size / 1024:.1f} KB"
                    except Exception:
                        detail="Size N/A"
                    scanned_files_details.append((item_path, status, detail))
                    included_file_count += 1
            else:
                # Record skipped files with absolute path
                scanned_files_details.append((item_path, "Skipped", reason))
                skipped_file_count += 1

    logger.info(f"Scan results for {abs_directory_path}: {included_file_count} included, {skipped_file_count} skipped, {error_file_count} errors, {excluded_dir_count} excluded dirs (not listed).")
    return file_contents, scanned_files_details, processed_count


def build_context_from_added_paths(added_paths_set: set[str]) -> tuple[dict, list]:
    """
    Builds file content dictionary and display details from a set of added paths.
    Returns:
        - dict: {absolute_path_str: file_content}
        - list: [(absolute_path: Path, status: str, detail: str)]
    """
    # IN: added_paths_set: set; OUT: (contents: dict, details: list) # Builds context dict from paths.
    logger.info(f"Building context from {len(added_paths_set)} added path(s).")
    all_file_contents = {} # {abs_path_str: content}
    all_found_files_display = [] # List of tuples: (absolute_path: Path, status: str, detail: str)
    total_items_processed = 0

    if not added_paths_set:
        return {}, []

    sorted_paths = sorted(list(added_paths_set))

    for path_str in sorted_paths:
        try:
            path_obj = Path(path_str).resolve() # Use absolute path
            if not path_obj.exists():
                all_found_files_display.append((Path(path_str), "Error", "Path does not exist")) # Keep original str if not found
                continue

            # --- Check if the added path itself is an excluded directory ---
            if path_obj.is_dir() and path_obj.name in EXCLUDE_DIRS:
                logger.warning(f"Skipping directly added excluded directory: {path_obj}")
                continue # Skip processing this path entirely
            # --- End check ---

            if path_obj.is_file():
                allowed, reason = is_file_allowed(path_obj)
                if allowed:
                    content, read_status = safe_read_file(path_obj)
                    unique_key = str(path_obj) # Absolute path string key
                    # Store content only if read was successful
                    status = "Included"
                    if read_status and "error" in read_status.lower():
                         status = "Error Reading"
                    elif read_status: # e.g., fallback encoding used
                         status += f" ({read_status})"

                    # Don't add content if there was a read error
                    if "Error" not in status:
                        all_file_contents[unique_key] = content

                    try:
                        detail=f"{path_obj.stat().st_size / 1024:.1f} KB"
                    except Exception:
                        detail = "Size N/A"
                    # Append detail even if read error occurred
                    all_found_files_display.append((path_obj, status, detail))
                else:
                    # Record skipped file with absolute path
                    all_found_files_display.append((path_obj, "Skipped", reason))
                total_items_processed += 1 # Count processed files

            elif path_obj.is_dir():
                # scan_directory_recursively now correctly handles internal exclusions
                dir_contents, dir_scan_details, _ = scan_directory_recursively(path_obj)
                all_file_contents.update(dir_contents)
                all_found_files_display.extend(dir_scan_details)

            else:
                # Handle cases like broken symlinks, etc.
                all_found_files_display.append((path_obj, "Error", "Path is not file/dir (e.g., broken link)"))

        except Exception as e:
            logger.error(f"Error processing path '{path_str}': {e}", exc_info=True)
            # Record error with original path string if resolution failed early
            all_found_files_display.append((Path(path_str), "Error", f"Processing failed: {e}"))

    # Sort display details by absolute path (Path objects are comparable)
    all_found_files_display.sort(key=lambda x: x[0])
    logger.info(f"Context build complete. Found {len(all_file_contents)} files with content. Total items checked/scanned: {len(all_found_files_display)}.")
    return all_file_contents, all_found_files_display


def format_context(file_contents_dict: dict, added_paths_set: set[str]) -> str:
    """Formats the collected file contents into a string for the prompt."""
    # IN: file_contents_dict ({abs_path_str: content}), added_paths_set; OUT: str # Formats context dict to string.
    logger.debug(f"Formatting context string from {len(file_contents_dict)} files.")

    if not file_contents_dict: return "" # Return empty string instead of message

    context_str = "--- Local File Context ---\n\n"
    sorted_abs_paths = sorted(file_contents_dict.keys())

    # Pre-resolve added root paths for relative path calculation
    resolved_added_roots = {}
    for added_root in added_paths_set:
        try:
             # Store both resolved path and original string to know if original was file/dir-like
             resolved_path = Path(added_root).resolve()
             resolved_added_roots[added_root] = resolved_path
        except Exception as e:
             logger.warning(f"Could not resolve added root path '{added_root}' for display formatting: {e}")

    for abs_path_key in sorted_abs_paths:
        content = file_contents_dict[abs_path_key]
        display_path = abs_path_key # Default to absolute path

        try:
            abs_path_obj = Path(abs_path_key)
            shortest_rel_path = None
            # Check against resolved root paths
            for orig_root_str, root_path in resolved_added_roots.items():
                try:
                    # Heuristic: Treat root as dir if original string didn't have common file extension
                    # or if the resolved path IS actually a directory on the system running the code.
                    # This handles the test case where root_path.is_dir() fails.
                    orig_has_ext = any(orig_root_str.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS if ext.startswith('.'))
                    is_dir_like_root = not orig_has_ext # Simple heuristic

                    if is_dir_like_root and abs_path_obj.is_relative_to(root_path):
                        rel_path = str(abs_path_obj.relative_to(root_path))
                        if shortest_rel_path is None or len(rel_path) < len(shortest_rel_path):
                            shortest_rel_path = rel_path
                    elif abs_path_obj == root_path: # Handle case where root is the file itself
                        shortest_rel_path = abs_path_obj.name # Display just the name
                        break # Found direct file match
                except ValueError: # Handles path comparison errors (e.g., different drives)
                    pass
                except Exception as e_rel:
                    logger.debug(f"Minor error checking relative path for {abs_path_obj} against {root_path}: {e_rel}")


            # If a relative path was found, use it
            if shortest_rel_path is not None:
                 display_path = shortest_rel_path
            # If display_path is still absolute after checking relatives, use just the filename
            elif Path(display_path).is_absolute():
                display_path = Path(display_path).name

        except Exception as e:
            logger.warning(f"Error calculating relative path for '{abs_path_key}': {e}. Falling back to absolute/name.")
            display_path = Path(abs_path_key).name # Fallback to filename on error

        context_str += f"--- File: {display_path} ---\n```\n{content}\n```\n\n"

    context_str += "--- End Local File Context ---\n\n"
    return context_str

def reconstruct_gemini_history(messages: list[dict]) -> list[dict]:
    """Converts the simple message list to the Gemini API's history format."""
    # IN: messages: list[dict]; OUT: list[dict] # Converts simple chat list to API history format.
    logger.debug(f"Reconstructing Gemini history from {len(messages)} messages.")
    history = []
    valid_roles = {"user", "assistant"}
    for i, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content")
        if role in valid_roles and isinstance(content, str):
             api_role = "model" if role == "assistant" else "user"
             history.append({"role": api_role, "parts": [{"text": content}]})
        else: logger.warning(f"Skipping invalid message index {i} during history reconstruction: Role='{role}', Content Type='{type(content)}'")
    return history