# app/data/database.py
# Version: 2.2.1 - Regenerated with full implementations
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
    return val.isoformat()

def convert_timestamp_iso(val):
    """Convert ISO 8601 string timestamp back to datetime.datetime object."""
    # SQLite stores timestamp; convert bytes back to string first
    dt_str = val.decode('utf-8')
    return datetime.datetime.fromisoformat(dt_str)

# Register the adapter and converter globally for sqlite3
# Adapter: Python type -> SQLite type
sqlite3.register_adapter(datetime.datetime, adapt_datetime_iso)
# Converter: Declared SQLite type name -> Python type
# Use "TIMESTAMP" as it's a common declaration, or match your CREATE TABLE exact type if needed
sqlite3.register_converter("TIMESTAMP", convert_timestamp_iso)
# If your CREATE TABLE uses DATETIME, you might need/prefer:
# sqlite3.register_converter("DATETIME", convert_timestamp_iso)
# Using TIMESTAMP is generally safer across SQLite versions.

logger.info("Registered sqlite3 datetime adapter and converter.")

# --- End Datetime Conversion Setup ---


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
        # Ensure detect_types includes PARSE_DECLTYPES for the converter to work
        conn = sqlite3.connect(DB_NAME, check_same_thread=False, timeout=10,
                               detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        logger.debug("Database connection successful.")
        yield conn
    except sqlite3.Error as e:
        logger.critical(f"Database connection/operation failed for {DB_NAME}: {e}", exc_info=True)
        raise
    finally:
        if conn:
            try:
                conn.close()
                logger.debug("Database connection closed.")
            except sqlite3.Error as e:
                logger.error(f"Error closing database connection: {e}", exc_info=True)

# --- Table Setup ---
def create_tables():
    """Creates/updates the necessary database tables."""
    logger.info(f"Checking/Creating database tables in {DB_NAME}...")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Instructions Table
            logger.debug("Checking/Creating 'instructions' table.")
            # Use TIMESTAMP type for columns storing datetime objects
            cursor.execute('''CREATE TABLE IF NOT EXISTS instructions (
                                name TEXT PRIMARY KEY,
                                instruction_text TEXT NOT NULL,
                                timestamp TIMESTAMP NOT NULL
                             )''')

            # Conversations Table Check/Migration
            logger.debug("Checking 'conversations' table schema.")
            needs_migration = False
            # Check existence of columns before trying to alter
            cursor.execute("PRAGMA table_info(conversations)")
            existing_columns = {row['name'] for row in cursor.fetchall()}

            if not existing_columns: # Table doesn't exist yet
                 logger.debug("'conversations' table does not exist, will be created.")
            else:
                 # Check for specific columns added in migration
                 if "generation_config_json" not in existing_columns:
                     needs_migration = True
                 if "system_instruction" not in existing_columns:
                      needs_migration = True
                 if "added_paths_json" not in existing_columns:
                      needs_migration = True

            if needs_migration:
                logger.warning("Attempting simple migration for 'conversations'.")
                try:
                    if "generation_config_json" not in existing_columns:
                         cursor.execute("ALTER TABLE conversations ADD COLUMN generation_config_json TEXT")
                    if "system_instruction" not in existing_columns:
                         cursor.execute("ALTER TABLE conversations ADD COLUMN system_instruction TEXT")
                    if "added_paths_json" not in existing_columns:
                         cursor.execute("ALTER TABLE conversations ADD COLUMN added_paths_json TEXT")
                    conn.commit() # Commit schema changes
                    logger.info("Simple migration successful for 'conversations'.")
                except sqlite3.Error as alter_err:
                    # Rollback on error during ALTER
                    conn.rollback()
                    logger.error(f"ALERT: Failed to ALTER 'conversations' table ({alter_err}). Manual migration might be needed.", exc_info=True)
                    # Potentially raise error or exit depending on severity
                    raise alter_err # Re-raise to indicate failure

            # Ensure Conversations Table Exists (Use TIMESTAMP for datetime columns)
            logger.debug("Ensuring 'conversations' table structure.")
            cursor.execute('''CREATE TABLE IF NOT EXISTS conversations (
                                conversation_id TEXT PRIMARY KEY,
                                title TEXT,
                                start_timestamp TIMESTAMP NOT NULL,
                                last_update_timestamp TIMESTAMP NOT NULL,
                                generation_config_json TEXT,
                                system_instruction TEXT,
                                added_paths_json TEXT
                             )''')

            # Chat Messages Table (Use TIMESTAMP for datetime columns)
            logger.debug("Checking/Creating 'chat_messages' table.")
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

            # Settings Table
            logger.debug("Checking/Creating 'settings' table.")
            cursor.execute('''CREATE TABLE IF NOT EXISTS settings (
                                key TEXT PRIMARY KEY,
                                value TEXT NOT NULL
                             )''')

            conn.commit() # Commit table creation/updates if needed
            logger.info("Database tables check/creation/update complete.")
    except sqlite3.Error as e:
        logger.error(f"Database table creation/check error during connection: {e}", exc_info=True)
        # Handle error appropriately, maybe raise it
        raise e

# --- Instruction Functions ---
# (No changes needed in function logic, adapter handles datetime)
def save_instruction(name: str, text: str) -> tuple[bool, str]:
    logger.debug(f"DB: Attempting to save instruction '{name}'")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            now = datetime.datetime.now() # Gets current time
            # Adapter automatically converts 'now' to ISO string for storage
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

# (No changes needed for load_instruction, get_instruction_names, delete_instruction)
def load_instruction(name: str) -> str | None:
    logger.debug(f"DB: Attempting to load instruction '{name}'")
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
            cursor.execute("SELECT name FROM instructions ORDER BY name COLLATE NOCASE")
            rows = cursor.fetchall()
            names = [row['name'] for row in rows]
            logger.debug(f"Found {len(names)} instruction names.")
    except sqlite3.Error as e:
        logger.error(f"DB Error getting instruction names: {e}", exc_info=True)
    return names

def delete_instruction(name: str) -> tuple[bool, str]:
    logger.warning(f"DB: Attempting to delete instruction '{name}'")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM instructions WHERE name = ?", (name,))
            changes = conn.total_changes # Use cursor.rowcount for specific query effect
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
# (No changes needed in function logic, adapter/converter handle datetime)
def start_new_conversation() -> str | None:
    logger.debug("DB: Starting new conversation")
    new_id = str(uuid.uuid4())
    now = datetime.datetime.now()
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Adapter converts 'now'
            cursor.execute(
                "INSERT INTO conversations (conversation_id, title, start_timestamp, last_update_timestamp) VALUES (?, ?, ?, ?)",
                (new_id, None, now, now)
            )
            conn.commit()
            logger.info(f"New conversation started with ID: {new_id}")
            return new_id
    except sqlite3.Error as e:
        logger.error(f"DB Error starting new conversation: {e}", exc_info=True)
        return None

def update_conversation_metadata(conversation_id: str, title: str = None, generation_config: dict = None, system_instruction: str = None, added_paths: set = None) -> bool:
    logger.debug(f"DB: Updating metadata for conversation {conversation_id}")
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

    if not updates:
        logger.warning(f"No metadata provided to update for conversation {conversation_id}")
        return True

    updates.append("last_update_timestamp = ?")
    params.append(datetime.datetime.now()) # Adapter converts 'now'
    params.append(conversation_id)
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
    # Converter automatically handles timestamp fields if SELECTed
    logger.debug(f"DB: Getting metadata for conversation {conversation_id}")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Select only non-timestamp fields if converter isn't needed here
            cursor.execute(
                "SELECT title, generation_config_json, system_instruction, added_paths_json FROM conversations WHERE conversation_id = ?",
                (conversation_id,)
            )
            row = cursor.fetchone()
            if row:
                metadata = {
                    "title": row["title"],
                    "generation_config": json.loads(row["generation_config_json"]) if row["generation_config_json"] else None,
                    "system_instruction": row["system_instruction"],
                    "added_paths": set(json.loads(row["added_paths_json"])) if row["added_paths_json"] else set()
                    # Timestamps not selected, so no conversion needed here
                }
                logger.debug(f"Metadata retrieved for conversation {conversation_id}")
                return metadata
            else:
                logger.warning(f"No conversation found with ID {conversation_id} for metadata retrieval.")
                return None
    except (sqlite3.Error, json.JSONDecodeError) as e:
        logger.error(f"DB/JSON Error getting metadata for conversation {conversation_id}: {e}", exc_info=True)
        return None

def get_recent_conversations(limit: int = 15) -> list[dict]:
    # Converter automatically handles last_update_timestamp
    logger.debug(f"DB: Getting {limit} recent conversations")
    convos = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT conversation_id, title, last_update_timestamp FROM conversations ORDER BY last_update_timestamp DESC LIMIT ?",
                (limit,)
            )
            rows = cursor.fetchall()
            # 'last_update' will be a datetime object due to the converter
            convos = [{"id": row["conversation_id"], "title": row["title"] or PLACEHOLDER_TITLE, "last_update": row["last_update_timestamp"]} for row in rows]
            logger.debug(f"Found {len(convos)} recent conversations.")
    except sqlite3.Error as e:
        logger.error(f"DB Error getting recent conversations: {e}", exc_info=True)
    return convos

