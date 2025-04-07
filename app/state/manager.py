# app/state/manager.py
# Manages Streamlit session state initialization and access.
import streamlit as st
import logging
from app.data import database as db
from app.logic import api_client
import datetime # Ensure datetime is imported

# Import types needed for grounding config in api_client, but not used directly here
# import google.ai.generativelanguage as glm
# import google.generativeai as genai

logger = logging.getLogger(__name__)

# --- Default Values ---
MAX_HISTORY_PAIRS = 15
DEFAULT_GEN_CONFIG = {
    "temperature": 0.7, "top_p": 1.0, "top_k": 40,
    "max_output_tokens": 4096, # Initial default, will be clamped by model limit
    "stop_sequences_str": "", "json_mode": False,
    "enable_grounding": False,
    "grounding_threshold": 0.0
}

# --- Initialization ---
def initialize_session_state():
    """Initializes all required session state variables with defaults."""
    # IN: None; OUT: None # Sets default values for session state keys.
    defaults = {
        # Basic chat state
        "messages": [], # List of dicts {id, role, content, timestamp} from DB
        "gemini_history": [], # API-formatted history [{role: 'user'/'model', parts: [...]}]
        "current_conversation_id": None,
        "loaded_conversations": [], # List of {id, title, last_update} from DB
        "action_needed": None, # Stores dict like {'action': 'delete', 'msg_id': 123}
        "pending_api_call": None, # Stores dict {'prompt': '...', 'convo_id': '...'}
        # Context state
        "added_paths": set(),
        "context_files_details": [], # List of tuples (abs_path, status, detail) - NOW USES ABS PATH
        "current_context_content_dict": {}, # {abs_path: content}
        "excluded_individual_files": set(), # Set of absolute paths to exclude
        # Model state
        "available_models": None, # List of model names from API
        "selected_model_name": api_client.DEFAULT_MODEL,
        "models_loaded_for_key": None, # Track which API key models were loaded for
        "current_model_instance": None, # Actual genai.GenerativeModel instance
        "current_model_max_output_tokens": api_client.FALLBACK_MODEL_MAX_OUTPUT_TOKENS,
        # Instruction state
        "system_instruction": "",
        "instruction_names": [], # List of names from DB
        "instr_save_name_value": "", # Holds the current value of the save input
        "next_instr_save_name": None, # Holds value for next run after load
        # Editing state
        "editing_message_id": None,
        "editing_message_content": "",
        # Token count state
        "current_token_count": 0,
        "current_token_count_str": "Token Count: N/A",
        # API Key state
        "api_key_loaded": False, # Flag to check if key loaded from DB at start
        "current_api_key": "",
        # Summary state
        "summary_result": None, # Stores dict {'timestamp': '...', 'summary': '...'}
        "clear_summary": False, # Flag to signal clearing the summary display
    }

    # Apply generation parameter defaults
    defaults.update(DEFAULT_GEN_CONFIG)

    # Initialize missing keys
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
            logger.debug(f"Initialized session state key '{key}'")

    # Load initial data that requires DB access
    if not st.session_state.api_key_loaded:
        loaded_key = db.load_setting('api_key')
        if loaded_key:
            st.session_state.current_api_key = loaded_key
            logger.info("Loaded API key from database into session state.")
        st.session_state.api_key_loaded = True # Mark as checked

    if not st.session_state.instruction_names: # Only load if empty
        st.session_state.instruction_names = db.get_instruction_names()

    # Load initial conversations if list is empty
    if not st.session_state.loaded_conversations:
        st.session_state.loaded_conversations = db.get_recent_conversations(limit=15)


