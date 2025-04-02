# gemini_local_chat.py
# Version: 2.2.0 - Added message controls (Delete, Edit, Regenerate, Summarize)
# NOTE: This requires database.py Version 2.2+ and gemini_logic.py v2.2+

import streamlit as st
import google.generativeai as genai
from google.generativeai.types import GenerationConfig
from pathlib import Path
import database as db  # Import database helper (ensure it's v2.1+)
import time
import gemini_logic as logic
import logging # Import logging
import logging_config # Import and run logging configuration setup

# Get a logger instance for this module
logger = logging.getLogger(__name__)

# --- Configuration ---
APP_VERSION = logic.APP_VERSION
PAGE_TITLE = "Gemini Chat Pro"
PAGE_ICON = "✨"
TITLE_MAX_LENGTH = logic.TITLE_MAX_LENGTH
DEFAULT_MODEL = logic.DEFAULT_MODEL
DEFAULT_MAX_OUTPUT_TOKENS_SLIDER = logic.DEFAULT_MAX_OUTPUT_TOKENS_SLIDER
FALLBACK_MODEL_MAX_OUTPUT_TOKENS = logic.FALLBACK_MODEL_MAX_OUTPUT_TOKENS
MAX_HISTORY_PAIRS = logic.MAX_HISTORY_PAIRS

# --- Streamlit Page Setup ---
st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")
col_main, col_params = st.columns([3, 1])

with col_main:
    st.title(f"{PAGE_ICON} {PAGE_TITLE}")

# --- Initialize Session State (Defaults are crucial) ---
# Basic state
if "messages" not in st.session_state: st.session_state.messages = [] # Will store dicts with id, role, content, timestamp
if "gemini_history" not in st.session_state: st.session_state.gemini_history = []
if "current_conversation_id" not in st.session_state: st.session_state.current_conversation_id = None
if "loaded_conversations" not in st.session_state: st.session_state.loaded_conversations = []
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
if "editing_message_id" not in st.session_state: st.session_state.editing_message_id = None
if "editing_message_content" not in st.session_state: st.session_state.editing_message_content = ""

# --- Generation parameters state (THESE ARE THE DEFAULTS FOR A *NEW* CHAT) ---
DEFAULT_GEN_CONFIG = {
    "temperature": 0.7,
    "top_p": 1.0,
    "top_k": 40,
    "max_output_tokens": DEFAULT_MAX_OUTPUT_TOKENS_SLIDER,
    "stop_sequences_str": "",
    "json_mode": False
}
for key, value in DEFAULT_GEN_CONFIG.items():
    if key not in st.session_state:
        st.session_state[key] = value
# --- End Generation parameters state ---
# Token count state
if "current_token_count" not in st.session_state: st.session_state.current_token_count = 0
if "current_token_count_str" not in st.session_state: st.session_state.current_token_count_str = "Token Count: N/A"
# API Key state
if 'api_key_loaded' not in st.session_state: st.session_state.api_key_loaded = False
if 'current_api_key' not in st.session_state: st.session_state.current_api_key = ""

# --- Function to Update State from Logic ---
# Encapsulates the state update logic after calling the refactored function
def reload_conversation_state(conversation_id):
    """Fetches messages and updates session state."""
    logger.info(f"Reloading state for conversation ID: {conversation_id}")
    if not conversation_id:
        st.session_state.messages = []
        st.session_state.gemini_history = []
        logger.debug("Cleared messages and history as conversation ID is None.")
        return

    loaded_messages = db.get_conversation_messages(conversation_id, include_ids_timestamps=True)
    st.session_state.messages = loaded_messages
    # Reconstruct history carefully, ensuring correct order and format
    st.session_state.gemini_history = logic.reconstruct_gemini_history(
        [{"role": m["role"], "content": m["content"]} for m in loaded_messages] # Pass only role/content
    )
    # Apply history limit
    if len(st.session_state.gemini_history) > MAX_HISTORY_PAIRS * 2:
        logger.warning(f"History truncated during reload ({len(st.session_state.gemini_history)} -> {MAX_HISTORY_PAIRS*2})")
        st.session_state.gemini_history = st.session_state.gemini_history[-(MAX_HISTORY_PAIRS * 2):]

    logger.debug(f"Reloaded {len(loaded_messages)} messages and reconstructed history ({len(st.session_state.gemini_history)} pairs).")

def update_state_from_logic():
    try:
        token_count, token_str, details, content_dict = logic.update_context_and_tokens(
            st.session_state.get("current_model_instance"),
            st.session_state.added_paths,
            st.session_state.system_instruction
        )
        st.session_state.current_token_count = token_count
        st.session_state.current_token_count_str = token_str
        st.session_state.context_files_details = details
        st.session_state.current_context_content_dict = content_dict
        # Update placeholder if it exists
        if 'token_count_placeholder' in st.session_state:
             st.session_state.token_count_placeholder.caption(st.session_state.current_token_count_str)
        logger.debug("Session state updated from logic.update_context_and_tokens")
    except Exception as e:
        logger.error(f"Error updating state from logic.update_context_and_tokens: {e}", exc_info=True)
        st.session_state.current_token_count = 0
        st.session_state.current_token_count_str = "Token Count: Error"
        st.session_state.context_files_details = []
        st.session_state.current_context_content_dict = {}


# --- DB & API Key Load ---
if not st.session_state.api_key_loaded:
    loaded_api_key = logic.load_api_key()
    if loaded_api_key:
        st.session_state.current_api_key = loaded_api_key
        logger.info("Loaded API key from database.")
    else:
        logger.info("No API key found in database.")
    st.session_state.api_key_loaded = True

# --- Sidebar ---
st.sidebar.header("Chat & Config")

# --- Conversation History (Sidebar) ---
st.sidebar.subheader("Conversations")

if st.sidebar.button("➕ New Chat", key="new_chat_button"):
    logger.info("Starting new chat.")
    st.session_state.messages = []
    st.session_state.gemini_history = []
    st.session_state.current_conversation_id = None
    st.session_state.editing_message_id = None # Clear editing state
    # Reset context, instructions, and parameters to default for a new chat
    st.session_state.added_paths = set()
    st.session_state.system_instruction = ""
    for key, value in DEFAULT_GEN_CONFIG.items():
        st.session_state[key] = value
    # Recalculate tokens after reset using the state update function
    update_state_from_logic()
    # Clamp max_output_tokens again after reset, based on current model limit
    limit = st.session_state.get('current_model_max_output_tokens', FALLBACK_MODEL_MAX_OUTPUT_TOKENS)
    if st.session_state.max_output_tokens > limit:
        st.session_state.max_output_tokens = limit
    elif st.session_state.max_output_tokens <= 0:
        st.session_state.max_output_tokens = min(DEFAULT_MAX_OUTPUT_TOKENS_SLIDER, limit)
    update_state_from_logic() # Recalculate tokens
    st.rerun()
st.session_state.loaded_conversations = db.get_recent_conversations(limit=15)

st.sidebar.markdown("---")
if not st.session_state.loaded_conversations:
    st.sidebar.caption("No past conversations found.")
