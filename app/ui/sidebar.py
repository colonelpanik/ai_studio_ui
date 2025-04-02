# app/ui/sidebar.py
# Renders the sidebar elements: new chat, history, API key, model select, context, instructions.
import streamlit as st
import logging
from pathlib import Path
import time # For potential delays after clearing query params
from app.data import database as db
from app.logic import api_client, context_manager
from app.state import manager as state_manager # Use state manager
import google.generativeai as genai

logger = logging.getLogger(__name__)

# --- Constants ---
TITLE_MAX_LENGTH = 50 # Keep consistent with original logic if needed elsewhere
APP_VERSION = "2.2.1" # Update version if needed

# --- Helper Function ---
def trigger_context_token_update():
    """Calculates context token count and updates state."""
    # IN: None; OUT: None # Calculates context/instruction tokens, updates state.
    logger.debug("Triggering context/token update calculation.")
    # Get required state values
    model_instance = st.session_state.get("current_model_instance")
    added_paths = st.session_state.get("added_paths", set())
    system_instruction = st.session_state.get("system_instruction", "")
    current_content_dict = st.session_state.get("current_context_content_dict", {})

    # 1. Rebuild Context Content if paths changed implicitly (safer to always rebuild)
    logger.debug("Rebuilding context content dictionary from added paths.")
    content_dict, display_details = context_manager.build_context_from_added_paths(added_paths)
    st.session_state.current_context_content_dict = content_dict
    st.session_state.context_files_details = display_details
    logger.debug(f"Context rebuilt: {len(content_dict)} files.")

    # 2. Format context string
    context_str = context_manager.format_context(content_dict, added_paths)

    # 3. Format instruction
    instruction_prefix = f"--- System Instruction ---\n{system_instruction}\n--- End System Instruction ---\n\n" if system_instruction.strip() else ""

    # 4. Combine for token counting
    text_for_token_count = instruction_prefix + context_str

    # 5. Count tokens if model is available
    token_count = 0
    token_count_str = "Token Count: N/A"
    if model_instance and text_for_token_count.strip():
        count, error = api_client.count_tokens(st.session_state.selected_model_name, text_for_token_count)
        if error:
            token_count_str = f"Token Count: Error ({error})"
            token_count = -1
            logger.error(f"Token counting failed: {error}")
        elif count is not None:
            token_count = count
            token_count_str = f"Token Count (Instr + Context): {token_count:,}"
            logger.info(f"Token count updated: {token_count}")
        # else: count is None without error? Should not happen based on api_client.count_tokens
    elif not model_instance:
        token_count_str = "Token Count: N/A (Model not ready)"
        token_count = -1
    else: # Empty text
        token_count_str = "Token Count: 0"
        token_count = 0

    # 6. Update state
    st.session_state.current_token_count = token_count
    st.session_state.current_token_count_str = token_count_str
    logger.debug(f"Token state updated: '{token_count_str}'")


# --- Main Sidebar Function ---
def display_sidebar():
    """Renders all elements within the Streamlit sidebar."""
    # IN: None; OUT: None # Renders the entire sidebar UI.
    st.sidebar.header("Chat & Config")

    # --- New Chat / Conversation History ---
    display_conversation_management()

    # --- API Key & Model Config ---
    display_api_model_config()

    # --- System Instructions ---
    display_system_instructions()

    # --- Context Management ---
    display_context_management()

    # --- Token Count & Footer ---
    display_token_count_and_footer()


# --- Sub-Sections for Clarity ---

def display_conversation_management():
    """Renders the New Chat button and conversation list."""
    # IN: None; OUT: None # Renders conversation list and new chat button.
    st.sidebar.subheader("Conversations")
    if st.sidebar.button("➕ New Chat", key="new_chat_button", use_container_width=True):
        state_manager.reset_chat_state_to_defaults()
        trigger_context_token_update() # Update tokens for empty state
        st.rerun()

    st.sidebar.markdown("---")
    # Refresh conversation list from DB before display
    st.session_state.loaded_conversations = db.get_recent_conversations(limit=15)
    convos = st.session_state.loaded_conversations

    if not convos:
        st.sidebar.caption("No past conversations found.")
    else:
        st.sidebar.caption("Recent Chats:")
        current_convo_id = st.session_state.get("current_conversation_id")
        for convo in convos:
            convo_id = convo["id"]
            title = convo["title"] or db.PLACEHOLDER_TITLE
            display_title = (title[:TITLE_MAX_LENGTH] + '...') if len(title) > TITLE_MAX_LENGTH + 3 else title
            is_selected = (convo_id == current_convo_id)

            col1, col2 = st.sidebar.columns([0.85, 0.15])
            with col1:
                if st.button(f"{display_title}", key=f"load_conv_{convo_id}",
                             help=f"Load: {title}", use_container_width=True,
                             type="primary" if is_selected else "secondary"):
                    if not is_selected:
                        handle_load_conversation(convo_id, display_title) # Pass title for spinner
            with col2:
                if st.button("❌", key=f"delete_conv_{convo_id}", help=f"Delete: {title}",
                             use_container_width=True):
                    handle_delete_conversation(convo_id, display_title)


