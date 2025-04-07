### app/logic/actions.py ###
# app/logic/actions.py
# Handles actions triggered by chat message buttons.
import streamlit as st
import logging
from app.data import database as db
from app.logic import api_client
# Removed unused import: from app.logic import context_manager
import datetime # Ensure datetime is imported

logger = logging.getLogger(__name__)

# --- Helper Function for Timestamp Processing ---
# This function is less critical now if we rely on state_manager's processing,
# but keep it for potential direct use or validation if needed elsewhere.
def _process_message_timestamps(messages: list[dict]) -> list[dict]:
    """Ensures 'timestamp' field is a datetime object in a list of messages."""
    processed = []
    for msg in messages:
        new_msg = msg.copy() # Avoid modifying original dicts in state directly if reused
        ts = new_msg.get("timestamp")
        if isinstance(ts, str):
            try:
                new_msg["timestamp"] = datetime.datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                logger.warning(f"Could not convert timestamp string '{ts}' in helper. Setting to None.")
                new_msg["timestamp"] = None
        elif not isinstance(ts, datetime.datetime):
            logger.warning(f"Unexpected timestamp type {type(ts)} in helper. Setting to None.")
            new_msg["timestamp"] = None
        # We keep the message even if timestamp is None for finding target ID,
        # but subsequent operations might need to filter for valid timestamps.
        processed.append(new_msg)
    return processed

# --- Helper Function for Summarization API Call ---
def _call_summarization_api(text_block: str, model_name: str) -> tuple[str | None, str | None]:
    """Calls the API to summarize the provided text block."""
    if not text_block.strip():
        return None, "No text provided for summarization."

    # Consider making context info and config more dynamic if needed
    context_info = "Note: Relevant local files might have been included as context."
    # Use a fraction of the main model's output limit for summary, ensure reasonable minimum
    summary_max_tokens = max(512, int(st.session_state.get('current_model_max_output_tokens', 8192) * 0.2))
    summary_config = {
        "temperature": 0.3, # Lower temperature for factual summary
        "max_output_tokens": summary_max_tokens,
        # No top_k/top_p needed usually for deterministic summary
    }
    summary_prompt = f"""You are an expert context summarizer tasked with condensing conversation history.
Summarize the key information, decisions, questions, and actions from the chat messages provided below.
Maintain the chronological flow of events where significant. Focus on information relevant for understanding the context going forward.
Ignore simple greetings or pleasantries unless they contain substantial information.
Be concise and clear.
{context_info}

--- Text to Summarize ---
{text_block}
--- End Text to Summarize ---

Provide only the summary below:"""

    logger.info(f"Requesting summary with max_tokens: {summary_max_tokens}")
    with st.spinner("Generating summary..."):
        summary_text, error_msg = api_client.generate_text(
            model_name=model_name,
            prompt=summary_prompt,
            generation_config_dict=summary_config,
            history=None # Summarization is a one-off task, don't use chat history
        )
    return summary_text, error_msg


# --- Action Handlers ---

def handle_delete_message(msg_id: int, current_convo_id: str | None):
    """Handles the 'delete' action."""
    if not current_convo_id:
        logger.error("Delete action failed: No current conversation ID.")
        st.error("Cannot delete message: No active conversation.")
        return
    logger.warning(f"Executing delete for message ID: {msg_id}")
    success, db_msg = db.delete_message_by_id(msg_id)
    st.toast(db_msg, icon="✅" if success else "❌")
    if not success:
        logger.error(f"Failed DB delete for message ID {msg_id}: {db_msg}")
    # State reload will happen in main.py after action completion

def handle_edit_message_setup(msg_id: int, messages: list):
    """Sets up the state for editing a user message. Uses the provided message list."""
    # Ensure messages list is provided (should be from st.session_state.messages)
    if messages is None:
        logger.error("Edit setup failed: Message list not provided.")
        st.error("Internal error: Cannot prepare edit.")
        return

    # Find message using message_id
    target_message_data = next((m for m in messages if m.get("message_id") == msg_id), None)

    if target_message_data and target_message_data.get("role") == "user":
        logger.info(f"Setting up edit state for message ID: {msg_id}")
        st.session_state.editing_message_id = msg_id
        st.session_state.editing_message_content = target_message_data.get('content', '') # Default to empty string
        st.session_state.clear_summary = True # Clear any previous summary display
    elif not target_message_data:
        logger.error(f"Could not find message data for edit action on ID {msg_id}")
        st.error("Error finding message to edit.")
    else:
        logger.warning(f"Attempted to edit non-user message ID: {msg_id}")
        st.warning("Only user messages can be edited.")
    # State reload/rerun happens in main.py