else:
    st.sidebar.caption("Recent Chats:")
    for convo in st.session_state.loaded_conversations:
        convo_id = convo["id"]
        # ... [Keep existing conversation title formatting] ...
        button_type = "primary" if convo_id == st.session_state.get("current_conversation_id") else "secondary"

        # col1, col2 = st.sidebar.columns([9, 1]) # Keep Delete Button if needed, or just one button
        # with col1:
st.sidebar.markdown("---")
if not st.session_state.loaded_conversations:
    st.sidebar.caption("No past conversations found.")
else:
    st.sidebar.caption("Recent Chats:")
    for convo in st.session_state.loaded_conversations:
        convo_id = convo["id"]
        convo_title = convo["title"] or db.PLACEHOLDER_TITLE # Raw title from DB

        # Create the potentially truncated title
        raw_display_title = (convo_title[:TITLE_MAX_LENGTH] + '...') if len(convo_title) > TITLE_MAX_LENGTH + 3 else convo_title

        display_title_escaped = raw_display_title.replace("{", "{{").replace("}", "}}")

        button_type = "primary" if convo_id == st.session_state.get("current_conversation_id") else "secondary"

        col1, col2 = st.sidebar.columns([0.85, 0.15]) # Adjust ratio as needed
        with col1:
            # Load Button
            if st.button(f"{display_title_escaped}", key=f"load_conv_{convo_id}", help=f"Load: {convo_title}", use_container_width=True, type=button_type):
                if convo_id != st.session_state.get("current_conversation_id"):
                    logger.info(f"Loading conversation ID: {convo_id}, Title: {raw_display_title}")
                    st.session_state.editing_message_id = None
                    with st.spinner(f"Loading chat: {raw_display_title}..."):
                        reload_conversation_state(convo_id)
                        loaded_metadata = db.get_conversation_metadata(convo_id)
                        if loaded_metadata is None:
                             st.warning(f"Could not load settings for chat {raw_display_title}. Using current/default settings.")
                             logger.warning(f"Could not load metadata for conversation ID: {convo_id}")
                        else:
                             # Update State (Settings)
                             st.session_state.system_instruction = loaded_metadata.get("system_instruction", "")
                             st.session_state.added_paths = loaded_metadata.get("added_paths", set())
                             loaded_gen_config = loaded_metadata.get("generation_config")
                             if loaded_gen_config:
                                 logger.info(f"Applying saved settings for conversation {convo_id}")
                                 for key, value in DEFAULT_GEN_CONFIG.items():
                                     st.session_state[key] = loaded_gen_config.get(key, value) # Use .get for safety
                                     if key not in loaded_gen_config:
                                         logger.warning(f"Config key '{key}' not found in saved metadata for {convo_id}, using default.")
                             else:
                                 logger.warning(f"No generation config saved for {convo_id}, resetting to defaults.")
                                 for key, value in DEFAULT_GEN_CONFIG.items():
                                     st.session_state[key] = value

                             # Clamp max tokens based on potentially loaded model limit
                             limit = st.session_state.get('current_model_max_output_tokens', FALLBACK_MODEL_MAX_OUTPUT_TOKENS)
                             if st.session_state.max_output_tokens > limit: st.session_state.max_output_tokens = limit
                             elif st.session_state.max_output_tokens <= 0: st.session_state.max_output_tokens = min(DEFAULT_MAX_OUTPUT_TOKENS_SLIDER, limit)
                             logger.debug(f"Settings applied for {convo_id}.")

                        update_state_from_logic()
                        st.session_state.current_conversation_id = convo_id
                        st.success(f"Loaded chat: {raw_display_title}")
                        st.rerun()
                else:
                    logger.debug(f"Conversation {convo_id} already loaded. Click ignored.")
                    st.toast("Chat already loaded.", icon="ℹ️")
        with col2:
            if st.button("❌", key=f"delete_conv_{convo_id}", help=f"Delete: {convo_title}", use_container_width=True, type="secondary"):
                logger.warning(f"Attempting to delete conversation '{raw_display_title}' (ID: {convo_id})")
                # Use the delete_conversation function from database.py
                success, message = db.delete_conversation(convo_id)
                if success:
                    st.success(message)
                    logger.info(message)
                    # If the deleted conversation was the current one, reset state
                    if convo_id == st.session_state.get("current_conversation_id"):
                        st.session_state.messages = []
                        st.session_state.gemini_history = []
                        st.session_state.current_conversation_id = None
                        st.session_state.editing_message_id = None
                        st.session_state.added_paths = set()
                        st.session_state.system_instruction = ""
                        for key, value in DEFAULT_GEN_CONFIG.items():
                            st.session_state[key] = value
                        update_state_from_logic()
                        logger.info("Cleared state as current conversation was deleted.")
                    # Refresh the list regardless
                    st.session_state.loaded_conversations = db.get_recent_conversations(limit=15)
                    st.rerun()
                else:
                    st.error(message)
                    logger.error(f"Failed to delete conversation {convo_id}: {message}")


# --- API Key & Model Config (Sidebar) ---
api_key_input = st.sidebar.text_input("Gemini API Key:", type="password", key="api_key_widget", value=st.session_state.current_api_key, help="Saved locally in SQLite DB.")
if api_key_input != st.session_state.current_api_key:
    logger.info("API key changed in input.")
    st.session_state.current_api_key = api_key_input
    # Reset model-related state when key changes
    st.session_state.available_models = None
    st.session_state.models_loaded_for_key = None
    st.session_state.selected_model_name = DEFAULT_MODEL
    st.session_state.current_model_instance = None
    st.session_state.current_model_max_output_tokens = FALLBACK_MODEL_MAX_OUTPUT_TOKENS
    st.session_state.current_token_count = 0
    st.session_state.current_token_count_str = "Token Count: N/A"
    if 'token_count_placeholder' in st.session_state:
         st.session_state.token_count_placeholder.caption(st.session_state.current_token_count_str)
    st.rerun() # Rerun to trigger model loading with the new key

st.sidebar.warning("API Key stored locally. [Clear Saved Key](?clear_key=true)", icon="⚠️")
if st.query_params.get("clear_key"):
    logger.info("Attempting to clear saved API key.")
    if logic.clear_api_key():
        st.success("Saved API Key cleared.")
        logger.info("Saved API key cleared successfully from DB.")
    else:
        st.error("Failed to clear saved API key from DB.")
        logger.error("Failed to clear saved API key from DB.")
    st.session_state.current_api_key = ""
    st.session_state.api_key_loaded = True # Mark as loaded even if cleared
    # Reset model state
    st.session_state.available_models = None
    st.session_state.models_loaded_for_key = None
    st.session_state.selected_model_name = DEFAULT_MODEL
    st.session_state.current_model_instance = None
    st.session_state.current_model_max_output_tokens = FALLBACK_MODEL_MAX_OUTPUT_TOKENS
    st.session_state.current_token_count = 0
    st.session_state.current_token_count_str = "Token Count: N/A"
    if 'token_count_placeholder' in st.session_state:
         st.session_state.token_count_placeholder.caption(st.session_state.current_token_count_str)
    st.query_params.clear()
    time.sleep(0.1) # Allow query param removal to register
    st.rerun()

