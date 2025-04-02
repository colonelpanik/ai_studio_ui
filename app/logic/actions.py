# app/logic/actions.py
# Handles actions triggered by chat message buttons.
import streamlit as st
import logging
from app.data import database as db
from app.logic import api_client
from app.logic import context_manager

logger = logging.getLogger(__name__)

def handle_delete_message(msg_id: int, current_convo_id: str | None):
    """Handles the 'delete' action."""
    # IN: msg_id, current_convo_id; OUT: None # Deletes message, reloads state.
    if not current_convo_id:
        logger.error("Delete action failed: No current conversation ID.")
        st.error("Cannot delete message: No active conversation.")
        return

    logger.warning(f"Executing delete for message ID: {msg_id}")
    success, db_msg = db.delete_message_by_id(msg_id)
    if success:
        st.toast(db_msg, icon="✅")
        st.session_state.clear_summary = True # Signal to clear summary display
    else:
        st.error(f"Failed to delete message: {db_msg}")
        logger.error(f"Failed DB delete for message ID {msg_id}: {db_msg}")
    # Reload state in main loop after action returns

def handle_edit_message_setup(msg_id: int, messages: list):
    """Sets up the state for editing a user message."""
    # IN: msg_id, messages; OUT: None # Sets state vars for editing message.
    target_message_data = next((m for m in messages if m.get("id") == msg_id), None)
    if target_message_data and target_message_data.get("role") == "user":
        logger.info(f"Setting up edit state for message ID: {msg_id}")
        st.session_state.editing_message_id = msg_id
        st.session_state.editing_message_content = target_message_data['content']
        st.session_state.clear_summary = True # Clear summary when edit starts
        # Rerun will happen in main loop naturally
    elif not target_message_data:
        logger.error(f"Could not find message data for edit action on ID {msg_id}")
        st.error("Error finding message to edit.")
    else: # Role wasn't user
        logger.warning(f"Attempted to edit non-user message ID: {msg_id}")
        st.warning("Only user messages can be edited.")

def handle_edit_message_save(edited_content: str, current_convo_id: str | None):
    """Handles saving an edited message and truncating history."""
    # IN: edited_content, current_convo_id; OUT: None # Saves edit, deletes subsequent msgs.
    editing_id = st.session_state.get("editing_message_id")
    if not editing_id or not current_convo_id:
        logger.error("Edit save failed: Missing editing ID or conversation ID.")
        st.error("Error saving edit: State is inconsistent.")
        st.session_state.editing_message_id = None # Clear inconsistent state
        return

    logger.info(f"Saving edit for message ID: {editing_id}")
    success_update, db_msg_update = db.update_message_content(editing_id, edited_content)

    if success_update:
        edited_msg_timestamp = None
        try: # Fetch timestamp *after* potential update
            # Use include_ids_timestamps=True to get the timestamp string
            current_msgs_for_edit = db.get_conversation_messages(current_convo_id, include_ids_timestamps=True)
            target_message = next((m for m in current_msgs_for_edit if m.get("id") == editing_id), None)
            if target_message:
                edited_msg_timestamp = target_message.get("timestamp")
                logger.info(f"Found timestamp '{edited_msg_timestamp}' for edited message {editing_id}.")
            else:
                 logger.error(f"Could not find edited message {editing_id} after update to get timestamp.")
                 st.error("Failed to find timestamp for edited message after update.")

        except Exception as e:
             logger.error(f"Error fetching timestamp after edit for msg {editing_id}: {e}", exc_info=True)
             st.error(f"Error fetching timestamp after edit: {e}")

        if edited_msg_timestamp:
            # Ensure timestamp is a string suitable for DB query
            ts_str = str(edited_msg_timestamp)
            logger.info(f"Deleting messages after timestamp: {ts_str}")
            success_del, db_msg_del = db.delete_messages_after_timestamp(current_convo_id, ts_str)
            if success_del:
                st.toast("Edit saved and subsequent history removed.", icon="✅")
                logger.info(f"Edit {editing_id} complete, history truncated after {ts_str}.")
            else:
                st.error(f"Failed to delete history after edit: {db_msg_del}")
                logger.error(f"Edit failed: DB delete_after failed for {ts_str}: {db_msg_del}")
        else:
             st.warning("Edit saved, but could not confirm timestamp. History might not be truncated correctly.")

        st.session_state.editing_message_id = None
        st.session_state.editing_message_content = ""
        # Reload state in main loop
    else:
        st.error(f"Failed to save edit: {db_msg_update}")
        logger.error(f"Edit save failed: DB update failed for {editing_id}: {db_msg_update}")
        st.session_state.editing_message_id = None # Clear state on failure