def handle_load_conversation(convo_id: str, display_title: str):
    """Loads a selected conversation and its associated state."""
    # IN: convo_id, display_title; OUT: None # Loads conversation state.
    logger.info(f"Loading conversation ID: {convo_id}, Title: {display_title}")
    st.session_state.editing_message_id = None # Clear any edit state

    with st.spinner(f"Loading chat: {display_title}..."):
        state_manager.reload_conversation_state(convo_id) # Load messages/history
        metadata = db.get_conversation_metadata(convo_id)

        if metadata is None:
            st.warning(f"Could not load settings for chat {display_title}. Using current/defaults.")
            logger.warning(f"No metadata found for conversation ID: {convo_id}")
            # Keep current settings, just update ID and messages/history
        else:
            # Update state from loaded metadata
            st.session_state.system_instruction = metadata.get("system_instruction", "")
            st.session_state.added_paths = metadata.get("added_paths", set())
            loaded_gen_config = metadata.get("generation_config")

            if loaded_gen_config:
                logger.info(f"Applying saved settings for conversation {convo_id}")
                for key, default_val in state_manager.DEFAULT_GEN_CONFIG.items():
                    st.session_state[key] = loaded_gen_config.get(key, default_val)
            else:
                logger.warning(f"No generation config found for {convo_id}, using defaults.")
                for key, value in state_manager.DEFAULT_GEN_CONFIG.items():
                    st.session_state[key] = value

            # Ensure max tokens is valid after loading potentially old settings
            state_manager.clamp_max_tokens()
            logger.debug(f"Settings applied for {convo_id}.")

        st.session_state.current_conversation_id = convo_id
        trigger_context_token_update() # Recalculate tokens with loaded context/instr
        st.success(f"Loaded chat: {display_title}")
        st.rerun()

def handle_delete_conversation(convo_id: str, display_title: str):
    """Deletes a conversation and updates state if it was the current one."""
    # IN: convo_id, display_title; OUT: None # Deletes conversation, resets state if current.
    logger.warning(f"Attempting to delete conversation '{display_title}' (ID: {convo_id})")
    success, message = db.delete_conversation(convo_id)
    if success:
        st.success(message)
        logger.info(message)
        # If the deleted conversation was the current one, reset state
        if convo_id == st.session_state.get("current_conversation_id"):
            state_manager.reset_chat_state_to_defaults()
            trigger_context_token_update() # Update tokens for empty state
            logger.info("Cleared state as current conversation was deleted.")
        # Refresh list in state (will be re-read next cycle anyway, but good practice)
        st.session_state.loaded_conversations = db.get_recent_conversations(limit=15)
        st.rerun()
    else:
        st.error(message)
        logger.error(f"Failed to delete conversation {convo_id}: {message}")