model_select_container = st.sidebar.empty()
models_successfully_loaded = False
model_instance = st.session_state.get("current_model_instance")

if st.session_state.current_api_key:
    active_api_key = st.session_state.current_api_key
    # Only try to load models if the key has changed or models aren't loaded yet
    if st.session_state.models_loaded_for_key != active_api_key:
        logger.info(f"Attempting to load models for API key ending with ...{active_api_key[-4:]}")
        try:
            with st.spinner("Configuring API & fetching models..."):
                genai.configure(api_key=active_api_key)
                model_list = []
                try:
                    logger.debug("Listing available models from API.")
                    for m in genai.list_models():
                        if 'generateContent' in m.supported_generation_methods:
                            model_list.append(m.name)
                    logger.info(f"Found {len(model_list)} usable models.")
                except Exception as list_err:
                    st.sidebar.error(f"Model list error: {list_err}")
                    logger.error(f"Error listing models: {list_err}", exc_info=True)
                    # Reset state on error
                    st.session_state.available_models = None
                    st.session_state.models_loaded_for_key = None # Mark as not loaded for this key
                    model_instance = None
                    st.session_state.current_model_instance = None
                    st.session_state.current_model_max_output_tokens = FALLBACK_MODEL_MAX_OUTPUT_TOKENS
                else:
                    # Models listed successfully
                    model_list.sort()
                    st.session_state.available_models = model_list
                    st.session_state.models_loaded_for_key = active_api_key # Mark as loaded for this key
                    logger.debug(f"Available models set: {model_list}")

                    # Attempt to save the key only after successful configuration/listing
                    logic.save_api_key(active_api_key) # Log inside function

                    # Select default or first available model
                    current_selection = st.session_state.selected_model_name
                    if not current_selection or current_selection not in model_list:
                        st.session_state.selected_model_name = DEFAULT_MODEL if DEFAULT_MODEL in model_list else (model_list[0] if model_list else None)
                        logger.info(f"Model selection updated to: {st.session_state.selected_model_name}")

                    # Initialize the selected model instance
                    if st.session_state.selected_model_name:
                        logger.info(f"Initializing model: {st.session_state.selected_model_name}")
                        limit = logic.get_model_output_limit(st.session_state.selected_model_name)
                        st.session_state.current_model_max_output_tokens = limit
                        logger.debug(f"Model output token limit: {limit}")
                        # Clamp max tokens setting based on new limit
                        if st.session_state.max_output_tokens > limit: st.session_state.max_output_tokens = limit
                        elif st.session_state.max_output_tokens <= 0: st.session_state.max_output_tokens = min(DEFAULT_MAX_OUTPUT_TOKENS_SLIDER, limit)
                        try:
                            model_instance = genai.GenerativeModel(st.session_state.selected_model_name)
                            st.session_state.current_model_instance = model_instance
                            logger.info(f"Model '{st.session_state.selected_model_name}' initialized successfully.")
                        except Exception as model_init_err:
                            st.error(f"Failed init model '{st.session_state.selected_model_name}': {model_init_err}")
                            logger.error(f"Failed to initialize model '{st.session_state.selected_model_name}': {model_init_err}", exc_info=True)
                            model_instance = None
                            st.session_state.current_model_instance = None
                            st.session_state.current_model_max_output_tokens = FALLBACK_MODEL_MAX_OUTPUT_TOKENS
                    else:
                        logger.warning("No model selected or available after listing.")
                        model_instance = None
                        st.session_state.current_model_instance = None
                        st.session_state.current_model_max_output_tokens = FALLBACK_MODEL_MAX_OUTPUT_TOKENS

                    models_successfully_loaded = True
                    # Update token counts *after* model potentially initialized/changed
                    update_state_from_logic()
                    # Rerun required to display the model selector now that models are loaded
                    st.rerun()

        except Exception as config_err:
            st.sidebar.error(f"API Key/Config error: {config_err}")
            logger.error(f"API Key configuration error: {config_err}", exc_info=True)
            # Reset state on config error
            st.session_state.available_models = None
            st.session_state.models_loaded_for_key = None
            st.session_state.selected_model_name = DEFAULT_MODEL
            model_instance = None
            st.session_state.current_model_instance = None
            st.session_state.current_model_max_output_tokens = FALLBACK_MODEL_MAX_OUTPUT_TOKENS
    else:
        # Key hasn't changed, models were loaded previously for this key
        # Ensure model instance exists if a model name is selected
        if not model_instance and st.session_state.selected_model_name:
            logger.info(f"Re-initializing model instance for {st.session_state.selected_model_name}")
            try:
                model_instance = genai.GenerativeModel(st.session_state.selected_model_name)
                st.session_state.current_model_instance = model_instance
                # Need to ensure max tokens limit is still correct
                limit = logic.get_model_output_limit(st.session_state.selected_model_name)
                st.session_state.current_model_max_output_tokens = limit
            except Exception as model_init_err:
                logger.error(f"Failed to re-initialize model '{st.session_state.selected_model_name}': {model_init_err}", exc_info=True)
                model_instance = None
                st.session_state.current_model_instance = None
        models_successfully_loaded = st.session_state.available_models is not None

else:
    # No API key entered
    if st.session_state.models_loaded_for_key is not None:
        logger.info("API key removed, resetting model state.")
        # Reset model state if key is removed
        st.session_state.available_models = None
        st.session_state.models_loaded_for_key = None
        st.session_state.selected_model_name = DEFAULT_MODEL
        model_instance = None
        st.session_state.current_model_instance = None
        st.session_state.current_model_max_output_tokens = FALLBACK_MODEL_MAX_OUTPUT_TOKENS
        st.session_state.current_token_count = 0
        st.session_state.current_token_count_str = "Token Count: N/A"
        if 'token_count_placeholder' in st.session_state:
            st.session_state.token_count_placeholder.caption(st.session_state.current_token_count_str)