def handle_edit_message_save(edited_content: str, current_convo_id: str | None):
    """Handles saving an edited message, truncating history, and triggering resubmit."""
    editing_id = st.session_state.get("editing_message_id")
    if not editing_id or not current_convo_id:
        logger.error("Edit save failed: Missing editing ID or conversation ID.")
        st.error("Error saving edit: State is inconsistent.")
        # Clear edit state regardless
        st.session_state.editing_message_id = None
        st.session_state.editing_message_content = ""
        return

    logger.info(f"Saving edit for message ID: {editing_id}")
    # 1. Update the content in the database
    success_update, db_msg_update = db.update_message_content(editing_id, edited_content)
    if not success_update:
        st.error(f"Failed to save edit: {db_msg_update}")
        logger.error(f"Edit save failed: DB update failed for {editing_id}: {db_msg_update}")
        st.session_state.editing_message_id = None
        st.session_state.editing_message_content = ""
        # State reload/rerun happens in main.py
        return
    logger.info(f"Successfully updated content for message ID: {editing_id}")

    # 2. Find the timestamp of the edited message *from the current state*
    edited_msg_timestamp = None
    target_message = None
    current_msgs_for_edit = st.session_state.get("messages", []) # Use state messages
    try:
        # Re-process timestamps just in case state wasn't perfectly up-to-date?
        # Or trust state_manager did its job. Let's trust state for now.
        # current_msgs_for_edit_processed = _process_message_timestamps(current_msgs_for_edit)
        target_message = next((m for m in current_msgs_for_edit if m.get("message_id") == editing_id), None)

        if target_message and isinstance(target_message.get("timestamp"), datetime.datetime):
            edited_msg_timestamp = target_message["timestamp"]
            logger.info(f"Found valid datetime object '{edited_msg_timestamp}' for edited message {editing_id} from state.")
        else:
            # This case should ideally not happen if state is managed correctly
            ts_info = target_message.get("timestamp") if target_message else "Not Found"
            raise ValueError(f"Target message {editing_id} not found in state or timestamp invalid ({ts_info}).")
    except Exception as e:
        logger.error(f"Error finding edited message/timestamp in state for msg {editing_id}: {e}", exc_info=True)
        st.error(f"Internal error: Could not find edited message state ({e}). Cannot proceed with delete/resubmit.")
        st.session_state.editing_message_id = None
        st.session_state.editing_message_content = ""
        # State reload/rerun happens in main.py
        return

    # 3. Delete messages *after* this timestamp from the database
    success_del = False
    logger.info(f"Attempting to delete messages after datetime: {edited_msg_timestamp} for convo {current_convo_id}")
    success_del, db_msg_del = db.delete_messages_after_timestamp(current_convo_id, edited_msg_timestamp)
    if success_del:
        logger.info(f"Successfully deleted messages after edited message. Result: {db_msg_del}")
    else:
        st.error(f"Failed to delete history after edit: {db_msg_del}")
        logger.error(f"Edit failed during delete phase: DB delete_after failed for {edited_msg_timestamp}: {db_msg_del}")
        # Even if delete fails, we updated the message, so clear edit state and let main reload.

    # 4. Set flag for API call only if both update and delete were successful
    if success_update and success_del:
        st.toast("Edit saved and subsequent history removed.", icon="✅")
        st.session_state.pending_api_call = {
            "prompt": edited_content,
            "convo_id": current_convo_id,
            "trigger": "edit_resubmit"
        }
        st.session_state.clear_summary = True
        logger.info("Set pending_api_call flag for edit resubmission.")
    else:
        logger.warning("Skipping API resubmit because update or delete failed.")
        # Ensure edit state is cleared if delete failed but update succeeded
        st.session_state.editing_message_id = None
        st.session_state.editing_message_content = ""

    # Always clear editing state after attempting save
    st.session_state.editing_message_id = None
    st.session_state.editing_message_content = ""
    # State reload/rerun happens in main.py

