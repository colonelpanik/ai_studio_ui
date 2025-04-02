# app/main.py
# Main Streamlit application script. Orchestrates UI and logic.
import streamlit as st
import logging
from pathlib import Path
import os
import datetime # Ensure datetime is imported for metadata saving

# --- Early Setup ---
try:
    # Assuming logger setup is in app/utils/logger.py based on previous context
    import app.utils.logger
    logger = logging.getLogger(__name__)
    logger.info("Starting Gemini Chat Pro Application...")
except ImportError as e:
    # Fallback basic logging if custom setup fails
    logging.basicConfig(level=logging.INFO)
    logging.error(f"Failed to import logging setup: {e}. Using basic config.")
    logger = logging.getLogger(__name__)
    logger.info("Starting Gemini Chat Pro Application (Basic Logging)...")

PAGE_TITLE = "Gemini Chat Pro"
PAGE_ICON = "✨"
st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")

# --- Import Core Modules ---
try:
    from app.state import manager as state_manager
    from app.data import database as db
    from app.logic import api_client, context_manager, actions
    from app.ui import sidebar, chat_display, parameter_controls # Ensure all UI modules imported
except ImportError as e:
    logger.critical(f"Failed to import core application modules: {e}", exc_info=True)
    st.error(f"Fatal Error: Could not load application components ({e}). Please check installation and file structure.")
    st.stop()

# --- Load Custom CSS ---
def load_css(file_path):
    """Loads CSS file into Streamlit app."""
    try:
        # Assuming static files are relative to the app directory
        css_full_path = Path(__file__).parent / file_path
        with open(css_full_path) as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
        logger.info(f"Loaded CSS from {css_full_path}")
    except FileNotFoundError:
        logger.error(f"CSS file not found at {file_path}")
    except Exception as e:
        logger.error(f"Error loading CSS from {file_path}: {e}", exc_info=True)

# Load the CSS file (adjust path if necessary)
css_file_relative = Path("static") / "style.css"
load_css(css_file_relative)

# --- Initialize Session State ---
try:
    state_manager.initialize_session_state()
    logger.debug("Session state initialized.")
except Exception as e:
     logger.critical(f"Failed to initialize session state: {e}", exc_info=True)
     st.error("Fatal Error: Could not initialize application state.")
     st.stop()

# --- Main App Structure ---
logger.debug("Setting up main layout with columns...")
col_main, col_params = st.columns([3, 1]) # Main chat area and parameters column

# --- Display Sidebar ---
try:
    sidebar.display_sidebar()
    logger.debug("Sidebar displayed.")
except Exception as e:
    logger.error(f"Error rendering sidebar: {e}", exc_info=True)
    st.sidebar.error(f"Error displaying sidebar: {e}")