def display_api_model_config():
    """Renders API key input and model selection dropdown."""
    # IN: None; OUT: None # Renders API key input and model selector.
    api_key_input = st.sidebar.text_input(
        "Gemini API Key:", type="password", key="api_key_widget",
        value=st.session_state.current_api_key, help="Saved locally in SQLite DB."
    )

    # Handle API Key Change
    if api_key_input != st.session_state.current_api_key:
        logger.info("API key changed in input.")
        st.session_state.current_api_key = api_key_input
        # Reset model-related state
        st.session_state.available_models = None
        st.session_state.models_loaded_for_key = None
        st.session_state.selected_model_name = api_client.DEFAULT_MODEL
        st.session_state.current_model_instance = None
        st.session_state.current_model_max_output_tokens = api_client.FALLBACK_MODEL_MAX_OUTPUT_TOKENS
        trigger_context_token_update() # Update token count (will show N/A)
        st.rerun() # Rerun to trigger model loading with new key

    # Clear API Key Link/Button
    if st.sidebar.button("Clear Saved Key", key="clear_api_key_btn"):
        logger.warning("Attempting to clear saved API key.")
        if db.delete_setting('api_key'):
            st.success("Saved API Key cleared.")
            logger.info("Saved API key cleared from DB.")
            st.session_state.current_api_key = ""
            # Reset model state aggressively
            st.session_state.available_models = None
            st.session_state.models_loaded_for_key = None
            st.session_state.selected_model_name = api_client.DEFAULT_MODEL
            st.session_state.current_model_instance = None
            st.session_state.current_model_max_output_tokens = api_client.FALLBACK_MODEL_MAX_OUTPUT_TOKENS
            trigger_context_token_update()
            st.rerun()
        else:
            st.error("Failed to clear saved API key from DB.")
            logger.error("Failed to clear saved API key setting from DB.")

    # Configure API and Load Models if Key Exists
    model_select_container = st.sidebar.empty()
    if st.session_state.current_api_key:
        # Configure API only if key seems valid and changed or not configured yet
        if st.session_state.models_loaded_for_key != st.session_state.current_api_key:
            with st.spinner("Configuring API & fetching models..."):
                api_configured = api_client.configure_api(st.session_state.current_api_key)
                if api_configured:
                    models = api_client.list_available_models()
                    st.session_state.available_models = models
                    st.session_state.models_loaded_for_key = st.session_state.current_api_key
                    if models:
                        # Save key only after successful config/list
                        db.save_setting('api_key', st.session_state.current_api_key)
                        # Set default selection
                        current_selection = st.session_state.selected_model_name
                        if not current_selection or current_selection not in models:
                            st.session_state.selected_model_name = api_client.DEFAULT_MODEL if api_client.DEFAULT_MODEL in models else models[0]
                        # Initialize selected model
                        initialize_selected_model()
                        trigger_context_token_update() # Update tokens with new model
                        st.rerun() # Rerun to display selector
                    else:
                        st.sidebar.warning("No suitable models found for this key.")
                        st.session_state.current_model_instance = None # Clear instance
                        trigger_context_token_update() # Update tokens
                        st.rerun() # Rerun to show warning
                else:
                    st.sidebar.error("API Key/Config error. Check key.")
                    st.session_state.available_models = None # Clear models on config error
                    st.session_state.models_loaded_for_key = None
                    st.session_state.current_model_instance = None
                    # No rerun needed, error is shown

    # Display Model Selector
    if st.session_state.available_models:
        try:
            current_selection = st.session_state.selected_model_name
            # Ensure current selection is valid, default if not
            if not current_selection or current_selection not in st.session_state.available_models:
                current_selection = api_client.DEFAULT_MODEL if api_client.DEFAULT_MODEL in st.session_state.available_models else st.session_state.available_models[0]
                st.session_state.selected_model_name = current_selection

            selected_index = st.session_state.available_models.index(current_selection)

            selected_model = model_select_container.selectbox(
                "Select Gemini Model:", options=st.session_state.available_models,
                index=selected_index, key='model_select_dropdown'
            )
            # Handle Model Change
            if selected_model != st.session_state.selected_model_name:
                logger.info(f"Model selection changed to: {selected_model}")
                st.session_state.selected_model_name = selected_model
                initialize_selected_model() # Init new model, updates limits/instance
                trigger_context_token_update() # Update token count for new model
                st.rerun() # Rerun to reflect changes (e.g., new token limit in params)

            # Ensure instance exists if selection hasn't changed but instance is missing
            elif not st.session_state.current_model_instance and st.session_state.selected_model_name:
                 logger.warning("Model instance missing, re-initializing...")
                 initialize_selected_model()
                 trigger_context_token_update() # Update tokens just in case
                 st.rerun() # Rerun to ensure UI consistency

        except Exception as e:
            model_select_container.error(f"Error displaying models: {e}")
            logger.error(f"Error in model selection display: {e}", exc_info=True)
    elif st.session_state.current_api_key and st.session_state.models_loaded_for_key == st.session_state.current_api_key:
        model_select_container.warning("No suitable models found for this key.")
    elif not st.session_state.current_api_key:
        model_select_container.info("Enter API Key to load models.")

def initialize_selected_model():
    """Initializes the GenerativeModel instance based on selected_model_name."""
    # IN: None; OUT: None # Initializes model instance, updates limits in state.
    selected_model = st.session_state.selected_model_name
    logger.info(f"Initializing model instance: {selected_model}")
    try:
        limit = api_client.get_model_output_limit(selected_model)
        st.session_state.current_model_max_output_tokens = limit
        state_manager.clamp_max_tokens() # Adjust slider state based on new limit
        # Create the model instance
        model_instance = genai.GenerativeModel(selected_model)
        st.session_state.current_model_instance = model_instance
        logger.info(f"Model '{selected_model}' initialized successfully (limit: {limit}).")
    except Exception as e:
        st.sidebar.error(f"Failed to initialize model '{selected_model}': {e}")
        logger.error(f"Failed to initialize model '{selected_model}': {e}", exc_info=True)
        st.session_state.current_model_instance = None
        st.session_state.current_model_max_output_tokens = api_client.FALLBACK_MODEL_MAX_OUTPUT_TOKENS