def delete_conversation(conversation_id: str) -> tuple[bool, str]:
    logger.warning(f"DB: Attempting to delete conversation {conversation_id}")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))
            deleted_count = cursor.rowcount
            conn.commit()
            if deleted_count > 0:
                logger.info(f"Conversation {conversation_id} deleted successfully.")
                return True, f"Conversation deleted."
            else:
                logger.warning(f"Conversation {conversation_id} not found for deletion.")
                return False, f"Conversation not found."
    except sqlite3.Error as e:
        logger.error(f"DB Error deleting conversation {conversation_id}: {e}", exc_info=True)
        return False, f"Database error deleting conversation: {e}"

def update_conversation_timestamp(conversation_id: str) -> bool:
    logger.debug(f"DB: Updating timestamp for conversation {conversation_id}")
    now = datetime.datetime.now() # Adapter converts 'now'
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
# (No changes needed in function logic, adapter/converter handle datetime)
def save_message(conversation_id: str, role: str, content: str, model_used: str = None, context_files: list = None, full_prompt_sent: str = None) -> bool:
    logger.debug(f"DB: Saving message for conversation {conversation_id} (Role: {role})")
    now = datetime.datetime.now() # Adapter converts 'now'
    context_json = json.dumps(context_files) if context_files is not None else None
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO chat_messages
                   (conversation_id, timestamp, role, content, model_used, context_files_json, full_prompt_sent)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (conversation_id, now, role, content, model_used, context_json, full_prompt_sent)
            )
            cursor.execute(
                "UPDATE conversations SET last_update_timestamp = ? WHERE conversation_id = ?",
                (now, conversation_id) # Adapter converts 'now' here too
            )
            conn.commit()
            logger.info(f"Message saved successfully for conversation {conversation_id}")
            return True
    except sqlite3.Error as e:
        logger.error(f"DB Error saving message for conversation {conversation_id}: {e}", exc_info=True)
        conn.rollback() # Rollback if either insert or update fails
        return False