# --- Main Column Content ---
with col_main:
    st.title(f"{PAGE_ICON} {PAGE_TITLE}")

    # --- Process Button Actions ---
    action_data = st.session_state.get("action_needed")
    if action_data:
        logger.info(f"Processing action: {action_data}")
        action_type = action_data.get("action")
        msg_id = action_data.get("msg_id")
        current_convo_id = st.session_state.get("current_conversation_id")
        messages = st.session_state.get("messages", [])
        st.session_state.action_needed = None # Clear flag immediately

        try:
            if action_type == "delete" and msg_id is not None:
                actions.handle_delete_message(msg_id, current_convo_id)
            elif action_type == "edit" and msg_id is not None:
                actions.handle_edit_message_setup(msg_id, messages)
                # Edit setup doesn't need immediate reload, rerun happens naturally
            elif action_type == "regenerate" and msg_id is not None:
                actions.handle_regenerate(msg_id, current_convo_id, messages)
                # Regenerate sets pending_api_call, main loop handles reload/rerun
            elif action_type == "summarize" and msg_id is not None:
                actions.handle_summarize(msg_id, current_convo_id)
                # Summarize updates state, main loop handles reload/rerun
            else:
                logger.warning(f"Unknown or incomplete action received: {action_data}")

            # Reload state and rerun only if necessary (e.g., after delete)
            # Edit setup modifies state, but rerun happens via UI interaction
            # Regenerate/Summarize rely on the main loop's pending_api_call check or state update
            if action_type == "delete" and current_convo_id:
                 logger.debug(f"Action '{action_type}' completed, reloading state and rerunning.")
                 state_manager.reload_conversation_state(current_convo_id)
                 st.rerun()
            elif action_type == "edit": # No immediate rerun needed after setup
                 st.rerun() # Rerun needed to display the edit interface

        except Exception as e:
            logger.error(f"Error processing action {action_data}: {e}", exc_info=True)
            st.error(f"An error occurred while handling the action: {e}")
            # Attempt to reload state even on error if possible
            if current_convo_id:
                state_manager.reload_conversation_state(current_convo_id)
            st.rerun() # Rerun to show error and potentially refreshed state


    # --- Display Main Chat Area ---
    try:
        chat_display.display_summary() # Display summary if available
        chat_display.display_messages() # Display chat history
        # Display chat input or edit area below messages
        prompt_content, is_edit_save = chat_display.display_chat_input()
        logger.debug("Chat display and input rendered in main column.")
    except Exception as e:
        logger.error(f"Error rendering main chat area: {e}", exc_info=True)
        st.error(f"Error displaying chat content: {e}")
        prompt_content, is_edit_save = None, False # Ensure safe defaults on error

    # --- Handle Chat Input / Edit Save ---
    if prompt_content is not None: # Check if chat_input returned a value (new submission or edit save)
        current_convo_id = st.session_state.get("current_conversation_id")

        if is_edit_save:
            # Handle saving an edited message
            logger.info("Handling edit save...")
            actions.handle_edit_message_save(prompt_content, current_convo_id)
            # handle_edit_message_save handles state clearing
            if current_convo_id:
                state_manager.reload_conversation_state(current_convo_id) # Reload after save/truncate
            st.rerun() # Rerun to show updated history
        else:
            # Handle new prompt submission
            logger.info(f"Handling new user prompt: '{prompt_content[:50]}...'")
            active_conversation_id = current_convo_id
            is_first_message = not active_conversation_id

            if is_first_message:
                # Start a new conversation in the database
                logger.info("First message submitted, starting new conversation.")
                new_conv_id = db.start_new_conversation()
                if new_conv_id:
                    active_conversation_id = new_conv_id
                    st.session_state.current_conversation_id = new_conv_id
                    logger.info(f"New conversation created: {active_conversation_id}")
                    # Save initial metadata (title, generation config, etc.)
                    try:
                        TITLE_MAX_LENGTH = 50
                        new_title = prompt_content[:TITLE_MAX_LENGTH].strip() or f"Chat {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
                        # Get all current config values from state, including grounding settings
                        current_gen_config = { k: st.session_state.get(k, v) for k, v in state_manager.DEFAULT_GEN_CONFIG.items() }
                        db.update_conversation_metadata(
                            conversation_id=active_conversation_id,
                            title=new_title,
                            generation_config=current_gen_config, # Saves grounding toggle & threshold
                            system_instruction=st.session_state.get("system_instruction", ""),
                            added_paths=st.session_state.get("added_paths", set())
                        )
                        # Refresh sidebar list
                        st.session_state.loaded_conversations = db.get_recent_conversations(limit=15)
                        logger.info(f"Saved initial metadata for {active_conversation_id}")
                    except Exception as meta_err:
                        st.error(f"Failed to save conversation metadata: {meta_err}")
                        logger.error(f"Error saving initial metadata: {meta_err}", exc_info=True)
                else:
                    # Handle DB error if conversation couldn't be created
                    st.error("Failed to create new conversation record.")
                    logger.critical("DB error: start_new_conversation failed.")
                    st.stop() # Stop execution if DB fails fundamentally

            # Prepare and Save User Message (for both new and existing conversations)
            if active_conversation_id: # Ensure we have a valid ID
                # Construct full prompt for logging (including context and instructions)
                context_dict = st.session_state.get('current_context_content_dict', {})
                added_paths = st.session_state.get('added_paths', set())
                context_str = context_manager.format_context(context_dict, added_paths)
                sys_instr = st.session_state.get("system_instruction", "").strip()
                instr_prefix = f"--- System Instruction ---\n{sys_instr}\n--- End System Instruction ---\n\n" if sys_instr else ""
                full_prompt_for_log = instr_prefix + context_str + prompt_content # Combine for logging

                logger.debug(f"Saving user message to DB for convo {active_conversation_id}")
                save_user_success = db.save_message(
                    conversation_id=active_conversation_id,
                    role='user',
                    content=prompt_content, # Save only the user's typed content
                    model_used=st.session_state.get('selected_model_name', 'unknown'),
                    context_files=list(context_dict.keys()), # Save list of context files used
                    full_prompt_sent=full_prompt_for_log # Save the fully constructed prompt
                )

                if save_user_success:
                    # Set flag to trigger API call in the next cycle
                    st.session_state.pending_api_call = {
                        "prompt": prompt_content, # Store the user's part of the prompt
                        "convo_id": active_conversation_id,
                        "trigger": "new_message" # Indicate reason for the call
                    }
                    logger.info("User message saved. Pending API call flag set.")
                    # Reload state to include the new user message immediately
                    state_manager.reload_conversation_state(active_conversation_id)
                    st.rerun() # Rerun to process the pending API call
                else:
                    # Handle DB error if message couldn't be saved
                    st.error("Failed to save user message to database. Cannot proceed.")
                    logger.error(f"DB save_message failed for user msg in convo {active_conversation_id}.")
                    # Consider st.stop() if saving is critical
            else:
                # This case should ideally not be reached if logic is correct
                st.error("Cannot save message: No active conversation ID found.")
                logger.error("Attempted to save message but active_conversation_id was None.")


    # --- Handle Pending API Call ---
    pending_call = st.session_state.get("pending_api_call")
    if pending_call:
        logger.info(f"Processing pending API call triggered by: {pending_call.get('trigger', 'unknown')}")
        st.session_state.pending_api_call = None # Clear flag immediately

        # Retrieve necessary data from state and the pending call info
        convo_id = pending_call.get("convo_id")
        prompt_user_part = pending_call.get("prompt") # The user's message part
        model_name = st.session_state.get("selected_model_name")
        model_instance = st.session_state.get("current_model_instance")

        # Validate required data before proceeding
        if not all([convo_id, prompt_user_part is not None, model_name, model_instance]):
            st.error("Cannot send to API: Missing critical state (conversation, prompt, or model).")
            logger.error(f"API call aborted. Missing state: convo={convo_id}, prompt={bool(prompt_user_part)}, model={model_name}, instance={bool(model_instance)}")
        else:
            # Reconstruct the full prompt to send to the API (including context/instructions)
            context_dict = st.session_state.get('current_context_content_dict', {})
            added_paths = st.session_state.get('added_paths', set())
            context_str = context_manager.format_context(context_dict, added_paths)
            sys_instr = st.session_state.get("system_instruction", "").strip()
            instr_prefix = f"--- System Instruction ---\n{sys_instr}\n--- End System Instruction ---\n\n" if sys_instr else ""
            full_prompt_to_send = instr_prefix + context_str + prompt_user_part

            # Prevent sending empty messages (e.g., if only context/instruction exists)
            if not full_prompt_to_send.strip():
                st.error("Cannot send an empty message to the AI.")
                logger.error("API call aborted: Constructed prompt is empty.")
            else:
                # Prepare Generation Config Dictionary and get grounding settings
                gen_config_dict = None
                enable_grounding_flag = st.session_state.get("enable_grounding", False)
                grounding_threshold_val = st.session_state.get("grounding_threshold", 0.0)
                try:
                    # Parse stop sequences from text area
                    stop_sequences = [seq.strip() for seq in st.session_state.get("stop_sequences_str", "").splitlines() if seq.strip()]
                    # Ensure max tokens slider value respects model limit
                    state_manager.clamp_max_tokens()
                    # Build the config dictionary
                    gen_config_dict = {
                        "temperature": st.session_state.temperature,
                        "top_p": st.session_state.top_p,
                        "top_k": st.session_state.top_k,
                        "max_output_tokens": st.session_state.max_output_tokens,
                        # Conditionally add stop sequences if any are defined
                        **({"stop_sequences": stop_sequences} if stop_sequences else {})
                    }
                    # Add response MIME type if JSON mode is enabled
                    if st.session_state.get("json_mode", False):
                        gen_config_dict["response_mime_type"] = "application/json"
                    logger.debug(f"Generation config: {gen_config_dict}")
                except Exception as e:
                    st.error(f"Error creating generation config: {e}")
                    logger.error(f"Failed to build generation config dict: {e}", exc_info=True)

                # Proceed with API call only if config was built successfully
                if gen_config_dict:
                    # Display spinner and placeholder in the chat area
                    with st.chat_message("assistant"):
                        status_placeholder = st.status(f"Asking {Path(model_name).name}...", expanded=False)
                        message_placeholder = st.empty()
                        message_placeholder.markdown("...") # Initial thinking indicator

                        try:
                            status_placeholder.update(label="Generating response...", state="running")
                            logger.info(f"Sending prompt to model {model_name}. Length: {len(full_prompt_to_send)}")
                            # Get correctly formatted API history
                            api_history = st.session_state.get("gemini_history", [])

                            # Call the API client function, passing grounding settings
                            response_text, error_msg = api_client.generate_text(
                                model_name=model_name,
                                prompt=full_prompt_to_send,
                                generation_config_dict=gen_config_dict,
                                enable_grounding=enable_grounding_flag,      # Pass grounding toggle state
                                grounding_threshold=grounding_threshold_val, # Pass grounding threshold value
                                history=api_history                          # Pass chat history
                            )

                            # Handle API response (error or success)
                            if error_msg:
                                st.error(f"API Error: {error_msg}")
                                logger.error(f"API call failed: {error_msg}")
                                message_placeholder.markdown(f"❌ Error: {error_msg}")
                                status_placeholder.update(label="API Error", state="error", expanded=True)
                                # Save error message as assistant response for context
                                db.save_message(conversation_id=convo_id, role='assistant', content=f"Error: {error_msg}", model_used=model_name)
                            elif response_text is not None:
                                logger.info(f"API call successful. Response length: {len(response_text)}")
                                message_placeholder.markdown(response_text) # Display response (includes citations if grounding used)
                                status_placeholder.update(label="Response received", state="complete")
                                # Save successful response to DB
                                save_assist_success = db.save_message(
                                    conversation_id=convo_id,
                                    role='assistant',
                                    content=response_text,
                                    model_used=model_name
                                )
                                if not save_assist_success:
                                    st.warning("Failed to save assistant response to database.")
                                    logger.error(f"DB save_message failed for assistant msg in convo {convo_id}")
                            else:
                                # Handle unexpected case where no text and no error were returned
                                 st.error("API Error: Received no response text and no error message.")
                                 logger.error("API call failed: No text and no error returned.")
                                 message_placeholder.markdown("❌ Error: Empty response from API.")
                                 status_placeholder.update(label="API Error", state="error", expanded=True)

                            # Reload state and rerun regardless of success/error to show new message/error
                            state_manager.reload_conversation_state(convo_id)
                            st.rerun()

                        except Exception as e:
                             # Catch-all for unexpected errors during the API call process
                             st.error(f"An unexpected error occurred during API call: {e}")
                             logger.critical(f"Critical error during API processing: {e}", exc_info=True)
                             message_placeholder.markdown(f"❌ Critical Error: {e}")
                             status_placeholder.update(label="Critical Error", state="error", expanded=True)
                             # Attempt to reload state even on critical error
                             if convo_id: state_manager.reload_conversation_state(convo_id)
                             st.rerun() # Rerun to show the critical error message

# --- Parameter Column Content ---
# Display the parameter controls in the right-hand column
with col_params:
    try:
        parameter_controls.display_parameter_controls()
        logger.debug("Parameter controls rendered in param column.")
    except Exception as e:
        logger.error(f"Error rendering parameter controls: {e}", exc_info=True)
        st.error(f"Error displaying parameters: {e}")


logger.debug("Main script execution finished for this run.")