def display_system_instructions():
    """Renders the expander for managing system instructions."""
    # IN: None; OUT: None # Renders system instruction input and load/save controls.
    with st.sidebar.expander("System Instructions", expanded=False):
        st.session_state.system_instruction = st.text_area(
            "Enter instructions:",
            value=st.session_state.get("system_instruction", ""),
            height=150,
            key="system_instruction_text_area",
            on_change=trigger_context_token_update # Update tokens on change
        )
        # Save Instruction
        instr_name_save = st.text_input("Save instruction as:", key="instr_save_name")
        if st.button("Save Instruction", key="save_instr_btn"):
            if instr_name_save and st.session_state.system_instruction:
                success, msg = db.save_instruction(instr_name_save, st.session_state.system_instruction)
                st.toast(msg, icon="✅" if success else "❌")
                if success:
                    st.session_state.instruction_names = db.get_instruction_names() # Refresh list
                    st.rerun()
            elif not instr_name_save: st.warning("Enter a name to save.")
            else: st.warning("Enter some instruction text to save.")

        st.markdown("---")
        # Load/Delete Instruction
        instruction_names = st.session_state.instruction_names
        if instruction_names:
            instr_name_load = st.selectbox("Load instruction:", options=[""] + instruction_names, key="instr_load_select")
            col_load, col_delete = st.columns(2)
            if col_load.button("Load", key="load_instr_btn", disabled=not instr_name_load, use_container_width=True):
                loaded_text = db.load_instruction(instr_name_load)
                if loaded_text is not None:
                    st.session_state.system_instruction = loaded_text
                    st.session_state.instr_save_name = instr_name_load # Pre-fill save name
                    trigger_context_token_update() # Update tokens
                    st.rerun() # Update text area value
                else: st.error(f"Could not load '{instr_name_load}'.")
            if col_delete.button("Delete", key="delete_instr_btn", disabled=not instr_name_load, use_container_width=True):
                current_text_if_loaded = db.load_instruction(instr_name_load) # Check text before delete
                success, msg = db.delete_instruction(instr_name_load)
                st.toast(msg, icon="✅" if success else "❌")
                if success:
                    st.session_state.instruction_names = db.get_instruction_names() # Refresh list
                    if st.session_state.system_instruction == current_text_if_loaded:
                        st.session_state.system_instruction = "" # Clear if deleted instruction was loaded
                    if st.session_state.instr_save_name == instr_name_load:
                        st.session_state.instr_save_name = "" # Clear pre-filled name
                    trigger_context_token_update()
                    st.rerun() # Update dropdown/text area
        else:
            st.caption("No saved instructions.")


def display_context_management():
    """Renders controls for adding/removing context paths and viewing files."""
    # IN: None; OUT: None # Renders context path input and file list expanders.
    st.sidebar.markdown("---")
    st.sidebar.header("Manage Context")
    new_path_input = st.sidebar.text_input("Add File/Folder Path:", key="new_path")
    if st.sidebar.button("Add Path", key="add_path_button"):
        if new_path_input:
            try:
                resolved_path = str(Path(new_path_input).resolve())
                if Path(resolved_path).exists():
                    if resolved_path not in st.session_state.added_paths:
                        st.session_state.added_paths.add(resolved_path)
                        st.sidebar.success(f"Added: {resolved_path}")
                        trigger_context_token_update() # Update tokens and file list
                        st.rerun()
                    else: st.sidebar.info("Path already added.")
                else: st.sidebar.error(f"Path not found: {new_path_input}")
            except Exception as e: st.sidebar.error(f"Error resolving path: {e}")
        else: st.sidebar.warning("Please enter a path to add.")

    # Managed Paths Expander
    with st.sidebar.expander("Managed Paths", expanded=True):
        if not st.session_state.added_paths: st.caption("No paths added.")
        else:
            paths_to_remove = []
            for path_str in sorted(list(st.session_state.added_paths)):
                col1, col2 = st.columns([4, 1])
                col1.code(path_str, language=None)
                if col2.button("❌", key=f"remove_{hash(path_str)}", help=f"Remove {path_str}"):
                    paths_to_remove.append(path_str)
            if paths_to_remove:
                needs_update = False
                for path in paths_to_remove:
                    if path in st.session_state.added_paths:
                        st.session_state.added_paths.discard(path); needs_update = True
                if needs_update:
                    trigger_context_token_update()
                    st.rerun()

    # Effective Files Expander
    with st.sidebar.expander("Effective Files", expanded=False):
        details = st.session_state.get('context_files_details', [])
        if not details: st.caption("Add paths to see files.")
        else:
            with st.container(height=300):
                inc, skip, err = 0, 0, 0
                for path, status, detail in sorted(details, key=lambda x: x[0]):
                    icon = "✅" if "Included" in status else ("⚠️" if "Skipped" in status else "❌")
                    color = "green" if "Included" in status else ("orange" if "Skipped" in status else "red")
                    st.markdown(f"<small><span style='color:{color};'>{icon} **{status}:** `{path}` ({detail})</span></small>", unsafe_allow_html=True)
                    if "Included" in status: inc+=1
                    elif "Skipped" in status: skip+=1
                    else: err+=1
                st.caption(f"**Total:** {inc} Included, {skip} Skipped, {err} Errors")

def display_token_count_and_footer():
    """Displays the token count and app footer."""
    # IN: None; OUT: None # Renders token count, refresh button, footer.
    st.sidebar.markdown("---")
    # Use placeholder for dynamic update if needed, but direct display is simpler
    st.sidebar.caption(st.session_state.get("current_token_count_str", "Token Count: N/A"))
    if st.sidebar.button("Refresh Tokens/Context", key="refresh_tokens_btn"):
        trigger_context_token_update()
        st.rerun() # Rerun to show updated count and file list immediately

    st.sidebar.markdown("---")
    # Placeholder for clear chat history button if needed
    # if st.sidebar.button("Clear Current Chat History"): ... handle action ...

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"<small>Version: {APP_VERSION} | Gemini Chat Pro</small>", unsafe_allow_html=True)