# Display Model Selector if models are loaded
if st.session_state.available_models:
    try:
        # Ensure current selection is valid
        current_selection = st.session_state.selected_model_name
        if not current_selection or current_selection not in st.session_state.available_models:
            current_selection = DEFAULT_MODEL if DEFAULT_MODEL in st.session_state.available_models else (st.session_state.available_models[0] if st.session_state.available_models else None)
            logger.warning(f"Invalid model selection '{st.session_state.selected_model_name}', defaulting to '{current_selection}'")
            st.session_state.selected_model_name = current_selection # Update state if changed

        if current_selection:
            selected_index = st.session_state.available_models.index(current_selection)
            selected_model = model_select_container.selectbox(
                "Select Gemini Model:",
                options=st.session_state.available_models,
                index=selected_index,
                key='model_select_dropdown'
            )
            # Handle model change
            if selected_model != st.session_state.selected_model_name:
                logger.info(f"Model selection changed from '{st.session_state.selected_model_name}' to '{selected_model}'")
                st.session_state.selected_model_name = selected_model
                # Get new limits and update state
                limit = logic.get_model_output_limit(selected_model)
                st.session_state.current_model_max_output_tokens = limit
                logger.debug(f"New model output token limit: {limit}")
                # Clamp max tokens setting
                if st.session_state.max_output_tokens > limit: st.session_state.max_output_tokens = limit
                elif st.session_state.max_output_tokens <= 0: st.session_state.max_output_tokens = min(DEFAULT_MAX_OUTPUT_TOKENS_SLIDER, limit)
                # Initialize the new model instance
                try:
                    logger.info(f"Initializing newly selected model: {selected_model}")
                    model_instance = genai.GenerativeModel(selected_model)
                    st.session_state.current_model_instance = model_instance
                    logger.info(f"Model '{selected_model}' initialized successfully.")
                except Exception as model_init_err:
                    st.error(f"Failed init selected model '{selected_model}': {model_init_err}")
                    logger.error(f"Failed to initialize selected model '{selected_model}': {model_init_err}", exc_info=True)
                    model_instance = None
                    st.session_state.current_model_instance = None
                # Update token count based on new model instance
                update_state_from_logic()
                # Rerun to reflect changes (e.g., updated token limit in slider label)
                st.rerun()
        else:
            model_select_container.warning("No valid model available to select.")
            logger.warning("Model selection dropdown: No valid model available.")
    except Exception as e:
        model_select_container.error(f"Error displaying models: {e}")
        logger.error(f"Error in model selection display logic: {e}", exc_info=True)
        st.session_state.available_models = None # Reset on error
elif st.session_state.current_api_key and st.session_state.models_loaded_for_key == st.session_state.current_api_key:
    model_select_container.warning("No suitable models found for this key.")
    logger.warning("Model selection: No suitable models found for the current API key.")
elif not st.session_state.current_api_key:
    model_select_container.info("Enter API Key to load models.")

# --- System Instructions Expander (Sidebar) ---
with st.sidebar.expander("System Instructions", expanded=False):
    # Define callback here to use the state update function
    def instruction_change_callback():
        logger.debug("System instruction text area changed.")
        update_state_from_logic()

    st.session_state.system_instruction = st.text_area(
        "Enter instructions:",
        value=st.session_state.get("system_instruction", ""),
        height=150,
        key="system_instruction_text_area",
        on_change=instruction_change_callback # Use defined callback
    )
    instr_name_save = st.text_input("Save as:", key="instr_save_name", placeholder="Enter name to save instruction")
    if st.button("Save Instruction", key="save_instr_btn"):
        if instr_name_save:
            logger.info(f"Attempting to save instruction as '{instr_name_save}'")
            success, message = db.save_instruction(instr_name_save, st.session_state.system_instruction)
            if success:
                st.success(message)
                logger.info(message)
                st.session_state.instruction_names = db.get_instruction_names() # Refresh list
                st.rerun()
            else:
                st.error(message)
                logger.error(f"Failed to save instruction '{instr_name_save}': {message}")
        else:
            st.warning("Please enter a name to save the instruction.")
            logger.warning("Save instruction button clicked with no name entered.")

    st.markdown("---")
    # Ensure instruction names are loaded if not present
    if not st.session_state.instruction_names:
        st.session_state.instruction_names = db.get_instruction_names()

    if st.session_state.instruction_names:
        instr_name_load = st.selectbox("Load instruction:", options=[""] + st.session_state.instruction_names, key="instr_load_select")
        col_load, col_delete = st.columns(2)
        with col_load:
            if st.button("Load", key="load_instr_btn", disabled=not instr_name_load, use_container_width=True):
                logger.info(f"Attempting to load instruction '{instr_name_load}'")
                loaded_text = db.load_instruction(instr_name_load)
                if loaded_text is not None:
                    st.session_state.system_instruction = loaded_text
                    update_state_from_logic() # Update tokens after loading
                    st.success(f"Loaded '{instr_name_load}'.")
                    logger.info(f"Instruction '{instr_name_load}' loaded successfully.")
                    st.session_state.instr_save_name = instr_name_load # Pre-fill save name
                    st.rerun() # Rerun to update text area
                else:
                    st.error(f"Could not load '{instr_name_load}'.")
                    logger.error(f"Failed to load instruction '{instr_name_load}' from DB.")
        with col_delete:
             if st.button("Delete", key="delete_instr_btn", disabled=not instr_name_load, use_container_width=True):
                 logger.warning(f"Attempting to delete instruction '{instr_name_load}'")
                 current_text_if_loaded = db.load_instruction(instr_name_load) # Get text before deleting
                 success, message = db.delete_instruction(instr_name_load)
                 if success:
                     st.success(message)
                     logger.info(message)
                     st.session_state.instruction_names = db.get_instruction_names() # Refresh list
                     # If the deleted instruction was loaded, clear the text area
                     if st.session_state.system_instruction == current_text_if_loaded:
                         st.session_state.system_instruction = ""
                         update_state_from_logic() # Update tokens
                     # Reset selection and potentially save name
                     st.session_state.instr_load_select = ""
                     if st.session_state.instr_save_name == instr_name_load:
                         st.session_state.instr_save_name = ""
                     st.rerun()
                 else:
                     st.error(message)
                     logger.error(f"Failed to delete instruction '{instr_name_load}': {message}")
    else:
        st.caption("No saved instructions.")

# --- Context Management (Sidebar) ---
st.sidebar.markdown("---")
st.sidebar.header("Manage Context")
new_path_input = st.sidebar.text_input("Add File/Folder Path:", key="new_path", placeholder="Enter path & click Add")
if st.sidebar.button("Add Path", key="add_path_button"):
    if new_path_input:
        logger.info(f"Attempting to add path: {new_path_input}")
        try:
            resolved_path_obj = Path(new_path_input).resolve()
            resolved_path = str(resolved_path_obj)
            if resolved_path_obj.exists():
                if resolved_path not in st.session_state.added_paths:
                     st.session_state.added_paths.add(resolved_path)
                     st.sidebar.success(f"Added: {resolved_path}")
                     logger.info(f"Added path to context: {resolved_path}")
                     update_state_from_logic() # Update tokens
                     st.rerun()
                else:
                     st.sidebar.info("Path already added.")
                     logger.debug(f"Path already in context: {resolved_path}")
            else:
                 st.sidebar.error(f"Path not found: {new_path_input}")
                 logger.error(f"Path not found when adding context: {new_path_input}")
        except Exception as e:
             st.sidebar.error(f"Error resolving path: {e}")
             logger.error(f"Error resolving path '{new_path_input}': {e}", exc_info=True)
    else:
        st.sidebar.warning("Please enter a path to add.")
        logger.warning("Add path button clicked with no input.")

with st.sidebar.expander("Managed Paths", expanded=True):
    if not st.session_state.added_paths:
        st.caption("No paths added.")
    else:
        col1, col2 = st.columns([4, 1])
        paths_to_remove = []
        # Sort paths for consistent display order
        sorted_paths = sorted(list(st.session_state.added_paths))
        for path_str in sorted_paths:
            with col1:
                st.code(path_str, language=None)
            with col2:
                # Add unique key to avoid Streamlit duplicate key errors if paths are similar
                button_key = f"remove_{hash(path_str)}"
                if st.button("❌", key=button_key, help=f"Remove {path_str}"):
                    paths_to_remove.append(path_str)
                    logger.debug(f"Marked path for removal: {path_str}")

        if paths_to_remove:
            logger.info(f"Removing paths: {paths_to_remove}")
            needs_update = False
            for path_to_remove in paths_to_remove:
                 if path_to_remove in st.session_state.added_paths:
                     st.session_state.added_paths.discard(path_to_remove)
                     needs_update = True
            if needs_update:
                update_state_from_logic() # Update tokens
                st.rerun()

