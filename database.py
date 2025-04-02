# database.py
# Version: 2.1.1 - Added logging
import sqlite3
import datetime
import json
import streamlit as st # Only needed for toast, consider removing if toast is removed
import uuid
import logging # Import logging
from pathlib import Path # For DB path construction

# Get a logger instance for this module
logger = logging.getLogger(__name__)

# Define DB path relative to this file's location for robustness
DB_DIR = Path(__file__).parent
DB_NAME = DB_DIR / "gemini_chat_history.db"
PLACEHOLDER_TITLE = "New Chat..."

def get_db_connection():
    """Creates a connection to the SQLite database."""
    logger.debug(f"Attempting to connect to database: {DB_NAME}")
    try:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False, timeout=10) # Added timeout
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        logger.debug("Database connection successful.")
        return conn
    except sqlite3.Error as e:
        logger.critical(f"FATAL: Database connection failed for {DB_NAME}: {e}", exc_info=True)
        # Optionally, raise the exception or exit if DB is critical
        # raise e
        st.exception(e) # Show error in UI if possible during setup
        return None # Indicate failure


def create_tables():
    """Creates/updates the necessary database tables."""
    logger.info(f"Checking/Creating database tables in {DB_NAME}...")
    conn = get_db_connection()
    if not conn:
        logger.critical("Cannot create tables: Database connection failed.")
        return # Stop if connection failed

    cursor = conn.cursor()
    try:
        # Instructions Table
        logger.debug("Checking/Creating 'instructions' table.")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS instructions (
                name TEXT PRIMARY KEY, instruction_text TEXT NOT NULL, timestamp DATETIME NOT NULL
            )
        ''')

        # Conversations Table (Check and potentially migrate)
        logger.debug("Checking 'conversations' table schema.")
        needs_migration = False
        try:
            # Check if new columns exist by trying to select one
            cursor.execute("SELECT generation_config_json FROM conversations LIMIT 1")
            logger.debug("'generation_config_json' column exists.")
        except sqlite3.OperationalError:
            logger.warning("'conversations' table seems outdated. Attempting simple migration.")
            needs_migration = True

        if needs_migration:
            try:
                logger.info("Adding 'generation_config_json' column.")
                cursor.execute("ALTER TABLE conversations ADD COLUMN generation_config_json TEXT")
                logger.info("Adding 'system_instruction' column.")
                cursor.execute("ALTER TABLE conversations ADD COLUMN system_instruction TEXT")
                logger.info("Adding 'added_paths_json' column.")
                cursor.execute("ALTER TABLE conversations ADD COLUMN added_paths_json TEXT")
                conn.commit() # Commit migration changes
                logger.info("Simple migration successful: Added settings columns to 'conversations'.")
            except sqlite3.Error as alter_err:
                logger.error(f"ALERT: Failed to ALTER 'conversations' table ({alter_err}). Manual migration might be needed or data could be lost if schema changes drastically.", exc_info=True)
                # Fallback: Create table anew if ALTER failed (DANGEROUS - data loss)
                # logger.critical("ALTER failed, attempting to DROP and RECREATE conversations table (DATA LOSS WILL OCCUR).")
                # cursor.execute("DROP TABLE IF EXISTS conversations")
                # Fallback omitted for safety, log indicates manual intervention needed

        # Ensure table exists regardless of migration status
        logger.debug("Ensuring 'conversations' table structure.")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                title TEXT,
                start_timestamp DATETIME NOT NULL,
                last_update_timestamp DATETIME NOT NULL,
                generation_config_json TEXT,
                system_instruction TEXT,
                added_paths_json TEXT
            )
        ''')

        # Chat Messages Table
        logger.debug("Checking/Creating 'chat_messages' table.")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                model_used TEXT,
                context_files_json TEXT,
                full_prompt_sent TEXT,
                FOREIGN KEY (conversation_id) REFERENCES conversations (conversation_id) ON DELETE CASCADE
            )
        ''')

        # Settings Table
        logger.debug("Checking/Creating 'settings' table.")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            )
        ''')
        conn.commit() # Commit table creation if needed
        logger.info("Database tables check/creation/update complete.")
    except sqlite3.Error as e:
        logger.error(f"Database table creation/check error: {e}", exc_info=True)
        # Attempt rollback? Might be complex depending on state.
        # conn.rollback()
    finally:
        logger.debug("Closing database connection after table setup.")
        conn.close()