def get_conversation_messages(conversation_id: str, include_ids_timestamps: bool = False) -> list[dict]:
    # Converter automatically handles 'timestamp' field
    logger.debug(f"DB: Getting messages for conversation {conversation_id} (Include IDs/TS: {include_ids_timestamps})")
    messages = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Select the timestamp column for the converter to work
            cursor.execute(
                "SELECT message_id, timestamp, role, content FROM chat_messages WHERE conversation_id = ? ORDER BY timestamp",
                (conversation_id,)
            )
            rows = cursor.fetchall()
            if include_ids_timestamps:
                # 'timestamp' will be a datetime object
                messages = [{"id": row["message_id"], "timestamp": row["timestamp"], "role": row["role"], "content": row["content"]} for row in rows]
            else:
                # Format for Gemini API history reconstruction (role/content only)
                messages = [{"role": row["role"], "content": row["content"]} for row in rows]
            logger.debug(f"Retrieved {len(messages)} messages for conversation {conversation_id}.")
    except sqlite3.Error as e:
        logger.error(f"DB Error getting messages for conversation {conversation_id}: {e}", exc_info=True)
    return messages

def delete_message_by_id(message_id: int) -> tuple[bool, str]:
    logger.warning(f"DB: Attempting to delete message ID {message_id}")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM chat_messages WHERE message_id = ?", (message_id,))
            deleted_count = cursor.rowcount
            conn.commit()
            if deleted_count > 0:
                logger.info(f"Message ID {message_id} deleted successfully.")
                return True, "Message deleted."
            else:
                logger.warning(f"Message ID {message_id} not found for deletion.")
                return False, "Message not found."
    except sqlite3.Error as e:
        logger.error(f"DB Error deleting message ID {message_id}: {e}", exc_info=True)
        return False, f"Database error deleting message: {e}"