with st.sidebar.expander("Effective Files", expanded=False):
    if not st.session_state.get('context_files_details', []):
        st.caption("Add paths to see files.")
    else:
        with st.container(height=300):
            inc_count, skip_count, err_count = 0, 0, 0
            # Sort details by path for consistent display
            sorted_details = sorted(st.session_state.context_files_details, key=lambda x: x[0])
            for path, status, detail in sorted_details:
                icon = "✅" if "Included" in status else ("⚠️" if "Skipped" in status else "❌")
                color = "green" if "Included" in status else ("orange" if "Skipped" in status else "red")
                st.markdown(f"<small><span style='color:{color};'>{icon} **{status}:** `{path}` ({detail})</span></small>", unsafe_allow_html=True)
                if "Included" in status: inc_count += 1
                elif "Skipped" in status: skip_count += 1
                else: err_count += 1
            st.caption(f"**Total:** {inc_count} Included, {skip_count} Skipped, {err_count} Errors")


# --- Token Count & Footer (Sidebar) ---
st.sidebar.markdown("---")
# Initialize placeholder if it doesn't exist
if 'token_count_placeholder' not in st.session_state:
     st.session_state.token_count_placeholder = st.sidebar.empty()
# Update the placeholder content using the value from session state
st.session_state.token_count_placeholder.caption(st.session_state.get("current_token_count_str", "Token Count: N/A"))

if st.sidebar.button("Refresh Tokens", key="refresh_tokens_btn"):
     logger.info("Manual token refresh triggered.")
     update_state_from_logic() # Use the state update function

st.sidebar.markdown("---")
if st.sidebar.button("Clear Current Chat History"):
    logger.warning("Clearing current chat history (messages only).")
    # This needs refinement - should delete messages from DB for the current convo?
    # For now, just clears UI state, but they remain in DB.
    # A better approach might be to delete from DB and reload.
    # Let's implement the DB deletion for clarity.
    current_convo_id = st.session_state.get("current_conversation_id")
    if current_convo_id:
        logger.info(f"Deleting all messages for current conversation: {current_convo_id}")
        # We need a function db.delete_all_messages(conversation_id) or similar
        # Placeholder: Reloading an empty state achieves the visual effect for now
        # but doesn't clean the DB. Add db.delete_all_messages if needed.
        st.session_state.messages = []
        st.session_state.gemini_history = []
        st.session_state.editing_message_id = None # Clear editing state
        # Optionally, update conversation timestamp or reset title?
        st.rerun()
    else:
        st.toast("No active conversation to clear.")
st.sidebar.markdown("---")
st.sidebar.markdown(f"<small>Version: {APP_VERSION} | {PAGE_TITLE}</small>", unsafe_allow_html=True)