# --- Instruction Functions ---
def save_instruction(name, text):
    """Saves or replaces a named instruction."""
    logger.info(f"Attempting to save instruction: '{name}'")
    if not name or not text:
        logger.error("Save instruction failed: Name or text is empty.")
        return False, "Name and instruction text cannot be empty."

    conn = get_db_connection()
    if not conn: return False, "Database connection failed."

    ts = datetime.datetime.now()
    try:
        cursor = conn.cursor()
        logger.debug(f"Executing INSERT OR REPLACE for instruction '{name}'.")
        cursor.execute( "INSERT OR REPLACE INTO instructions (name, instruction_text, timestamp) VALUES (?, ?, ?)", (name.strip(), text, ts))
        conn.commit()
        logger.info(f"Instruction '{name}' saved successfully.")
        return True, f"Instruction '{name}' saved."
    except sqlite3.Error as e:
        logger.error(f"DB error saving instruction '{name}': {e}", exc_info=True)
        conn.rollback() # Rollback on error
        return False, f"DB error saving instruction: {e}"
    finally:
        if conn:
            logger.debug("Closing DB connection after save_instruction.")
            conn.close()

def load_instruction(name):
    """Loads the text of a named instruction."""
    logger.info(f"Attempting to load instruction: '{name}'")
    conn = get_db_connection()
    if not conn: return None

    instruction_text = None
    try:
        cursor = conn.cursor()
        logger.debug(f"Executing SELECT for instruction '{name}'.")
        cursor.execute("SELECT instruction_text FROM instructions WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row:
            instruction_text = row['instruction_text']
            logger.info(f"Instruction '{name}' loaded successfully.")
        else:
            logger.warning(f"Instruction '{name}' not found in database.")
    except sqlite3.Error as e:
        logger.error(f"DB error loading instruction '{name}': {e}", exc_info=True)
    finally:
        if conn:
            logger.debug("Closing DB connection after load_instruction.")
            conn.close()
    return instruction_text

def get_instruction_names():
    """Gets a list of all saved instruction names."""
    logger.info("Fetching all instruction names.")
    conn = get_db_connection()
    if not conn: return []

    names = []
    try:
        cursor = conn.cursor()
        logger.debug("Executing SELECT for all instruction names.")
        cursor.execute("SELECT name FROM instructions ORDER BY name ASC")
        rows = cursor.fetchall()
        names = [row['name'] for row in rows]
        logger.info(f"Found {len(names)} saved instructions.")
    except sqlite3.Error as e:
        logger.error(f"DB error getting instruction names: {e}", exc_info=True)
    finally:
        if conn:
            logger.debug("Closing DB connection after get_instruction_names.")
            conn.close()
    return names

def delete_instruction(name):
    """Deletes a named instruction."""
    logger.warning(f"Attempting to delete instruction: '{name}'") # Warning as it's destructive
    conn = get_db_connection()
    if not conn: return False, "Database connection failed."

    try:
        cursor = conn.cursor()
        logger.debug(f"Executing DELETE for instruction '{name}'.")
        cursor.execute("DELETE FROM instructions WHERE name = ?", (name,))
        conn.commit()
        # Check if any row was actually deleted
        if cursor.rowcount > 0:
            logger.info(f"Instruction '{name}' deleted successfully.")
            return True, f"Instruction '{name}' deleted."
        else:
            logger.warning(f"Instruction '{name}' not found for deletion.")
            return False, f"Instruction '{name}' not found."
    except sqlite3.Error as e:
        logger.error(f"DB error deleting instruction '{name}': {e}", exc_info=True)
        conn.rollback()
        return False, f"DB error deleting instruction: {e}"
    finally:
        if conn:
            logger.debug("Closing DB connection after delete_instruction.")
            conn.close()


# --- Conversation Functions ---
def start_new_conversation():
    """Creates a new conversation record and returns its ID."""
    logger.info("Starting new conversation record.")
    conn = get_db_connection()
    if not conn: return None

    conv_id = str(uuid.uuid4())
    now = datetime.datetime.now()
    try:
        cursor = conn.cursor()
        logger.debug(f"Executing INSERT for new conversation '{conv_id}'.")
        cursor.execute(
            """INSERT INTO conversations
            (conversation_id, title, start_timestamp, last_update_timestamp,
                generation_config_json, system_instruction, added_paths_json)
            VALUES (?, ?, ?, ?, NULL, NULL, NULL)""",
            (conv_id, PLACEHOLDER_TITLE, now, now)
        )
        conn.commit()
        logger.info(f"New conversation {conv_id} created successfully.")
        return conv_id
    except sqlite3.Error as e:
        logger.error(f"DB error starting new conversation: {e}", exc_info=True)
        conn.rollback()
        return None
    finally:
        if conn:
            logger.debug("Closing DB connection after start_new_conversation.")
            conn.close()

def update_conversation_metadata(conversation_id, title=None, generation_config=None, system_instruction=None, added_paths=None):
    """Updates metadata for a conversation."""
    logger.info(f"Attempting to update metadata for conversation: {conversation_id}")
    conn = get_db_connection()
    if not conn: return False

    updates = []
    params = []
    log_details = [] # For logging what's being updated

    if title is not None:
        updates.append("title = ?")
        params.append(title)
        log_details.append(f"title='{title[:20]}...'")
    if generation_config is not None:
        try:
            gen_conf_json = json.dumps(generation_config)
            updates.append("generation_config_json = ?")
            params.append(gen_conf_json)
            log_details.append("generation_config")
        except TypeError as json_err:
            logger.error(f"JSON TypeError encoding generation_config for {conversation_id}: {json_err}", exc_info=True)
            # Skip this update if encoding fails
    if system_instruction is not None:
        updates.append("system_instruction = ?")
        params.append(system_instruction)
        log_details.append(f"system_instruction='{system_instruction[:30]}...'")
    if added_paths is not None:
        try:
            # Convert set to list for JSON compatibility
            added_paths_list = list(added_paths)
            paths_json = json.dumps(added_paths_list)
            updates.append("added_paths_json = ?")
            params.append(paths_json)
            log_details.append(f"added_paths ({len(added_paths_list)} items)")
        except TypeError as json_err:
            logger.error(f"JSON TypeError encoding added_paths for {conversation_id}: {json_err}", exc_info=True)
            # Skip this update

    if not updates:
        logger.warning(f"No valid metadata updates provided for conversation {conversation_id}.")
        if conn: conn.close()
        return False # Nothing to update

    # Always update the timestamp when metadata is changed
    now = datetime.datetime.now()
    updates.append("last_update_timestamp = ?")
    params.append(now)
    log_details.append("last_update_timestamp")

    params.append(conversation_id) # For the WHERE clause

    sql = f"UPDATE conversations SET {', '.join(updates)} WHERE conversation_id = ?"
    logger.debug(f"Executing UPDATE for conversation {conversation_id}. Fields: {', '.join(log_details)}")

    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        logger.info(f"Metadata updated successfully for conversation {conversation_id}.")
        return True
    except sqlite3.Error as e:
        logger.error(f"DB error updating conversation metadata for {conversation_id}: {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        if conn:
            logger.debug("Closing DB connection after update_conversation_metadata.")
            conn.close()

def get_conversation_metadata(conversation_id):
    """Retrieves metadata for a specific conversation."""
    logger.info(f"Attempting to get metadata for conversation: {conversation_id}")
    conn = get_db_connection()
    if not conn: return None

    metadata = None
    try:
        cursor = conn.cursor()
        logger.debug(f"Executing SELECT for metadata of conversation {conversation_id}.")
        cursor.execute(
            """SELECT title, generation_config_json, system_instruction, added_paths_json
            FROM conversations WHERE conversation_id = ?""",
            (conversation_id,)
        )
        row = cursor.fetchone()
        if row:
            logger.debug(f"Metadata row found for {conversation_id}.")
            gen_config = None
            added_paths = set() # Default to empty set

            # Safely decode JSON fields
            try:
                if row["generation_config_json"]:
                    gen_config = json.loads(row["generation_config_json"])
                    logger.debug("Decoded generation_config JSON.")
            except json.JSONDecodeError as e:
                logger.error(f"JSONDecodeError for generation_config_json in {conversation_id}: {e}", exc_info=True)
                # Keep gen_config as None

            try:
                if row["added_paths_json"]:
                    loaded_list = json.loads(row["added_paths_json"])
                    if isinstance(loaded_list, list):
                        added_paths = set(loaded_list)
                        logger.debug(f"Decoded added_paths JSON ({len(added_paths)} items).")
                    else:
                        logger.error(f"Decoded added_paths_json is not a list for {conversation_id}.")
            except json.JSONDecodeError as e:
                logger.error(f"JSONDecodeError for added_paths_json in {conversation_id}: {e}", exc_info=True)
                # Keep added_paths as empty set

            metadata = {
                "title": row["title"],
                "generation_config": gen_config,
                "system_instruction": row["system_instruction"],
                "added_paths": added_paths
            }
            logger.info(f"Metadata retrieved successfully for conversation {conversation_id}.")
        else:
            logger.warning(f"No metadata found for conversation {conversation_id}.")

    except sqlite3.Error as e:
        logger.error(f"DB error getting conversation metadata for {conversation_id}: {e}", exc_info=True)
    finally:
        if conn:
            logger.debug("Closing DB connection after get_conversation_metadata.")
            conn.close()
    return metadata

def get_recent_conversations(limit=15):
    """Retrieves recent conversation IDs and titles."""
    logger.info(f"Fetching {limit} recent conversations.")
    conn = get_db_connection()
    if not conn: return []

    conversations = []
    try:
        cursor = conn.cursor()
        logger.debug(f"Executing SELECT for {limit} recent conversations.")
        cursor.execute(
            "SELECT conversation_id, title, last_update_timestamp FROM conversations ORDER BY last_update_timestamp DESC LIMIT ?",
            (limit,)
        )
        rows = cursor.fetchall()
        logger.debug(f"Found {len(rows)} conversation rows.")
        conversations = [{
            "id": row["conversation_id"],
            "title": row["title"] if row["title"] else PLACEHOLDER_TITLE,
            "last_update": row["last_update_timestamp"]
            } for row in rows]
        logger.info(f"Retrieved {len(conversations)} recent conversations.")
    except sqlite3.Error as e:
        logger.error(f"DB error getting recent conversations: {e}", exc_info=True)
    finally:
        if conn:
            logger.debug("Closing DB connection after get_recent_conversations.")
            conn.close()
    return conversations

def get_conversation_messages(conversation_id, include_ids_timestamps=False):
    """
    Retrieves messages for a specific conversation.
    Optionally includes message_id and timestamp.
    """
    logger.info(f"Fetching messages for conversation: {conversation_id} (Include IDs/TS: {include_ids_timestamps})")
    conn = get_db_connection()
    if not conn: return [] # Return empty list on connection failure

    messages = []
    try:
        cursor = conn.cursor()
        select_fields = "role, content"
        if include_ids_timestamps:
            select_fields = "message_id, role, content, timestamp"

        logger.debug(f"Executing SELECT ({select_fields}) for messages of conversation {conversation_id}.")
        cursor.execute(
            f"SELECT {select_fields} FROM chat_messages WHERE conversation_id = ? ORDER BY timestamp ASC",
            (conversation_id,)
        )
        rows = cursor.fetchall()
        if include_ids_timestamps:
            messages = [
                {
                    "id": row["message_id"], # Unique DB ID
                    "role": row["role"],
                    "content": row["content"],
                    "timestamp": row["timestamp"] # Store as string or datetime object? Let's keep as string from DB for now.
                } for row in rows
            ]
        else:
            messages = [{"role": row["role"], "content": row["content"]} for row in rows]

        logger.info(f"Retrieved {len(messages)} messages for conversation {conversation_id}.")
    except sqlite3.Error as e:
        logger.error(f"DB error getting conversation messages for {conversation_id}: {e}", exc_info=True)
        messages = [] # Ensure empty list on error
    finally:
        if conn:
            logger.debug("Closing DB connection after get_conversation_messages.")
            conn.close()
    return messages


def delete_message_by_id(message_id):
    """Deletes a specific message by its database ID."""
    logger.warning(f"Attempting to delete message with ID: {message_id}")
    conn = get_db_connection()
    if not conn: return False, "Database connection failed."

    try:
        cursor = conn.cursor()
        logger.debug(f"Executing DELETE for message ID {message_id}.")
        cursor.execute("DELETE FROM chat_messages WHERE message_id = ?", (message_id,))
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"Message ID {message_id} deleted successfully.")
            return True, f"Message deleted."
        else:
            logger.warning(f"Message ID {message_id} not found for deletion.")
            return False, "Message not found."
    except sqlite3.Error as e:
        logger.error(f"DB error deleting message ID {message_id}: {e}", exc_info=True)
        conn.rollback()
        return False, f"DB error deleting message: {e}"
    finally:
        if conn:
            logger.debug("Closing DB connection after delete_message_by_id.")
            conn.close()

def delete_messages_after_timestamp(conversation_id, timestamp_str):
    """Deletes all messages in a conversation strictly after a given timestamp string."""
    logger.warning(f"Attempting to delete messages after {timestamp_str} in conversation {conversation_id}")
    conn = get_db_connection()
    if not conn: return False, "Database connection failed."

    try:
        cursor = conn.cursor()
        # Ensure timestamp comparison works correctly with the stored format
        logger.debug(f"Executing DELETE for messages after {timestamp_str} in conv {conversation_id}.")
        cursor.execute(
            "DELETE FROM chat_messages WHERE conversation_id = ? AND timestamp > ?",
            (conversation_id, timestamp_str)
        )
        deleted_count = cursor.rowcount
        conn.commit()
        logger.info(f"Deleted {deleted_count} messages after {timestamp_str} in conversation {conversation_id}.")
        return True, f"Deleted {deleted_count} subsequent messages."
    except sqlite3.Error as e:
        logger.error(f"DB error deleting messages after {timestamp_str} in conv {conversation_id}: {e}", exc_info=True)
        conn.rollback()
        return False, f"DB error deleting subsequent messages: {e}"
    finally:
        if conn:
            logger.debug("Closing DB connection after delete_messages_after_timestamp.")
            conn.close()

def update_message_content(message_id, new_content):
    """Updates the content of a specific message."""
    logger.info(f"Attempting to update content for message ID: {message_id}")
    conn = get_db_connection()
    if not conn: return False, "Database connection failed."

    # We should also update the conversation's last_update_timestamp here
    now = datetime.datetime.now()

    try:
        cursor = conn.cursor()
        logger.debug(f"Executing UPDATE for content of message ID {message_id}.")
        cursor.execute("UPDATE chat_messages SET content = ? WHERE message_id = ?", (new_content, message_id))

        # Get conversation ID to update its timestamp
        cursor.execute("SELECT conversation_id FROM chat_messages WHERE message_id = ?", (message_id,))
        row = cursor.fetchone()
        if row:
            conversation_id = row['conversation_id']
            logger.debug(f"Executing UPDATE for conversation {conversation_id} timestamp (triggered by message update).")
            cursor.execute(
                "UPDATE conversations SET last_update_timestamp = ? WHERE conversation_id = ?",
                (now, conversation_id)
            )
        else:
            logger.warning(f"Could not find conversation ID for message {message_id} to update timestamp.")


        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"Content updated successfully for message ID {message_id}.")
            return True, "Message content updated."
        else:
            # This case might happen if the update didn't change anything or message_id was wrong
            logger.warning(f"Message ID {message_id} not found or content unchanged during update.")
            # Check if message exists
            cursor.execute("SELECT 1 FROM chat_messages WHERE message_id = ?", (message_id,))
            if cursor.fetchone():
                return True, "Message content unchanged." # Still success if no actual change needed
            else:
                return False, "Message not found for update."

    except sqlite3.Error as e:
        logger.error(f"DB error updating content for message ID {message_id}: {e}", exc_info=True)
        conn.rollback()
        return False, f"DB error updating message content: {e}"
    finally:
        if conn:
            logger.debug("Closing DB connection after update_message_content.")
            conn.close()