# app/ui/sidebar.py
# Renders the sidebar elements: new chat, history, API key, model select, context, instructions.
import streamlit as st
import logging
from pathlib import Path
import time # For potential delays after clearing query params
from app.data import database as db
from app.logic import api_client, context_manager
from app.state import manager as state_manager # Use state manager

logger = logging.getLogger(__name__)

# --- Constants ---
TITLE_MAX_LENGTH = 50 # Keep consistent with original logic if needed elsewhere
APP_VERSION = "2.2.1" # Update version if needed

# --- Helper Function ---
def trigger_context_token_update():
    """Calculates context token count and updates state."""
    # IN: None; OUT: None # Calculates context/instruction tokens, updates state.
    logger.debug("Triggering context/token update calculation.")
    # Get required state values
    model_instance = st.session_state.get("current_model_instance")
    added_paths = st.session_state.get("added_paths", set())
    system_instruction = st.session_state.get("system_instruction", "")
    current_content_dict = st.session_state.get("current_context_content_dict", {})

    # 1. Rebuild Context Content if paths changed implicitly (safer to always rebuild)
    logger.debug("Rebuilding context content dictionary from added paths.")
    content_dict, display_details = context_manager.build_context_from_added_paths(added_paths)
    st.session_state.current_context_content_dict = content_dict
    st.session_state.context_files_details = display_details
    logger.debug(f"Context rebuilt: {len(content_dict)} files.")

    # 2. Format context string
    context_str = context_manager.format_context(content_dict, added_paths)

    # 3. Format instruction
    instruction_prefix = f"--- System Instruction ---\n{system_instruction}\n--- End System Instruction ---\n\n" if system_instruction.strip() else ""

    # 4. Combine for token counting
    text_for_token_count = instruction_prefix + context_str

    # 5. Count tokens if model is available
    token_count = 0
    token_count_str = "Token Count: N/A"
    if model_instance and text_for_token_count.strip():
        count, error = api_client.count_tokens(st.session_state.selected_model_name, text_for_token_count)
        if error:
            token_count_str = f"Token Count: Error ({error})"
            token_count = -1
            logger.error(f"Token counting failed: {error}")
        elif count is not None:
            token_count = count
            token_count_str = f"Token Count (Instr + Context): {token_count:,}"
            logger.info(f"Token count updated: {token_count}")
        # else: count is None without error? Should not happen based on api_client.count_tokens
    elif not model_instance:
        token_count_str = "Token Count: N/A (Model not ready)"
        token_count = -1
    else: # Empty text
        token_count_str = "Token Count: 0"
        token_count = 0

    # 6. Update state
    st.session_state.current_token_count = token_count
    st.session_state.current_token_count_str = token_count_str
    logger.debug(f"Token state updated: '{token_count_str}'")


# --- Main Sidebar Function ---
def display_sidebar():
    """Renders all elements within the Streamlit sidebar."""
    # IN: None; OUT: None # Renders the entire sidebar UI.
    st.sidebar.header("Chat & Config")

    # --- New Chat / Conversation History ---
    display_conversation_management()

    # --- API Key & Model Config ---
    display_api_model_config()

    # --- System Instructions ---
    display_system_instructions()

    # --- Context Management ---
    display_context_management()

    # --- Token Count & Footer ---
    display_token_count_and_footer()


# --- Sub-Sections for Clarity ---

def display_conversation_management():
    """Renders the New Chat button and conversation list."""
    # IN: None; OUT: None # Renders conversation list and new chat button.
    st.sidebar.subheader("Conversations")
    if st.sidebar.button("➕ New Chat", key="new_chat_button", use_container_width=True):
        state_manager.reset_chat_state_to_defaults()
        trigger_context_token_update() # Update tokens for empty state
        st.rerun()

    st.sidebar.markdown("---")
    # Refresh conversation list from DB before display
    st.session_state.loaded_conversations = db.get_recent_conversations(limit=15)
    convos = st.session_state.loaded_conversations

    if not convos:
        st.sidebar.caption("No past conversations found.")
    else:
        st.sidebar.caption("Recent Chats:")
        current_convo_id = st.session_state.get("current_conversation_id")
        for convo in convos:
            convo_id = convo["id"]
            title = convo["title"] or db.PLACEHOLDER_TITLE
            display_title = (title[:TITLE_MAX_LENGTH] + '...') if len(title) > TITLE_MAX_LENGTH + 3 else title
            is_selected = (convo_id == current_convo_id)

            col1, col2 = st.sidebar.columns([0.85, 0.15])
            with col1:
                if st.button(f"{display_title}", key=f"load_conv_{convo_id}",
                             help=f"Load: {title}", use_container_width=True,
                             type="primary" if is_selected else "secondary"):
                    if not is_selected:
                        handle_load_conversation(convo_id, display_title) # Pass title for spinner
            with col2:
                if st.button("❌", key=f"delete_conv_{convo_id}", help=f"Delete: {title}",
                             use_container_width=True):
                    handle_delete_conversation(convo_id, display_title)