# ==============================================
# --- Main Chat Area (Left/Center Column) ---
# ==============================================
with col_main:
    # Model/Chat Initialization Check
    model = st.session_state.get("current_model_instance")
    chat = None
    if model:
        try:
            # Use the history stored in session state, which is updated when loading/sending messages
            current_gemini_history = st.session_state.get("gemini_history", [])

            # Limit history length *before* starting chat
            if len(current_gemini_history) > MAX_HISTORY_PAIRS * 2:
                 logger.warning(f"History length ({len(current_gemini_history)}) exceeds limit ({MAX_HISTORY_PAIRS * 2}), truncating.")
                 current_gemini_history = current_gemini_history[-(MAX_HISTORY_PAIRS * 2):]
                 st.session_state.gemini_history = current_gemini_history # Update state with truncated history

            logger.debug(f"Starting chat with history length: {len(current_gemini_history)}")
            chat = model.start_chat(history=current_gemini_history)
        except Exception as chat_init_err:
            st.error(f"Error starting chat session: {chat_init_err}")
            logger.error(f"Error starting chat session: {chat_init_err}", exc_info=True)
            model = None # Prevent further attempts if init fails
            st.session_state.current_model_instance = None # Clear instance state
    elif st.session_state.selected_model_name and st.session_state.current_api_key:
        # Attempt to re-initialize if model instance is missing but key/name are set
        logger.warning("Model instance missing, attempting re-initialization.")
        try:
             model = genai.GenerativeModel(st.session_state.selected_model_name)
             st.session_state.current_model_instance = model
             chat = model.start_chat(history=st.session_state.get("gemini_history", []))
             logger.info("Model re-initialized successfully.")
        except Exception as e:
             st.error(f"Failed to re-initialize model: {e}")
             logger.error(f"Failed to re-initialize model '{st.session_state.selected_model_name}': {e}", exc_info=True)
             st.session_state.current_model_instance = None


    # Display warnings if prerequisites aren't met
    if not st.session_state.current_api_key:
        st.warning("API Key required (in sidebar).")
    elif not model:
        st.warning("Select/Initialize Model (in sidebar).")

    # --- Check for Pending API Call ---
    # Process this *before* displaying messages or input, as it might cause a rerun
    if "pending_api_call" in st.session_state and st.session_state.pending_api_call:
        pending_data = st.session_state.pending_api_call
        logger.info("Processing pending API call...")
        # Clear the flag immediately
        del st.session_state["pending_api_call"]

        # Ensure model/chat are ready (redundant check might be ok)
        if not model:
             # Attempt re-initialization one last time
             if st.session_state.selected_model_name and st.session_state.current_api_key:
                 logger.warning("Model instance missing for pending call, attempting final re-initialization.")
                 try:
                     model = genai.GenerativeModel(st.session_state.selected_model_name)
                     st.session_state.current_model_instance = model
                     logger.info("Model re-initialized successfully for pending call.")
                 except Exception as e:
                     st.error(f"Model not ready. Failed to re-initialize: {e}")
                     logger.error(f"Pending call halted: Failed to re-initialize model '{st.session_state.selected_model_name}': {e}", exc_info=True)
                     st.session_state.current_model_instance = None
                     st.stop()
             else:
                 st.error("Model not ready for pending API call.")
                 logger.error("Pending API call aborted: Model not ready.")
                 st.stop()

        # Ensure chat object is ready
        if not chat:
             try:
                 logger.warning("Chat object missing for pending call, attempting to restart chat session.")
                 current_gemini_history = st.session_state.get("gemini_history", [])
                 if len(current_gemini_history) > MAX_HISTORY_PAIRS * 2:
                     current_gemini_history = current_gemini_history[-(MAX_HISTORY_PAIRS * 2):]
                     st.session_state.gemini_history = current_gemini_history
                 chat = model.start_chat(history=current_gemini_history)
                 logger.info("Chat session restarted successfully for pending call.")
             except Exception as e:
                 st.error(f"Failed to restart chat session for pending call: {e}")
                 logger.error(f"Pending call halted: Failed to restart chat session: {e}", exc_info=True)
                 st.stop()

        if not chat: # Final check
             st.error("Chat session could not be initialized for pending call.")
             logger.critical("Pending call halted: Chat session is None after attempting restart.")
             st.stop()


        active_conversation_id = pending_data["convo_id"]
        prompt_to_send = pending_data["prompt"]

        # Retrieve necessary context/instruction state (should be correct from the previous run state)
        context_content_dict = st.session_state.get('current_context_content_dict', {})
        context_files_list = list(context_content_dict.keys()) # Needed? Maybe not here.
        # context = logic.format_context(context_content_dict, st.session_state.added_paths) if context_content_dict else "No local file context provided."
        # system_instruction = st.session_state.get("system_instruction", "").strip()
        # instruction_prefix = f"--- System Instruction ---\n{system_instruction}\n--- End System Instruction ---\n\n" if system_instruction else ""
        # full_prompt_for_log was already saved with the user message.

        # Prepare Generation Config
        generation_config = None
        try:
            logger.debug("Preparing generation config for pending API call.")
            stop_sequences = [seq.strip() for seq in st.session_state.stop_sequences_str.splitlines() if seq.strip()]
            model_limit = st.session_state.get('current_model_max_output_tokens', FALLBACK_MODEL_MAX_OUTPUT_TOKENS)
            user_setting = st.session_state.max_output_tokens
            max_tokens_for_api = max(1, min(user_setting, model_limit))
            if user_setting != max_tokens_for_api:
                logger.warning(f"Adjusted max_output_tokens from {user_setting} to {max_tokens_for_api} due to model limit ({model_limit}) or minimum value.")

            gen_config_dict_api = {
                "temperature": st.session_state.temperature,
                "top_p": st.session_state.top_p,
                "top_k": st.session_state.top_k,
                "max_output_tokens": max_tokens_for_api,
                **({"stop_sequences": stop_sequences} if stop_sequences else {})
            }
            if st.session_state.json_mode:
                gen_config_dict_api["response_mime_type"] = "application/json"
                logger.debug("JSON output mode enabled for pending call.")

            logger.debug(f"Generation config for pending API call: {gen_config_dict_api}")
            generation_config = GenerationConfig(**gen_config_dict_api)

        except Exception as e:
            st.error(f"Error creating generation config for pending call: {e}")
            logger.error(f"Error creating GenerationConfig object for pending call: {e}", exc_info=True)
            generation_config = None
            # Need to decide how to handle this - stop or try default? Let's stop.
            st.stop()


        # --- Send to Gemini & Display Response ---
        if generation_config is not None:
            try:
                logger.info(f"Sending pending prompt to model: {st.session_state.selected_model_name}")
                # We need to display the response within the chat message context
                with st.chat_message("assistant"):
                    message_placeholder = st.empty()
                    full_response_content = ""
                    model_short_name = Path(st.session_state.selected_model_name).name if st.session_state.selected_model_name else "Gemini"

                    with st.spinner(f"Asking {model_short_name}... (Processing pending request)"):
                        # Send only the user's latest message to the chat object
                        response = chat.send_message(
                            prompt_to_send, # Use the prompt from the pending data
                            stream=True,
                            generation_config=generation_config # Pass the config object
                            )

                    logger.debug("Streaming response from model for pending call...")
                    for chunk in response:
                        chunk_text = getattr(chunk, 'text', None)
                        if chunk_text:
                            full_response_content += chunk_text
                            message_placeholder.markdown(full_response_content + "▌")

                    message_placeholder.markdown(full_response_content) # Final display
                    logger.info(f"Response received for pending call (length: {len(full_response_content)}).")

                # Add AI response to UI history AND internal gemini_history
                # We need the timestamp and ID - save to DB first, then reload state
                logger.debug(f"Saving assistant message from pending call to DB for conversation {active_conversation_id}")
                save_assist_success = db.save_message(
                    conversation_id=active_conversation_id, role='assistant', content=full_response_content,
                    model_used=st.session_state.selected_model_name
                )
                if not save_assist_success:
                    st.warning("Failed to save assistant response to the database.")
                    # Reload state anyway to try and recover UI consistency
                    reload_conversation_state(active_conversation_id)
                    st.rerun()
                else:
                    # Reload state one last time to ensure DB and UI are synced after assistant message
                    reload_conversation_state(active_conversation_id)
                    # Rerun to update display and potentially sidebar order
                    st.rerun() # Final rerun for this interaction cycle

            except Exception as e:
                st.error(f"Error during Gemini communication for pending call: {e}")
                logger.error(f"Error during chat.send_message or response processing for pending call: {e}", exc_info=True)
                # Reload state to ensure consistency despite error?
                reload_conversation_state(active_conversation_id)
                st.rerun()
        else:
             logger.error("Pending API call aborted: Generation config was None.")
             # Reload state to be safe
             reload_conversation_state(active_conversation_id)
             st.rerun()


    # --- Display Chat Messages with Controls ---
    # Reload state ensures messages are up-to-date before display
    current_convo_id_for_display = st.session_state.get("current_conversation_id")
    if current_convo_id_for_display: # Only show messages if a conversation is active
        # Optionally display current convo ID - removed for cleaner look maybe
        # st.info(f"Conversation ID: {current_convo_id_for_display}", icon="🆔")

        # Create a container for messages
        message_container = st.container() # Adjust height if desired: height=600

        with message_container:
            # Use a copy of the messages list for safe iteration if actions cause reruns
            messages_to_display = list(st.session_state.get("messages", []))

            for i, message in enumerate(messages_to_display):
                msg_id = message.get("id")
                msg_role = message.get("role")
                msg_content = message.get("content")
                msg_timestamp = message.get("timestamp") # Needed for delete_after actions

                if not all([msg_id, msg_role is not None, msg_content is not None, msg_timestamp]):
                    logger.error(f"Skipping message at index {i} due to missing data: {message}")
                    continue # Skip malformed messages

                with st.chat_message(msg_role):
                    # Use columns for content and controls
                    col_content, col_controls = st.columns([0.9, 0.1]) # Adjust ratio as needed

                    with col_content:
                        st.markdown(msg_content)

                    with col_controls:
                        # Create a mini-container for buttons
                        button_container = st.container()
                        with button_container:
                            # --- Delete Button ---
                            if st.button("🗑️", key=f"del_{msg_id}", help="Delete this message", use_container_width=True):
                                logger.warning(f"User initiated delete for message ID: {msg_id}")
                                success, db_msg = db.delete_message_by_id(msg_id)
                                if success:
                                    st.toast(db_msg, icon="✅")
                                    # No need to manually update state, reload will handle it
                                    reload_conversation_state(st.session_state.current_conversation_id)
                                    logger.info(f"Message {msg_id} deleted from DB. Reloading state.")
                                    st.rerun()
                                else:
                                    st.error(f"Failed to delete message: {db_msg}")
                                    logger.error(f"Failed DB delete for message ID {msg_id}: {db_msg}")

                            # --- Edit Button (Only for User Messages) ---
                            if msg_role == "user":
                                if st.button("✏️", key=f"edit_{msg_id}", help="Edit this message (deletes subsequent history)", use_container_width=True):
                                    logger.info(f"User initiated edit for message ID: {msg_id}")
                                    # Set state to indicate editing mode
                                    st.session_state.editing_message_id = msg_id
                                    st.session_state.editing_message_content = msg_content
                                    st.rerun() # Rerun to change the chat input area

                            # --- Regenerate Button (Only for Assistant Messages) ---
                            if msg_role == "assistant":
                                # Find the preceding user message
                                preceding_user_msg = None
                                if i > 0:
                                     potential_user_msg = messages_to_display[i-1]
                                     if potential_user_msg.get('role') == 'user':
                                         preceding_user_msg = potential_user_msg

                                if preceding_user_msg:
                                     user_msg_id = preceding_user_msg['id']
                                     user_msg_timestamp = preceding_user_msg['timestamp']
                                     user_msg_content = preceding_user_msg['content']

                                     if st.button("🔄", key=f"regen_{msg_id}", help="Regenerate this response (deletes subsequent history)", use_container_width=True):
                                         logger.warning(f"User initiated regenerate for assistant message ID: {msg_id} (based on user msg {user_msg_id})")
                                         # 1. Delete messages AFTER the preceding user message
                                         success_del, db_msg_del = db.delete_messages_after_timestamp(st.session_state.current_conversation_id, user_msg_timestamp)
                                         if success_del:
                                             st.toast(db_msg_del, icon="✅")
                                             # 2. Set flag/state to trigger regeneration with the user prompt
                                             st.session_state.pending_api_call = {
                                                 "prompt": user_msg_content,
                                                 "convo_id": st.session_state.current_conversation_id
                                             }
                                             logger.info(f"History truncated after user message {user_msg_id}. Set pending API call for regeneration.")
                                             # 3. Reload state to reflect deletions before the API call happens on next run
                                             reload_conversation_state(st.session_state.current_conversation_id)
                                             st.rerun() # Rerun to process the pending call
                                         else:
                                             st.error(f"Failed to delete subsequent messages for regenerate: {db_msg_del}")
                                             logger.error(f"Regenerate failed: DB delete_after failed for timestamp {user_msg_timestamp}: {db_msg_del}")

                            # --- Summarize After Button ---
                            # Can summarize after any message, even the last one (summarizes nothing)
                            if st.button("📄", key=f"summ_{msg_id}", help="Summarize history after this message", use_container_width=True):
                                logger.info(f"User initiated summarize after message ID: {msg_id} (timestamp: {msg_timestamp})")
                                if not model:
                                    st.warning("Model not available for summarization.")
                                else:
                                    with st.spinner("Fetching messages to summarize..."):
                                        # Fetch messages strictly after the current one's timestamp
                                        messages_to_summarize = db.get_messages_after_timestamp(st.session_state.current_conversation_id, msg_timestamp)

                                    if not messages_to_summarize:
                                        st.toast("No messages found after this one to summarize.", icon="ℹ️")
                                    else:
                                        logger.debug(f"Found {len(messages_to_summarize)} messages to summarize.")
                                        # Format the text block nicely
                                        text_block = "\n---\n".join([f"**{m['role'].capitalize()}** ({m['timestamp']}):\n{m['content']}" for m in messages_to_summarize])

                                        # TODO: Add context file info more dynamically if possible
                                        context_info = "Note: Relevant local files were previously included as context."

                                        with st.spinner("Asking Gemini to summarize..."):
                                            summary, error = logic.summarize_text_for_context(text_block, model, context_info)

                                        if error:
                                            st.error(f"Summarization failed: {error}")
                                            logger.error(f"Summarization call failed: {error}")
                                        elif summary is not None:
                                            # Display summary nicely
                                            expander_title = f"Summary of History After Message ({msg_timestamp})"
                                            with st.expander(expander_title, expanded=True):
                                                st.markdown(summary)
                                            logger.info("Summary generated and displayed in expander.")
                                        else:
                                            st.error("Summarization returned an unexpected result.")
                                            logger.error("Summarization returned None summary and None error.")


    # --- Chat Input Area ---
    # Modify chat input based on editing state
    prompt_placeholder = "Ask a question or type your message..."
    button_label = "Send" # Default
    input_key="chat_input_main"
    current_editing_id = st.session_state.get("editing_message_id")

    if current_editing_id:
        prompt_placeholder = "Enter edited message and press Enter or click Save..."
        button_label = "Save Edit"
        input_key="chat_input_edit" # Use a different key to allow pre-filling value
        st.warning(f"Editing message ID: {current_editing_id}. Saving will delete subsequent history.", icon="⚠️")
        prompt_value = st.session_state.editing_message_content
    else:
        prompt_value = "" # Default for new message

    # Use columns for input and button
    input_col, button_col = st.columns([4, 1])

    with input_col:
        # Use text_area for potentially longer edits, but treat Enter as submit like chat_input
        # Using chat_input is simpler for Enter handling, but lacks pre-filling. Let's stick with chat_input
        # and handle the edit logic carefully. We'll use the placeholder to guide the user.
        prompt = st.chat_input(
            prompt_placeholder,
            key=input_key,
            # value=prompt_value, # chat_input doesn't support default value
            # We handle the value logic below based on state
            )

    # Logic to handle the input based on whether we are editing or sending new
    if prompt: # Input was submitted
        if current_editing_id:
            # --- Handle Edit Save ---
            edited_content = prompt
            logger.info(f"User submitted edit for message ID: {current_editing_id}")

            # 1. Update the message content in DB
            success_update, db_msg_update = db.update_message_content(current_editing_id, edited_content)

            if success_update:
                # 2. Find the timestamp of the edited message (needed for deletion)
                edited_msg_timestamp = None
                # Need to fetch the message data again as state might be slightly stale
                current_msgs_for_edit = db.get_conversation_messages(st.session_state.current_conversation_id, include_ids_timestamps=True)
                for msg in current_msgs_for_edit:
                     if msg.get("id") == current_editing_id:
                         edited_msg_timestamp = msg.get("timestamp")
                         break

                if edited_msg_timestamp:
                    # 3. Delete messages AFTER the edited message's timestamp
                    success_del, db_msg_del = db.delete_messages_after_timestamp(st.session_state.current_conversation_id, edited_msg_timestamp)
                    if success_del:
                        st.toast("Edit saved and subsequent history removed.", icon="✅")
                        logger.info(f"Edit for message {current_editing_id} completed and history truncated after {edited_msg_timestamp}.")
                    else:
                        st.error(f"Failed to delete history after edit: {db_msg_del}")
                        logger.error(f"Edit failed: DB delete_after failed for timestamp {edited_msg_timestamp}: {db_msg_del}")
                        # History remains, but edit is saved. Inform user?
                        st.warning("Edit saved, but failed to remove subsequent history.")

                    # 4. Clear editing state and reload/rerun
                    st.session_state.editing_message_id = None
                    st.session_state.editing_message_content = ""
                    reload_conversation_state(st.session_state.current_conversation_id)
                    st.rerun()
                else:
                     st.error("Failed to find timestamp for edited message after update. History not truncated.")
                     logger.error(f"Edit failed: Could not find timestamp for message ID {current_editing_id} after update.")
                     # Clear editing state anyway
                     st.session_state.editing_message_id = None
                     st.session_state.editing_message_content = ""
                     reload_conversation_state(st.session_state.current_conversation_id) # Reload to show updated content
                     st.rerun()
            else:
                st.error(f"Failed to save edit: {db_msg_update}")
                logger.error(f"Edit failed: DB update_message_content failed for ID {current_editing_id}: {db_msg_update}")
                # Clear editing state
                st.session_state.editing_message_id = None
                st.session_state.editing_message_content = ""
                st.rerun() # Rerun to exit editing mode

        else:
            # --- Handle Regular Prompt Submission (Save and Set Flag) ---
            logger.info(f"User prompt received, saving and scheduling API call: '{prompt[:50]}...'")
            # Prerequisites Check
            if not st.session_state.current_api_key:
                st.error("API Key required.")
                logger.error("Send message halted: API key missing.")
                st.stop()
            if not model:
                 st.error("Model not ready.")
                 logger.error("Send message halted: Model not ready.")
                 st.stop() # Add checks for model readiness

            # Conversation ID & Metadata Management
            active_conversation_id = st.session_state.current_conversation_id
            is_first_message = not active_conversation_id

            if is_first_message:
                logger.info("First message in a new conversation.")
                new_conv_id = db.start_new_conversation()
                if new_conv_id:
                    st.session_state.current_conversation_id = new_conv_id
                    active_conversation_id = new_conv_id
                    logger.info(f"New conversation created with ID: {active_conversation_id}")
                    # --- Save Metadata on First Message ---
                    try:
                        logger.debug(f"Saving initial metadata for conversation {active_conversation_id}")
                        new_title = prompt[:TITLE_MAX_LENGTH].strip() or f"Chat {datetime.datetime.now().strftime('%H:%M:%S')}"
                        current_gen_config = {key: st.session_state[key] for key in DEFAULT_GEN_CONFIG.keys()}
                        current_instruction = st.session_state.system_instruction
                        current_paths = st.session_state.added_paths
                        update_success = db.update_conversation_metadata(
                            conversation_id=active_conversation_id, title=new_title,
                            generation_config=current_gen_config, system_instruction=current_instruction,
                            added_paths=current_paths
                        )
                        if update_success:
                            logger.info(f"Saved initial metadata for conversation {active_conversation_id}")
                            st.session_state.loaded_conversations = db.get_recent_conversations(limit=15) # Refresh sidebar list
                        else:
                            logger.error(f"Failed to save initial metadata for conversation {active_conversation_id}")
                            st.warning("Failed to save conversation settings.")
                    except Exception as meta_save_err:
                        st.error(f"Failed to save conversation metadata: {meta_save_err}")
                        logger.error(f"Error saving initial metadata for {active_conversation_id}: {meta_save_err}", exc_info=True)
                else:
                    st.error("Failed to create a new conversation record.")
                    logger.critical("Failed to create new conversation record in DB.")
                    st.stop()
            else:
                logger.debug(f"Continuing conversation ID: {active_conversation_id}")

            # Prepare context/instruction for logging with the user message
            context_content_dict = st.session_state.get('current_context_content_dict', {})
            context_files_list = list(context_content_dict.keys())
            context = logic.format_context(context_content_dict, st.session_state.added_paths) if context_content_dict else "No local file context provided."
            system_instruction = st.session_state.get("system_instruction", "").strip()
            instruction_prefix = f"--- System Instruction ---\n{system_instruction}\n--- End System Instruction ---\n\n" if system_instruction else ""
            full_prompt_for_log = instruction_prefix + context + "\n\n---\n\nUser Question:\n" + prompt

            # --- Save User Message to DB ---
            logger.debug(f"Saving user message to DB for conversation {active_conversation_id}")
            save_user_success = db.save_message(
                conversation_id=active_conversation_id, role='user', content=prompt,
                model_used=st.session_state.selected_model_name,
                context_files=context_files_list,
                full_prompt_sent=full_prompt_for_log
            )
            if not save_user_success:
                st.warning("Failed to save user message to the database. Cannot proceed.")
            else:
                # --- Set Pending API Call Flag ---
                st.session_state.pending_api_call = {
                    "prompt": prompt,
                    "convo_id": active_conversation_id
                }
                logger.info("User message saved. Pending API call flag set. Reloading state and rerunning.")
                # Reload state first to include the new message ID/Timestamp before the pending call processes it
                reload_conversation_state(active_conversation_id)
                st.rerun()


