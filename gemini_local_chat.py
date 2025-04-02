# gemini_local_chat.py
# Version: 2.0 - Layout refactor, conversation history, param column, slider
# NOTE: This requires database.py Version 2.0 or later.

import streamlit as st
import google.generativeai as genai
import google.ai.generativelanguage as glm
from google.generativeai.types import GenerationConfig, Model
import os
from pathlib import Path
import json
import datetime
import database as db # Import database helper (ensure it's v2.0+)
import time # For potential UI delays/reruns

# --- Configuration ---
APP_VERSION = "2.0"
PAGE_TITLE = "Gemini Chat Pro"
PAGE_ICON = "✨"
# File processing configs (unchanged)
ALLOWED_EXTENSIONS = {'.py', '.txt', '.md', '.json', '.yaml', '.yml', '.html', '.css', '.js', '.sh', '.bash', '.zsh', '.java', '.c', '.cpp', '.h', '.hpp', '.cs', '.go', '.rb', '.php', '.sql', '.rs', '.swift', '.kt', '.scala', '.pl', '.pm', '.lua', '.toml', '.ini', '.cfg', '.conf', '.dockerfile', 'docker-compose.yml', '.gitignore', '.gitattributes', '.csv', '.tsv', '.xml', '.rst', '.tex', '.R'}
EXCLUDE_DIRS = {'__pycache__', 'venv', '.venv', '.git', '.idea', '.vscode', 'node_modules', 'build', 'dist', 'target', 'logs', '.pytest_cache', '.mypy_cache', 'site-packages', 'migrations', '__MACOSX', '.DS_Store', 'env'}
EXCLUDE_EXTENSIONS = {'.pyc', '.pyo', '.log', '.tmp', '.temp', '.bak', '.swp', '.swo', '.dll', '.so', '.dylib', '.exe', '.o', '.a', '.obj', '.lib', '.class', '.jar', '.war', '.ear', '.lock', '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar', '.iso', '.img', '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.svg', '.mp3', '.wav', '.ogg', '.flac', '.mp4', '.avi', '.mov', '.wmv', '.mkv', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp'}
MAX_FILE_SIZE_MB = 5
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
# Default model and token limits
DEFAULT_MODEL = "models/gemini-1.5-flash-latest"
DEFAULT_MAX_OUTPUT_TOKENS_SLIDER = 4096 # Default for the setting slider before model limit is known
FALLBACK_MODEL_MAX_OUTPUT_TOKENS = 65536
MAX_HISTORY_PAIRS = 15 # Max user/model pairs in gemini_history before pruning

# --- Helper Functions (Unchanged from v1.6, except format_context key usage) ---
def is_file_allowed(file_path: Path):
    if not file_path.is_file(): return False, "Not a file"
    file_suffix_lower = file_path.suffix.lower()
    if file_path.name in ALLOWED_EXTENSIONS: return True, "Allowed by name"
    if file_suffix_lower in EXCLUDE_EXTENSIONS: return False, f"Excluded extension ({file_suffix_lower})"
    if file_suffix_lower not in ALLOWED_EXTENSIONS: return False, f"Extension not in allowed list"
    try:
        if file_path.stat().st_size > MAX_FILE_SIZE_BYTES: return False, f"Exceeds size limit ({MAX_FILE_SIZE_MB}MB)"
    except OSError as e: return False, f"Cannot get file size ({e})"
    return True, "Allowed by extension"

def safe_read_file(file_path: Path):
    try: content = file_path.read_text(encoding='utf-8'); return content, None
    except UnicodeDecodeError:
        try: content = file_path.read_text(encoding='latin-1'); return content, "Read with fallback encoding (latin-1)"
        except Exception as e: return f"Error reading file: Could not decode content - {e}", "Read error (fallback failed)"
    except Exception as e: return f"Error reading file: {e}", "Read error"

def scan_directory_recursively(directory_path: Path):
    file_contents = {}; scanned_files_details = []; processed_count = 0
    for root, dirs, files in os.walk(directory_path, topdown=True):
        root_path = Path(root); processed_count += 1 + len(dirs) + len(files)
        if root_path.name in EXCLUDE_DIRS: dirs[:]= []; files[:]= []; scanned_files_details.append((str(root_path.relative_to(directory_path)), "Skipped", f"Excluded directory ({root_path.name})")); continue
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for filename in files:
            item_path = root_path / filename; relative_path = item_path.relative_to(directory_path); relative_path_str = str(relative_path)
            allowed, reason = is_file_allowed(item_path)
            if allowed:
                content, read_status = safe_read_file(item_path)
                if read_status and "error" in read_status.lower(): scanned_files_details.append((relative_path_str, "Error Reading", read_status))
                else:
                    # Use absolute path as key for uniqueness across different added root paths
                    file_contents[str(item_path.resolve())] = content; status = "Included" + (f" ({read_status})" if read_status else "")
                    try: detail=f"{item_path.stat().st_size / 1024:.1f} KB"
                    except: detail="Size N/A"
                    scanned_files_details.append((relative_path_str, status, detail))
            else: scanned_files_details.append((relative_path_str, "Skipped", reason))
    return file_contents, scanned_files_details, processed_count

def build_context_from_added_paths(added_paths_set):
    all_file_contents = {}; all_found_files_display = []; total_items_processed = 0
    if not added_paths_set: return {}, []
    sorted_paths = sorted(list(added_paths_set))
    for path_str in sorted_paths:
        try:
            path_obj = Path(path_str).resolve()
            if path_obj.is_file():
                allowed, reason = is_file_allowed(path_obj)
                if allowed:
                    content, read_status = safe_read_file(path_obj); unique_key = str(path_obj) # Absolute path
                    all_file_contents[unique_key] = content
                    try: detail=f"{path_obj.stat().st_size / 1024:.1f} KB" + (f" ({read_status})" if read_status else "")
                    except: detail = "Size N/A" + (f" ({read_status})" if read_status else "")
                    all_found_files_display.append((str(path_obj), "Included", detail)) # Display absolute path
                else: all_found_files_display.append((str(path_obj), "Skipped", reason))
            elif path_obj.is_dir():
                dir_contents, dir_scan_details, processed_count = scan_directory_recursively(path_obj)
                total_items_processed += processed_count
                # dir_contents already uses absolute path as key
                all_file_contents.update(dir_contents)
                # Add directory root to display details
                # all_found_files_display.append((str(path_obj), "Scanned", f"{len(dir_contents)} files found")) # Optional: Add dir summary
                for rel_path, status, detail in dir_scan_details:
                    abs_p_str = str(path_obj / rel_path); all_found_files_display.append((abs_p_str, status, detail)) # Display absolute path
            else: all_found_files_display.append((path_str, "Error", "Path does not exist"))
        except Exception as e: all_found_files_display.append((path_str, "Error", f"Processing failed: {e}"))
    # Sort display by the absolute path string
    all_found_files_display.sort(key=lambda x: x[0])
    return all_file_contents, all_found_files_display

def format_context(file_contents_dict):
    if not file_contents_dict: return "No local file context provided or found."
    context_str = "--- Local File Context ---\n\n"; sorted_keys = sorted(file_contents_dict.keys())
    for abs_path_key in sorted_keys: # Keys are now absolute paths
        content = file_contents_dict[abs_path_key]
        # Try to show a relative path if possible, based on added root paths
        display_path = abs_path_key
        for added_root in st.session_state.get('added_paths', set()):
            try:
                added_root_path = Path(added_root).resolve()
                if Path(abs_path_key).is_relative_to(added_root_path):
                    display_path = str(Path(abs_path_key).relative_to(added_root_path))
                    if added_root_path.is_file(): # If root was a file, just show filename
                         display_path = Path(abs_path_key).name
                    break # Use first match
            except (ValueError, TypeError): # is_relative_to needs Python 3.9+
                if abs_path_key.startswith(str(added_root_path)):
                     display_path = os.path.relpath(abs_path_key, str(added_root_path))
                     if added_root_path.is_file(): display_path = Path(abs_path_key).name
                     break

        context_str += f"--- File: {display_path} ---\n"; context_str += f"```\n{content}\n```\n\n"
    context_str += "--- End Local File Context ---\n\n"; return context_str


def update_context_and_tokens(model_instance):
    token_count = 0; token_count_str = "Token Count: N/A"; context_content_dict = {}; context_files_details = []
    if 'added_paths' in st.session_state and st.session_state.added_paths:
        content_dict, display_details = build_context_from_added_paths(st.session_state.added_paths)
        context_files_details = display_details; context_content_dict = content_dict
    st.session_state.context_files_details = context_files_details
    st.session_state.current_context_content_dict = context_content_dict

    if model_instance:
        try:
            current_instruction = st.session_state.get("system_instruction", "").strip()
            instruction_prefix = f"--- System Instruction ---\n{current_instruction}\n--- End System Instruction ---\n\n" if current_instruction else ""
            current_context = format_context(context_content_dict)
            text_for_token_count = instruction_prefix + current_context
            if text_for_token_count.strip() and text_for_token_count != "No local file context provided or found.":
                 with st.spinner("Calculating context/instruction tokens..."):
                    # Make context only temporarily for token counting if needed
                    # temp_parts = [{"text": text_for_token_count}]
                    # count_response = model_instance.count_tokens(temp_parts)
                    count_response = model_instance.count_tokens(text_for_token_count) # Count combined text
                    token_count = count_response.total_tokens
                    token_count_str = f"Token Count (Instr + Context): {token_count:,}"
            else: token_count_str = "Token Count: 0"
        except Exception as e: print(f"Error counting tokens: {e}"); token_count_str = f"Token Count: Error ({e})"
    else: token_count_str = "Token Count: N/A (Add API Key & Model)"
    st.session_state.current_token_count = token_count
    st.session_state.current_token_count_str = token_count_str
    # Update the placeholder immediately if it exists
    if 'token_count_placeholder' in st.session_state:
         st.session_state.token_count_placeholder.caption(st.session_state.current_token_count_str)


def get_model_output_limit(model_name):
    try:
        with st.spinner(f"Fetching limits for {Path(model_name).name}..."):
            model_info = genai.get_model(model_name)
        if hasattr(model_info, 'output_token_limit'): return model_info.output_token_limit
        else: print(f"Warning: output_token_limit not found for {model_name}."); return FALLBACK_MODEL_MAX_OUTPUT_TOKENS
    except Exception as e: print(f"Error getting model info for {model_name}: {e}"); return FALLBACK_MODEL_MAX_OUTPUT_TOKENS

# --- Function to reconstruct gemini_history from messages ---
def reconstruct_gemini_history(messages):
    history = []
    current_context_dict = st.session_state.get('current_context_content_dict', {})
    system_instruction = st.session_state.get("system_instruction", "").strip()
    instruction_prefix = f"--- System Instruction ---\n{system_instruction}\n--- End System Instruction ---\n\n" if system_instruction else ""
    context_str = format_context(current_context_dict) if current_context_dict else ""

    for msg in messages:
        if msg["role"] == "user":
            # Reconstruct the full prompt potentially sent for the *first* user message
            # For subsequent user messages in history, just use the content.
            # This is an approximation, as the exact context/instruction might have changed mid-conversation.
            # The API history expects alternating user/model turns.
            full_prompt = instruction_prefix + context_str + "\n\n---\n\nUser Question:\n" + msg["content"]
            # Only add the full prompt for the *first* user turn in the reconstructed history
            # For simplicity here, we'll just use the content for history reconstruction.
            # A more accurate approach might involve storing the 'full_prompt_sent' with the user message in DB
            # and retrieving it when loading. For now, just use content.
            history.append({"role": "user", "parts": [{"text": msg["content"]}]})
        elif msg["role"] == "assistant":
            history.append({"role": "model", "parts": [{"text": msg["content"]}]})
    return history


# --- Streamlit Page Setup ---
st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")
# Use columns for layout: Sidebar | Main Chat | Parameters
col_main, col_params = st.columns([3, 1]) # Adjust ratio as needed

with col_main:
    st.title(f"{PAGE_ICON} {PAGE_TITLE}")

# --- Initialize Session State ---
# Basic state
if "messages" not in st.session_state: st.session_state.messages = [] # For UI display
if "gemini_history" not in st.session_state: st.session_state.gemini_history = [] # For API context
if "current_conversation_id" not in st.session_state: st.session_state.current_conversation_id = None
if "loaded_conversations" not in st.session_state: st.session_state.loaded_conversations = [] # Store [{'id':.., 'title':..}, ...]
# Context state
if "added_paths" not in st.session_state: st.session_state.added_paths = set()
if "context_files_details" not in st.session_state: st.session_state.context_files_details = []
if "current_context_content_dict" not in st.session_state: st.session_state.current_context_content_dict = {}
# Model state
if "available_models" not in st.session_state: st.session_state.available_models = None
if "selected_model_name" not in st.session_state: st.session_state.selected_model_name = DEFAULT_MODEL
if "models_loaded_for_key" not in st.session_state: st.session_state.models_loaded_for_key = None
if "current_model_instance" not in st.session_state: st.session_state.current_model_instance = None
if "current_model_max_output_tokens" not in st.session_state: st.session_state.current_model_max_output_tokens = FALLBACK_MODEL_MAX_OUTPUT_TOKENS
# Instruction state
if "system_instruction" not in st.session_state: st.session_state.system_instruction = ""
if "instruction_names" not in st.session_state: st.session_state.instruction_names = db.get_instruction_names()
# Generation parameters state (Defaults set here)
if "temperature" not in st.session_state: st.session_state.temperature = 0.7
if "top_p" not in st.session_state: st.session_state.top_p = 1.0
if "top_k" not in st.session_state: st.session_state.top_k = 40
# Max output tokens now uses a default value, will be clamped later by model limit
if "max_output_tokens" not in st.session_state: st.session_state.max_output_tokens = DEFAULT_MAX_OUTPUT_TOKENS_SLIDER
if "stop_sequences_str" not in st.session_state: st.session_state.stop_sequences_str = ""
if "json_mode" not in st.session_state: st.session_state.json_mode = False
# Token count state
if "current_token_count" not in st.session_state: st.session_state.current_token_count = 0
if "current_token_count_str" not in st.session_state: st.session_state.current_token_count_str = "Token Count: N/A"
# API Key state
if 'api_key_loaded' not in st.session_state: st.session_state.api_key_loaded = False
if 'current_api_key' not in st.session_state: st.session_state.current_api_key = ""


# --- Initialize DB & Load API Key ---
# Ensure tables exist on first run
# db.create_tables() # Moved to end of database.py on import

if not st.session_state.api_key_loaded:
    loaded_api_key = db.load_setting('api_key')
    if loaded_api_key:
        st.session_state.current_api_key = loaded_api_key
    st.session_state.api_key_loaded = True

# --- Sidebar ---
st.sidebar.header("Chat & Config")

# --- Conversation History (Sidebar) ---
st.sidebar.subheader("Conversations")

# Button to start a new chat
if st.sidebar.button("➕ New Chat", key="new_chat_button"):
    st.session_state.messages = []
    st.session_state.gemini_history = []
    st.session_state.current_conversation_id = None # Signal to create new one on next message
    # Optionally clear context/instructions for a truly fresh start
    # st.session_state.added_paths = set()
    # st.session_state.system_instruction = ""
    # update_context_and_tokens(st.session_state.get("current_model_instance"))
    st.rerun()

# Load and display recent conversations
# We load this on each run potentially, could optimize if slow
st.session_state.loaded_conversations = db.get_recent_conversations(limit=15) # Load more initially

st.sidebar.markdown("---")
if not st.session_state.loaded_conversations:
    st.sidebar.caption("No past conversations found.")
else:
    st.sidebar.caption("Recent Chats:")
    # Use buttons for selection, unique key is essential
    for convo in st.session_state.loaded_conversations:
        convo_id = convo["id"]
        convo_title = convo["title"] if convo["title"] else f"Chat from {convo.get('last_update', '')}"
        # Truncate title if too long for button
        display_title = (convo_title[:25] + '...') if len(convo_title) > 28 else convo_title
        if st.sidebar.button(f"{display_title}", key=f"load_conv_{convo_id}", help=f"Load: {convo_title}", use_container_width=True):
            if convo_id != st.session_state.get("current_conversation_id"):
                with st.spinner(f"Loading chat: {display_title}..."):
                    loaded_messages = db.get_conversation_messages(convo_id)
                    if loaded_messages is not None:
                        st.session_state.messages = loaded_messages # Update UI messages
                        # Reconstruct API history (important for context continuation)
                        st.session_state.gemini_history = reconstruct_gemini_history(loaded_messages)
                         # Prune loaded history if it's too long for the API
                        if len(st.session_state.gemini_history) > MAX_HISTORY_PAIRS * 2:
                            st.session_state.gemini_history = st.session_state.gemini_history[-(MAX_HISTORY_PAIRS * 2):]
                        st.session_state.current_conversation_id = convo_id
                        # Note: System instruction and context are NOT loaded, they remain as set.
                        # To load them, they'd need to be saved with the conversation.
                        st.success(f"Loaded chat: {display_title}")
                        st.rerun()
                    else:
                        st.error(f"Failed to load messages for chat {display_title}.")
            else:
                st.sidebar.info("Chat already loaded.") # Or just do nothing

st.sidebar.markdown("---") # Separator before API Key

# --- API Key & Model Config (Sidebar) ---
api_key_input = st.sidebar.text_input( "Gemini API Key:", type="password", key="api_key_widget", value=st.session_state.current_api_key, help="Saved locally in SQLite DB.")
# Logic to handle API key changes and state reset
if api_key_input != st.session_state.current_api_key:
    st.session_state.current_api_key = api_key_input
    # Reset dependent states
    st.session_state.available_models = None; st.session_state.models_loaded_for_key = None; st.session_state.selected_model_name = DEFAULT_MODEL; st.session_state.current_model_instance = None; st.session_state.current_model_max_output_tokens = FALLBACK_MODEL_MAX_OUTPUT_TOKENS;
    st.session_state.current_token_count = 0; st.session_state.current_token_count_str = "Token Count: N/A";
    # Trigger rerun to apply changes and attempt model loading
    st.rerun()

# Link to clear key - Consider making this a button for clearer action
st.sidebar.warning("API Key stored locally. [Clear Saved Key](?clear_key=true)", icon="⚠️")
if st.query_params.get("clear_key"):
    if db.delete_setting('api_key'): st.success("Saved API Key cleared.")
    else: st.error("Failed to clear saved API key from DB.")
    # Reset relevant state variables
    st.session_state.current_api_key = ""; st.session_state.api_key_loaded = True # Mark checked but empty
    st.session_state.available_models = None; st.session_state.models_loaded_for_key = None; st.session_state.selected_model_name = DEFAULT_MODEL; st.session_state.current_model_instance = None; st.session_state.current_model_max_output_tokens = FALLBACK_MODEL_MAX_OUTPUT_TOKENS;
    st.session_state.current_token_count = 0; st.session_state.current_token_count_str = "Token Count: N/A";
    # Clear query params and rerun
    st.query_params.clear();
    # Need a slight delay or Streamlit might not pick up state change before rerun finishes processing params
    time.sleep(0.1)
    st.rerun()


# --- Model Loading & Selection (Sidebar) ---
model_select_container = st.sidebar.empty()
models_successfully_loaded = False
model_instance = st.session_state.get("current_model_instance")

if st.session_state.current_api_key:
    active_api_key = st.session_state.current_api_key
    if st.session_state.models_loaded_for_key != active_api_key:
        try:
            with st.spinner("Configuring API & fetching models..."):
                genai.configure(api_key=active_api_key); model_list = []
                try:
                    for m in genai.list_models():
                        if 'generateContent' in m.supported_generation_methods: model_list.append(m.name)
                except Exception as list_err: st.sidebar.error(f"Model list error: {list_err}"); st.session_state.available_models = None; st.session_state.models_loaded_for_key = None; model_instance = None; st.session_state.current_model_instance = None; st.session_state.current_model_max_output_tokens = FALLBACK_MODEL_MAX_OUTPUT_TOKENS
                else:
                    model_list.sort(); st.session_state.available_models = model_list; st.session_state.models_loaded_for_key = active_api_key
                    if db.save_setting('api_key', active_api_key): print("API Key saved.")
                    else: print("Failed to save API key.")

                    current_selection = st.session_state.selected_model_name
                    if not current_selection or current_selection not in model_list:
                        st.session_state.selected_model_name = DEFAULT_MODEL if DEFAULT_MODEL in model_list else (model_list[0] if model_list else None)

                    if st.session_state.selected_model_name:
                        limit = get_model_output_limit(st.session_state.selected_model_name)
                        st.session_state.current_model_max_output_tokens = limit
                        # CLAMP existing max_output_tokens setting if it exceeds new limit
                        if st.session_state.max_output_tokens > limit:
                             st.session_state.max_output_tokens = limit
                        elif st.session_state.max_output_tokens <= 0: # Ensure it's at least 1
                             st.session_state.max_output_tokens = min(DEFAULT_MAX_OUTPUT_TOKENS_SLIDER, limit)

                        try: model_instance = genai.GenerativeModel(st.session_state.selected_model_name); st.session_state.current_model_instance = model_instance
                        except Exception as model_init_err: st.error(f"Failed init model '{st.session_state.selected_model_name}': {model_init_err}"); model_instance = None; st.session_state.current_model_instance = None; st.session_state.current_model_max_output_tokens = FALLBACK_MODEL_MAX_OUTPUT_TOKENS
                    else:
                        model_instance = None; st.session_state.current_model_instance = None; st.session_state.current_model_max_output_tokens = FALLBACK_MODEL_MAX_OUTPUT_TOKENS
                    models_successfully_loaded = True
                    update_context_and_tokens(model_instance) # Update tokens after model load

        except Exception as config_err: st.sidebar.error(f"API Key/Config error: {config_err}"); st.session_state.available_models = None; st.session_state.models_loaded_for_key = None; st.session_state.selected_model_name = DEFAULT_MODEL; model_instance = None; st.session_state.current_model_instance = None; st.session_state.current_model_max_output_tokens = FALLBACK_MODEL_MAX_OUTPUT_TOKENS
    else: # Key hasn't changed AND models were loaded
        if not model_instance and st.session_state.selected_model_name:
             try: model_instance = genai.GenerativeModel(st.session_state.selected_model_name); st.session_state.current_model_instance = model_instance
             except Exception as model_init_err: print(f"Failed re-init model: {model_init_err}"); model_instance = None; st.session_state.current_model_instance = None
        models_successfully_loaded = st.session_state.available_models is not None
else: # No API Key
    if st.session_state.models_loaded_for_key is not None:
        st.session_state.available_models = None; st.session_state.models_loaded_for_key = None; st.session_state.selected_model_name = DEFAULT_MODEL; model_instance = None; st.session_state.current_model_instance = None; st.session_state.current_model_max_output_tokens = FALLBACK_MODEL_MAX_OUTPUT_TOKENS; st.session_state.current_token_count = 0; st.session_state.current_token_count_str = "Token Count: N/A";

# Display Model Selectbox (Sidebar)
if st.session_state.available_models:
    try:
        current_selection = st.session_state.selected_model_name
        if not current_selection or current_selection not in st.session_state.available_models:
            current_selection = DEFAULT_MODEL if DEFAULT_MODEL in st.session_state.available_models else (st.session_state.available_models[0] if st.session_state.available_models else None)

        if current_selection:
             selected_index = st.session_state.available_models.index(current_selection)
             selected_model = model_select_container.selectbox( "Select Gemini Model:", options=st.session_state.available_models, index=selected_index, key='model_select_dropdown')

             if selected_model != st.session_state.selected_model_name:
                 st.session_state.selected_model_name = selected_model
                 limit = get_model_output_limit(selected_model) # Fetch limit for new model
                 st.session_state.current_model_max_output_tokens = limit
                 # Reset user setting ONLY if it exceeds new limit, otherwise keep user pref
                 if st.session_state.max_output_tokens > limit:
                     st.session_state.max_output_tokens = limit
                 elif st.session_state.max_output_tokens <= 0: # Ensure > 0
                     st.session_state.max_output_tokens = min(DEFAULT_MAX_OUTPUT_TOKENS_SLIDER, limit)

                 try: model_instance = genai.GenerativeModel(selected_model); st.session_state.current_model_instance = model_instance
                 except Exception as model_init_err: st.error(f"Failed init selected model '{selected_model}': {model_init_err}"); model_instance = None; st.session_state.current_model_instance = None
                 update_context_and_tokens(model_instance) # Update tokens for new model
                 st.rerun() # Rerun crucial to update slider max/value
        else: model_select_container.warning("No valid model available.")
    except Exception as e: model_select_container.error(f"Error displaying models: {e}"); st.session_state.available_models = None
elif st.session_state.current_api_key and st.session_state.models_loaded_for_key == st.session_state.current_api_key: model_select_container.warning("No suitable models found for this key.")
elif not st.session_state.current_api_key: model_select_container.warning("Enter API Key to load models.")


# --- System Instructions Expander (Top of Sidebar) ---
with st.sidebar.expander("System Instructions", expanded=False):
    def instruction_change_callback():
        update_context_and_tokens(st.session_state.get("current_model_instance"))

    st.session_state.system_instruction = st.text_area(
        "Enter instructions:", value=st.session_state.get("system_instruction", ""), height=150,
        key="system_instruction_text_area", on_change=instruction_change_callback
    )

    instr_name_save = st.text_input("Save as:", key="instr_save_name")
    if st.button("Save Instruction", key="save_instr_btn"):
        success, message = db.save_instruction(instr_name_save, st.session_state.system_instruction)
        if success: st.success(message); st.session_state.instruction_names = db.get_instruction_names(); st.rerun()
        else: st.error(message)
    st.markdown("---")

    if not st.session_state.instruction_names: st.session_state.instruction_names = db.get_instruction_names() # Reload if empty
    if st.session_state.instruction_names:
        instr_name_load = st.selectbox("Load instruction:", options=[""] + st.session_state.instruction_names, key="instr_load_select")
        col_load, col_delete = st.columns(2)
        with col_load:
            if st.button("Load", key="load_instr_btn", disabled=not instr_name_load):
                loaded_text = db.load_instruction(instr_name_load)
                if loaded_text is not None:
                    st.session_state.system_instruction = loaded_text
                    update_context_and_tokens(st.session_state.get("current_model_instance"))
                    st.success(f"Loaded '{instr_name_load}'.")
                    # Clear save name field after load
                    st.session_state.instr_save_name = instr_name_load # Pre-fill save name
                    st.rerun()
                else: st.error(f"Could not load '{instr_name_load}'.")
        with col_delete:
             if st.button("Delete", key="delete_instr_btn", disabled=not instr_name_load):
                 current_text_if_loaded = db.load_instruction(instr_name_load) # Check content before delete
                 success, message = db.delete_instruction(instr_name_load)
                 if success:
                     st.success(message); st.session_state.instruction_names = db.get_instruction_names()
                     if st.session_state.system_instruction == current_text_if_loaded:
                          st.session_state.system_instruction = ""
                          update_context_and_tokens(st.session_state.get("current_model_instance"))
                     # Clear selectbox and potentially save name
                     st.session_state.instr_load_select = ""
                     if st.session_state.instr_save_name == instr_name_load:
                          st.session_state.instr_save_name = ""
                     st.rerun()
                 else: st.error(message)
    else: st.caption("No saved instructions.")


# --- Context Management (Sidebar) ---
st.sidebar.markdown("---") # Separator
st.sidebar.header("Manage Context")
new_path_input = st.sidebar.text_input("Add File/Folder Path:", key="new_path", placeholder="Enter path & click Add")
if st.sidebar.button("Add Path", key="add_path_button"):
    if new_path_input:
        try:
            resolved_path_obj = Path(new_path_input).resolve(); resolved_path = str(resolved_path_obj)
            if resolved_path_obj.exists():
                if resolved_path not in st.session_state.added_paths:
                     st.session_state.added_paths.add(resolved_path); st.sidebar.success(f"Added: {resolved_path}")
                     update_context_and_tokens(st.session_state.get("current_model_instance")); st.rerun()
                else: st.sidebar.info("Path already added.")
            else: st.sidebar.error(f"Path not found: {new_path_input}")
        except Exception as e: st.sidebar.error(f"Error resolving path: {e}")
    else: st.sidebar.warning("Please enter a path to add.")

with st.sidebar.expander("Managed Paths", expanded=True):
    if not st.session_state.added_paths: st.caption("No paths added.")
    else:
        col1, col2 = st.columns([4, 1]); paths_to_remove = []
        for path_str in sorted(list(st.session_state.added_paths)):
            with col1: st.code(path_str, language=None) # Display resolved path
            with col2:
                if st.button("❌", key=f"remove_{path_str}", help=f"Remove {path_str}"): paths_to_remove.append(path_str)
        if paths_to_remove:
            needs_update = False
            for path_to_remove in paths_to_remove:
                 if path_to_remove in st.session_state.added_paths: st.session_state.added_paths.discard(path_to_remove); needs_update = True
            if needs_update: update_context_and_tokens(st.session_state.get("current_model_instance")); st.rerun()

with st.sidebar.expander("Effective Files", expanded=False):
    if not st.session_state.get('context_files_details', []): st.caption("Add paths to see files.")
    else:
        with st.container(height=300):
            inc_count, skip_count, err_count = 0, 0, 0
            # Display absolute paths for clarity
            for path, status, detail in st.session_state.context_files_details:
                icon = "✅" if "Included" in status else ("⚠️" if "Skipped" in status else "❌")
                color = "green" if "Included" in status else ("orange" if "Skipped" in status else "red")
                st.markdown(f"<span style='color:{color};'>{icon} **{status}:** `{path}` ({detail})</span>", unsafe_allow_html=True)
                if "Included" in status: inc_count += 1
                elif "Skipped" in status: skip_count += 1
                else: err_count += 1
            st.caption(f"Total: {inc_count} Incl, {skip_count} Skip, {err_count} Err")


# --- Token Count Display & Refresh (Sidebar) ---
st.sidebar.markdown("---") # Separator
if 'token_count_placeholder' not in st.session_state:
     st.session_state.token_count_placeholder = st.sidebar.empty()
st.session_state.token_count_placeholder.caption(st.session_state.get("current_token_count_str", "Token Count: N/A"))

if st.sidebar.button("Refresh Tokens", key="refresh_tokens_btn"):
     update_context_and_tokens(st.session_state.get("current_model_instance"))


# --- Clear Chat / Footer (Sidebar) ---
st.sidebar.markdown("---") # Separator
if st.sidebar.button("Clear Current Chat History"):
    st.session_state.messages = []; st.session_state.gemini_history = []
    # Keep current_conversation_id, let user decide to start new one
    st.rerun()
st.sidebar.markdown("---"); st.sidebar.markdown(f"Version: {APP_VERSION} | {PAGE_TITLE}")


# ==============================================
# --- Main Chat Area (Left/Center Column) ---
# ==============================================
with col_main:
    # Model/Chat Initialization Check
    model = st.session_state.get("current_model_instance")
    chat = None
    if model:
        try:
            # Rebuild history just before starting chat if loading from DB happened
            current_gemini_history = reconstruct_gemini_history(st.session_state.messages)
            # Prune if necessary before starting chat
            if len(current_gemini_history) > MAX_HISTORY_PAIRS * 2:
                 current_gemini_history = current_gemini_history[-(MAX_HISTORY_PAIRS * 2):]
            chat = model.start_chat(history=current_gemini_history) # Use potentially pruned history
            st.session_state.gemini_history = current_gemini_history # Store the potentially pruned history back
        except Exception as chat_init_err:
            st.error(f"Error starting chat session: {chat_init_err}")
            model = None # Invalidate model if chat fails

    if not st.session_state.current_api_key: st.warning("API Key required (in sidebar).")
    elif not model: st.warning("Select/Initialize Model (in sidebar).")

    # Display previous chat messages from state
    for message in st.session_state.messages:
        with st.chat_message(message["role"]): st.markdown(message["content"])

    # Get user input
    prompt = st.chat_input("Ask a question...")

    if prompt:
        # --- Prerequisites Check ---
        if not st.session_state.current_api_key: st.error("API Key required."); st.stop()
        if not model: st.error("Model not ready."); st.stop()
        if not chat: # Ensure chat is valid (re-check after potential init failure)
            try:
                 # Attempt to restart chat if it failed before but model is now okay
                 current_gemini_history = reconstruct_gemini_history(st.session_state.messages)
                 if len(current_gemini_history) > MAX_HISTORY_PAIRS * 2:
                     current_gemini_history = current_gemini_history[-(MAX_HISTORY_PAIRS * 2):]
                 chat = model.start_chat(history=current_gemini_history)
                 st.session_state.gemini_history = current_gemini_history
            except Exception as e:
                 st.error(f"Failed to start chat session: {e}"); st.stop()
        if not chat: st.error("Chat session could not be initialized."); st.stop() # Final check

        # --- Conversation ID Management ---
        if not st.session_state.current_conversation_id:
            # Start a new conversation in DB if one isn't active
            new_conv_id = db.start_new_conversation()
            if new_conv_id:
                st.session_state.current_conversation_id = new_conv_id
                # Refresh sidebar conversations list? Not strictly needed immediately.
            else:
                st.error("Failed to create a new conversation record in the database.")
                st.stop()

        active_conversation_id = st.session_state.current_conversation_id

        # Add user message to UI state
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        # --- Prepare for API Call ---
        context = "No context."; file_contents_dict = st.session_state.get('current_context_content_dict', {}); context_files_list = list(file_contents_dict.keys()) # Use absolute paths
        if file_contents_dict: context = format_context(file_contents_dict)
        system_instruction = st.session_state.get("system_instruction", "").strip(); instruction_prefix = f"--- System Instruction ---\n{system_instruction}\n--- End System Instruction ---\n\n" if system_instruction else ""
        full_prompt = instruction_prefix + context + "\n\n---\n\nUser Question:\n" + prompt

        # --- Save User Message to DB ---
        db.save_message(
            conversation_id=active_conversation_id,
            role='user',
            content=prompt,
            model_used=st.session_state.selected_model_name, # Store model used for this turn
            context_files=context_files_list, # Save paths used for this turn
            full_prompt_sent=full_prompt # Save the constructed prompt
        )

        # --- Prepare Generation Config --- (Using values from state, set by right column)
        try:
            stop_sequences = [seq.strip() for seq in st.session_state.stop_sequences_str.splitlines() if seq.strip()]
            # Clamp max_output_tokens from slider value against actual model limit
            max_tokens_for_api = min(st.session_state.max_output_tokens, st.session_state.get('current_model_max_output_tokens', FALLBACK_MODEL_MAX_OUTPUT_TOKENS))

            gen_config_dict = {
                "temperature": st.session_state.temperature,
                "top_p": st.session_state.top_p,
                "top_k": st.session_state.top_k,
                "max_output_tokens": max_tokens_for_api, # Use the clamped value
                **({"stop_sequences": stop_sequences} if stop_sequences else {})
            }
            if st.session_state.json_mode: gen_config_dict["response_mime_type"] = "application/json"
            generation_config = gen_config_dict # Use dict directly
            # print("Generation Config:", generation_config) # Debug print
        except Exception as e: st.error(f"Error creating generation config: {e}"); generation_config = None; st.stop()

        # --- Send to Gemini & Display Response ---
        if generation_config is not None:
            try:
                with st.chat_message("assistant"):
                    message_placeholder = st.empty(); full_response_content = ""
                    model_short_name = Path(st.session_state.selected_model_name).name if st.session_state.selected_model_name else "Gemini"
                    with st.spinner(f"Asking {model_short_name}..."):
                        # Send only the latest prompt, history is managed by the 'chat' object
                        response = chat.send_message(
                            prompt, # Send only the user's latest message content
                            stream=True,
                            generation_config=GenerationConfig(**generation_config) # Pass the config object
                            # Note: The 'full_prompt' with context/instructions was conceptually part of the *first* message sent
                            # via chat.send_message OR implicitly included in the history. Subsequent turns send only delta.
                            # Let's test sending only 'prompt' as `start_chat` already has history.
                            # If context needs to be re-injected explicitly every time, the logic needs adjustment.
                            # The Gemini API generally uses the history provided to `start_chat`.
                            )

                    for chunk in response:
                        if hasattr(chunk, 'text') and chunk.text:
                            full_response_content += chunk.text; message_placeholder.markdown(full_response_content + "▌")
                        # Handle potential errors/feedback if needed (e.g., safety)
                        # elif hasattr(chunk, 'prompt_feedback'): etc.

                    message_placeholder.markdown(full_response_content) # Final display

                # Add AI response to UI history
                st.session_state.messages.append({"role": "assistant", "content": full_response_content})

                # --- Save AI Response to DB ---
                db.save_message(
                    conversation_id=active_conversation_id,
                    role='assistant',
                    content=full_response_content,
                    model_used=st.session_state.selected_model_name
                )

                # Update gemini_history (internal API state) - IMPORTANT
                # The 'chat' object might update its internal history, but we also sync our session state copy
                # Reconstruct just to be safe, though chat.history might be accessible directly
                st.session_state.gemini_history = reconstruct_gemini_history(st.session_state.messages)
                # Prune if needed AFTER adding new messages
                if len(st.session_state.gemini_history) > MAX_HISTORY_PAIRS * 2:
                     st.session_state.gemini_history = st.session_state.gemini_history[-(MAX_HISTORY_PAIRS * 2):]
                     # Also prune UI messages to match? Optional, UI can show more.
                     # st.session_state.messages = st.session_state.messages[-(MAX_HISTORY_PAIRS * 2):]

            except Exception as e:
                st.error(f"Error during Gemini communication: {e}")
                # Rollback last user message from UI state if AI failed
                if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
                    st.session_state.messages.pop()
                # DB already saved user message, maybe delete it or mark as failed? Complex. For now, leave it.
                # Also rollback gemini_history state
                if st.session_state.gemini_history and st.session_state.gemini_history[-1]["role"] == "user":
                     st.session_state.gemini_history.pop()

            # No automatic rerun needed here, message display updates handle it
            st.rerun() # Force rerun to ensure sidebar conversation list might update order


# =========================================
# --- Generation Parameters (Right Column) ---
# =========================================
with col_params:
    st.header("Parameters")
    st.markdown("---")

    # Retrieve limits/values from session state
    model_max_limit = st.session_state.get('current_model_max_output_tokens', FALLBACK_MODEL_MAX_OUTPUT_TOKENS)
    # Ensure current slider value doesn't exceed the model's actual limit from state
    current_max_output_setting = st.session_state.get('max_output_tokens', DEFAULT_MAX_OUTPUT_TOKENS_SLIDER)
    # Clamp value before passing to slider IF necessary (e.g., if limit decreased)
    if current_max_output_setting > model_max_limit: current_max_output_setting = model_max_limit
    if current_max_output_setting <= 0: current_max_output_setting = min(DEFAULT_MAX_OUTPUT_TOKENS_SLIDER, model_max_limit) # Ensure > 0


    # Use a slider for Max Output Tokens
    st.session_state.max_output_tokens = st.slider(
        f"Max Output Tokens (Limit: {model_max_limit:,})",
        min_value=1,
        max_value=model_max_limit, # Dynamic max based on selected model
        value=current_max_output_setting, # Current setting, clamped
        step=max(1, model_max_limit // 256), # Dynamic step size, min 1
        key="maxoutput_slider", # New key for slider
        help=f"Max tokens per response. Current model limit: {model_max_limit:,}"
    )

    # Temperature, Top P, Top K Sliders (remain sliders)
    st.session_state.temperature = st.slider( "Temperature:", 0.0, 2.0, step=0.05, value=st.session_state.temperature, key="temp_slider", help="Controls randomness (Default: 0.7)")
    st.session_state.top_p = st.slider( "Top P:", 0.0, 1.0, step=0.01, value=st.session_state.top_p, key="topp_slider", help="Nucleus sampling probability (Default: 1.0)")
    st.session_state.top_k = st.slider( "Top K:", 1, 100, step=1, value=st.session_state.top_k, key="topk_slider", help="Considers top K tokens (Default: 40)") # TopK limit isn't usually model dependent in the same way

    st.markdown("---")

    # Stop Sequences & JSON Mode (remain the same)
    st.session_state.stop_sequences_str = st.text_area( "Stop Sequences (one per line):", value=st.session_state.stop_sequences_str, key="stopseq_textarea", height=80, help="Stop generation if these appear.")
    st.session_state.json_mode = st.toggle( "JSON Output Mode", value=st.session_state.json_mode, key="json_toggle", help="Request structured JSON output.")