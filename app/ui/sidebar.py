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
import datetime # Required for type checking

logger = logging.getLogger(__name__)

# --- Constants ---
TITLE_MAX_LENGTH = 50 # Keep consistent with original logic if needed elsewhere
APP_VERSION = "2.2.1" # Update version if needed

# --- Helper Functions ---

def trigger_context_token_update():
    """Calculates context token count and updates state, considering exclusions."""
    # IN: None; OUT: None # Calculates context/instruction tokens, updates state.
    logger.debug("Triggering context/token update calculation (considering exclusions).")
    # Get required state values
    model_instance = st.session_state.get("current_model_instance")
    added_paths = st.session_state.get("added_paths", set())
    system_instruction = st.session_state.get("system_instruction", "")
    # Load the set of individually excluded files for this conversation
    excluded_files = st.session_state.get("excluded_individual_files", set())

    # 1. Build Potential Context (Scan all initially added paths)
    logger.debug("Building potential context content dictionary from added paths.")
    potential_content_dict, potential_display_details = context_manager.build_context_from_added_paths(added_paths)
    logger.debug(f"Potential context built: {len(potential_content_dict)} files found initially.")

    # 2. Filter based on excluded_individual_files
    final_content_dict = {}
    final_display_details = []
    included_count, skipped_count, error_count, user_excluded_count = 0, 0, 0, 0

    for abs_path, status, detail in potential_display_details:
        # Convert relative path back to absolute if needed (ensure consistency)
        # Assuming context_manager returns absolute paths in display_details now
        # If not, resolve based on added_paths if necessary
        abs_path_str = str(abs_path) # Ensure string representation

        if abs_path_str in excluded_files:
            # Mark as excluded by user, do not add to final_content_dict
            final_display_details.append((abs_path, "Excluded (User)", detail))
            user_excluded_count += 1
        else:
            # Keep original status and detail, add to final content if included
            final_display_details.append((abs_path, status, detail))
            if "Included" in status and abs_path_str in potential_content_dict:
                final_content_dict[abs_path_str] = potential_content_dict[abs_path_str]
                included_count += 1
            elif "Skipped" in status:
                skipped_count += 1
            elif "Error" in status:
                error_count += 1

    # Sort final details list
    final_display_details.sort(key=lambda x: x[0])
    st.session_state.context_files_details = final_display_details
    st.session_state.current_context_content_dict = final_content_dict
    logger.info(f"Final context: {included_count} Included, {user_excluded_count} User Excluded, {skipped_count} Skipped (Auto), {error_count} Errors.")

    # 3. Format final context string
    context_str = context_manager.format_context(final_content_dict, added_paths) # Use filtered dict

    # 4. Format instruction
    instruction_prefix = f"--- System Instruction ---\n{system_instruction}\n--- End System Instruction ---\n\n" if system_instruction.strip() else ""

    # 5. Combine for token counting
    text_for_token_count = instruction_prefix + context_str

    # 6. Count tokens if model is available
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
    elif not model_instance:
        token_count_str = "Token Count: N/A (Model not ready)"
        token_count = -1
    else: # Empty text
        token_count_str = "Token Count: 0"
        token_count = 0

    # 7. Update state
    st.session_state.current_token_count = token_count
    st.session_state.current_token_count_str = token_count_str
    logger.debug(f"Token state updated: '{token_count_str}'")