# =========================================
# --- Generation Parameters (Right Column) ---
# =========================================
with col_params:
    st.header("Parameters")
    st.markdown("---")

    # Retrieve limits/values from potentially loaded state
    model_max_limit = st.session_state.get('current_model_max_output_tokens', FALLBACK_MODEL_MAX_OUTPUT_TOKENS)
    current_max_output_setting = st.session_state.get('max_output_tokens', DEFAULT_MAX_OUTPUT_TOKENS_SLIDER)

    # Clamp value before passing to slider
    clamped_max_output_setting = max(1, min(current_max_output_setting, model_max_limit))
    if clamped_max_output_setting != current_max_output_setting:
        logger.debug(f"Clamping max_output_tokens from {current_max_output_setting} to {clamped_max_output_setting}")
        st.session_state.max_output_tokens = clamped_max_output_setting

    # Use widgets, values driven by session_state
    st.session_state.max_output_tokens = st.slider(
        f"Max Output Tokens (Limit: {model_max_limit:,})",
        min_value=1,
        max_value=model_max_limit,
        value=st.session_state.max_output_tokens,
        step=max(1, model_max_limit // 256),
        key="maxoutput_slider",
        help=f"Max tokens per response. Current model limit: {model_max_limit:,}"
    )
    st.session_state.temperature = st.slider(
        "Temperature:", 0.0, 2.0, step=0.05,
        value=st.session_state.temperature,
        key="temp_slider", help="Controls randomness (0=deterministic, >1=more random). Default: 0.7"
    )
    st.session_state.top_p = st.slider(
        "Top P:", 0.0, 1.0, step=0.01,
        value=st.session_state.top_p,
        key="topp_slider", help="Nucleus sampling probability (consider tokens summing up to this probability). Default: 1.0"
    )
    st.session_state.top_k = st.slider(
        "Top K:", 1, 100, step=1, # Ensure Top K is at least 1
        value=st.session_state.top_k,
        key="topk_slider", help="Consider the top K most likely tokens at each step. Default: 40"
    )
    st.markdown("---")
    st.session_state.stop_sequences_str = st.text_area(
        "Stop Sequences (one per line):",
        value=st.session_state.stop_sequences_str,
        key="stopseq_textarea", height=80,
        help="Stop generation if the model outputs any of these exact sequences."
    )
    st.session_state.json_mode = st.toggle(
        "JSON Output Mode",
        value=st.session_state.json_mode,
        key="json_toggle",
        help="Request structured JSON output (model must support it)."
    )