def delete_conversation(conversation_id):
    
    """Deletes a conversation and all its messages."""
    logger.warning(f"Attempting to delete conversation and its messages: {conversation_id}")
    conn = get_db_connection()
    if not conn: return False, "Database connection failed."

    try:
        cursor = conn.cursor()
        # ON DELETE CASCADE on chat_messages table should handle message deletion
        logger.debug(f"Executing DELETE for conversation ID {conversation_id} from 'conversations' table.")
        cursor.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))
        conn.commit()
        # Check if any row was actually deleted
        if cursor.rowcount > 0:
            logger.info(f"Conversation {conversation_id} and associated messages deleted successfully.")
            return True, f"Conversation deleted."
        else:
            logger.warning(f"Conversation {conversation_id} not found for deletion.")
            return False, f"Conversation not found."
    except sqlite3.Error as e:
        logger.error(f"DB error deleting conversation {conversation_id}: {e}", exc_info=True)
        conn.rollback()
        return False, f"DB error deleting conversation: {e}"
    finally:
        if conn:
            logger.debug("Closing DB connection after delete_conversation.")
            conn.close()

def get_messages_after_timestamp(conversation_id, timestamp_str):
    """Retrieves messages (including IDs and timestamps) after a specific timestamp.
       GUARANTEES returning a list.
    """
    logger.info(f"Fetching messages after {timestamp_str} in conversation {conversation_id}")
    conn = None
    # GUARANTEE: Initialize as empty list
    messages = []

    try:
        conn = get_db_connection()
        if not conn:
            logger.error("Cannot get messages after timestamp: Database connection failed.")
            # GUARANTEE: Return [] if connection fails
            return [] # Explicit return []

        cursor = conn.cursor()
        logger.debug(f"Executing SELECT for messages after {timestamp_str} in conv {conversation_id}.")
        # Ensure the timestamp string comparison is robust in SQLite.
        # Using YYYY-MM-DD HH:MM:SS.ffffff format generally works well.
        cursor.execute(
            "SELECT message_id, role, content, timestamp FROM chat_messages WHERE conversation_id = ? AND timestamp > ? ORDER BY timestamp ASC",
            (conversation_id, timestamp_str)
        )
        rows = cursor.fetchall() # Returns [] if no rows match '>' condition

        # Process rows (this won't run if rows is empty)
        messages = [
            {
                "id": row["message_id"],
                "role": row["role"],
                "content": row["content"],
                "timestamp": str(row["timestamp"])
            } for row in rows
        ]
        logger.info(f"Retrieved {len(messages)} messages after {timestamp_str} for conversation {conversation_id}.")
        # If rows was empty, messages is correctly [] here.

    except sqlite3.Error as e:
        logger.error(f"DB error getting messages after {timestamp_str} in conv {conversation_id}: {e}", exc_info=True)
        # GUARANTEE: Return [] on SQLite error. 'messages' is already [].
        return []
    except Exception as e_generic:
        logger.error(f"Generic error getting messages after {timestamp_str} in conv {conversation_id}: {e_generic}", exc_info=True)
        # GUARANTEE: Return [] on any other error. 'messages' is already [].
        return []
    finally:
        if conn:
            try:
                logger.debug("Closing DB connection after get_messages_after_timestamp.")
                conn.close()
            except Exception:
                pass # Ignore close errors

    # GUARANTEE: Return the list (which is [] if no rows found or error occurred)
    return messages


