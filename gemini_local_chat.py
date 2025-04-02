import streamlit as st
import google.generativeai as genai
import os
from pathlib import Path

# --- Configuration ---
PAGE_TITLE = "Gemini Chat with Managed Context"
PAGE_ICON = "📝"

# File extensions to include (remains the same)
ALLOWED_EXTENSIONS = {'.py', '.txt', '.md', '.json', '.yaml', '.yml', '.html', '.css', '.js', '.sh', '.bash', '.zsh', '.java', '.c', '.cpp', '.h', '.hpp', '.cs', '.go', '.rb', '.php', '.sql', '.rs', '.swift', '.kt', '.scala', '.pl', '.pm', '.lua', '.toml', '.ini', '.cfg', '.conf', '.dockerfile', 'docker-compose.yml', '.gitignore', '.gitattributes', '.csv', '.tsv', '.xml', '.rst', '.tex', '.R'}

# Directories to completely ignore (remains the same)
EXCLUDE_DIRS = {'__pycache__', 'venv', '.venv', '.git', '.idea', '.vscode', 'node_modules', 'build', 'dist', 'target', 'logs', '.pytest_cache', '.mypy_cache', 'site-packages', 'migrations', '__MACOSX', '.DS_Store', 'env'}

# Specific file extensions to ignore (remains the same)
EXCLUDE_EXTENSIONS = {'.pyc', '.pyo', '.log', '.tmp', '.temp', '.bak', '.swp', '.swo', '.dll', '.so', '.dylib', '.exe', '.o', '.a', '.obj', '.lib', '.class', '.jar', '.war', '.ear', '.lock', '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar', '.iso', '.img', '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.svg', '.mp3', '.wav', '.ogg', '.flac', '.mp4', '.avi', '.mov', '.wmv', '.mkv', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp'}

# Max file size to read (e.g., 5MB)
MAX_FILE_SIZE_MB = 5
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# --- Helper Functions ---

def is_file_allowed(file_path: Path):
    """Checks if a single file should be included based on extensions and size."""
    if not file_path.is_file():
        return False, "Not a file"

    file_suffix_lower = file_path.suffix.lower()
    if file_suffix_lower in EXCLUDE_EXTENSIONS:
        return False, f"Excluded extension ({file_suffix_lower})"
    if file_suffix_lower not in ALLOWED_EXTENSIONS and file_path.name not in ALLOWED_EXTENSIONS:
         return False, f"Extension/name not in allowed list"

    # Size check
    try:
        file_size = file_path.stat().st_size
        if file_size > MAX_FILE_SIZE_BYTES:
            return False, f"Exceeds size limit ({MAX_FILE_SIZE_MB}MB)"
        # Optionally skip empty files? Let's include them for now.
    except OSError as e:
        return False, f"Cannot get file size ({e})"

    return True, "Allowed"


def safe_read_file(file_path: Path):
    """Reads a file with error handling and encoding fallbacks."""
    try:
        content = file_path.read_text(encoding='utf-8')
        return content, None # Content, No error
    except UnicodeDecodeError:
        try:
            content = file_path.read_text(encoding='latin-1')
            return content, "Read with fallback encoding (latin-1)"
        except Exception as e:
            return f"Error reading file: Could not decode content - {e}", "Read error (fallback failed)"
    except Exception as e:
        return f"Error reading file: {e}", "Read error"


def scan_directory_recursively(directory_path: Path):
    """
    Scans a directory RECURSIVELY for allowed files, excluding specified
    items. Returns dict {relative_path_str: content} and stats.
    """
    file_contents = {}
    scanned_files_details = [] # List of tuples: (relative_path, status, detail)
    processed_count = 0

    for root, dirs, files in os.walk(directory_path, topdown=True):
        root_path = Path(root)
        processed_count += 1 + len(dirs) + len(files) # Rough count

        # --- Directory Exclusion ---
        if root_path.name in EXCLUDE_DIRS:
            dirs[:] = [] # Don't recurse
            files[:] = [] # Don't process files here
            scanned_files_details.append((root_path.relative_to(directory_path), "Skipped", f"Excluded directory name ({root_path.name})"))
            continue

        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS] # Filter subdirs

        for filename in files:
            item_path = root_path / filename
            relative_path = item_path.relative_to(directory_path)
            relative_path_str = str(relative_path)

            # --- File Exclusion & Reading ---
            allowed, reason = is_file_allowed(item_path)
            if allowed:
                content, read_status = safe_read_file(item_path)
                if read_status and "error" in read_status.lower():
                    scanned_files_details.append((relative_path_str, "Error Reading", read_status))
                    # Optionally include error content: file_contents[relative_path_str] = content
                else:
                    file_contents[relative_path_str] = content
                    status = "Included" + (f" ({read_status})" if read_status else "")
                    scanned_files_details.append((relative_path_str, status, f"{item_path.stat().st_size / 1024:.1f} KB"))
            else:
                 scanned_files_details.append((relative_path_str, "Skipped", reason))

    return file_contents, scanned_files_details, processed_count