def handle_regenerate(target_assistant_msg_id: int, current_convo_id: str | None, messages: list):
    """Handles regenerating a response based on the preceding user message."""
    # IN: target_assistant_msg_id, current_convo_id, messages; OUT: None # Deletes msgs, sets pending API call.
    if not current_convo_id:
        logger.error("Regenerate failed: No current conversation ID.")
        st.error("Cannot regenerate: No active conversation.")
        return

    preceding_user_msg = None
    target_msg_index = -1
    for idx, msg in enumerate(messages):
        if msg.get("id") == target_assistant_msg_id:
            target_msg_index = idx
            break

    if target_msg_index > 0:
        if messages[target_msg_index - 1].get("role") == "user":
            preceding_user_msg = messages[target_msg_index - 1]
            logger.debug(f"Found preceding user message (ID: {preceding_user_msg.get('id')}) for regeneration.")

    if preceding_user_msg and preceding_user_msg.get("timestamp"):
        ts_str = str(preceding_user_msg["timestamp"]) # Use timestamp of preceding user msg
        logger.warning(f"Executing regenerate based on preceding user message (TS: {ts_str})")
        success_del, db_msg_del = db.delete_messages_after_timestamp(current_convo_id, ts_str)

        if success_del:
            st.toast(db_msg_del, icon="✅")
            logger.info(f"Deleted messages after {ts_str} for regeneration.")
            # Set flag/state to trigger API call with the user prompt
            st.session_state.pending_api_call = {
                "prompt": preceding_user_msg["content"], # The preceding user prompt
                "convo_id": current_convo_id,
                "trigger": "regenerate" # Add trigger info
            }
            st.session_state.clear_summary = True # Clear summary display
            logger.info("Set pending_api_call flag for regeneration.")
            # State reload and rerun happen in main loop
        else:
            st.error(f"Failed to delete messages for regenerate: {db_msg_del}")
            logger.error(f"Regenerate failed: DB delete_after failed for {ts_str}: {db_msg_del}")
    else:
        st.error("Could not find preceding user message to regenerate from.")
        logger.error(f"Regenerate failed: No valid preceding user msg for assistant msg {target_assistant_msg_id}")


def handle_summarize(target_msg_id: int, current_convo_id: str | None):
    """Handles summarizing messages after the target message."""
    # IN: target_msg_id, current_convo_id; OUT: None # Fetches msgs, calls summary API, stores result.
    if not current_convo_id:
        logger.error("Summarize failed: No current conversation ID.")
        st.error("Cannot summarize: No active conversation.")
        return

    target_message_data = db.get_conversation_messages(current_convo_id, include_ids_timestamps=True)
    target_message = next((m for m in target_message_data if m.get("id") == target_msg_id), None)

    if not target_message or not target_message.get("timestamp"):
        logger.error(f"Could not find message data or timestamp for summarize action on ID {target_msg_id}")
        st.error("Error finding message for summarization.")
        return

    target_timestamp = str(target_message["timestamp"])
    logger.info(f"Executing summarize after message ID: {target_msg_id} (timestamp: {target_timestamp})")

    model_instance = st.session_state.get("current_model_instance")
    if not model_instance:
        st.warning("Model not available for summarization.")
        logger.warning("Summarize action aborted: Model instance not found.")
        return

    with st.spinner("Summarizing subsequent history..."):
        messages_to_summarize = db.get_messages_after_timestamp(current_convo_id, target_timestamp)
        logger.debug(f"Found {len(messages_to_summarize)} messages after {target_timestamp} for summarization.")

        if not messages_to_summarize:
            st.toast("No messages found after this one to summarize.", icon="ℹ️")
            st.session_state.summary_result = None # Clear previous summary if any
            return

        text_block = "\n---\n".join([f"**{m.get('role','?').capitalize()}** ({str(m.get('timestamp','?'))[:19]}):\n{m.get('content','')}" for m in messages_to_summarize])
        context_info = "Note: Relevant local files might have been included as context."

        # Use a simplified config for summarization
        summary_config = {
            "temperature": 0.3,
            "max_output_tokens": max(1024, int(st.session_state.get('current_model_max_output_tokens', 8192) * 0.2)),
             # No stop sequences or JSON mode needed for summary
        }

        # Construct summarization prompt (similar to original logic)
        summary_prompt = f"""You are an expert context summarizer...
Summarize the key points... in the text below. Maintain chronological flow... Be concise...
{context_info}
--- Text to Summarize ---
{text_block}
--- End Text to Summarize ---
Provide only the summary below:"""

        # Call API directly (using generate_text which handles non-chat)
        summary_text, error = api_client.generate_text(
            model_name=st.session_state.selected_model_name,
            prompt=summary_prompt,
            generation_config_dict=summary_config,
            history=None # No history needed for one-off summary
        )

    if error:
        st.error(f"Summarization failed: {error}")
        logger.error(f"Summarization call failed: {error}")
        st.session_state.summary_result = None
    elif summary_text is not None:
        st.session_state.summary_result = {
            "timestamp": target_timestamp,
            "summary": summary_text
        }
        st.session_state.clear_summary = False # Ensure flag is false so summary shows
        logger.info("Summary generated successfully.")
        # Rerun happens in main loop
    else:
        st.error("Summarization returned an unexpected result (None).")
        logger.error("Summarization returned None summary and None error.")
        st.session_state.summary_result = None