def delete_messages_after_timestamp(conversation_id: str, timestamp_obj: datetime.datetime) -> tuple[bool, str]:
    """Deletes messages after a given datetime object."""
    # Takes datetime object, adapter converts it for comparison
    logger.warning(f"DB: Attempting to delete messages after {timestamp_obj.isoformat()} for conversation {conversation_id}")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Adapter converts timestamp_obj for the comparison
            cursor.execute(
                "DELETE FROM chat_messages WHERE conversation_id = ? AND timestamp > ?",
                (conversation_id, timestamp_obj)
            )
            deleted_count = cursor.rowcount
            conn.commit()
            logger.info(f"Deleted {deleted_count} message(s) after {timestamp_obj.isoformat()} for conversation {conversation_id}.")
            if deleted_count > 0: # Only update convo timestamp if messages were actually deleted
                 update_conversation_timestamp(conversation_id)
            return True, f"Deleted {deleted_count} message(s)."
    except sqlite3.Error as e:
        logger.error(f"DB Error deleting messages after {timestamp_obj.isoformat()} for {conversation_id}: {e}", exc_info=True)
        return False, f"Database error deleting messages: {e}"
    except Exception as e_conv: # Catch potential errors converting timestamp if not datetime
        logger.error(f"Error processing timestamp for deletion: {e_conv}", exc_info=True)
        return False, f"Invalid timestamp format for deletion: {e_conv}"


def update_message_content(message_id: int, new_content: str) -> tuple[bool, str]:
    logger.debug(f"DB: Updating content for message ID {message_id}")
    now = datetime.datetime.now() # Adapter converts 'now'
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            convo_id_row = cursor.execute("SELECT conversation_id FROM chat_messages WHERE message_id = ?", (message_id,)).fetchone()
            if not convo_id_row:
                 logger.warning(f"Message ID {message_id} not found for content update.")
                 return False, "Message not found for update."

            convo_id = convo_id_row['conversation_id']
            cursor.execute(
                "UPDATE chat_messages SET content = ? WHERE message_id = ?",
                (new_content, message_id)
            )
            updated_count = cursor.rowcount
            if updated_count > 0:
                # Also update conversation timestamp
                cursor.execute("UPDATE conversations SET last_update_timestamp = ? WHERE conversation_id = ?", (now, convo_id))
                conn.commit() # Commit both updates
                logger.info(f"Content updated for message ID {message_id} and conversation timestamp.")
                return True, "Message content updated."
            else:
                 # This case should not happen if convo_id_row was found, but good to handle
                 conn.rollback()
                 logger.warning(f"Message ID {message_id} found but content update affected 0 rows.")
                 return False, "Message found, but update failed unexpectedly."

    except sqlite3.Error as e:
        logger.error(f"DB Error updating content for message ID {message_id}: {e}", exc_info=True)
        # Attempt rollback in case of error during transaction
        try: conn.rollback()
        except: pass # Ignore rollback errors if connection is already closed/invalid
        return False, f"Database error updating message: {e}"

def get_messages_after_timestamp(conversation_id: str, timestamp_obj: datetime.datetime) -> list[dict]:
    """Retrieves messages after a specific datetime object."""
    # Takes datetime object, adapter converts it for comparison
    # Converter automatically handles 'timestamp' field on retrieval
    logger.debug(f"DB: Getting messages after {timestamp_obj.isoformat()} for conversation {conversation_id}")
    messages = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Adapter converts timestamp_obj for the comparison
            cursor.execute(
                """SELECT message_id, timestamp, role, content FROM chat_messages
                   WHERE conversation_id = ? AND timestamp > ?
                   ORDER BY timestamp""",
                (conversation_id, timestamp_obj)
            )
            rows = cursor.fetchall()
            # 'timestamp' will be datetime object
            messages = [{"id": row["message_id"], "timestamp": row["timestamp"], "role": row["role"], "content": row["content"]} for row in rows]
            logger.debug(f"Found {len(messages)} messages after {timestamp_obj.isoformat()} for conversation {conversation_id}")
    except sqlite3.Error as e:
        logger.error(f"DB Error getting messages after {timestamp_obj.isoformat()} for {conversation_id}: {e}", exc_info=True)
    except Exception as e_conv: # Catch potential errors converting timestamp if not datetime
        logger.error(f"Error processing timestamp for retrieval: {e_conv}", exc_info=True)
    return messages

# --- Settings Functions ---
# (No changes needed)
def save_setting(key: str, value: str) -> bool:
    logger.debug(f"DB: Saving setting '{key}'")
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
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
            deleted_count = cursor.rowcount
            conn.commit()
            if deleted_count > 0:
                logger.info(f"Setting '{key}' deleted.")
                return True
            else:
                logger.warning(f"Setting '{key}' not found for deletion.")
                return False
    except sqlite3.Error as e:
        logger.error(f"DB Error deleting setting '{key}': {e}", exc_info=True)
        return False

# --- Initialize DB on module import ---
# This ensures create_tables() and adapter registration happens early
logger.debug("Running initial create_tables() on database module import.")
create_tables()