def build_context_from_added_paths(added_paths_set):
    """
    Iterates through user-added paths, reads files/scans directories,
    and aggregates the context.
    """
    all_file_contents = {} # Stores {unique_key: content}
    all_found_files_display = [] # Stores tuples: (display_path, status, detail) for UI
    total_items_processed = 0

    if not added_paths_set:
        return {}, [] # Return empty if nothing added

    sorted_paths = sorted(list(added_paths_set)) # Process consistently

    with st.spinner("Building context from added paths..."):
        for path_str in sorted_paths:
            try:
                path_obj = Path(path_str).resolve() # Use absolute paths for consistency

                if path_obj.is_file():
                    display_name = f"{path_obj.name} (File)"
                    allowed, reason = is_file_allowed(path_obj)
                    if allowed:
                        content, read_status = safe_read_file(path_obj)
                        unique_key = str(path_obj) # Use absolute path as key for single files
                        all_file_contents[unique_key] = content
                        status_detail = f"{path_obj.stat().st_size / 1024:.1f} KB" + (f" ({read_status})" if read_status else "")
                        all_found_files_display.append((str(path_obj), "Included", status_detail))
                    else:
                        all_found_files_display.append((str(path_obj), "Skipped", reason))

                elif path_obj.is_dir():
                    display_name = f"{path_obj.name}/ (Directory)"
                    dir_contents, dir_scan_details, processed_count = scan_directory_recursively(path_obj)
                    total_items_processed += processed_count

                    # Add directory contents with a prefix to avoid collisions maybe?
                    # Using absolute paths within the dir scan results might be safer.
                    for rel_path_str, content in dir_contents.items():
                        abs_file_path = path_obj / rel_path_str
                        unique_key = str(abs_file_path) # Use absolute path as key
                        all_file_contents[unique_key] = content
                        # Add details from dir_scan_details to the main display list
                        # Find the corresponding entry (can be inefficient for large lists)
                        # For simplicity, we'll just add a marker for the dir itself
                        # A better approach might be to pass all_found_files_display into scan_directory

                    # Update main display list with details from this directory scan
                    for rel_path, status, detail in dir_scan_details:
                         abs_p_str = str(path_obj / rel_path)
                         all_found_files_display.append((abs_p_str, status, detail))

                else:
                    all_found_files_display.append((path_str, "Error", "Path does not exist or is not a file/directory"))

            except Exception as e:
                 all_found_files_display.append((path_str, "Error", f"Failed to process path: {e}"))

    # Sort the final display list by path
    all_found_files_display.sort(key=lambda x: x[0])
    return all_file_contents, all_found_files_display


def format_context(file_contents_dict):
    """Formats the aggregated file contents for the LLM prompt."""
    if not file_contents_dict:
        return "No local file context provided or found."

    context_str = "--- Local File Context ---\n\n"
    # Sort by the file path (key) for consistent context ordering
    for path_key in sorted(file_contents_dict.keys()):
        content = file_contents_dict[path_key]
        # Display the key which should be a meaningful path (absolute or relative)
        context_str += f"--- File: {path_key} ---\n"
        context_str += f"```\n{content}\n```\n\n"
    context_str += "--- End Local File Context ---\n\n"
    return context_str