def update_conversation_timestamp(conversation_id):
    """Explicitly updates the last_update_timestamp for a conversation."""
    # Note: save_message now handles this automatically. This function remains for potential other uses.
    logger.info(f"Explicitly updating timestamp for conversation: {conversation_id}")
    conn = get_db_connection()
    if not conn: return False

    now = datetime.datetime.now()
    try:
        cursor = conn.cursor()
        logger.debug(f"Executing UPDATE for timestamp of conversation {conversation_id}.")
        cursor.execute(
            "UPDATE conversations SET last_update_timestamp = ? WHERE conversation_id = ?",
            (now, conversation_id)
        )
        conn.commit()
        logger.info(f"Timestamp updated successfully for conversation {conversation_id}.")
        return True
    except sqlite3.Error as e:
        logger.error(f"DB error explicitly updating conversation timestamp for {conversation_id}: {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        if conn:
            logger.debug("Closing DB connection after update_conversation_timestamp.")
            conn.close()


def save_message(conversation_id, role, content, model_used=None, context_files=None, full_prompt_sent=None):
    """Saves a chat message and updates the conversation timestamp."""
    logger.info(f"Attempting to save {role} message for conversation: {conversation_id}")
    conn = get_db_connection()
    if not conn: return False

    ts = datetime.datetime.now()
    context_files_json = None
    if context_files is not None:
        try:
            context_files_json = json.dumps(context_files)
            logger.debug("Encoded context files list to JSON.")
        except TypeError as json_err:
            logger.error(f"JSON TypeError encoding context_files for {conversation_id}, message save: {json_err}", exc_info=True)
            # Decide if save should proceed without context_files_json or fail
            # context_files_json will remain None

    success = False
    try:
        cursor = conn.cursor()
        logger.debug(f"Executing INSERT for {role} message into chat_messages.")
        cursor.execute(
            """INSERT INTO chat_messages
            (conversation_id, timestamp, role, content, model_used, context_files_json, full_prompt_sent)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (conversation_id, ts, role, content, model_used, context_files_json, full_prompt_sent)
        )
        logger.debug(f"Executing UPDATE for conversation timestamp (triggered by save_message).")
        cursor.execute(
            "UPDATE conversations SET last_update_timestamp = ? WHERE conversation_id = ?",
            (ts, conversation_id)
        )
        conn.commit()
        logger.info(f"{role.capitalize()} message saved successfully for conversation {conversation_id}.")
        success = True
    except sqlite3.Error as e:
        logger.error(f"DB error saving {role} message or updating timestamp for {conversation_id}: {e}", exc_info=True)
        conn.rollback()
        # Use toast for user feedback in UI thread if Streamlit context is available
        try:
            st.toast(f"⚠️ Error saving message to DB: {e}", icon="💾")
        except Exception as toast_err:
            logger.warning(f"Could not display DB save error toast: {toast_err}") # Log if toast fails
    finally:
        if conn:
            logger.debug("Closing DB connection after save_message.")
            conn.close()
    return success


# --- Settings Functions ---
def save_setting(key, value):
    """Saves or replaces a key-value setting."""
    # Avoid logging sensitive values like API keys directly
    log_value = value if key != 'api_key' else f"<{len(value)} chars>"
    logger.info(f"Attempting to save setting: key='{key}', value='{log_value}'")
    conn = get_db_connection()
    if not conn: return False

    try:
        cursor = conn.cursor()
        logger.debug(f"Executing INSERT OR REPLACE for setting '{key}'.")
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        logger.info(f"Setting '{key}' saved successfully.")
        return True
    except sqlite3.Error as e:
        logger.error(f"DB error saving setting '{key}': {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        if conn:
            logger.debug("Closing DB connection after save_setting.")
            conn.close()

def load_setting(key):
    """Loads a setting value by key."""
    logger.info(f"Attempting to load setting: '{key}'")
    conn = get_db_connection()
    if not conn: return None

    value = None
    try:
        cursor = conn.cursor()
        logger.debug(f"Executing SELECT for setting '{key}'.")
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row:
            value = row['value']
            # Avoid logging sensitive values
            log_value = value if key != 'api_key' else f"<{len(value)} chars>"
            logger.info(f"Setting '{key}' loaded successfully (value='{log_value}').")
        else:
            logger.info(f"Setting '{key}' not found in database.")
    except sqlite3.Error as e:
        logger.error(f"DB error loading setting '{key}': {e}", exc_info=True)
    finally:
        if conn:
            logger.debug("Closing DB connection after load_setting.")
            conn.close()
    return value

def delete_setting(key):
    """Deletes a setting by key."""
    logger.warning(f"Attempting to delete setting: '{key}'") # Warning as it's destructive
    conn = get_db_connection()
    if not conn: return False

    try:
        cursor = conn.cursor()
        logger.debug(f"Executing DELETE for setting '{key}'.")
        cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"Setting '{key}' deleted successfully.")
            return True
        else:
            logger.warning(f"Setting '{key}' not found for deletion.")
            return False # Return False if key didn't exist
    except sqlite3.Error as e:
        logger.error(f"DB error deleting setting '{key}': {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        if conn:
            logger.debug("Closing DB connection after delete_setting.")
            conn.close()

# --- Initialize DB on module import ---
# This ensures tables are checked/created when the module is first imported.
logger.debug("Running initial create_tables() on database module import.")
create_tables()