# app/data/database.py
# Version: 2.2.1 - Regenerated with full implementations
import sqlite3
import datetime
import json
import uuid
import logging
from pathlib import Path
from contextlib import contextmanager

# Get a logger instance for this module
logger = logging.getLogger(__name__)

# Define DB path relative to this file's location for robustness
# Assuming this file is in app/data/, the project root is parent.parent
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
        conn.execute("PRAGMA foreign_keys = ON")
        logger.debug("Database connection successful.")
        yield conn
    except sqlite3.Error as e:
        logger.critical(f"Database connection/operation failed for {DB_NAME}: {e}", exc_info=True)
        # Re-raise or handle as appropriate for your app's error strategy
        raise # Raising allows calling functions to handle DB errors
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
            cursor.execute('''CREATE TABLE IF NOT EXISTS instructions (
                                name TEXT PRIMARY KEY,
                                instruction_text TEXT NOT NULL,
                                timestamp DATETIME NOT NULL
                             )''')
            # Conversations Table Check/Migration
            logger.debug("Checking 'conversations' table schema.")
            needs_migration = False
            try: cursor.execute("SELECT generation_config_json FROM conversations LIMIT 1")
            except sqlite3.OperationalError: needs_migration = True

            if needs_migration:
                try:
                    logger.warning("Attempting simple migration for 'conversations'.")
                    cursor.execute("ALTER TABLE conversations ADD COLUMN generation_config_json TEXT")
                    cursor.execute("ALTER TABLE conversations ADD COLUMN system_instruction TEXT")
                    cursor.execute("ALTER TABLE conversations ADD COLUMN added_paths_json TEXT")
                    conn.commit() # Commit schema changes
                    logger.info("Simple migration successful for 'conversations'.")
                except sqlite3.Error as alter_err:
                    logger.error(f"ALERT: Failed to ALTER 'conversations' table ({alter_err}). Manual migration might be needed.", exc_info=True)

            # Ensure Conversations Table Exists
            logger.debug("Ensuring 'conversations' table structure.")
            cursor.execute('''CREATE TABLE IF NOT EXISTS conversations (
                                conversation_id TEXT PRIMARY KEY,
                                title TEXT,
                                start_timestamp DATETIME NOT NULL,
                                last_update_timestamp DATETIME NOT NULL,
                                generation_config_json TEXT,
                                system_instruction TEXT,
                                added_paths_json TEXT
                             )''')
            # Chat Messages Table
            logger.debug("Checking/Creating 'chat_messages' table.")
            cursor.execute('''CREATE TABLE IF NOT EXISTS chat_messages (
                                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                conversation_id TEXT NOT NULL,
                                timestamp DATETIME NOT NULL,
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
            conn.commit() # Commit table creation if needed
            logger.info("Database tables check/creation/update complete.")
    except sqlite3.Error as e:
        logger.error(f"Database table creation/check error during connection: {e}", exc_info=True)
    # Connection is closed automatically by context manager

# --- Instruction Functions ---
def save_instruction(name: str, text: str) -> tuple[bool, str]:
    """Saves or updates a system instruction."""
    logger.debug(f"DB: Attempting to save instruction '{name}'")
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
    """Loads a system instruction by name."""
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
    """Gets a list of all saved instruction names."""
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
    """Deletes a system instruction by name."""
    logger.warning(f"DB: Attempting to delete instruction '{name}'")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM instructions WHERE name = ?", (name,))
            changes = conn.total_changes
            conn.commit()
            if changes > 0:
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
    """Creates a new conversation record and returns its ID."""
    logger.debug("DB: Starting new conversation")
    new_id = str(uuid.uuid4())
    now = datetime.datetime.now()
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO conversations (conversation_id, title, start_timestamp, last_update_timestamp) VALUES (?, ?, ?, ?)",
                (new_id, None, now, now) # Start with no title
            )
            conn.commit()
            logger.info(f"New conversation started with ID: {new_id}")
            return new_id
    except sqlite3.Error as e:
        logger.error(f"DB Error starting new conversation: {e}", exc_info=True)
        return None

def update_conversation_metadata(conversation_id: str, title: str = None, generation_config: dict = None, system_instruction: str = None, added_paths: set = None) -> bool:
    """Updates metadata for a given conversation."""
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
        # Convert set to list for JSON serialization
        params.append(json.dumps(list(added_paths)))

    if not updates:
        logger.warning(f"No metadata provided to update for conversation {conversation_id}")
        return True # No change needed is considered success

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
    """Retrieves metadata for a specific conversation."""
    logger.debug(f"DB: Getting metadata for conversation {conversation_id}")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
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
    """Gets a list of recent conversations."""
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
            convos = [{"id": row["conversation_id"], "title": row["title"] or PLACEHOLDER_TITLE, "last_update": row["last_update_timestamp"]} for row in rows]
            logger.debug(f"Found {len(convos)} recent conversations.")
    except sqlite3.Error as e:
        logger.error(f"DB Error getting recent conversations: {e}", exc_info=True)
    return convos

def delete_conversation(conversation_id: str) -> tuple[bool, str]:
    """Deletes a conversation and its messages (via CASCADE)."""
    logger.warning(f"DB: Attempting to delete conversation {conversation_id}")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Foreign key constraint with ON DELETE CASCADE should handle chat_messages
            cursor.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))
            changes = conn.total_changes
            conn.commit()
            if changes > 0:
                logger.info(f"Conversation {conversation_id} deleted successfully.")
                return True, f"Conversation deleted."
            else:
                logger.warning(f"Conversation {conversation_id} not found for deletion.")
                return False, f"Conversation not found."
    except sqlite3.Error as e:
        logger.error(f"DB Error deleting conversation {conversation_id}: {e}", exc_info=True)
        return False, f"Database error deleting conversation: {e}"

def update_conversation_timestamp(conversation_id: str) -> bool:
    """Updates the last_update_timestamp for a conversation."""
    logger.debug(f"DB: Updating timestamp for conversation {conversation_id}")
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
def save_message(conversation_id: str, role: str, content: str, model_used: str = None, context_files: list = None, full_prompt_sent: str = None) -> bool:
    """Saves a chat message to the database."""
    logger.debug(f"DB: Saving message for conversation {conversation_id} (Role: {role})")
    now = datetime.datetime.now()
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
            # Crucially, update the conversation's last update time as well
            cursor.execute(
                "UPDATE conversations SET last_update_timestamp = ? WHERE conversation_id = ?",
                (now, conversation_id)
            )
            conn.commit() # Commit both insert and update
            logger.info(f"Message saved successfully for conversation {conversation_id}")
            return True
    except sqlite3.Error as e:
        logger.error(f"DB Error saving message for conversation {conversation_id}: {e}", exc_info=True)
        return False

def get_conversation_messages(conversation_id: str, include_ids_timestamps: bool = False) -> list[dict]:
    """Retrieves messages for a conversation, ordered by timestamp."""
    logger.debug(f"DB: Getting messages for conversation {conversation_id} (Include IDs/TS: {include_ids_timestamps})")
    messages = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT message_id, timestamp, role, content FROM chat_messages WHERE conversation_id = ? ORDER BY timestamp",
                (conversation_id,)
            )
            rows = cursor.fetchall()
            if include_ids_timestamps:
                messages = [{"id": row["message_id"], "timestamp": row["timestamp"], "role": row["role"], "content": row["content"]} for row in rows]
            else:
                # Format for Gemini API history reconstruction (role/content only)
                messages = [{"role": row["role"], "content": row["content"]} for row in rows]
            logger.debug(f"Retrieved {len(messages)} messages for conversation {conversation_id}.")
    except sqlite3.Error as e:
        logger.error(f"DB Error getting messages for conversation {conversation_id}: {e}", exc_info=True)
        # Return empty list on error
    return messages

def delete_message_by_id(message_id: int) -> tuple[bool, str]:
    """Deletes a single message by its ID."""
    logger.warning(f"DB: Attempting to delete message ID {message_id}")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # We might need the conversation ID to update its timestamp? Or maybe not required for single delete.
            # Let's assume not for now.
            cursor.execute("DELETE FROM chat_messages WHERE message_id = ?", (message_id,))
            changes = conn.total_changes
            conn.commit()
            if changes > 0:
                logger.info(f"Message ID {message_id} deleted successfully.")
                return True, "Message deleted."
            else:
                logger.warning(f"Message ID {message_id} not found for deletion.")
                return False, "Message not found."
    except sqlite3.Error as e:
        logger.error(f"DB Error deleting message ID {message_id}: {e}", exc_info=True)
        return False, f"Database error deleting message: {e}"

def delete_messages_after_timestamp(conversation_id: str, timestamp_str: str) -> tuple[bool, str]:
    """Deletes messages in a conversation that occurred after a given timestamp."""
    logger.warning(f"DB: Attempting to delete messages after {timestamp_str} for conversation {conversation_id}")
    try:
        # Convert timestamp string to datetime object for comparison if needed,
        # but SQLite can compare ISO8601 strings directly.
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM chat_messages WHERE conversation_id = ? AND timestamp > ?",
                (conversation_id, timestamp_str)
            )
            changes = conn.total_changes # Note: total_changes might reflect session changes, cursor.rowcount is often better for last query
            deleted_count = cursor.rowcount
            conn.commit()
            logger.info(f"Deleted {deleted_count} message(s) after {timestamp_str} for conversation {conversation_id}.")
            # Also update conversation timestamp? Deleting history should arguably update it.
            update_conversation_timestamp(conversation_id)
            return True, f"Deleted {deleted_count} message(s)."
    except sqlite3.Error as e:
        logger.error(f"DB Error deleting messages after {timestamp_str} for {conversation_id}: {e}", exc_info=True)
        return False, f"Database error deleting messages: {e}"

def update_message_content(message_id: int, new_content: str) -> tuple[bool, str]:
    """Updates the content of a specific message."""
    logger.debug(f"DB: Updating content for message ID {message_id}")
    now = datetime.datetime.now() # Update timestamp? Assumed not based on action logic, but could be added.
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Also update conversation timestamp when a message is edited
            convo_id_row = cursor.execute("SELECT conversation_id FROM chat_messages WHERE message_id = ?", (message_id,)).fetchone()

            cursor.execute(
                "UPDATE chat_messages SET content = ? WHERE message_id = ?",
                (new_content, message_id)
            )
            changes = cursor.rowcount
            if changes > 0 and convo_id_row:
                cursor.execute("UPDATE conversations SET last_update_timestamp = ? WHERE conversation_id = ?", (now, convo_id_row['conversation_id']))
                conn.commit() # Commit both updates
                logger.info(f"Content updated for message ID {message_id}.")
                return True, "Message content updated."
            elif changes <= 0:
                conn.rollback() # Nothing was updated
                logger.warning(f"Message ID {message_id} not found for content update.")
                return False, "Message not found for update."
            else: # Changes > 0 but convo_id not found (shouldn't happen)
                conn.rollback()
                logger.error(f"Message ID {message_id} updated, but failed to find parent conversation ID.")
                return False, "Message updated, but failed to update conversation timestamp."
    except sqlite3.Error as e:
        logger.error(f"DB Error updating content for message ID {message_id}: {e}", exc_info=True)
        return False, f"Database error updating message: {e}"

def get_messages_after_timestamp(conversation_id: str, timestamp_str: str) -> list[dict]:
    """Retrieves messages after a specific timestamp, including IDs and timestamps."""
    logger.debug(f"DB: Getting messages after {timestamp_str} for conversation {conversation_id}")
    messages = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT message_id, timestamp, role, content FROM chat_messages
                   WHERE conversation_id = ? AND timestamp > ?
                   ORDER BY timestamp""",
                (conversation_id, timestamp_str)
            )
            rows = cursor.fetchall()
            # Format suitable for display/processing, includes IDs/timestamps
            messages = [{"id": row["message_id"], "timestamp": row["timestamp"], "role": row["role"], "content": row["content"]} for row in rows]
            logger.debug(f"Found {len(messages)} messages after {timestamp_str} for conversation {conversation_id}")
    except sqlite3.Error as e:
        logger.error(f"DB Error getting messages after {timestamp_str} for {conversation_id}: {e}", exc_info=True)
    return messages

# --- Settings Functions ---
def save_setting(key: str, value: str) -> bool:
    """Saves or updates a setting."""
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
    """Loads a setting value."""
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
    """Deletes a setting."""
    logger.warning(f"DB: Attempting to delete setting '{key}'")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
            changes = conn.total_changes
            conn.commit()
            if changes > 0:
                logger.info(f"Setting '{key}' deleted.")
                return True
            else:
                logger.warning(f"Setting '{key}' not found for deletion.")
                return False # Not found isn't really an error, but indicates no change
    except sqlite3.Error as e:
        logger.error(f"DB Error deleting setting '{key}': {e}", exc_info=True)
        return False

# --- Initialize DB on module import ---
logger.debug("Running initial create_tables() on database module import.")
create_tables() # Ensure tables are ready when this module is loaded