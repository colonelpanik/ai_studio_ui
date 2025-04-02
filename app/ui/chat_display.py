# app/ui/chat_display.py
# Renders the main chat area including messages with hover buttons.
import streamlit as st
import logging
from app.state import manager as state_manager # Use state manager

logger = logging.getLogger(__name__)


def display_messages():
    """Displays chat messages with hover controls using injected HTML and CSS."""
    # IN: None; OUT: None # Renders chat messages from state with CSS hover buttons.

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
        msg_id = message.get("id")
        msg_role = message.get("role")
        msg_content = message.get("content")

        # Basic validation
        if not all([msg_id is not None, msg_role, msg_content is not None]):
            logger.error(f"Skipping invalid message at index {i}: {message}")
            continue

        # --- Inject HTML Wrapper for CSS Targeting ---
        # This container helps group the message and its hover buttons for CSS rules
        # We use markdown with unsafe_allow_html=True to inject divs with specific classes
        container_key = f"msg_block_{msg_id}"
        st.markdown(f'<div class="chat-message-block" id="{container_key}">', unsafe_allow_html=True)

        # Use columns: One for the message bubble, one conceptually holds the buttons (styled by CSS later)
        msg_cols = st.columns([0.95, 0.05]) # Adjust ratio if needed (second column is mostly placeholder)

        # Column 1: Display the actual chat message
        with msg_cols[0]:
            with st.chat_message(msg_role):
                 st.markdown(msg_content, unsafe_allow_html=False) # Render actual content safely

        # Column 2: Define the buttons that will be positioned by CSS
        with msg_cols[1]:
            # Inject a wrapper div for the buttons targeted by CSS
            st.markdown('<div class="message-action-buttons">', unsafe_allow_html=True)
            # Use a container to group buttons vertically if needed by CSS flex direction
            with st.container():
                # --- Define Buttons ---
                # Common delete button
                if st.button("🗑️", key=f"del_{msg_id}", help="Delete message", use_container_width=True):
                    logger.info(f"Delete button clicked for msg {msg_id}")
                    st.session_state.action_needed = {"action": "delete", "msg_id": msg_id}
                    st.rerun()

                # Common summarize button
                if st.button("📄", key=f"sum_{msg_id}", help="Summarize after", use_container_width=True):
                    logger.info(f"Summarize button clicked for msg {msg_id}")
                    st.session_state.action_needed = {"action": "summarize", "msg_id": msg_id}
                    st.rerun()

                # Role-specific buttons
                if msg_role == "user":
                    if st.button("✏️", key=f"edit_{msg_id}", help="Edit message", use_container_width=True):
                         logger.info(f"Edit button clicked for msg {msg_id}")
                         st.session_state.action_needed = {"action": "edit", "msg_id": msg_id}
                         st.rerun()
                elif msg_role == "assistant":
                    if st.button("🔄", key=f"regen_{msg_id}", help="Regenerate response", use_container_width=True):
                         logger.info(f"Regenerate button clicked for msg {msg_id}")
                         st.session_state.action_needed = {"action": "regenerate", "msg_id": msg_id}
                         st.rerun()
            # Close the injected button wrapper div
            st.markdown('</div>', unsafe_allow_html=True)

        # Close the injected main message block wrapper div
        st.markdown('</div>', unsafe_allow_html=True)
    # --- End of Message Loop ---

def display_summary():
    """Displays the generated summary if available in state."""
    # IN: None; OUT: None # Renders summary from state in an expander.
    if st.session_state.get("clear_summary"):
        st.session_state.summary_result = None
        st.session_state.clear_summary = False # Reset flag

    summary_data = st.session_state.get("summary_result")
    if summary_data:
        ts = summary_data.get('timestamp', 'N/A')
        summary = summary_data.get('summary', 'Error: Summary content missing.')
        expander_title = f"Summary of History After Message ({str(ts)[:19]})"
        expander_key = f"summary_expander_{ts}" # Unique key
        with st.expander(expander_title, expanded=True, key=expander_key):
            st.markdown(summary)
        # Keep summary in state until explicitly cleared or overwritten


def display_chat_input():
    """Displays the chat input area, handling edit mode with styled container."""
    # IN: None; OUT: (prompt_content: str | None, is_edit_save: bool) # Renders chat input.
    prompt_placeholder = "Ask a question or type your message..."
    input_key="chat_input_main"
    current_editing_id = st.session_state.get("editing_message_id")
    # Disable input if model isn't ready
    # Ensure required state keys exist before accessing
    model_ready = st.session_state.get("current_model_instance") is not None
    input_disabled = not model_ready

    if current_editing_id:
        # Wrap edit elements in a div for styling
        st.markdown('<div class="edit-input-container">', unsafe_allow_html=True)

        st.warning(f"Editing message ID: {current_editing_id}. Saving will delete subsequent history.", icon="⚠️")

        edited_content = st.text_area(
            "Edit message:", # Label is hidden by label_visibility
            value=st.session_state.get("editing_message_content", ""),
            key="edit_text_area",
            height=100,
            label_visibility="collapsed" # Hide the actual label visually
        )
        col1, col2 = st.columns([1,1])
        with col1:
            save_clicked = st.button("Save Edit", key="save_edit_btn", use_container_width=True, type="primary")
        with col2:
            cancel_clicked = st.button("Cancel Edit", key="cancel_edit_btn", use_container_width=True)

        st.markdown('</div>', unsafe_allow_html=True) # Close the wrapper div

        # Process button clicks *after* rendering them
        if save_clicked:
            return edited_content, True # Return content and edit flag
        if cancel_clicked:
             st.session_state.editing_message_id = None
             st.session_state.editing_message_content = ""
             st.rerun() # Rerun to switch back to chat_input
        return None, False # Don't process if no button clicked yet
    else:
        # Use st.chat_input for regular input
        prompt = st.chat_input(
            prompt_placeholder,
            key=input_key,
            disabled=input_disabled,
            # on_submit= # Optional: Add callback if needed
        )
        # st.chat_input returns the submitted text directly or None
        return prompt, False # Return prompt content and False for edit flag