def handle_load_conversation(convo_id: str, display_title: str):
    """Loads a selected conversation and its associated state."""
    # IN: convo_id, display_title; OUT: None # Loads conversation state.
    logger.info(f"Loading conversation ID: {convo_id}, Title: {display_title}")
    st.session_state.editing_message_id = None # Clear any edit state

    with st.spinner(f"Loading chat: {display_title}..."):
        state_manager.reload_conversation_state(convo_id) # Load messages/history
        metadata = db.get_conversation_metadata(convo_id)

        if metadata is None:
            st.warning(f"Could not load settings for chat {display_title}. Using current/defaults.")
            logger.warning(f"No metadata found for conversation ID: {convo_id}")
            # Keep current settings, just update ID and messages/history
        else:
            # Update state from loaded metadata
            st.session_state.system_instruction = metadata.get("system_instruction", "")
            st.session_state.added_paths = metadata.get("added_paths", set())
            loaded_gen_config = metadata.get("generation_config")

            if loaded_gen_config:
                logger.info(f"Applying saved settings for conversation {convo_id}")
                for key, default_val in state_manager.DEFAULT_GEN_CONFIG.items():
                    st.session_state[key] = loaded_gen_config.get(key, default_val)
            else:
                logger.warning(f"No generation config found for {convo_id}, using defaults.")
                for key, value in state_manager.DEFAULT_GEN_CONFIG.items():
                    st.session_state[key] = value

            # Ensure max tokens is valid after loading potentially old settings
            state_manager.clamp_max_tokens()
            logger.debug(f"Settings applied for {convo_id}.")

        st.session_state.current_conversation_id = convo_id
        trigger_context_token_update() # Recalculate tokens with loaded context/instr
        st.success(f"Loaded chat: {display_title}")
        st.rerun()

def handle_delete_conversation(convo_id: str, display_title: str):
    """Deletes a conversation and updates state if it was the current one."""
    # IN: convo_id, display_title; OUT: None # Deletes conversation, resets state if current.
    logger.warning(f"Attempting to delete conversation '{display_title}' (ID: {convo_id})")
    success, message = db.delete_conversation(convo_id)
    if success:
        st.success(message)
        logger.info(message)
        # If the deleted conversation was the current one, reset state
        if convo_id == st.session_state.get("current_conversation_id"):
            state_manager.reset_chat_state_to_defaults()
            trigger_context_token_update() # Update tokens for empty state
            logger.info("Cleared state as current conversation was deleted.")
        # Refresh list in state (will be re-read next cycle anyway, but good practice)
        st.session_state.loaded_conversations = db.get_recent_conversations(limit=15)
        st.rerun()
    else:
        st.error(message)
        logger.error(f"Failed to delete conversation {convo_id}: {message}")