# --- Streamlit Page Setup ---
st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")
st.title(f"{PAGE_ICON} {PAGE_TITLE}")

# --- Initialize Session State ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "gemini_history" not in st.session_state:
    st.session_state.gemini_history = []
if "added_paths" not in st.session_state:
    st.session_state.added_paths = set() # Use a set to store added paths
if "context_files_details" not in st.session_state:
     st.session_state.context_files_details = [] # To store display info


# --- Sidebar ---
st.sidebar.header("Configuration")
api_key = st.sidebar.text_input("Enter your Gemini API Key:", type="password", key="api_key_input")

st.sidebar.header("Manage Context")
new_path_input = st.sidebar.text_input("Add Directory or File Path:", key="new_path", placeholder="Enter path and click Add")
if st.sidebar.button("Add Path", key="add_path_button"):
    if new_path_input:
        resolved_path = str(Path(new_path_input).resolve()) # Store resolved path
        # Basic check if path exists before adding
        if Path(resolved_path).exists():
             st.session_state.added_paths.add(resolved_path)
             st.sidebar.success(f"Added: {resolved_path}")
             st.rerun() # Rerun to update display and context
        else:
             st.sidebar.error(f"Path not found: {new_path_input}")
    else:
        st.sidebar.warning("Please enter a path to add.")

# Display Added Paths with Remove buttons
with st.sidebar.expander("Managed Context Paths", expanded=True):
    if not st.session_state.added_paths:
        st.caption("No paths added yet.")
    else:
        # Create columns for path and remove button
        col1, col2 = st.columns([4, 1]) # Adjust ratio as needed
        paths_to_remove = []
        for path_str in sorted(list(st.session_state.added_paths)):
            with col1:
                 st.code(path_str, language=None) # Use code block for better path display
            with col2:
                # Use path_str directly in key for uniqueness
                if st.button("❌", key=f"remove_{path_str}", help=f"Remove {path_str}"):
                    paths_to_remove.append(path_str)

        if paths_to_remove:
             for path_to_remove in paths_to_remove:
                  st.session_state.added_paths.discard(path_to_remove)
             st.rerun() # Rerun to reflect removal


# Display Effective Context Files (Result of scanning)
with st.sidebar.expander("Effective Context Files", expanded=False): # Start collapsed
     if not st.session_state.get('context_files_details', []):
          st.caption("Add paths and send a message to see files here.")
     else:
          # Use a container with height for scrolling if list is long
          with st.container(height=300): # Adjust height as needed
               files_included_count = 0
               files_skipped_count = 0
               files_error_count = 0
               for path, status, detail in st.session_state.context_files_details:
                    icon = "✅" if "Included" in status else ("⚠️" if "Skipped" in status else "❌")
                    color = "green" if "Included" in status else ("orange" if "Skipped" in status else "red")
                    st.markdown(f"<span style='color:{color};'>{icon} **{status}:** `{path}` ({detail})</span>", unsafe_allow_html=True)
                    if "Included" in status: files_included_count += 1
                    elif "Skipped" in status: files_skipped_count += 1
                    else: files_error_count += 1
               st.caption(f"Total: {files_included_count} Included, {files_skipped_count} Skipped, {files_error_count} Errors")


# Clear Chat Button
if st.sidebar.button("Clear Chat History"):
    st.session_state.messages = []
    st.session_state.gemini_history = []
    st.rerun()

# --- Gemini API Configuration (remains mostly the same) ---
model_name = "gemini-1.5-flash-latest"
model = None
chat = None
if api_key:
    try:
        if 'genai_configured' not in st.session_state or st.session_state.get('last_api_key') != api_key:
            genai.configure(api_key=api_key)
            st.session_state.genai_configured = True
            st.session_state.last_api_key = api_key
            # Don't show success message every rerun, maybe once or on change
            # st.sidebar.success("Gemini API Configured.")

        model = genai.GenerativeModel(model_name)
        chat = model.start_chat(history=st.session_state.gemini_history) # Recreate chat with current history

    except Exception as e:
        st.sidebar.error(f"Error configuring Gemini API: {e}")
        st.error(f"Failed to configure Gemini API. Please check your key. Error: {e}")
        api_key = None
        st.session_state.genai_configured = False
