# database.py
# Version: 2.0 - Added conversations table and related functions

import sqlite3
import datetime
import json
import streamlit as st
import uuid # Use UUID for conversation IDs

DB_NAME = "gemini_chat_history.db"

def get_db_connection():
    """Creates a connection to the SQLite database."""
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable foreign key constraint enforcement
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def create_tables():
    """Creates/updates the necessary database tables."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Instructions Table (No change)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS instructions (
                name TEXT PRIMARY KEY, instruction_text TEXT NOT NULL, timestamp DATETIME NOT NULL
            )
        ''')

        # Conversations Table (New)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY, -- Using TEXT for UUID
                title TEXT,                     -- Optional title
                start_timestamp DATETIME NOT NULL,
                last_update_timestamp DATETIME NOT NULL
            )
        ''')

        # Chat Messages Table (Modified)
        # Drop old table if it exists without conversation_id (simple migration for this example)
        # In a production scenario, you'd use ALTER TABLE ADD COLUMN carefully.
        try:
            # Check if conversation_id column exists
            cursor.execute("SELECT conversation_id FROM chat_messages LIMIT 1")
        except sqlite3.OperationalError:
            print("Attempting simple migration: Dropping and recreating chat_messages table.")
            cursor.execute("DROP TABLE IF EXISTS chat_messages") # Drop if schema is old
            cursor.execute('''
                CREATE TABLE chat_messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL, -- Changed to TEXT
                    timestamp DATETIME NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')), -- Removed 'system_instruction' role here
                    content TEXT NOT NULL,
                    model_used TEXT,
                    context_files_json TEXT,
                    full_prompt_sent TEXT, -- Primarily for user messages
                    FOREIGN KEY (conversation_id) REFERENCES conversations (conversation_id) ON DELETE CASCADE
                )
            ''')
        else:
             # If table exists and has the column, ensure it's created if it doesn't exist at all
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


        # Settings Table (No change)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            )
        ''')
        conn.commit()
        print("Database tables checked/created/updated successfully.")
    except sqlite3.Error as e:
        print(f"Database table creation/check error: {e}")
    finally:
        conn.close()

# --- Instruction Functions (Unchanged) ---
def save_instruction(name, text):
    if not name or not text: return False, "Name and instruction text cannot be empty."
    conn = get_db_connection(); ts = datetime.datetime.now()
    try: cursor = conn.cursor(); cursor.execute( "INSERT OR REPLACE INTO instructions (name, instruction_text, timestamp) VALUES (?, ?, ?)", (name.strip(), text, ts)); conn.commit(); return True, f"Instruction '{name}' saved."
    except sqlite3.Error as e: return False, f"DB error saving instruction: {e}"
    finally: conn.close()

def load_instruction(name):
    conn = get_db_connection()
    try: cursor = conn.cursor(); cursor.execute("SELECT instruction_text FROM instructions WHERE name = ?", (name,)); row = cursor.fetchone(); return row['instruction_text'] if row else None
    except sqlite3.Error as e: print(f"DB error loading instruction: {e}"); return None
    finally: conn.close()

def get_instruction_names():
    conn = get_db_connection()
    try: cursor = conn.cursor(); cursor.execute("SELECT name FROM instructions ORDER BY name ASC"); rows = cursor.fetchall(); return [row['name'] for row in rows]
    except sqlite3.Error as e: print(f"DB error getting instruction names: {e}"); return []
    finally: conn.close()

def delete_instruction(name):
    conn = get_db_connection()
    try: cursor = conn.cursor(); cursor.execute("DELETE FROM instructions WHERE name = ?", (name,)); conn.commit(); return True, f"Instruction '{name}' deleted."
    except sqlite3.Error as e: return False, f"DB error deleting instruction: {e}"
    finally: conn.close()


# --- Conversation Functions (New/Modified) ---
def start_new_conversation(title=None):
    """Creates a new conversation record and returns its ID."""
    conn = get_db_connection()
    conv_id = str(uuid.uuid4()) # Generate a unique ID
    now = datetime.datetime.now()
    if title is None:
        title = f"Chat {now.strftime('%Y-%m-%d %H:%M')}" # Default title
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO conversations (conversation_id, title, start_timestamp, last_update_timestamp) VALUES (?, ?, ?, ?)",
            (conv_id, title, now, now)
        )
        conn.commit()
        return conv_id
    except sqlite3.Error as e:
        print(f"DB error starting new conversation: {e}")
        return None
    finally:
        conn.close()

def get_recent_conversations(limit=10):
    """Retrieves recent conversation IDs and titles, ordered by last update time."""
    conn = get_db_connection()
    conversations = []
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT conversation_id, title, last_update_timestamp FROM conversations ORDER BY last_update_timestamp DESC LIMIT ?",
            (limit,)
        )
        rows = cursor.fetchall()
        conversations = [{"id": row["conversation_id"], "title": row["title"], "last_update": row["last_update_timestamp"]} for row in rows]
    except sqlite3.Error as e:
        print(f"DB error getting recent conversations: {e}")
    finally:
        conn.close()
    return conversations

def get_conversation_messages(conversation_id):
    """Retrieves all messages for a specific conversation, ordered by timestamp."""
    conn = get_db_connection()
    messages = []
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content, timestamp FROM chat_messages WHERE conversation_id = ? ORDER BY timestamp ASC",
            (conversation_id,)
        )
        rows = cursor.fetchall()
        # Convert to the simple dict format used by st.session_state.messages
        messages = [{"role": row["role"], "content": row["content"]} for row in rows]
    except sqlite3.Error as e:
        print(f"DB error getting conversation messages for {conversation_id}: {e}")
    finally:
        conn.close()
    return messages

def update_conversation_timestamp(conversation_id):
    """Updates the last_update_timestamp for a conversation."""
    conn = get_db_connection()
    now = datetime.datetime.now()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE conversations SET last_update_timestamp = ? WHERE conversation_id = ?",
            (now, conversation_id)
        )
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"DB error updating conversation timestamp for {conversation_id}: {e}")
        return False
    finally:
        conn.close()

def save_message(conversation_id, role, content, model_used=None, context_files=None, full_prompt_sent=None):
    """Saves a chat message associated with a specific conversation."""
    conn = get_db_connection()
    ts = datetime.datetime.now()
    context_files_json = json.dumps(context_files) if context_files is not None else None # Handle None explicitly
    success = False
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO chat_messages
               (conversation_id, timestamp, role, content, model_used, context_files_json, full_prompt_sent)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (conversation_id, ts, role, content, model_used, context_files_json, full_prompt_sent)
        )
        conn.commit()
        success = True
    except sqlite3.Error as e:
        print(f"DB error saving message: {e}")
        st.toast(f"⚠️ Error saving message to DB: {e}", icon="💾")
    finally:
        conn.close()

    # Update conversation timestamp *after* successfully saving the message
    if success:
        update_conversation_timestamp(conversation_id)

    return success


# --- Settings Functions (Unchanged) ---
def save_setting(key, value):
    conn = get_db_connection()
    try: cursor = conn.cursor(); cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)); conn.commit(); return True
    except sqlite3.Error as e: print(f"DB error saving setting '{key}': {e}"); return False
    finally: conn.close()

def load_setting(key):
    conn = get_db_connection()
    try: cursor = conn.cursor(); cursor.execute("SELECT value FROM settings WHERE key = ?", (key,)); row = cursor.fetchone(); return row['value'] if row else None
    except sqlite3.Error as e: print(f"DB error loading setting '{key}': {e}"); return None
    finally: conn.close()

def delete_setting(key):
    conn = get_db_connection()
    try: cursor = conn.cursor(); cursor.execute("DELETE FROM settings WHERE key = ?", (key,)); conn.commit(); return True
    except sqlite3.Error as e: print(f"DB error deleting setting '{key}': {e}"); return False
    finally: conn.close()

# --- Initialize DB on module import ---
create_tables()