def display_api_model_config():
    """Renders API key input and model selection dropdown."""
    # IN: None; OUT: None # Renders API key input and model selector.
    api_key_input = st.sidebar.text_input(
        "Gemini API Key:", type="password", key="api_key_widget",
        value=st.session_state.current_api_key, help="Saved locally in SQLite DB."
    )

    # Handle API Key Change
    if api_key_input != st.session_state.current_api_key:
        logger.info("API key changed in input.")
        st.session_state.current_api_key = api_key_input
        # Reset model-related state
        st.session_state.available_models = None
        st.session_state.models_loaded_for_key = None
        st.session_state.selected_model_name = api_client.DEFAULT_MODEL
        st.session_state.current_model_instance = None
        st.session_state.current_model_max_output_tokens = api_client.FALLBACK_MODEL_MAX_OUTPUT_TOKENS
        trigger_context_token_update() # Update token count (will show N/A)
        st.rerun() # Rerun to trigger model loading with new key

    # Clear API Key Link/Button
    if st.sidebar.button("Clear Saved Key", key="clear_api_key_btn"):
        logger.warning("Attempting to clear saved API key.")
        if db.delete_setting('api_key'):
            st.success("Saved API Key cleared.")
            logger.info("Saved API key cleared from DB.")
            st.session_state.current_api_key = ""
            # Reset model state aggressively
            st.session_state.available_models = None
            st.session_state.models_loaded_for_key = None
            st.session_state.selected_model_name = api_client.DEFAULT_MODEL
            st.session_state.current_model_instance = None
            st.session_state.current_model_max_output_tokens = api_client.FALLBACK_MODEL_MAX_OUTPUT_TOKENS
            trigger_context_token_update()
            st.rerun()
        else:
            st.error("Failed to clear saved API key from DB.")
            logger.error("Failed to clear saved API key setting from DB.")

    # Configure API and Load Models if Key Exists
    model_select_container = st.sidebar.empty()
    if st.session_state.current_api_key:
        # Configure API only if key seems valid and changed or not configured yet
        if st.session_state.models_loaded_for_key != st.session_state.current_api_key:
            with st.spinner("Configuring API & fetching models..."):
                api_configured = api_client.configure_api(st.session_state.current_api_key)
                if api_configured:
                    models = api_client.list_available_models()
                    st.session_state.available_models = models
                    st.session_state.models_loaded_for_key = st.session_state.current_api_key
                    if models:
                        # Save key only after successful config/list
                        db.save_setting('api_key', st.session_state.current_api_key)
                        # Set default selection
                        current_selection = st.session_state.selected_model_name
                        if not current_selection or current_selection not in models:
                            st.session_state.selected_model_name = api_client.DEFAULT_MODEL if api_client.DEFAULT_MODEL in models else models[0]
                        # Initialize selected model
                        initialize_selected_model()
                        trigger_context_token_update() # Update tokens with new model
                        st.rerun() # Rerun to display selector
                    else:
                        st.sidebar.warning("No suitable models found for this key.")
                        st.session_state.current_model_instance = None # Clear instance
                        trigger_context_token_update() # Update tokens
                        st.rerun() # Rerun to show warning
                else:
                    st.sidebar.error("API Key/Config error. Check key.")
                    st.session_state.available_models = None # Clear models on config error
                    st.session_state.models_loaded_for_key = None
                    st.session_state.current_model_instance = None
                    # No rerun needed, error is shown

    # Display Model Selector
    if st.session_state.available_models:
        try:
            current_selection = st.session_state.selected_model_name
            # Ensure current selection is valid, default if not
            if not current_selection or current_selection not in st.session_state.available_models:
                current_selection = api_client.DEFAULT_MODEL if api_client.DEFAULT_MODEL in st.session_state.available_models else st.session_state.available_models[0]
                st.session_state.selected_model_name = current_selection

            selected_index = st.session_state.available_models.index(current_selection)

            selected_model = model_select_container.selectbox(
                "Select Gemini Model:", options=st.session_state.available_models,
                index=selected_index, key='model_select_dropdown'
            )
            # Handle Model Change
            if selected_model != st.session_state.selected_model_name:
                logger.info(f"Model selection changed to: {selected_model}")
                st.session_state.selected_model_name = selected_model
                initialize_selected_model() # Init new model, updates limits/instance
                trigger_context_token_update() # Update token count for new model
                st.rerun() # Rerun to reflect changes (e.g., new token limit in params)

            # Ensure instance exists if selection hasn't changed but instance is missing
            elif not st.session_state.current_model_instance and st.session_state.selected_model_name:
                 logger.warning("Model instance missing, re-initializing...")
                 initialize_selected_model()
                 trigger_context_token_update() # Update tokens just in case
                 st.rerun() # Rerun to ensure UI consistency

        except Exception as e:
            model_select_container.error(f"Error displaying models: {e}")
            logger.error(f"Error in model selection display: {e}", exc_info=True)
    elif st.session_state.current_api_key and st.session_state.models_loaded_for_key == st.session_state.current_api_key:
        model_select_container.warning("No suitable models found for this key.")
    elif not st.session_state.current_api_key:
        model_select_container.info("Enter API Key to load models.")

def initialize_selected_model():
    """Initializes the GenerativeModel instance based on selected_model_name."""
    # IN: None; OUT: None # Initializes model instance, updates limits in state.
    selected_model = st.session_state.selected_model_name
    logger.info(f"Initializing model instance: {selected_model}")
    try:
        limit = api_client.get_model_output_limit(selected_model)
        st.session_state.current_model_max_output_tokens = limit
        state_manager.clamp_max_tokens() # Adjust slider state based on new limit
        # Create the model instance
        model_instance = genai.GenerativeModel(selected_model)
        st.session_state.current_model_instance = model_instance
        logger.info(f"Model '{selected_model}' initialized successfully (limit: {limit}).")
    except Exception as e:
        st.sidebar.error(f"Failed to initialize model '{selected_model}': {e}")
        logger.error(f"Failed to initialize model '{selected_model}': {e}", exc_info=True)
        st.session_state.current_model_instance = None
        st.session_state.current_model_max_output_tokens = api_client.FALLBACK_MODEL_MAX_OUTPUT_TOKENS