else:
     if 'genai_configured' in st.session_state:
        st.session_state.genai_configured = False
        st.session_state.last_api_key = None


# --- Main Chat Interface ---
if not api_key:
     st.warning("Please enter your Gemini API Key in the sidebar to enable chat.")
if not st.session_state.added_paths:
     st.info("Add files or directories using the 'Manage Context' section in the sidebar.")

# Display previous chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Get user input
prompt = st.chat_input("Ask a question...")

if prompt:
    # Prerequisites check
    if not api_key:
        st.error("Cannot proceed. Gemini API Key required.")
        st.stop()
    if not model or not chat:
        st.error("Cannot proceed. Gemini model not initialized.")
        st.stop()

    # Add user message display
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # --- Build Context ---
    context = "No context paths added."
    file_contents_dict = {}

    if st.session_state.added_paths:
        # Build context aggregates files/dirs, returns content dict and display list
        file_contents_dict, context_files_details = build_context_from_added_paths(st.session_state.added_paths)
        st.session_state.context_files_details = context_files_details # Store details for sidebar display

        if file_contents_dict:
            context = format_context(file_contents_dict)
            # Check size (rough estimate)
            context_char_limit = 3_500_000
            if len(context) > context_char_limit:
                st.warning(f"Context size is very large ({len(context):,} chars). May exceed model limits.")
        else:
             context = "No suitable files found in the added paths matching the criteria."

    # Construct full prompt
    full_prompt = context + "\n\n---\n\nBased on the local file context provided above, please answer the following question:\n\n" + prompt

    # Add to Gemini history
    try:
        st.session_state.gemini_history.append({"role": "user", "parts": [{"text": full_prompt}]})
    except Exception as e:
        st.error(f"Error preparing message for Gemini history: {e}")
        if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
             st.session_state.messages.pop()
        st.stop()

    # --- Send to Gemini & Display Response ---
    try:
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            with st.spinner("Gemini is thinking..."):
                response = chat.send_message(full_prompt, stream=True)

            full_response_content = ""
            for chunk in response:
                if chunk.text:
                    full_response_content += chunk.text
                    message_placeholder.markdown(full_response_content + "▌")

            message_placeholder.markdown(full_response_content)

        # Add AI response to histories
        st.session_state.messages.append({"role": "assistant", "content": full_response_content})
        st.session_state.gemini_history.append({"role": "model", "parts": [{"text": full_response_content}]})

        # --- History Pruning (remains the same) ---
        MAX_HISTORY_PAIRS = 15
        if len(st.session_state.gemini_history) > MAX_HISTORY_PAIRS * 2:
            st.session_state.gemini_history = st.session_state.gemini_history[-(MAX_HISTORY_PAIRS * 2):]
            st.session_state.messages = st.session_state.messages[-(MAX_HISTORY_PAIRS * 2):]
            # Re-sync chat object if pruned (important!)
            chat = model.start_chat(history=st.session_state.gemini_history)
            # st.info(f"Chat history pruned...") # Optional info

    except Exception as e:
        st.error(f"An error occurred communicating with Gemini: {e}")
        # Rollback last user message on error
        if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
             st.session_state.messages.pop()
        if st.session_state.gemini_history and st.session_state.gemini_history[-1]["role"] == "user":
             st.session_state.gemini_history.pop()
        # No need to explicitly rollback context_files_details as it will refresh on next run

    # Rerun at the end of processing a prompt to update the "Effective Context Files" display
    # based on the scan that just happened.
    st.rerun()


# --- Sidebar Footer ---
st.sidebar.markdown("---")
st.sidebar.markdown(f"Version: 1.1 | {PAGE_TITLE}")