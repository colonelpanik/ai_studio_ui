### app/data/database.py ###
# app/data/database.py
# Version: 2.2.1+ (Includes timestamp override for save_message)
# Added datetime adapter/converter for sqlite3 compatibility
import sqlite3
import datetime
import json
import uuid
import logging
from pathlib import Path
from contextlib import contextmanager

# Get a logger instance for this module
logger = logging.getLogger(__name__)

# --- Datetime <-> ISO Format Conversion for SQLite ---

def adapt_datetime_iso(val):
    """Adapt datetime.datetime to timezone-aware ISO 8601 format."""
    # Ensure timezone-aware or convert naive to UTC before formatting?
    # For simplicity, assuming naive or consistent timezone usage for now.
    return val.isoformat()

def convert_timestamp_iso(val):
    """Convert ISO 8601 string timestamp back to datetime.datetime object."""
    # SQLite stores timestamp; convert bytes back to string first
    dt_str = val.decode('utf-8')
    try:
        # Handle potential timezone info (like Z or +00:00) if present
        if dt_str.endswith('Z'):
            dt_str = dt_str[:-1] + '+00:00'
        # fromisoformat handles microseconds correctly
        # Make robust against potential space separator from older formats if needed
        dt_str_cleaned = dt_str.replace(' ', 'T')
        return datetime.datetime.fromisoformat(dt_str_cleaned)
    except ValueError as ve:
        logger.error(f"Could not convert timestamp string '{val.decode('utf-8')}' to datetime: {ve}. Returning None.")
        return None # Or raise an error, or return epoch?
    except Exception as e:
        logger.error(f"Unexpected error converting timestamp: {e}", exc_info=True)
        return None


# Register the adapter and converter globally for sqlite3
sqlite3.register_adapter(datetime.datetime, adapt_datetime_iso)
sqlite3.register_converter("TIMESTAMP", convert_timestamp_iso)

logger.info("Registered sqlite3 datetime adapter and converter.")

# Define DB path relative to this file's location for robustness
APP_ROOT_DIR = Path(__file__).parent.parent.parent
DB_NAME = APP_ROOT_DIR / "gemini_chat_history.db"
PLACEHOLDER_TITLE = "New Chat..." # Consistent placeholder