# --- State Update Helpers ---
def reload_conversation_state(conversation_id: str | None):
    """
    Fetches messages/history for a conversation_id, ensures timestamps are
    datetime objects in st.session_state.messages, and updates Gemini history.
    """
    logger.info(f"Reloading state for conversation ID: {conversation_id}")
    from app.logic.context_manager import reconstruct_gemini_history

    logger.info(f"Checking conversation_id INSIDE reload: '{conversation_id}' (Type: {type(conversation_id)})")

    if not conversation_id:
        st.session_state.messages = []
        st.session_state.gemini_history = []
        logger.debug("Cleared messages and history as conversation ID is None.")
        return

    # Fetch messages including timestamps (DB function should return datetime objects due to converter)
    loaded_messages_raw = db.get_conversation_messages(conversation_id, include_ids_timestamps=True)
    logger.info(f"Loaded {len(loaded_messages_raw)} raw messages from DB.")

    # --- ADDED: Explicitly ensure timestamps are datetime objects ---
    processed_messages = []
    for msg in loaded_messages_raw:
        ts = msg.get("timestamp")
        if isinstance(ts, str):
            try:
                msg["timestamp"] = datetime.datetime.fromisoformat(ts)
                logger.warning(f"Converted string timestamp '{ts}' back to datetime for message {msg.get('message_id')}.")
            except (ValueError, TypeError):
                logger.error(f"Could not convert invalid timestamp string '{ts}' for message {msg.get('message_id')}. Setting to None.", exc_info=True)
                msg["timestamp"] = None # Or handle differently?
        elif not isinstance(ts, datetime.datetime):
             logger.warning(f"Message {msg.get('message_id')} has unexpected timestamp type: {type(ts)}. Setting to None.")
             msg["timestamp"] = None
        processed_messages.append(msg)
    # --- END ADDED ---

    st.session_state.messages = processed_messages # Assign processed list to state
    logger.debug(f"Processed {len(processed_messages)} messages assigned to session state.")


    # Reconstruct history for the API (using processed messages)
    api_history_input = [{"role": m["role"], "content": m["content"]} for m in processed_messages]
    reconstructed_history = reconstruct_gemini_history(api_history_input)

    # Apply history length limit
    if len(reconstructed_history) > MAX_HISTORY_PAIRS * 2:
        start_index = len(reconstructed_history) - (MAX_HISTORY_PAIRS * 2)
        st.session_state.gemini_history = reconstructed_history[start_index:]
        logger.warning(f"History truncated ({len(reconstructed_history)} -> {len(st.session_state.gemini_history)})")
    else:
        st.session_state.gemini_history = reconstructed_history

    logger.debug(f"Reloaded state complete. Final history length: {len(st.session_state.gemini_history)}")


def reset_chat_state_to_defaults():
    """Resets chat-specific state variables to their default values for a new chat."""
    # IN: None; OUT: None # Resets state for a new chat.
    logger.info("Resetting chat state to defaults.")
    st.session_state.messages = []
    st.session_state.gemini_history = []
    st.session_state.current_conversation_id = None
    st.session_state.editing_message_id = None
    st.session_state.editing_message_content = ""
    st.session_state.added_paths = set()
    st.session_state.system_instruction = ""
    st.session_state.summary_result = None # Clear summary
    st.session_state.clear_summary = False
    st.session_state.excluded_individual_files = set() # Reset exclusions
    st.session_state.instr_save_name_value = "" # Reset save name input value
    st.session_state.next_instr_save_name = None # Reset next value flag
    # Reset generation parameters from defaults
    for key, value in DEFAULT_GEN_CONFIG.items(): # Now includes grounding_threshold
        st.session_state[key] = value
    # Clamp max_output_tokens again after reset, based on current model limit
    clamp_max_tokens()


def clamp_max_tokens():
    """Ensures max_output_tokens is within the current model's limit."""
    # IN: None; OUT: None # Adjusts max_output_tokens based on model limit.
    limit = st.session_state.get('current_model_max_output_tokens', api_client.FALLBACK_MODEL_MAX_OUTPUT_TOKENS)
    current_value = st.session_state.get('max_output_tokens', DEFAULT_GEN_CONFIG['max_output_tokens'])
    clamped_value = max(1, min(current_value, limit))
    if clamped_value != current_value:
        logger.debug(f"Clamping max_output_tokens from {current_value} to {clamped_value} (limit: {limit})")
        st.session_state.max_output_tokens = clamped_value

# --- Accessors ---
def get_current_messages():
    """Returns the list of messages, ensuring timestamps are datetime objects."""
    # Ensure messages are processed on access if needed, though reload should handle it.
    messages = st.session_state.get("messages", [])
    # Optional: Add a check here too, though might be redundant if reload works.
    # for msg in messages:
    #     if isinstance(msg.get("timestamp"), str):
    #         # Attempt conversion or log error
    #         pass
    return messages


def get_current_conversation_id():
    return st.session_state.get("current_conversation_id")