def handle_regenerate(target_assistant_msg_id: int, current_convo_id: str | None, messages: list):
    """Handles regenerating a response based on the preceding user message."""
    if not current_convo_id:
        logger.error("Regenerate failed: No current conversation ID.")
        st.error("Cannot regenerate: No active conversation.")
        return
    if messages is None:
        logger.error("Regenerate failed: Message list not provided.")
        st.error("Internal error: Cannot regenerate response.")
        return

    # Ensure timestamps are datetime objects for reliable comparison/finding index
    processed_messages = _process_message_timestamps(messages) # Process state messages

    preceding_user_msg = None
    target_msg_index = -1
    for idx, msg in enumerate(processed_messages):
        if msg.get("message_id") == target_assistant_msg_id:
            target_msg_index = idx
            break

    if target_msg_index > 0 and processed_messages[target_msg_index - 1].get("role") == "user":
        preceding_user_msg = processed_messages[target_msg_index - 1]

    if preceding_user_msg and isinstance(preceding_user_msg.get("timestamp"), datetime.datetime):
        # Timestamp of the user message *before* the assistant message we clicked regenerate on
        user_msg_timestamp = preceding_user_msg["timestamp"]
        user_msg_content = preceding_user_msg.get("content")
        user_msg_id = preceding_user_msg.get("message_id")

        logger.warning(f"Executing regenerate based on preceding user message ID {user_msg_id} (TS: {user_msg_timestamp})")

        # Delete messages *after* the preceding user message
        success_del, db_msg_del = db.delete_messages_after_timestamp(current_convo_id, user_msg_timestamp)

        if success_del:
            logger.info(f"Successfully deleted messages after user message {user_msg_id} for regeneration. Result: {db_msg_del}")
            st.toast("History truncated for regeneration.", icon="✅")
            st.session_state.pending_api_call = {
                "prompt": user_msg_content, # Resend the user's prompt
                "convo_id": current_convo_id,
                "trigger": "regenerate"
            }
            st.session_state.clear_summary = True
            logger.info("Set pending_api_call flag for regeneration.")
        else:
            st.error(f"Failed to delete messages for regenerate: {db_msg_del}")
            logger.error(f"Regenerate failed: DB delete_after failed for {user_msg_timestamp}: {db_msg_del}")
            # State reload/rerun happens in main.py

    elif preceding_user_msg:
        # This case implies the timestamp wasn't a datetime object
        ts_type = type(preceding_user_msg.get("timestamp"))
        logger.error(f"Regenerate failed: Preceding user msg {preceding_user_msg.get('message_id')} has invalid timestamp type: {ts_type}")
        st.error(f"Could not regenerate: Invalid timestamp found ({ts_type}). Please refresh.")
    else:
        st.error("Could not find preceding user message to regenerate from.")
        logger.error(f"Regenerate failed: No valid preceding user msg found before assistant msg {target_assistant_msg_id}")
    # State reload/rerun happens in main.py

