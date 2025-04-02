# app/main.py
# Main Streamlit application script. Orchestrates UI and logic.
# Regenerated to place parameters back in the right column.
import streamlit as st
import logging
from pathlib import Path
import os
import datetime # Ensure datetime is imported for metadata saving

# --- Early Setup: Logging and Page Config ---
try:
    import app.utils.logger
    logger = logging.getLogger(__name__)
    logger.info("Starting Gemini Chat Pro Application...")
except ImportError as e:
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
    try:
        css_full_path = Path(__file__).parent / file_path
        with open(css_full_path) as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
        logger.info(f"Loaded CSS from {css_full_path}")
    except FileNotFoundError:
        logger.error(f"CSS file not found at {css_full_path}")
    except Exception as e:
        logger.error(f"Error loading CSS from {css_full_path}: {e}", exc_info=True)

# Ensure your style.css has fixes for chat input overlap (no position:fixed)
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
# Reintroduce columns for main chat and parameters
col_main, col_params = st.columns([3, 1]) # Original column layout

# --- Display Sidebar ---
# Sidebar display remains the same
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
        st.session_state.action_needed = None # Clear flag
        try:
            if action_type == "delete" and msg_id is not None:
                actions.handle_delete_message(msg_id, current_convo_id)
            elif action_type == "edit" and msg_id is not None:
                actions.handle_edit_message_setup(msg_id, messages)
            elif action_type == "regenerate" and msg_id is not None:
                actions.handle_regenerate(msg_id, current_convo_id, messages)
            elif action_type == "summarize" and msg_id is not None:
                actions.handle_summarize(msg_id, current_convo_id)
            else:
                logger.warning(f"Unknown or incomplete action received: {action_data}")

            if action_type in ["delete", "regenerate", "edit", "summarize"]:
                 logger.debug(f"Action '{action_type}' completed, reloading state if necessary and rerunning.")
                 state_manager.reload_conversation_state(current_convo_id)
                 st.rerun()
        except Exception as e:
            logger.error(f"Error processing action {action_data}: {e}", exc_info=True)
            st.error(f"An error occurred while handling the action: {e}")
            if current_convo_id: # Avoid error if convo ID is None
                state_manager.reload_conversation_state(current_convo_id)
            st.rerun()

    # --- Display Main Chat Area ---
    try:
        chat_display.display_summary()
        chat_display.display_messages()
        # Chat input will render here, below messages in the main column flow
        prompt_content, is_edit_save = chat_display.display_chat_input()
        logger.debug("Chat display and input rendered in main column.")
    except Exception as e:
        logger.error(f"Error rendering main chat area: {e}", exc_info=True)
        st.error(f"Error displaying chat content: {e}")
        prompt_content, is_edit_save = None, False

    # --- Handle Chat Input / Edit Save ---
    # This logic stays the same, but prompt_content comes from chat_input in col_main
    if prompt_content is not None:
        current_convo_id = st.session_state.get("current_conversation_id")
        if is_edit_save:
            logger.info("Handling edit save...")
            actions.handle_edit_message_save(prompt_content, current_convo_id)
            if current_convo_id:
                state_manager.reload_conversation_state(current_convo_id)
            st.rerun()
        else:
            # Handle new prompt submission
            logger.info(f"Handling new user prompt: '{prompt_content[:50]}...'")
            active_conversation_id = current_convo_id
            is_first_message = not active_conversation_id

            if is_first_message:
                logger.info("First message submitted, starting new conversation.")
                new_conv_id = db.start_new_conversation()
                if new_conv_id:
                    active_conversation_id = new_conv_id
                    st.session_state.current_conversation_id = new_conv_id
                    logger.info(f"New conversation created: {active_conversation_id}")
                    try:
                        TITLE_MAX_LENGTH = 50
                        new_title = prompt_content[:TITLE_MAX_LENGTH].strip() or f"Chat {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
                        current_gen_config = { k: st.session_state[k] for k in state_manager.DEFAULT_GEN_CONFIG if k in st.session_state }
                        db.update_conversation_metadata(
                            conversation_id=active_conversation_id, title=new_title,
                            generation_config=current_gen_config,
                            system_instruction=st.session_state.get("system_instruction", ""),
                            added_paths=st.session_state.get("added_paths", set())
                        )
                        st.session_state.loaded_conversations = db.get_recent_conversations(limit=15)
                        logger.info(f"Saved initial metadata for {active_conversation_id}")
                    except Exception as meta_err:
                        st.error(f"Failed to save conversation metadata: {meta_err}")
                        logger.error(f"Error saving initial metadata: {meta_err}", exc_info=True)
                else:
                    st.error("Failed to create new conversation record.")
                    logger.critical("DB error: start_new_conversation failed.")
                    st.stop()
            # else: # Existing conversation - no need for 'else', active_conversation_id is already set

            # Prepare and Save User Message (applies to both new and existing convos)
            if active_conversation_id: # Ensure we have an ID
                context_dict = st.session_state.get('current_context_content_dict', {})
                added_paths = st.session_state.get('added_paths', set())
                context_str = context_manager.format_context(context_dict, added_paths)
                sys_instr = st.session_state.get("system_instruction", "").strip()
                instr_prefix = f"--- System Instruction ---\n{sys_instr}\n--- End System Instruction ---\n\n" if sys_instr else ""
                full_prompt_for_log = instr_prefix + context_str + prompt_content

                logger.debug(f"Saving user message to DB for convo {active_conversation_id}")
                save_user_success = db.save_message(
                    conversation_id=active_conversation_id, role='user', content=prompt_content,
                    model_used=st.session_state.get('selected_model_name', 'unknown'),
                    context_files=list(context_dict.keys()),
                    full_prompt_sent=full_prompt_for_log
                )

                if save_user_success:
                    st.session_state.pending_api_call = {
                        "prompt": prompt_content,
                        "convo_id": active_conversation_id,
                        "trigger": "new_message"
                    }
                    logger.info("User message saved. Pending API call flag set.")
                    state_manager.reload_conversation_state(active_conversation_id)
                    st.rerun()
                else:
                    st.error("Failed to save user message to database. Cannot proceed.")
                    logger.error(f"DB save_message failed for user msg in convo {active_conversation_id}.")
                    # Consider st.stop() here if saving is critical
            else:
                # This case should ideally not be reached if logic is correct
                st.error("Cannot save message: No active conversation ID found.")
                logger.error("Attempted to save message but active_conversation_id was None.")


    # --- Handle Pending API Call ---
    pending_call = st.session_state.get("pending_api_call")
    if pending_call:
        logger.info(f"Processing pending API call triggered by: {pending_call.get('trigger', 'unknown')}")
        st.session_state.pending_api_call = None # Clear flag

        convo_id = pending_call.get("convo_id")
        prompt_user_part = pending_call.get("prompt")
        model_name = st.session_state.get("selected_model_name")
        model_instance = st.session_state.get("current_model_instance")

        if not all([convo_id, prompt_user_part is not None, model_name, model_instance]):
            st.error("Cannot send to API: Missing critical state (conversation, prompt, or model).")
            logger.error(f"API call aborted. Missing state: convo={convo_id}, prompt={bool(prompt_user_part)}, model={model_name}, instance={bool(model_instance)}")
        else:
            # Reconstruct Full Prompt
            context_dict = st.session_state.get('current_context_content_dict', {})
            added_paths = st.session_state.get('added_paths', set())
            context_str = context_manager.format_context(context_dict, added_paths)
            sys_instr = st.session_state.get("system_instruction", "").strip()
            instr_prefix = f"--- System Instruction ---\n{sys_instr}\n--- End System Instruction ---\n\n" if sys_instr else ""
            full_prompt_to_send = instr_prefix + context_str + prompt_user_part

            if not full_prompt_to_send.strip():
                st.error("Cannot send an empty message to the AI.")
                logger.error("API call aborted: Constructed prompt is empty.")
            else:
                # Prepare Generation Config
                gen_config_dict = None
                try:
                    stop_sequences = [seq.strip() for seq in st.session_state.get("stop_sequences_str", "").splitlines() if seq.strip()]
                    state_manager.clamp_max_tokens()
                    gen_config_dict = {
                        "temperature": st.session_state.temperature, "top_p": st.session_state.top_p,
                        "top_k": st.session_state.top_k, "max_output_tokens": st.session_state.max_output_tokens,
                        **({"stop_sequences": stop_sequences} if stop_sequences else {})
                    }
                    if st.session_state.get("json_mode", False):
                        gen_config_dict["response_mime_type"] = "application/json"
                    logger.debug(f"Generation config: {gen_config_dict}")
                except Exception as e:
                    st.error(f"Error creating generation config: {e}")
                    logger.error(f"Failed to build generation config dict: {e}", exc_info=True)

                # Call API and Handle Response (inside col_main)
                if gen_config_dict:
                    # Display spinner/response in the main chat area column
                    with st.chat_message("assistant"):
                        status_placeholder = st.status(f"Asking {Path(model_name).name}...", expanded=False)
                        message_placeholder = st.empty()
                        message_placeholder.markdown("...") # Initial placeholder
                        try:
                            status_placeholder.update(label="Generating response...", state="running")
                            logger.info(f"Sending prompt to model {model_name}. Length: {len(full_prompt_to_send)}")
                            api_history = st.session_state.get("gemini_history", [])

                            response_text, error_msg = api_client.generate_text(
                                model_name=model_name, prompt=full_prompt_to_send,
                                generation_config_dict=gen_config_dict, history=api_history
                            )

                            if error_msg:
                                st.error(f"API Error: {error_msg}") # Show error in main column
                                logger.error(f"API call failed: {error_msg}")
                                message_placeholder.markdown(f"❌ Error: {error_msg}")
                                status_placeholder.update(label="API Error", state="error", expanded=True)
                                db.save_message(conversation_id=convo_id, role='assistant', content=f"Error: {error_msg}")
                            elif response_text is not None:
                                logger.info(f"API call successful. Response length: {len(response_text)}")
                                message_placeholder.markdown(response_text)
                                status_placeholder.update(label="Response received", state="complete")
                                save_assist_success = db.save_message(
                                    conversation_id=convo_id, role='assistant', content=response_text, model_used=model_name
                                )
                                if not save_assist_success:
                                    st.warning("Failed to save assistant response to database.")
                                    logger.error(f"DB save_message failed for assistant msg in convo {convo_id}")
                            else:
                                 st.error("API Error: Received no response text and no error message.")
                                 logger.error("API call failed: No text and no error returned.")
                                 message_placeholder.markdown("❌ Error: Empty response from API.")
                                 status_placeholder.update(label="API Error", state="error", expanded=True)

                            state_manager.reload_conversation_state(convo_id)
                            st.rerun()
                        except Exception as e:
                             st.error(f"An unexpected error occurred during API call: {e}")
                             logger.critical(f"Critical error during API processing: {e}", exc_info=True)
                             message_placeholder.markdown(f"❌ Critical Error: {e}")
                             status_placeholder.update(label="Critical Error", state="error", expanded=True)
                             state_manager.reload_conversation_state(convo_id)
                             st.rerun()

# --- Parameter Column Content ---
with col_params:
    # Place the parameter controls here, called ONLY ONCE
    try:
        parameter_controls.display_parameter_controls()
        logger.debug("Parameter controls rendered in param column.")
    except Exception as e:
        logger.error(f"Error rendering parameter controls: {e}", exc_info=True)
        st.error(f"Error displaying parameters: {e}")


logger.debug("Main script execution finished for this run.")