# --- NEW: Callback for File Exclusion Checkbox ---
def _handle_file_exclusion_change(abs_path_str: str):
    """Callback function when a file exclusion checkbox is toggled."""
    # The checkbox value is already updated in st.session_state by the time the callback runs
    is_checked = st.session_state[f"exclude_cb_{hash(abs_path_str)}"] # Get current state of the checkbox

    if is_checked:
        # Checkbox is checked (Include the file) -> Remove from exclusion set
        if abs_path_str in st.session_state.excluded_individual_files:
            st.session_state.excluded_individual_files.discard(abs_path_str)
            logger.info(f"Checkbox '{abs_path_str}' checked (Included): Removed from exclusion set.")
            trigger_context_token_update() # Recalculate
            # No rerun needed here, on_change handles it implicitly.
        else:
             logger.debug(f"Checkbox '{abs_path_str}' checked (Included): Was already not excluded.")
    else:
        # Checkbox is unchecked (Exclude the file) -> Add to exclusion set
        if abs_path_str not in st.session_state.excluded_individual_files:
            st.session_state.excluded_individual_files.add(abs_path_str)
            logger.info(f"Checkbox '{abs_path_str}' unchecked (Excluded): Added to exclusion set.")
            trigger_context_token_update() # Recalculate
            # No rerun needed here, on_change handles it implicitly.
        else:
            logger.debug(f"Checkbox '{abs_path_str}' unchecked (Excluded): Was already excluded.")

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
    display_system_instructions() # Modified

    # --- Context Management ---
    display_context_management() # Modified for spacing and file list

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
                if st.button("🗑️", key=f"delete_conv_{convo_id}", help=f"Delete: {title}", # Use Trash icon
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
            # Reset exclusions if metadata missing
            st.session_state.excluded_individual_files = set()
            st.session_state.system_instruction = "" # Reset instruction too
            # Reset gen config to defaults
            for key, value in state_manager.DEFAULT_GEN_CONFIG.items():
                 st.session_state[key] = value
            st.session_state.next_instr_save_name = None # Reset potential pre-fill

        else:
            # Update state from loaded metadata
            st.session_state.system_instruction = metadata.get("system_instruction", "")
            st.session_state.added_paths = metadata.get("added_paths", set())
            st.session_state.excluded_individual_files = metadata.get("excluded_individual_files", set())
            # Pre-fill save name field if loaded instruction matches a saved one?
            # This is complex, let's skip pre-filling save name on load for now
            st.session_state.next_instr_save_name = None # Clear any pending pre-fill
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
        trigger_context_token_update() # Recalculate tokens with loaded context/instr/exclusions
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
    st.sidebar.markdown("---") # Divider before API section
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
    st.sidebar.markdown("---") # Divider before Instructions
    with st.sidebar.expander("System Instructions", expanded=False):
        st.session_state.system_instruction = st.text_area(
            "Enter instructions:",
            value=st.session_state.get("system_instruction", ""),
            height=150,
            key="system_instruction_text_area",
            on_change=trigger_context_token_update # Update tokens on change
        )

        # --- Modified Save Name Input ---
        # Determine the value for the text input *before* rendering it
        save_name_default = ""
        if st.session_state.next_instr_save_name is not None:
            # Use the value set by the Load button from the *previous* run
            save_name_default = st.session_state.next_instr_save_name
            st.session_state.next_instr_save_name = None # Clear the flag after using it
            logger.debug(f"Pre-filling instruction save name with: {save_name_default}")
        else:
            # Otherwise, use the value currently held by the widget's state
             save_name_default = st.session_state.instr_save_name_value

        # Render the text input using the determined value
        # We store the widget's current value in 'instr_save_name_value'
        st.session_state.instr_save_name_value = st.text_input(
            "Save instruction as:",
            value=save_name_default,
            key="instr_save_name_input_widget" # Use a distinct key for the widget itself
        )
        # --- End Modified Save Name Input ---

        if st.button("Save Instruction", key="save_instr_btn"):
            # Use the value from the widget's state variable for saving
            name_to_save = st.session_state.instr_save_name_value
            if name_to_save and st.session_state.system_instruction:
                success, msg = db.save_instruction(name_to_save, st.session_state.system_instruction)
                st.toast(msg, icon="✅" if success else "❌")
                if success:
                    st.session_state.instruction_names = db.get_instruction_names() # Refresh list
                    # Clear the input field *state* after successful save for next run
                    st.session_state.instr_save_name_value = ""
                    st.rerun() # Rerun to show updated list and cleared input
            elif not name_to_save: st.warning("Enter a name to save.")
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
                    # --- MODIFIED: Set flag for next run ---
                    st.session_state.next_instr_save_name = instr_name_load # Pre-fill save name for *next* run
                    # --- END MODIFIED ---
                    trigger_context_token_update() # Update tokens
                    st.rerun() # Rerun to update text area value and pre-fill input on next cycle
                else: st.error(f"Could not load '{instr_name_load}'.")

            if col_delete.button("Delete", key="delete_instr_btn", disabled=not instr_name_load, use_container_width=True):
                # Get the text before deleting to potentially clear the text area
                text_being_deleted = db.load_instruction(instr_name_load)
                success, msg = db.delete_instruction(instr_name_load)
                st.toast(msg, icon="✅" if success else "❌")
                if success:
                    st.session_state.instruction_names = db.get_instruction_names() # Refresh list
                    # Clear the text area if the deleted instruction was loaded
                    if st.session_state.system_instruction == text_being_deleted:
                        st.session_state.system_instruction = ""
                    # Clear the save name input field if the deleted instruction was there
                    if st.session_state.instr_save_name_value == instr_name_load:
                        st.session_state.instr_save_name_value = ""
                    st.session_state.next_instr_save_name = None # Ensure no pending pre-fill
                    trigger_context_token_update()
                    st.rerun() # Update dropdown/text area/input field
        else:
            st.caption("No saved instructions.")


def display_context_management():
    """Renders controls for adding/removing context paths and viewing files."""
    # IN: None; OUT: None # Renders context path input and file list expanders.
    st.sidebar.markdown("---") # Divider before Context
    st.sidebar.header("Manage Context")

    # --- Path Input Row ---
    col_input, col_button = st.sidebar.columns([4, 1]) # Adjust ratio as needed
    with col_input:
        # REMOVED explicit key="new_path_input_widget"
        new_path_input = st.text_input(
            "PathInput", # Internal key/label
            label_visibility="collapsed",
            placeholder="Enter or Paste File/Folder Path"
        )
    with col_button:
        add_clicked = st.button(
            "Add", # Simpler label
            key="add_path_button", # Keep key for button click detection
            use_container_width=True # Button fills its column
        )

    # Add caption below the input row
    st.sidebar.caption("Browser security limits prevent direct path browsing. Please copy/paste the full path.", unsafe_allow_html=True)

    # Process button click *after* widgets are rendered
    if add_clicked:
        # Use the value returned by text_input in this run (which reflects the input from the *previous* run before the click)
        if new_path_input:
            try:
                resolved_path = str(Path(new_path_input).resolve())
                if Path(resolved_path).exists():
                    if resolved_path not in st.session_state.added_paths:
                        st.session_state.added_paths.add(resolved_path)
                        st.sidebar.success(f"Added: {resolved_path}")
                        # REMOVED attempt to clear st.session_state.new_path_input_widget
                        trigger_context_token_update()
                        st.rerun() # Rerun will clear the input implicitly (widget rendered fresh without a key)
                    else:
                        st.sidebar.info("Path already added.")
                        # Optionally force a rerun even if path exists to clear the input?
                        # st.rerun() # Uncomment if you want input cleared even on duplicate add attempt
                else:
                    st.sidebar.error(f"Path not found: {new_path_input}")
            except Exception as e:
                st.sidebar.error(f"Error resolving path: {e}")
        else:
            st.sidebar.warning("Please enter a path to add.")

    # Managed Paths Expander
    with st.sidebar.expander("Managed Root Paths", expanded=True): # Renamed for clarity
        if not st.session_state.added_paths: st.caption("No root paths added.")
        else:
            paths_to_remove = []
            # Use columns for tighter layout
            for path_str in sorted(list(st.session_state.added_paths)):
                col1, col2 = st.columns([0.85, 0.15])
                col1.code(path_str, language=None)
                if col2.button("🗑️", key=f"remove_root_{hash(path_str)}", help=f"Remove Root Path: {path_str}"):
                    paths_to_remove.append(path_str)
            if paths_to_remove:
                needs_update = False
                for path in paths_to_remove:
                    if path in st.session_state.added_paths:
                        st.session_state.added_paths.discard(path)
                        # Also remove any individual file exclusions that came FROM this root path?
                        removed_from_exclusions = set()
                        root_path_obj = Path(path)
                        for excluded_file in st.session_state.excluded_individual_files:
                            try:
                                if Path(excluded_file).is_relative_to(root_path_obj):
                                    removed_from_exclusions.add(excluded_file)
                            except ValueError: pass # Different drives
                            except Exception as e:
                                logger.warning(f"Error checking relative path for exclusion removal: {e}")

                        if removed_from_exclusions:
                             st.session_state.excluded_individual_files -= removed_from_exclusions
                             logger.info(f"Removed {len(removed_from_exclusions)} individual file exclusions under removed root: {path}")

                        needs_update = True
                if needs_update:
                    trigger_context_token_update()
                    st.rerun()

    # Effective Files Expander - Using Checkboxes
    with st.sidebar.expander("Effective Files (Included/Excluded)", expanded=False): # Renamed for clarity
        details = st.session_state.get('context_files_details', [])
        excluded_files = st.session_state.get("excluded_individual_files", set())
        if not details: st.caption("Add paths to see files.")
        else:
            inc, skip_auto, skip_user, err = 0, 0, 0, 0
            # Use a container with specific height for scrolling if list is long
            with st.container(height=300): # Adjust height as needed
                for abs_path, status, detail in details:
                    abs_path_str = str(abs_path)
                    file_hash = hash(abs_path_str)
                    checkbox_key = f"exclude_cb_{file_hash}"

                    # Determine if the checkbox should be enabled
                    # Disable if skipped automatically (dir, size, type) or error
                    is_disabled = ("Skipped" in status and "Excluded directory" not in detail) or "Error" in status

                    # Determine the initial state of the checkbox
                    # Checked = Included (i.e., NOT in the exclusion set)
                    is_checked = abs_path_str not in excluded_files

                    col_cb, col_info = st.columns([0.1, 0.9], gap="small")

                    with col_cb:
                        # Render the checkbox
                        st.checkbox(
                            "Incl", # Minimal label, hidden
                            value=is_checked,
                            key=checkbox_key,
                            on_change=_handle_file_exclusion_change,
                            args=(abs_path_str,),
                            disabled=is_disabled,
                            label_visibility="collapsed",
                            help=f"Toggle inclusion for: {abs_path_str}" if not is_disabled else f"File status: {status}"
                        )

                    with col_info:
                        # Determine display path (relative preferred)
                        try:
                            display_path = Path(abs_path).name # Default to filename
                            shortest_rel_path = None
                            for root_path_str in st.session_state.added_paths:
                                try:
                                    root_path = Path(root_path_str)
                                    if abs_path.is_relative_to(root_path):
                                        rel_path_str = str(abs_path.relative_to(root_path))
                                        if shortest_rel_path is None or len(rel_path_str) < len(shortest_rel_path):
                                            shortest_rel_path = rel_path_str
                                except ValueError: pass
                                except Exception as e: logger.warning(f"Error calculating relative path '{abs_path}' vs '{root_path_str}': {e}")
                            if shortest_rel_path is not None: display_path = shortest_rel_path
                            if Path(display_path).is_absolute(): display_path = Path(display_path).name
                        except Exception: display_path = abs_path_str

                        # Determine final status text based on checkbox state and original status
                        final_status_text = ""
                        if is_disabled:
                            final_status_text = f"{status} ({detail})" # Show original skip/error reason
                            if "Skipped" in status: err+=1 # Treat errors/auto-skips as errors for count
                            else: err+=1
                        elif not is_checked: # Manually excluded
                            final_status_text = f"Excluded (User) ({detail})"
                            skip_user+=1
                        else: # Included
                            final_status_text = f"Included ({detail})"
                            inc+=1

                        st.markdown(f"<small>**{display_path}**<br>  └ {final_status_text}</small>", unsafe_allow_html=True)

            # Summary Count Below Container
            st.caption(f"**Context:** {inc} Included, {skip_user} Excluded (User), {err} Skipped/Errors")


def display_token_count_and_footer():
    """Displays the token count and app footer."""
    # IN: None; OUT: None # Renders token count, refresh button, footer.
    st.sidebar.markdown("---")
    # Use placeholder for dynamic update if needed, but direct display is simpler
    st.sidebar.caption(st.session_state.get("current_token_count_str", "Token Count: N/A"))
    if st.sidebar.button("Refresh Tokens/Context", key="refresh_tokens_btn", use_container_width=True):
        trigger_context_token_update()
        st.rerun() # Rerun to show updated count and file list immediately

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"<small>Version: {APP_VERSION} | Gemini Chat Pro</small>", unsafe_allow_html=True)