# --- Renamed: handle_summarize_after ---
def handle_summarize_after(target_msg_id: int, current_convo_id: str | None):
    """Handles summarizing messages *after* the target message."""
    logger.info(f"Initiating Summarize After for message ID: {target_msg_id}")
    if not current_convo_id:
        logger.error("Summarize After failed: No current conversation ID.")
        st.error("Cannot summarize: No active conversation.")
        return

    target_timestamp_obj = None
    model_name = st.session_state.get("selected_model_name")
    if not model_name:
        st.warning("Model not selected, cannot summarize.")
        return

    # --- Use messages from state ---
    current_messages = st.session_state.get("messages", [])
    try:
        # Process timestamps just to be safe, although state *should* be correct
        processed_messages = _process_message_timestamps(current_messages)
        target_message = next((m for m in processed_messages if m.get("message_id") == target_msg_id), None)
        if target_message and isinstance(target_message.get("timestamp"), datetime.datetime):
            target_timestamp_obj = target_message["timestamp"]
            logger.info(f"Summarize After: Target timestamp found in state: {target_timestamp_obj}")
        else:
            # This means the message ID wasn't found in the current state's message list
            raise ValueError(f"Target message {target_msg_id} not found in current state or has invalid timestamp.")
    except Exception as e:
         logger.error(f"Error finding target message/timestamp in state for Summarize After: {e}", exc_info=True)
         st.error(f"Error preparing for Summarize After: {e}")
         return
    # --- End using state ---

    # Fetch messages AFTER the target timestamp from DB for summarization content
    messages_to_summarize_raw = db.get_messages_after_timestamp(current_convo_id, target_timestamp_obj)
    messages_to_summarize = _process_message_timestamps(messages_to_summarize_raw)

    if not messages_to_summarize:
        st.toast("No messages found after this one to summarize.", icon="ℹ️")
        return
    logger.debug(f"Found {len(messages_to_summarize)} valid messages after target for summarization.")

    # Format messages for the summary prompt
    text_block = "\n---\n".join([
        f"**{m.get('role','?').capitalize()}** "
        f"({m.get('timestamp').isoformat(sep=' ', timespec='seconds')}):\n"
        f"{m.get('content','')}"
        for m in messages_to_summarize if m.get("timestamp") # Ensure timestamp exists for formatting
    ])

    summary_text, error_msg = _call_summarization_api(text_block, model_name)

    if error_msg or summary_text is None:
        st.error(f"Summarization failed: {error_msg or 'Empty response'}")
        logger.error(f"Summarize After API call failed: {error_msg or 'Empty response'}")
        # State reload/rerun happens in main.py
        return
    logger.info("Summarize After: Summary generated successfully by API.")

    # Delete original messages AFTER the target timestamp from DB
    logger.warning(f"Attempting to delete original messages after {target_timestamp_obj} for summarization.")
    success_del, db_msg_del = db.delete_messages_after_timestamp(current_convo_id, target_timestamp_obj)
    if not success_del:
        st.error(f"Failed to delete original messages after summarization: {db_msg_del}")
        logger.error(f"Summarize After failed during delete phase: {db_msg_del}")
        # State reload/rerun happens in main.py
        return
    logger.info(f"Successfully deleted messages ({db_msg_del}) after summarization.")

    # Save the summary as a new message (using current timestamp, will appear after target)
    summary_message_content = (
        f"**Summary of conversation after "
        f"{target_timestamp_obj.strftime('%Y-%m-%d %H:%M:%S')}:**\n\n{summary_text}"
    )
    logger.info("Attempting to save 'Summarize After' result as a new assistant message.")
    save_summary_success = db.save_message(
        conversation_id=current_convo_id,
        role='assistant',
        content=summary_message_content,
        model_used=f"summarized_by_{model_name}", # Indicate summarizer model
        # No timestamp_override needed here, uses default 'now'
    )
    if not save_summary_success:
        st.error("Failed to save the generated summary to the chat history.")
        logger.error(f"Failed to save 'Summarize After' message to DB for convo {current_convo_id}.")
        # State reload/rerun happens in main.py
        return

    logger.info("Summarize After: Summary successfully saved as a new message.")
    st.toast("Conversation summarized after target and updated!", icon="✅")
    st.session_state.summary_result = None # Clear any old summary display data
    st.session_state.clear_summary = False
    # State reload/rerun happens in main.py

