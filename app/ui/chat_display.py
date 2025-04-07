### app/ui/chat_display.py ###
# app/ui/chat_display.py
# Renders the main chat area including messages with hover buttons.
import streamlit as st
import logging
import datetime # Added for timestamp check

# Import state manager if needed for other functions, but not strictly for display_messages
# from app.state import manager as state_manager

logger = logging.getLogger(__name__)


def display_messages():
    """Displays chat messages with hover controls using injected HTML and CSS."""
    messages_to_display = st.session_state.get("messages", [])
    logger.info(f"Displaying messages. Message count RECEIVED: {len(messages_to_display)}")

    current_convo_id = st.session_state.get("current_conversation_id")

    if not current_convo_id:
        st.info("Start a new chat or load a previous one from the sidebar.")
        return

    if not messages_to_display:
        st.caption("Chat history is empty.")
        # Optionally display a welcome message or instructions here
        # st.markdown("Welcome! Ask me anything.")

    logger.debug(f"Displaying {len(messages_to_display)} messages for conversation {current_convo_id}")

    # --- Message Loop ---
    for i, message in enumerate(messages_to_display):
        msg_id = message.get("message_id")
        msg_role = message.get("role")
        msg_content = message.get("content")
        msg_timestamp = message.get("timestamp") # Get timestamp for validation

        # Basic validation including timestamp type check
        if not all([
            msg_id is not None, # This check will now use the correct ID
            msg_role,
            msg_content is not None,
            isinstance(msg_timestamp, datetime.datetime) # Ensure timestamp is valid
        ]):
            logger.error(
                f"Skipping invalid message at index {i} (Extracted ID: {msg_id}, "
                f"Role: {msg_role}, TS Type: {type(msg_timestamp)}): {message}"
            )
            continue

        # --- Inject HTML Wrapper for CSS Targeting ---
        container_key = f"msg_block_{msg_id}"
        st.markdown(f'<div class="chat-message-block" id="{container_key}">', unsafe_allow_html=True)

        # Use columns: One for the message bubble, one conceptually holds the buttons (styled by CSS later)
        msg_cols = st.columns([0.95, 0.05]) # Adjust ratio if needed

        # Column 1: Display the actual chat message
        with msg_cols[0]:
            with st.chat_message(msg_role):
                 st.markdown(msg_content, unsafe_allow_html=True)

        # Column 2: Define the buttons that will be positioned by CSS
        with msg_cols[1]:
            # Inject a wrapper div for the buttons targeted by CSS
            st.markdown('<div class="message-action-buttons">', unsafe_allow_html=True)
            # Use a container to group buttons horizontally
            with st.container():
                # --- Define Buttons (Using Single Glyphs) ---
                is_summary_msg = msg_role == 'assistant' and msg_content.startswith("**Summary of conversation")

                # Summarize Before Button
                if not is_summary_msg:
                    if st.button("🔼", key=f"sum_before_{msg_id}", help="Summarize Before", use_container_width=True): # Changed Icon
                        logger.info(f"Summarize Before button clicked for msg {msg_id}")
                        st.session_state.action_needed = {"action": "summarize_before", "msg_id": msg_id}
                        st.rerun()

                # Summarize After Button
                if not is_summary_msg:
                    if st.button("🔽", key=f"sum_after_{msg_id}", help="Summarize After", use_container_width=True): # Changed Icon
                        logger.info(f"Summarize After button clicked for msg {msg_id}")
                        st.session_state.action_needed = {"action": "summarize_after", "msg_id": msg_id}
                        st.rerun()

                # Delete Button
                if not is_summary_msg:
                    if st.button("🗑️", key=f"del_{msg_id}", help="Delete message", use_container_width=True):
                        logger.info(f"Delete button clicked for msg {msg_id}")
                        st.session_state.action_needed = {"action": "delete", "msg_id": msg_id}
                        st.rerun()

                # Edit Button (User only)
                if msg_role == "user" and not is_summary_msg:
                    if st.button("✏️", key=f"edit_{msg_id}", help="Edit message", use_container_width=True):
                         logger.info(f"Edit button clicked for msg {msg_id}")
                         st.session_state.action_needed = {"action": "edit", "msg_id": msg_id}
                         st.rerun()

                # Regenerate Button (Assistant only)
                elif msg_role == "assistant" and not is_summary_msg:
                    if st.button("🔄", key=f"regen_{msg_id}", help="Regenerate response", use_container_width=True):
                         logger.info(f"Regenerate button clicked for msg {msg_id}")
                         st.session_state.action_needed = {"action": "regenerate", "msg_id": msg_id}
                         st.rerun()

            # Close the injected button wrapper div
            st.markdown('</div>', unsafe_allow_html=True)

        # Close the injected main message block wrapper div
        st.markdown('</div>', unsafe_allow_html=True)
    # --- End of Message Loop ---


def display_chat_input():
    """Displays the chat input area, handling edit mode with styled container."""
    prompt_placeholder = "Ask a question or type your message..."
    input_key="chat_input_main"
    current_editing_id = st.session_state.get("editing_message_id")
    # Disable input if model isn't ready
    model_ready = st.session_state.get("current_model_instance") is not None
    input_disabled = not model_ready # Don't disable main input during edit anymore

    if current_editing_id:
        # --- Edit Mode ---
        # Wrap edit elements in a div for styling (fixed positioning via CSS)
        st.markdown('<div class="edit-input-container">', unsafe_allow_html=True)

        st.warning(f"Editing message ID: {current_editing_id}. Saving will delete subsequent history and resubmit.", icon="⚠️")

        edited_content = st.text_area(
            "Edit message:", # Label is hidden by label_visibility
            value=st.session_state.get("editing_message_content", ""),
            key="edit_text_area",
            height=100,
            label_visibility="collapsed" # Hide the actual label visually
        )
        col1, col2 = st.columns([1,1])
        with col1:
            # Disable save if content is empty? Optional.
            save_disabled = not bool(edited_content.strip())
            save_clicked = st.button(
                "Save Edit & Resubmit",
                key="save_edit_btn",
                use_container_width=True,
                type="primary",
                disabled=save_disabled
            )
        with col2:
            cancel_clicked = st.button(
                "Cancel Edit",
                key="cancel_edit_btn",
                use_container_width=True
            )

        st.markdown('</div>', unsafe_allow_html=True) # Close the wrapper div

        # Process button clicks *after* rendering them
        if save_clicked:
            logger.info("Save Edit button clicked.")
            return edited_content, True # Return content and edit flag
        if cancel_clicked:
             logger.info("Cancel Edit button clicked.")
             st.session_state.editing_message_id = None
             st.session_state.editing_message_content = ""
             st.rerun() # Rerun to switch back to chat_input
        # If neither button was clicked (or save disabled and clicked), don't proceed
        # Return None here to allow regular chat input to show below
        return None, False
    # --- Regular Chat Input ---
    # Always display the regular chat input, even during edit mode
    # Fixed positioning will be handled by CSS
    prompt = st.chat_input(
        prompt_placeholder,
        key=input_key,
        disabled=input_disabled or current_editing_id is not None, # Disable if model not ready OR if editing
    )
    # st.chat_input returns the submitted text directly or None
    # If editing, we ignore this prompt return value
    if current_editing_id:
        return None, False # Don't process regular input if edit was active
    else:
        return prompt, False # Return prompt content and False for edit flag