def display_system_instructions():
    """Renders the expander for managing system instructions."""
    # IN: None; OUT: None # Renders system instruction input and load/save controls.
    with st.sidebar.expander("System Instructions", expanded=False):
        st.session_state.system_instruction = st.text_area(
            "Enter instructions:",
            value=st.session_state.get("system_instruction", ""),
            height=150,
            key="system_instruction_text_area",
            on_change=trigger_context_token_update # Update tokens on change
        )
        # Save Instruction
        instr_name_save = st.text_input("Save instruction as:", key="instr_save_name")
        if st.button("Save Instruction", key="save_instr_btn"):
            if instr_name_save and st.session_state.system_instruction:
                success, msg = db.save_instruction(instr_name_save, st.session_state.system_instruction)
                st.toast(msg, icon="✅" if success else "❌")
                if success:
                    st.session_state.instruction_names = db.get_instruction_names() # Refresh list
                    st.rerun()
            elif not instr_name_save: st.warning("Enter a name to save.")
            else: st.warning("Enter some instruction text to save.")

        st.markdown("---")
        # Load/Delete Instruction
        instruction_names = st.session_state.instruction_names
        if instruction_names:
            instr_name_load = st.selectbox("Load instruction:", options=[""] + instruction_names, key="instr_load_select")
            col_load, col_delete = st.columns(2)
            if col_load.button("Load", key="load_instr_btn", disabled=not instr_name_load, use_container_width=True):
                loaded_text = db.load_instruction(instr_name_load)
                if loaded_text is not None:
                    st.session_state.system_instruction = loaded_text
                    st.session_state.instr_save_name = instr_name_load # Pre-fill save name
                    trigger_context_token_update() # Update tokens
                    st.rerun() # Update text area value
                else: st.error(f"Could not load '{instr_name_load}'.")
            if col_delete.button("Delete", key="delete_instr_btn", disabled=not instr_name_load, use_container_width=True):
                current_text_if_loaded = db.load_instruction(instr_name_load) # Check text before delete
                success, msg = db.delete_instruction(instr_name_load)
                st.toast(msg, icon="✅" if success else "❌")
                if success:
                    st.session_state.instruction_names = db.get_instruction_names() # Refresh list
                    if st.session_state.system_instruction == current_text_if_loaded:
                        st.session_state.system_instruction = "" # Clear if deleted instruction was loaded
                    if st.session_state.instr_save_name == instr_name_load:
                        st.session_state.instr_save_name = "" # Clear pre-filled name
                    trigger_context_token_update()
                    st.rerun() # Update dropdown/text area
        else:
            st.caption("No saved instructions.")


def display_context_management():
    """Renders controls for adding/removing context paths and viewing files."""
    # IN: None; OUT: None # Renders context path input and file list expanders.
    st.sidebar.markdown("---")
    st.sidebar.header("Manage Context")
    new_path_input = st.sidebar.text_input("Add File/Folder Path:", key="new_path")
    if st.sidebar.button("Add Path", key="add_path_button"):
        if new_path_input:
            try:
                resolved_path = str(Path(new_path_input).resolve())
                if Path(resolved_path).exists():
                    if resolved_path not in st.session_state.added_paths:
                        st.session_state.added_paths.add(resolved_path)
                        st.sidebar.success(f"Added: {resolved_path}")
                        trigger_context_token_update() # Update tokens and file list
                        st.rerun()
                    else: st.sidebar.info("Path already added.")
                else: st.sidebar.error(f"Path not found: {new_path_input}")
            except Exception as e: st.sidebar.error(f"Error resolving path: {e}")
        else: st.sidebar.warning("Please enter a path to add.")

    # Managed Paths Expander
    with st.sidebar.expander("Managed Paths", expanded=True):
        if not st.session_state.added_paths: st.caption("No paths added.")
        else:
            paths_to_remove = []
            for path_str in sorted(list(st.session_state.added_paths)):
                col1, col2 = st.columns([4, 1])
                col1.code(path_str, language=None)
                if col2.button("❌", key=f"remove_{hash(path_str)}", help=f"Remove {path_str}"):
                    paths_to_remove.append(path_str)
            if paths_to_remove:
                needs_update = False
                for path in paths_to_remove:
                    if path in st.session_state.added_paths:
                        st.session_state.added_paths.discard(path); needs_update = True
                if needs_update:
                    trigger_context_token_update()
                    st.rerun()

    # Effective Files Expander
    with st.sidebar.expander("Effective Files", expanded=False):
        details = st.session_state.get('context_files_details', [])
        if not details: st.caption("Add paths to see files.")
        else:
            with st.container(height=300):
                inc, skip, err = 0, 0, 0
                for path, status, detail in sorted(details, key=lambda x: x[0]):
                    icon = "✅" if "Included" in status else ("⚠️" if "Skipped" in status else "❌")
                    color = "green" if "Included" in status else ("orange" if "Skipped" in status else "red")
                    st.markdown(f"<small><span style='color:{color};'>{icon} **{status}:** `{path}` ({detail})</span></small>", unsafe_allow_html=True)
                    if "Included" in status: inc+=1
                    elif "Skipped" in status: skip+=1
                    else: err+=1
                st.caption(f"**Total:** {inc} Included, {skip} Skipped, {err} Errors")

def display_token_count_and_footer():
    """Displays the token count and app footer."""
    # IN: None; OUT: None # Renders token count, refresh button, footer.
    st.sidebar.markdown("---")
    # Use placeholder for dynamic update if needed, but direct display is simpler
    st.sidebar.caption(st.session_state.get("current_token_count_str", "Token Count: N/A"))
    if st.sidebar.button("Refresh Tokens/Context", key="refresh_tokens_btn"):
        trigger_context_token_update()
        st.rerun() # Rerun to show updated count and file list immediately

    st.sidebar.markdown("---")
    # Placeholder for clear chat history button if needed
    # if st.sidebar.button("Clear Current Chat History"): ... handle action ...

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"<small>Version: {APP_VERSION} | Gemini Chat Pro</small>", unsafe_allow_html=True)