# --- MODIFIED: handle_summarize_before ---
def handle_summarize_before(target_msg_id: int, current_convo_id: str | None):
    """Handles summarizing messages *before* the target message."""
    logger.info(f"Initiating Summarize Before for message ID: {target_msg_id}")
    if not current_convo_id:
        logger.error("Summarize Before failed: No current conversation ID.")
        st.error("Cannot summarize: No active conversation.")
        return

    target_timestamp_obj = None
    model_name = st.session_state.get("selected_model_name")
    if not model_name:
        st.warning("Model not selected, cannot summarize.")
        return

    # --- Use messages from state ---
    current_messages = st.session_state.get("messages", [])
    try:
        # Process timestamps just to be safe
        processed_messages = _process_message_timestamps(current_messages)
        target_message = next((m for m in processed_messages if m.get("message_id") == target_msg_id), None)
        if target_message and isinstance(target_message.get("timestamp"), datetime.datetime):
            target_timestamp_obj = target_message["timestamp"]
            logger.info(f"Summarize Before: Target timestamp found in state: {target_timestamp_obj}")
        else:
            raise ValueError(f"Target message {target_msg_id} not found in current state or has invalid timestamp.")
    except Exception as e:
         logger.error(f"Error finding target message/timestamp in state for Summarize Before: {e}", exc_info=True)
         st.error(f"Error preparing for Summarize Before: {e}")
         return
    # --- End using state ---

    # --- Calculate Timestamp for Summary ---
    try:
        # Subtract a small delta (e.g., 1 microsecond) from the target message's timestamp
        summary_timestamp = target_timestamp_obj - datetime.timedelta(microseconds=1)
        logger.info(f"Calculated summary insertion timestamp: {summary_timestamp}")
    except Exception as ts_calc_err:
        logger.error(f"Error calculating summary timestamp: {ts_calc_err}", exc_info=True)
        st.error(f"Internal error calculating timestamp: {ts_calc_err}")
        return
    # --- End Calculate Timestamp ---

    # Get messages BEFORE the target timestamp from DB
    messages_to_summarize_raw = db.get_messages_before_timestamp(current_convo_id, target_timestamp_obj)
    messages_to_summarize = _process_message_timestamps(messages_to_summarize_raw)

    if not messages_to_summarize:
        st.toast("No messages found before this one to summarize.", icon="ℹ️")
        return
    logger.debug(f"Found {len(messages_to_summarize)} valid messages before target for summarization.")

    text_block = "\n---\n".join([
        f"**{m.get('role','?').capitalize()}** "
        f"({m.get('timestamp').isoformat(sep=' ', timespec='seconds')}):\n"
        f"{m.get('content','')}"
        for m in messages_to_summarize if m.get("timestamp")
    ])

    summary_text, error_msg = _call_summarization_api(text_block, model_name)

    if error_msg or summary_text is None:
        st.error(f"Summarization failed: {error_msg or 'Empty response'}")
        logger.error(f"Summarize Before API call failed: {error_msg or 'Empty response'}")
        # State reload/rerun happens in main.py
        return
    logger.info("Summarize Before: Summary generated successfully by API.")

    # Delete messages BEFORE the target timestamp from DB
    logger.warning(f"Attempting to delete original messages before {target_timestamp_obj} for summarization.")
    success_del, db_msg_del = db.delete_messages_before_timestamp(current_convo_id, target_timestamp_obj)
    if not success_del:
        st.error(f"Failed to delete original messages before summarization: {db_msg_del}")
        logger.error(f"Summarize Before failed during delete phase: {db_msg_del}")
        # State reload/rerun happens in main.py
        return
    logger.info(f"Successfully deleted messages ({db_msg_del}) before summarization.")

    # --- Save Summary with Timestamp Override ---
    summary_message_content = (
        f"**Summary of conversation before "
        f"{target_timestamp_obj.strftime('%Y-%m-%d %H:%M:%S')}:**\n\n{summary_text}"
    )
    logger.info(f"Attempting to save 'Summarize Before' result with timestamp {summary_timestamp}.")
    save_summary_success = db.save_message(
        conversation_id=current_convo_id,
        role='assistant',
        content=summary_message_content,
        model_used=f"summarized_by_{model_name}", # Indicate summarizer model
        timestamp_override=summary_timestamp # Pass the calculated timestamp
    )
    # --- End Save Summary ---

    if not save_summary_success:
        st.error("Failed to save the generated summary to the chat history.")
        logger.error(f"Failed to save 'Summarize Before' message to DB for convo {current_convo_id}.")
        # State reload/rerun happens in main.py
        return

    logger.info("Summarize Before: Summary successfully saved as a new message.")
    st.toast("Conversation summarized before target and updated!", icon="✅")
    st.session_state.summary_result = None # Clear any old summary display data
    st.session_state.clear_summary = False
    # State reload/rerun happens in main.py

# --- End MODIFIED ---