# --- Connection Management ---
@contextmanager
def get_db_connection():
    """Provides a database connection context manager."""
    conn = None
    try:
        logger.debug(f"Attempting to connect to database: {DB_NAME}")
        conn = sqlite3.connect(DB_NAME, check_same_thread=False, timeout=10,
                               detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        conn.row_factory = sqlite3.Row
        # Enable Write-Ahead Logging for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        logger.debug("Database connection successful (WAL mode enabled).")
        yield conn
    except sqlite3.Error as e:
        logger.critical(f"Database connection/operation failed for {DB_NAME}: {e}", exc_info=True)
        raise
    finally:
        if conn:
            try:
                conn.close()
                logger.debug("Database connection closed.")
            except Exception as close_err:
                logger.error(f"Error closing DB connection: {close_err}", exc_info=True)


# --- Table Setup ---
def create_tables():
    """Creates/updates the necessary database tables."""
    logger.info(f"Checking/Creating database tables in {DB_NAME}...")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Instructions Table
            cursor.execute('''CREATE TABLE IF NOT EXISTS instructions (
                                  name TEXT PRIMARY KEY,
                                  instruction_text TEXT NOT NULL,
                                  timestamp TIMESTAMP NOT NULL
                              )''')
            # Conversations Table Check/Migration
            cursor.execute("PRAGMA table_info(conversations)")
            existing_columns = {row['name'] for row in cursor.fetchall()}
            # Added excluded_files_json
            required_columns = {
                "generation_config_json",
                "system_instruction",
                "added_paths_json",
                "excluded_files_json"
            }
            missing_columns = required_columns - existing_columns if existing_columns else required_columns
            # Ensure Conversations Table Base Exists Before Altering
            cursor.execute('''CREATE TABLE IF NOT EXISTS conversations (
                                  conversation_id TEXT PRIMARY KEY,
                                  title TEXT,
                                  start_timestamp TIMESTAMP NOT NULL,
                                  last_update_timestamp TIMESTAMP NOT NULL
                              )''')
            # Apply missing columns
            if missing_columns:
                logger.warning(f"Missing columns in 'conversations': {missing_columns}. Attempting migration.")
                try:
                    for col in missing_columns:
                        # Check again just before altering in case of concurrent creation? Unlikely needed.
                        cursor.execute(f"ALTER TABLE conversations ADD COLUMN {col} TEXT")
                        logger.info(f"Added column '{col}' to conversations.")
                    conn.commit()
                    logger.info("Simple migration successful for 'conversations'.")
                except sqlite3.Error as alter_err:
                    conn.rollback()
                    # Check if the error is "duplicate column name" - might happen in race conditions
                    if "duplicate column name" in str(alter_err).lower():
                         logger.warning(f"Column addition failed, likely already exists: {alter_err}")
                    else:
                         logger.error(f"ALERT: Failed to ALTER 'conversations' table ({alter_err}). Manual migration might be needed.", exc_info=True)
                         # Decide if this should be fatal. For now, we log and continue.
                         # raise alter_err
            # Chat Messages Table
            cursor.execute('''CREATE TABLE IF NOT EXISTS chat_messages (
                                  message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                  conversation_id TEXT NOT NULL,
                                  timestamp TIMESTAMP NOT NULL,
                                  role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                                  content TEXT NOT NULL,
                                  model_used TEXT,
                                  context_files_json TEXT,
                                  full_prompt_sent TEXT,
                                  FOREIGN KEY (conversation_id) REFERENCES conversations (conversation_id) ON DELETE CASCADE
                              )''')
            # Index for faster message retrieval
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation_timestamp ON chat_messages (conversation_id, timestamp)")
            # Settings Table
            cursor.execute('''CREATE TABLE IF NOT EXISTS settings (
                                  key TEXT PRIMARY KEY,
                                  value TEXT NOT NULL
                              )''')
            conn.commit()
            logger.info("Database tables check/creation/update complete.")
    except sqlite3.Error as e:
        logger.error(f"Database table creation/check error: {e}", exc_info=True)
        raise e # Raising might be better to halt startup if DB is broken

# --- Instruction Functions ---
def save_instruction(name: str, text: str) -> tuple[bool, str]:
    logger.debug(f"DB: Attempting to save instruction '{name}'")
    if not name or not text:
        logger.warning("DB: Save instruction aborted, empty name or text.")
        return False, "Instruction name and text cannot be empty."
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            now = datetime.datetime.now()
            cursor.execute(
                "INSERT OR REPLACE INTO instructions (name, instruction_text, timestamp) VALUES (?, ?, ?)",
                (name, text, now)
            )
            conn.commit()
            logger.info(f"Instruction '{name}' saved successfully.")
            return True, f"Instruction '{name}' saved."
    except sqlite3.Error as e:
        logger.error(f"DB Error saving instruction '{name}': {e}", exc_info=True)
        return False, f"Database error saving instruction: {e}"

def load_instruction(name: str) -> str | None:
    logger.debug(f"DB: Attempting to load instruction '{name}'")
    if not name: return None
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT instruction_text FROM instructions WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row:
                logger.debug(f"Instruction '{name}' loaded successfully.")
                return row['instruction_text']
            else:
                logger.warning(f"Instruction '{name}' not found.")
                return None
    except sqlite3.Error as e:
        logger.error(f"DB Error loading instruction '{name}': {e}", exc_info=True)
        return None

def get_instruction_names() -> list[str]:
    logger.debug("DB: Getting instruction names")
    names = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Order case-insensitively
            cursor.execute("SELECT name FROM instructions ORDER BY name COLLATE NOCASE")
            names = [row['name'] for row in cursor.fetchall()]
            logger.debug(f"Found {len(names)} instruction names.")
    except sqlite3.Error as e:
        logger.error(f"DB Error getting instruction names: {e}", exc_info=True)
    return names

def delete_instruction(name: str) -> tuple[bool, str]:
    logger.warning(f"DB: Attempting to delete instruction '{name}'")
    if not name: return False, "No instruction name provided."
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM instructions WHERE name = ?", (name,))
            deleted_count = cursor.rowcount
            conn.commit()
            if deleted_count > 0:
                logger.info(f"Instruction '{name}' deleted successfully.")
                return True, f"Instruction '{name}' deleted."
            else:
                logger.warning(f"Instruction '{name}' not found for deletion.")
                return False, f"Instruction '{name}' not found."
    except sqlite3.Error as e:
        logger.error(f"DB Error deleting instruction '{name}': {e}", exc_info=True)
        return False, f"Database error deleting instruction: {e}"

# --- Conversation Functions ---
def start_new_conversation() -> str | None:
    logger.debug("DB: Starting new conversation")
    new_id = str(uuid.uuid4())
    now = datetime.datetime.now()
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Initialize with required fields and potentially null/default JSONs
            cursor.execute(
                """INSERT INTO conversations (
                       conversation_id, title, start_timestamp, last_update_timestamp,
                       generation_config_json, system_instruction, added_paths_json, excluded_files_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (new_id, None, now, now, None, None, None, None)
            )
            conn.commit()
            logger.info(f"New conversation started with ID: {new_id}")
            return new_id
    except sqlite3.Error as e:
        logger.error(f"DB Error starting new conversation: {e}", exc_info=True)
        return None

def update_conversation_metadata(
    conversation_id: str,
    title: str | None = None,
    generation_config: dict | None = None,
    system_instruction: str | None = None,
    added_paths: set | None = None,
    excluded_individual_files: set | None = None
) -> bool:
    logger.debug(f"DB: Updating metadata for conversation {conversation_id}")
    if not conversation_id: return False
    updates = []
    params = []
    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if generation_config is not None:
        updates.append("generation_config_json = ?")
        params.append(json.dumps(generation_config))
    if system_instruction is not None:
        updates.append("system_instruction = ?")
        params.append(system_instruction)
    if added_paths is not None:
        updates.append("added_paths_json = ?")
        params.append(json.dumps(list(added_paths)))
    if excluded_individual_files is not None:
        updates.append("excluded_files_json = ?")
        params.append(json.dumps(list(excluded_individual_files)))

    if not updates:
        logger.warning(f"No metadata provided to update for conversation {conversation_id}")
        # Still update timestamp? Maybe not if nothing changed. Let's return True.
        return True

    # Always update the timestamp when metadata changes
    updates.append("last_update_timestamp = ?")
    params.append(datetime.datetime.now())

    params.append(conversation_id) # For the WHERE clause
    sql = f"UPDATE conversations SET {', '.join(updates)} WHERE conversation_id = ?"

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            conn.commit()
            logger.info(f"Metadata updated successfully for conversation {conversation_id}")
            return True
    except sqlite3.Error as e:
        logger.error(f"DB Error updating metadata for conversation {conversation_id}: {e}", exc_info=True)
        return False

def get_conversation_metadata(conversation_id: str) -> dict | None:
    logger.debug(f"DB: Getting metadata for conversation {conversation_id}")
    if not conversation_id: return None
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT title, generation_config_json, system_instruction,
                          added_paths_json, excluded_files_json
                   FROM conversations WHERE conversation_id = ?""",
                (conversation_id,)
            )
            row = cursor.fetchone()
            if row:
                metadata = dict(row) # Convert Row object to dict
                try:
                    metadata["generation_config"] = json.loads(row["generation_config_json"]) if row["generation_config_json"] else None
                except (json.JSONDecodeError, TypeError) as e:
                     logger.error(f"Failed to parse generation_config_json for {conversation_id}: {e}")
                     metadata["generation_config"] = None
                try:
                    metadata["added_paths"] = set(json.loads(row["added_paths_json"])) if row["added_paths_json"] else set()
                except (json.JSONDecodeError, TypeError) as e:
                    logger.error(f"Failed to parse added_paths_json for {conversation_id}: {e}")
                    metadata["added_paths"] = set()
                try:
                    metadata["excluded_individual_files"] = set(json.loads(row["excluded_files_json"])) if row["excluded_files_json"] else set()
                except (json.JSONDecodeError, TypeError) as e:
                    logger.error(f"Failed to parse excluded_files_json for {conversation_id}: {e}")
                    metadata["excluded_individual_files"] = set()

                logger.debug(f"Metadata retrieved for conversation {conversation_id}")
                return metadata
            else:
                logger.warning(f"No conversation found with ID {conversation_id} for metadata retrieval.")
                return None
    except sqlite3.Error as e:
        logger.error(f"DB Error getting metadata for conversation {conversation_id}: {e}", exc_info=True)
        return None

def get_recent_conversations(limit: int = 15) -> list[dict]:
    logger.debug(f"DB: Getting {limit} recent conversations")
    convos = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT conversation_id, title, last_update_timestamp
                   FROM conversations ORDER BY last_update_timestamp DESC LIMIT ?""",
                (limit,)
            )
            rows = cursor.fetchall()
            convos = [{
                "id": row["conversation_id"],
                "title": row["title"] or PLACEHOLDER_TITLE, # Use placeholder if title is None/empty
                "last_update": row["last_update_timestamp"] # Should be datetime object
            } for row in rows]
            logger.debug(f"Found {len(convos)} recent conversations.")
    except sqlite3.Error as e:
        logger.error(f"DB Error getting recent conversations: {e}", exc_info=True)
    return convos

def delete_conversation(conversation_id: str) -> tuple[bool, str]:
    logger.warning(f"DB: Attempting to delete conversation {conversation_id}")
    if not conversation_id: return False, "No conversation ID provided."
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Foreign key cascade should handle deleting associated messages
            cursor.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))
            deleted_count = cursor.rowcount
            conn.commit()
            if deleted_count > 0:
                logger.info(f"Conversation {conversation_id} deleted successfully (affected {deleted_count} row(s)).")
                return True, "Conversation deleted."
            else:
                logger.warning(f"Conversation {conversation_id} not found for deletion.")
                return False, "Conversation not found."
    except sqlite3.Error as e:
        logger.error(f"DB Error deleting conversation {conversation_id}: {e}", exc_info=True)
        return False, f"Database error deleting conversation: {e}"

def update_conversation_timestamp(conversation_id: str) -> bool:
    """Updates only the last_update_timestamp of a conversation to now."""
    logger.debug(f"DB: Updating timestamp for conversation {conversation_id}")
    if not conversation_id: return False
    now = datetime.datetime.now()
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE conversations SET last_update_timestamp = ? WHERE conversation_id = ?",
                (now, conversation_id)
            )
            conn.commit()
            logger.debug(f"Timestamp updated for conversation {conversation_id}")
            return True
    except sqlite3.Error as e:
        logger.error(f"DB Error updating timestamp for conversation {conversation_id}: {e}", exc_info=True)
        return False

# --- Chat Message Functions ---
# --- MODIFIED: Added timestamp_override ---
def save_message(
    conversation_id: str,
    role: str,
    content: str,
    model_used: str | None = None,
    context_files: list | None = None,
    full_prompt_sent: str | None = None,
    timestamp_override: datetime.datetime | None = None # New optional parameter
) -> bool:
    """Saves a message, allowing timestamp override."""
    log_ts_info = f"(Timestamp Override: {timestamp_override})" if timestamp_override else "(Timestamp: Now)"
    logger.debug(f"DB: Saving message for conversation {conversation_id} (Role: {role}) {log_ts_info}")
    if not conversation_id or not role or content is None:
        logger.error("DB: Save message aborted, missing required field (convo_id, role, content).")
        return False
    if role not in ('user', 'assistant'):
        logger.error(f"DB: Save message aborted, invalid role '{role}'.")
        return False

    # Determine the timestamp to save
    timestamp_to_save = timestamp_override if timestamp_override is not None else datetime.datetime.now()
    # Timestamp for conversation update should always be 'now' to reflect the operation time
    operation_timestamp = datetime.datetime.now()

    context_json = json.dumps(context_files) if context_files is not None else None

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO chat_messages (
                       conversation_id, timestamp, role, content, model_used,
                       context_files_json, full_prompt_sent
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    conversation_id,
                    timestamp_to_save, # Use the determined timestamp
                    role,
                    content,
                    model_used,
                    context_json,
                    full_prompt_sent
                )
            )
            # Update conversation timestamp using the operation time, not the override time
            cursor.execute(
                "UPDATE conversations SET last_update_timestamp = ? WHERE conversation_id = ?",
                (operation_timestamp, conversation_id)
            )
            conn.commit()
            logger.info(f"Message saved successfully for conversation {conversation_id}")
            return True
    except sqlite3.Error as e:
        logger.error(f"DB Error saving message for conversation {conversation_id}: {e}", exc_info=True)
        # Attempt rollback explicitly on error? Context manager should handle commit/rollback.
        # try: conn.rollback()
        # except: pass
        return False
# --- END MODIFIED ---

def get_conversation_messages(conversation_id: str, include_ids_timestamps: bool = False) -> list[dict]:
    """Retrieves messages, optionally including DB ID and timestamp."""
    logger.debug(f"DB: Getting messages for conversation {conversation_id} (Include IDs/TS: {include_ids_timestamps})")
    if not conversation_id: return []
    messages = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Select necessary columns based on flag
            columns = "message_id, timestamp, role, content" if include_ids_timestamps else "role, content"
            cursor.execute(
                f"SELECT {columns} FROM chat_messages WHERE conversation_id = ? ORDER BY timestamp",
                (conversation_id,)
            )
            rows = cursor.fetchall()
            # Convert Row objects to dictionaries
            messages = [dict(row) for row in rows]
            # Timestamps should be datetime objects due to converter if include_ids_timestamps is True
            logger.debug(f"Retrieved {len(messages)} messages for conversation {conversation_id}.")
    except sqlite3.Error as e:
        logger.error(f"DB Error getting messages for conversation {conversation_id}: {e}", exc_info=True)
    return messages

def delete_message_by_id(message_id: int) -> tuple[bool, str]:
    logger.warning(f"DB: Attempting to delete message ID {message_id}")
    if not isinstance(message_id, int): return False, "Invalid message ID provided."
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM chat_messages WHERE message_id = ?", (message_id,))
            deleted_count = cursor.rowcount
            conn.commit()
            if deleted_count > 0:
                logger.info(f"Message ID {message_id} deleted successfully.")
                # Consider updating conversation timestamp? Deleting msg is an update.
                # convo_id = get_convo_id_for_message(conn, message_id) # Need helper or another query
                # if convo_id: update_conversation_timestamp(convo_id)
                return True, "Message deleted."
            else:
                logger.warning(f"Message ID {message_id} not found for deletion.")
                return False, "Message not found."
    except sqlite3.Error as e:
        logger.error(f"DB Error deleting message ID {message_id}: {e}", exc_info=True)
        return False, f"Database error deleting message: {e}"

def delete_messages_after_timestamp(conversation_id: str, timestamp_obj: datetime.datetime) -> tuple[bool, str]:
    """Deletes messages with timestamp > the given datetime object."""
    logger.warning(f"DB: Attempting to delete messages after {timestamp_obj.isoformat()} for conversation {conversation_id}")
    if not conversation_id or not isinstance(timestamp_obj, datetime.datetime):
         logger.error(f"Invalid input for delete_messages_after_timestamp: convo='{conversation_id}', ts_type={type(timestamp_obj)}")
         return False, "Invalid conversation ID or timestamp type for deletion."
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM chat_messages WHERE conversation_id = ? AND timestamp > ?",
                (conversation_id, timestamp_obj)
            )
            deleted_count = cursor.rowcount
            conn.commit()
            logger.info(f"Deleted {deleted_count} message(s) after {timestamp_obj.isoformat()} for conversation {conversation_id}.")
            if deleted_count > 0:
                # Update conversation timestamp as content changed
                update_success = update_conversation_timestamp(conversation_id)
                if not update_success: logger.warning(f"Failed to update convo timestamp after deleting messages for {conversation_id}")
            return True, f"Deleted {deleted_count} message(s)."
    except sqlite3.Error as e:
        logger.error(f"DB Error deleting messages after {timestamp_obj.isoformat()} for {conversation_id}: {e}", exc_info=True)
        return False, f"Database error deleting messages: {e}"

def update_message_content(message_id: int, new_content: str) -> tuple[bool, str]:
    logger.debug(f"DB: Updating content for message ID {message_id}")
    if not isinstance(message_id, int) or new_content is None:
         return False, "Invalid message ID or content for update."
    operation_timestamp = datetime.datetime.now()
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Find conversation ID first to update its timestamp
            cursor.execute("SELECT conversation_id FROM chat_messages WHERE message_id = ?", (message_id,))
            convo_id_row = cursor.fetchone()
            if not convo_id_row:
                logger.warning(f"Message ID {message_id} not found for content update.")
                return False, "Message not found for update."
            convo_id = convo_id_row['conversation_id']

            # Update message content
            cursor.execute("UPDATE chat_messages SET content = ? WHERE message_id = ?", (new_content, message_id))
            updated_count = cursor.rowcount

            if updated_count > 0:
                # Update conversation timestamp
                cursor.execute(
                    "UPDATE conversations SET last_update_timestamp = ? WHERE conversation_id = ?",
                    (operation_timestamp, convo_id)
                )
                conn.commit()
                logger.info(f"Content updated for message ID {message_id} and conversation timestamp updated.")
                return True, "Message content updated."
            else:
                # This case should be rare if the SELECT found the message_id
                conn.rollback() # Ensure no partial commit
                logger.warning(f"Message ID {message_id} found but content update affected 0 rows.")
                return False, "Message found, but update failed unexpectedly."
    except sqlite3.Error as e:
        logger.error(f"DB Error updating content for message ID {message_id}: {e}", exc_info=True)
        # Context manager should handle rollback on exception
        return False, f"Database error updating message: {e}"

def get_messages_after_timestamp(conversation_id: str, timestamp_obj: datetime.datetime) -> list[dict]:
    """Retrieves messages with timestamp > the specific datetime object."""
    logger.debug(f"DB: Getting messages after {timestamp_obj.isoformat()} for conversation {conversation_id}")
    if not conversation_id or not isinstance(timestamp_obj, datetime.datetime):
        logger.error(f"Invalid input for get_messages_after_timestamp: convo='{conversation_id}', ts_type={type(timestamp_obj)}")
        return []
    messages = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Select all relevant columns needed by caller (e.g., summarizer needs role, content, timestamp)
            cursor.execute(
                """SELECT message_id, timestamp, role, content FROM chat_messages
                   WHERE conversation_id = ? AND timestamp > ? ORDER BY timestamp""",
                (conversation_id, timestamp_obj)
            )
            messages = [dict(row) for row in cursor.fetchall()] # Convert to dict list
            logger.debug(f"Found {len(messages)} messages after {timestamp_obj.isoformat()} for conversation {conversation_id}")
    except sqlite3.Error as e:
        logger.error(f"DB Error getting messages after {timestamp_obj.isoformat()} for {conversation_id}: {e}", exc_info=True)
    return messages

# --- NEW: get_messages_before_timestamp ---
def get_messages_before_timestamp(conversation_id: str, timestamp_obj: datetime.datetime) -> list[dict]:
    """Retrieves messages with timestamp < the specific datetime object."""
    logger.debug(f"DB: Getting messages before {timestamp_obj.isoformat()} for conversation {conversation_id}")
    if not conversation_id or not isinstance(timestamp_obj, datetime.datetime):
        logger.error(f"Invalid input for get_messages_before_timestamp: convo='{conversation_id}', ts_type={type(timestamp_obj)}")
        return []
    messages = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Select all relevant columns needed by caller (e.g., summarizer needs role, content, timestamp)
            cursor.execute(
                """SELECT message_id, timestamp, role, content FROM chat_messages
                   WHERE conversation_id = ? AND timestamp < ? ORDER BY timestamp""",
                (conversation_id, timestamp_obj)
            )
            messages = [dict(row) for row in cursor.fetchall()] # Convert to dict list
            logger.debug(f"Found {len(messages)} messages before {timestamp_obj.isoformat()} for conversation {conversation_id}")
    except sqlite3.Error as e:
        logger.error(f"DB Error getting messages before {timestamp_obj.isoformat()} for {conversation_id}: {e}", exc_info=True)
    return messages

# --- NEW: delete_messages_before_timestamp ---
def delete_messages_before_timestamp(conversation_id: str, timestamp_obj: datetime.datetime) -> tuple[bool, str]:
    """Deletes messages with timestamp < the given datetime object."""
    logger.warning(f"DB: Attempting to delete messages before {timestamp_obj.isoformat()} for conversation {conversation_id}")
    if not conversation_id or not isinstance(timestamp_obj, datetime.datetime):
         logger.error(f"Invalid input for delete_messages_before_timestamp: convo='{conversation_id}', ts_type={type(timestamp_obj)}")
         return False, "Invalid conversation ID or timestamp type for deletion."
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM chat_messages WHERE conversation_id = ? AND timestamp < ?",
                (conversation_id, timestamp_obj)
            )
            deleted_count = cursor.rowcount
            conn.commit()
            logger.info(f"Deleted {deleted_count} message(s) before {timestamp_obj.isoformat()} for conversation {conversation_id}.")
            if deleted_count > 0:
                 # Update conversation timestamp only if messages were actually deleted
                 update_success = update_conversation_timestamp(conversation_id)
                 if not update_success: logger.warning(f"Failed to update convo timestamp after deleting messages for {conversation_id}")
            return True, f"Deleted {deleted_count} message(s)."
    except sqlite3.Error as e:
        logger.error(f"DB Error deleting messages before {timestamp_obj.isoformat()} for {conversation_id}: {e}", exc_info=True)
        return False, f"Database error deleting messages: {e}"


# --- Settings Functions ---
def save_setting(key: str, value: str) -> bool:
    logger.debug(f"DB: Saving setting '{key}'")
    if not key or value is None: return False
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
            logger.info(f"Setting '{key}' saved successfully.")
            return True
    except sqlite3.Error as e:
        logger.error(f"DB Error saving setting '{key}': {e}", exc_info=True)
        return False

def load_setting(key: str) -> str | None:
    logger.debug(f"DB: Loading setting '{key}'")
    if not key: return None
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                logger.debug(f"Setting '{key}' loaded.")
                return row['value']
            else:
                logger.debug(f"Setting '{key}' not found.")
                return None
    except sqlite3.Error as e:
        logger.error(f"DB Error loading setting '{key}': {e}", exc_info=True)
        return None

def delete_setting(key: str) -> bool:
    logger.warning(f"DB: Attempting to delete setting '{key}'")
    if not key: return False
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
            deleted_count = cursor.rowcount
            conn.commit()
            if deleted_count > 0:
                logger.info(f"Setting '{key}' deleted.");
                return True
            else:
                logger.warning(f"Setting '{key}' not found for deletion.")
                return False
    except sqlite3.Error as e:
        logger.error(f"DB Error deleting setting '{key}': {e}", exc_info=True)
        return False

# --- Initialize DB on module import ---
try:
    logger.debug("Running initial create_tables() on database module import.")
    create_tables()
except Exception as init_db_err:
    # Log critical error and potentially exit if DB setup fails fundamentally
    logger.critical(f"FATAL: Initial database setup failed: {init_db_err}", exc_info=True)
    # Depending on the application, you might want to sys.exit(1) here