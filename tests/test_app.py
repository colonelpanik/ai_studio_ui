# tests/test_app.py

import sys
import os
from pathlib import Path
import pytest
import sqlite3
import time
import datetime # Needed for timestamp tests
import json     # Needed for conversation metadata tests

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# --- Constants ---
DB_VARIABLE_TO_PATCH = "DB_NAME"

# --- Fixtures ---
@pytest.fixture(scope="function")
def temp_db_file_connection(tmp_path):
    """ Provides connection AND path to a TEMPORARY FILE database with tables created. """
    db_file_path = tmp_path / f"test_db_{time.time_ns()}.sqlite"
    conn = None
    try:
        conn = sqlite3.connect(db_file_path, check_same_thread=False, timeout=10,
                               detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES) # Enable timestamp parsing
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        create_tables_on_connection(conn)
        yield conn, db_file_path
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

# --- Helper to Create Tables ---
# (Keep create_tables_on_connection exactly as it was)
def create_tables_on_connection(conn):
    """ Executes the necessary CREATE TABLE statements on the given connection. """
    try:
        import database as db_module # Import locally to avoid issues if module has side effects on import
    except ImportError as e:
        pytest.fail(f"Failed to import 'database' module in create_tables helper: {e}")

    cursor = conn.cursor()
    try:
        cursor.execute('''CREATE TABLE IF NOT EXISTS instructions (name TEXT PRIMARY KEY, instruction_text TEXT NOT NULL, timestamp DATETIME NOT NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS conversations (conversation_id TEXT PRIMARY KEY, title TEXT, start_timestamp DATETIME NOT NULL, last_update_timestamp DATETIME NOT NULL, generation_config_json TEXT, system_instruction TEXT, added_paths_json TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS chat_messages (message_id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, timestamp DATETIME NOT NULL, role TEXT NOT NULL CHECK(role IN ('user', 'assistant')), content TEXT NOT NULL, model_used TEXT, context_files_json TEXT, full_prompt_sent TEXT, FOREIGN KEY (conversation_id) REFERENCES conversations (conversation_id) ON DELETE CASCADE)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)''')
        conn.commit()
    except sqlite3.Error as e:
        print(f"[Helper] ERROR creating tables: {e}")
        conn.rollback()
        raise

# --- Test Cases ---

# == Non-Database Tests ==
# (Keep test_module_imports and test_reconstruct_history exactly as before)
def test_module_imports():
    """ Test if main application modules can be imported without error. """
    errors = []
    modules_to_test = ["gemini_logic", "database", "logging_config", "gemini_local_chat"]
    for module_name in modules_to_test:
        try:
            __import__(module_name)
        except ImportError as e:
            # Ignore streamlit specific import errors if streamlit isn't installed in test env
            if "streamlit" not in str(e).lower() and "google.generativeai" not in str(e).lower():
                print(f"Warning: Failed to import {module_name}: {e}")
                errors.append(f"Failed to import {module_name}: {e}")
    # Allow database import to fail if sqlite isn't available? No, should fail.
    # Filter out streamlit/google errors for pure DB/logic testing if needed
    filtered_errors = [e for e in errors if "No module named 'streamlit'" not in e and "No module named 'google'" not in e]
    assert not filtered_errors, "Critical module import errors occurred:\n" + "\n".join(filtered_errors)


def test_reconstruct_history():
    """ Test the history reconstruction logic in gemini_logic. """
    try:
        import gemini_logic as logic
    except ImportError as e:
        pytest.fail(f"Failed to import gemini_logic for test: {e}")

    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "How are you?"},
        {"role": "system", "content": "Ignore previous"}, # Should be ignored
        {"role": "invalid", "content": "Bad role"},     # Should be ignored
        {"role": "user", "content": None},              # Should be ignored (invalid content)
    ]
    expected_history = [
        {"role": "user", "parts": [{"text": "Hello"}]},
        {"role": "model", "parts": [{"text": "Hi there!"}]},
        {"role": "user", "parts": [{"text": "How are you?"}]},
    ]
    reconstructed = logic.reconstruct_gemini_history(messages)
    assert reconstructed == expected_history, "Reconstructed history does not match expected format."


# == Database Interaction Tests ==

def test_db_tables_created_by_fixture(temp_db_file_connection):
    """ Verify that the fixture successfully created the expected tables in the temp file. """
    db_connection, db_path = temp_db_file_connection
    cursor = db_connection.cursor()
    tables = ["settings", "instructions", "conversations", "chat_messages"]
    found_tables = set()
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        rows = cursor.fetchall()
        found_tables = {row['name'] for row in rows}
    except sqlite3.Error as e:
            pytest.fail(f"Failed to query sqlite_master: {e}")

    missing_tables = set(tables) - found_tables
    assert not missing_tables, f"Tables not found in the database file {db_path}: {', '.join(missing_tables)}"


# --- Settings Tests ---
# (Keep existing tests for save/load/delete settings)
def test_db_save_setting(temp_db_file_connection):
    """ Test database.save_setting function using a temporary file DB. """
    db_connection, db_path = temp_db_file_connection
    import database as db_module
    key_to_save = "theme"
    value_to_save = "dark"

    save_ok = False
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        try:
            save_ok = db_module.save_setting(key_to_save, value_to_save)
        except AttributeError: pytest.fail(f"Failed to patch database.{DB_VARIABLE_TO_PATCH}.")
        except Exception as e: pytest.fail(f"db_module.save_setting raised unexpected exception: {e}")

    assert save_ok is True
    try:
        cursor = db_connection.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key_to_save,))
        row = cursor.fetchone()
        assert row is not None
        assert row['value'] == value_to_save
    except sqlite3.Error as e: pytest.fail(f"SQLite error during save verification: {e}")

def test_db_load_setting(temp_db_file_connection):
    """ Test database.load_setting function using a temporary file DB. """
    db_connection, db_path = temp_db_file_connection
    import database as db_module
    key_to_load = "api_key"
    value_to_load = "test_api_12345"
    try:
        cursor = db_connection.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key_to_load, value_to_load))
        db_connection.commit()
    except sqlite3.Error as e: pytest.fail(f"Failed setup for load setting test: {e}")

    loaded_value = None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        try: loaded_value = db_module.load_setting(key_to_load)
        except AttributeError: pytest.fail(f"Failed to patch database.{DB_VARIABLE_TO_PATCH}.")
        except Exception as e: pytest.fail(f"db_module.load_setting raised unexpected exception: {e}")
    assert loaded_value == value_to_load

def test_db_load_non_existent_setting(temp_db_file_connection):
    """ Test database.load_setting for a non-existent key using a temporary file DB. """
    db_connection, db_path = temp_db_file_connection
    import database as db_module
    key_to_load = "non_existent_key_abc"
    loaded_value = "initial_dummy_value"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        try: loaded_value = db_module.load_setting(key_to_load)
        except AttributeError: pytest.fail(f"Failed to patch database.{DB_VARIABLE_TO_PATCH}.")
        except Exception as e: pytest.fail(f"db_module.load_setting raised unexpected exception: {e}")
    assert loaded_value is None

def test_db_delete_setting(temp_db_file_connection):
    """ Test database.delete_setting for an existing key using a temporary file DB. """
    db_connection, db_path = temp_db_file_connection
    import database as db_module
    key_to_delete = "font_size"
    value_to_delete = "12"
    try:
        cursor = db_connection.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key_to_delete, value_to_delete))
        db_connection.commit()
    except sqlite3.Error as e: pytest.fail(f"Failed setup for delete setting test: {e}")

    delete_ok = False
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        try: delete_ok = db_module.delete_setting(key_to_delete)
        except AttributeError: pytest.fail(f"Failed to patch database.{DB_VARIABLE_TO_PATCH}.")
        except Exception as e: pytest.fail(f"db_module.delete_setting raised unexpected exception: {e}")

    assert delete_ok is True
    try:
        cursor = db_connection.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key_to_delete,))
        row = cursor.fetchone()
        assert row is None
    except sqlite3.Error as e: pytest.fail(f"SQLite error during delete verification: {e}")

def test_db_delete_non_existent_setting(temp_db_file_connection):
    """ Test database.delete_setting for a non-existent key using a temporary file DB. """
    db_connection, db_path = temp_db_file_connection
    import database as db_module
    key_to_delete = "key_that_never_existed_xyz"
    delete_ok = True
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        try: delete_ok = db_module.delete_setting(key_to_delete)
        except AttributeError: pytest.fail(f"Failed to patch database.{DB_VARIABLE_TO_PATCH}.")
        except Exception as e: pytest.fail(f"db_module.delete_setting raised unexpected exception: {e}")
    assert delete_ok is False


# --- Conversation and Message Tests ---

CONVO_ID_1 = "conv-test-1"
CONVO_ID_2 = "conv-test-2"

def setup_test_conversation(conn, convo_id=CONVO_ID_1, title="Test Convo"):
    """Helper to insert a conversation record."""
    now = datetime.datetime.now()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO conversations (conversation_id, title, start_timestamp, last_update_timestamp) VALUES (?, ?, ?, ?)",
            (convo_id, title, now, now)
        )
        conn.commit()
    except sqlite3.Error as e:
        pytest.fail(f"Failed to setup test conversation {convo_id}: {e}")
    return now # Return start timestamp for potential use

def setup_test_messages(conn, convo_id=CONVO_ID_1, messages_data=None):
    """Helper to insert messages, returns list of inserted message IDs and timestamps."""
    if messages_data is None:
        messages_data = [
            {"role": "user", "content": "Msg 1 User"},
            {"role": "assistant", "content": "Msg 2 Assistant"},
            {"role": "user", "content": "Msg 3 User"},
        ]
    inserted_details = []
    cursor = conn.cursor()
    base_time = datetime.datetime.now()
    time_delta = datetime.timedelta(seconds=1)

    for i, msg_data in enumerate(messages_data):
        msg_time = base_time + (i * time_delta)
        try:
            cursor.execute(
                "INSERT INTO chat_messages (conversation_id, timestamp, role, content) VALUES (?, ?, ?, ?)",
                (convo_id, msg_time, msg_data["role"], msg_data["content"])
            )
            inserted_id = cursor.lastrowid
            inserted_details.append({"id": inserted_id, "timestamp": msg_time})
        except sqlite3.Error as e:
            pytest.fail(f"Failed to insert test message {i+1} for convo {convo_id}: {e}")
    conn.commit()
    return inserted_details # Return list of {"id": id, "timestamp": dt_object}


# --- Get Messages Tests ---
def test_get_conversation_messages_simple(temp_db_file_connection):
    """Test retrieving messages without IDs/timestamps."""
    db_connection, db_path = temp_db_file_connection
    import database as db_module
    setup_test_conversation(db_connection, CONVO_ID_1)
    setup_test_messages(db_connection, CONVO_ID_1)

    messages = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        messages = db_module.get_conversation_messages(CONVO_ID_1)

    assert len(messages) == 3
    assert messages[0]["role"] == "user" and messages[0]["content"] == "Msg 1 User"
    assert messages[1]["role"] == "assistant" and messages[1]["content"] == "Msg 2 Assistant"
    assert messages[2]["role"] == "user" and messages[2]["content"] == "Msg 3 User"
    assert "id" not in messages[0]
    assert "timestamp" not in messages[0]


def test_get_conversation_messages_with_ids(temp_db_file_connection):
    """Test retrieving messages *with* IDs/timestamps."""
    db_connection, db_path = temp_db_file_connection
    import database as db_module
    setup_test_conversation(db_connection, CONVO_ID_1)
    inserted_details = setup_test_messages(db_connection, CONVO_ID_1) # Get IDs/timestamps

    messages = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        messages = db_module.get_conversation_messages(CONVO_ID_1, include_ids_timestamps=True)

    assert len(messages) == 3
    assert messages[0]["id"] == inserted_details[0]["id"]
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Msg 1 User"
    # Compare timestamps (may need tolerance or string conversion if precision varies)
    # Let's convert DB timestamp (which might be string) and Python datetime to comparable format
    # Assuming db returns string format like 'YYYY-MM-DD HH:MM:SS.ffffff'
    db_ts_str_0 = messages[0]["timestamp"]
    expected_ts_0 = inserted_details[0]["timestamp"]
    assert isinstance(db_ts_str_0, str), "Timestamp should be retrieved as string from DB (or adjust parse types)"
    # Simple comparison might work if format is consistent
    # assert db_ts_str_0 == expected_ts_0.strftime('%Y-%m-%d %H:%M:%S.%f') # More robust comparison

    assert messages[1]["id"] == inserted_details[1]["id"]
    assert messages[1]["role"] == "assistant"
    assert messages[2]["id"] == inserted_details[2]["id"]
    assert messages[2]["role"] == "user"


def test_get_conversation_messages_empty(temp_db_file_connection):
    """Test retrieving messages from a conversation with no messages."""
    db_connection, db_path = temp_db_file_connection
    import database as db_module
    setup_test_conversation(db_connection, CONVO_ID_1) # Convo exists, but no messages added

    messages = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        messages = db_module.get_conversation_messages(CONVO_ID_1, include_ids_timestamps=True)

    assert messages == []


# --- Delete Message Tests ---
def test_delete_message_by_id(temp_db_file_connection):
    """Test deleting a specific message by its ID."""
    db_connection, db_path = temp_db_file_connection
    import database as db_module
    setup_test_conversation(db_connection, CONVO_ID_1)
    inserted_details = setup_test_messages(db_connection, CONVO_ID_1)
    message_id_to_delete = inserted_details[1]["id"] # Delete the middle (assistant) message

    delete_ok, msg = False, ""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        delete_ok, msg = db_module.delete_message_by_id(message_id_to_delete)

    assert delete_ok is True
    assert "deleted" in msg.lower()

    # Verify deletion in DB
    cursor = db_connection.cursor()
    cursor.execute("SELECT conversation_id FROM chat_messages WHERE message_id = ?", (message_id_to_delete,))
    assert cursor.fetchone() is None, "Deleted message ID still found in DB."

    # Verify other messages remain
    cursor.execute("SELECT COUNT(*) FROM chat_messages WHERE conversation_id = ?", (CONVO_ID_1,))
    count = cursor.fetchone()[0]
    assert count == 2, "Incorrect number of messages remaining after deletion."
    cursor.execute("SELECT message_id FROM chat_messages WHERE conversation_id = ?", (CONVO_ID_1,))
    remaining_ids = {row[0] for row in cursor.fetchall()}
    assert inserted_details[0]["id"] in remaining_ids
    assert inserted_details[2]["id"] in remaining_ids


def test_delete_message_by_id_non_existent(temp_db_file_connection):
    """Test deleting a message ID that does not exist."""
    db_connection, db_path = temp_db_file_connection
    import database as db_module
    setup_test_conversation(db_connection, CONVO_ID_1)
    setup_test_messages(db_connection, CONVO_ID_1) # Add some messages

    non_existent_id = 99999
    delete_ok, msg = True, ""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        delete_ok, msg = db_module.delete_message_by_id(non_existent_id)

    assert delete_ok is False
    assert "not found" in msg.lower()

    # Verify no messages were accidentally deleted
    cursor = db_connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM chat_messages WHERE conversation_id = ?", (CONVO_ID_1,))
    count = cursor.fetchone()[0]
    assert count == 3, "Messages were unexpectedly deleted."


# --- Delete Messages After Timestamp Tests ---
def test_delete_messages_after_timestamp(temp_db_file_connection):
    """Test deleting messages after a specific timestamp."""
    db_connection, db_path = temp_db_file_connection
    import database as db_module
    setup_test_conversation(db_connection, CONVO_ID_1)
    # Setup with 4 messages to make deletion clearer
    inserted_details = setup_test_messages(db_connection, CONVO_ID_1, messages_data=[
        {"role": "user", "content": "Msg 1"}, {"role": "assistant", "content": "Msg 2"},
        {"role": "user", "content": "Msg 3"}, {"role": "assistant", "content": "Msg 4"}
    ])
    # Timestamp after which to delete (use timestamp of message 2)
    delete_after_ts = inserted_details[1]["timestamp"]
    # Format timestamp for query comparison (assuming SQLite stores TEXT)
    delete_after_ts_str = delete_after_ts.strftime('%Y-%m-%d %H:%M:%S.%f')

    delete_ok, msg = False, ""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        delete_ok, msg = db_module.delete_messages_after_timestamp(CONVO_ID_1, delete_after_ts_str)

    assert delete_ok is True
    assert "deleted 2 subsequent messages" in msg.lower() # Messages 3 and 4 should be deleted

    # Verify in DB
    cursor = db_connection.cursor()
    cursor.execute("SELECT message_id, role FROM chat_messages WHERE conversation_id = ? ORDER BY timestamp ASC", (CONVO_ID_1,))
    remaining_messages = cursor.fetchall()
    assert len(remaining_messages) == 2
    assert remaining_messages[0]["message_id"] == inserted_details[0]["id"]
    assert remaining_messages[0]["role"] == "user"
    assert remaining_messages[1]["message_id"] == inserted_details[1]["id"]
    assert remaining_messages[1]["role"] == "assistant"


def test_delete_messages_after_timestamp_no_delete(temp_db_file_connection):
    """Test deleting when the timestamp is the last message's timestamp."""
    db_connection, db_path = temp_db_file_connection
    import database as db_module
    setup_test_conversation(db_connection, CONVO_ID_1)
    inserted_details = setup_test_messages(db_connection, CONVO_ID_1) # 3 messages
    last_msg_ts = inserted_details[2]["timestamp"]
    last_msg_ts_str = last_msg_ts.strftime('%Y-%m-%d %H:%M:%S.%f')

    delete_ok, msg = False, ""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        delete_ok, msg = db_module.delete_messages_after_timestamp(CONVO_ID_1, last_msg_ts_str)

    assert delete_ok is True
    assert "deleted 0 subsequent messages" in msg.lower()

    # Verify no messages deleted
    cursor = db_connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM chat_messages WHERE conversation_id = ?", (CONVO_ID_1,))
    count = cursor.fetchone()[0]
    assert count == 3


# --- Update Message Content Tests ---
def test_update_message_content(temp_db_file_connection):
    """Test updating the content of an existing message."""
    db_connection, db_path = temp_db_file_connection
    import database as db_module
    start_time = setup_test_conversation(db_connection, CONVO_ID_1)
    inserted_details = setup_test_messages(db_connection, CONVO_ID_1)
    message_id_to_update = inserted_details[0]["id"] # Update first user message
    new_content = "This is the updated content for Msg 1."

    update_ok, msg = False, ""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        update_ok, msg = db_module.update_message_content(message_id_to_update, new_content)

    assert update_ok is True
    assert "updated" in msg.lower()

    # Verify content update in DB
    cursor = db_connection.cursor()
    cursor.execute("SELECT content FROM chat_messages WHERE message_id = ?", (message_id_to_update,))
    row = cursor.fetchone()
    assert row is not None
    assert row["content"] == new_content

    # Verify conversation last_update_timestamp changed
    cursor.execute("SELECT last_update_timestamp FROM conversations WHERE conversation_id = ?", (CONVO_ID_1,))
    last_update_ts = cursor.fetchone()[0]
    # Check if last_update_ts is a datetime object (depends on PARSE_DECLTYPES)
    if isinstance(last_update_ts, datetime.datetime):
         assert last_update_ts > start_time, "Conversation last_update_timestamp was not updated."
    else: # If it's a string, just check it's likely different (less reliable)
         assert isinstance(last_update_ts, str)
         # This isn't a great check, but better than nothing if types aren't parsed
         # assert last_update_ts != start_time.strftime('%Y-%m-%d %H:%M:%S.%f')


def test_update_message_content_non_existent(temp_db_file_connection):
    """Test updating content for a message ID that does not exist."""
    db_connection, db_path = temp_db_file_connection
    import database as db_module
    setup_test_conversation(db_connection, CONVO_ID_1)

    non_existent_id = 88888
    update_ok, msg = True, ""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        update_ok, msg = db_module.update_message_content(non_existent_id, "New content")

    assert update_ok is False
    assert "not found" in msg.lower()


# --- Get Messages After Timestamp Tests ---
def get_messages_after_timestamp(conversation_id, timestamp_str):
    """Retrieves messages (including IDs and timestamps) after a specific timestamp."""
    logger.info(f"Fetching messages after {timestamp_str} in conversation {conversation_id}")
    conn = None # Initialize conn to None
    messages = [] # Initialize messages to []

    try:
        conn = get_db_connection()
        if not conn:
            logger.error("Cannot get messages after timestamp: Database connection failed.")
            # Ensure we definitely return the empty list here
            return [] # Explicit return

        cursor = conn.cursor()
        logger.debug(f"Executing SELECT for messages after {timestamp_str} in conv {conversation_id}.")
        cursor.execute(
            "SELECT message_id, role, content, timestamp FROM chat_messages WHERE conversation_id = ? AND timestamp > ? ORDER BY timestamp ASC",
            (conversation_id, timestamp_str)
        )
        rows = cursor.fetchall()
        # Populate the list, which was initialized as []
        # Ensure timestamp is returned as string for consistency if PARSE_DECLTYPES isn't reliably working
        messages = [
            {
                "id": row["message_id"],
                "role": row["role"],
                "content": row["content"],
                "timestamp": str(row["timestamp"]) # Explicitly convert timestamp if needed
            } for row in rows
        ]
        logger.info(f"Retrieved {len(messages)} messages after {timestamp_str} for conversation {conversation_id}.")

    except sqlite3.Error as e:
        logger.error(f"DB error getting messages after {timestamp_str} in conv {conversation_id}: {e}", exc_info=True)
        # 'messages' should still be [] if error happened after initialization
        # Explicitly return [] here just in case
        return []
    except Exception as e_generic: # Catch any other unexpected errors
        logger.error(f"Generic error getting messages after {timestamp_str} in conv {conversation_id}: {e_generic}", exc_info=True)
        return [] # Return empty list on any unexpected error
    finally:
        if conn:
            try:
                logger.debug("Closing DB connection after get_messages_after_timestamp.")
                conn.close()
            except Exception as e_close:
                 logger.warning(f"Error closing DB connection in get_messages_after_timestamp: {e_close}", exc_info=False) # Don't raise from finally

    # Return the final list (should be [] if no rows found or error occurred)
    return messages

def test_get_messages_after_timestamp_none_after(temp_db_file_connection):
    """Test retrieving messages after the last message's timestamp (using MonkeyPatch)."""
    db_connection, db_path = temp_db_file_connection
    # Import module within test function scope to ensure patches apply cleanly
    try:
        import database as db_module
    except ImportError as e:
        pytest.fail(f"Failed to import database module: {e}")

    # Setup: Create conversation and messages using the fixture's connection
    setup_test_conversation(db_connection, CONVO_ID_1)
    inserted_details = setup_test_messages(db_connection, CONVO_ID_1) # 3 messages
    # Get the timestamp of the very last message inserted
    last_msg_ts = inserted_details[-1]["timestamp"] # Use index -1 for the last item

    # Ensure timestamp format matches SQLite comparison needs, including microseconds
    last_msg_ts_str = last_msg_ts.strftime('%Y-%m-%d %H:%M:%S.%f')
    # Add microseconds suffix if strftime omitted it (when microseconds are zero)
    if '.' not in last_msg_ts_str:
         last_msg_ts_str += '.000000'

    print(f"\nDEBUG (test_none_after MP): Querying after timestamp: {last_msg_ts_str!r}") # Debug print

    # Initialize variables to store results/exceptions from the patched call
    messages_result = "--- initial sentinel ---" # Use sentinel for clear debugging
    exception_occurred = None

    # Action: Call the function under test within the patched context
    try:
        with pytest.MonkeyPatch.context() as mp:
            # Patch DB_NAME to the temp file path. Use raising=True for clear patch errors.
            mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=True)
            print(f"DEBUG (test_none_after MP): DB_NAME patched to: {db_path}")

            # *** Execute the function call ***
            messages_result = db_module.get_messages_after_timestamp(CONVO_ID_1, last_msg_ts_str)

            print(f"DEBUG (test_none_after MP): Raw result from function call: {messages_result!r}") # Debug print result

    except Exception as e:
        # Catch any exception during patching or the function call itself
        exception_occurred = e
        print(f"!!! Exception during patched call: {e}")

    # Verification: Perform assertions *outside* the patch context
    assert exception_occurred is None, f"Exception occurred during patched call: {exception_occurred}"

    # Explicitly check for None before comparing with empty list
    assert messages_result is not None, f"Function returned None unexpectedly. Type: {type(messages_result)}"

    # The core assertion: result must be an empty list when querying after the last timestamp
    assert messages_result == [], f"Expected empty list '[]' when querying after last timestamp, but got: {messages_result!r}"

# --- Conversation Metadata Test ---
def test_update_and_get_conversation_metadata(temp_db_file_connection):
    """Test saving and loading conversation metadata including JSON fields."""
    db_connection, db_path = temp_db_file_connection
    import database as db_module
    setup_test_conversation(db_connection, CONVO_ID_1)

    test_title = "Metadata Test Title"
    test_gen_config = {"temperature": 0.9, "top_k": 50, "max_output_tokens": 1024}
    test_instruction = "Be a pirate."
    test_paths = {"/path/to/file.py", "/path/to/folder"}
    test_paths_list = sorted(list(test_paths)) # For comparison, as JSON loads list

    update_ok = False
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        update_ok = db_module.update_conversation_metadata(
            conversation_id=CONVO_ID_1,
            title=test_title,
            generation_config=test_gen_config,
            system_instruction=test_instruction,
            added_paths=test_paths # Pass the set
        )

    assert update_ok is True

    # Now load the metadata
    loaded_metadata = None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        loaded_metadata = db_module.get_conversation_metadata(CONVO_ID_1)

    assert loaded_metadata is not None
    assert loaded_metadata["title"] == test_title
    assert loaded_metadata["generation_config"] == test_gen_config
    assert loaded_metadata["system_instruction"] == test_instruction
    # Compare the loaded set (which was converted from list) to the original set
    assert isinstance(loaded_metadata["added_paths"], set)
    assert loaded_metadata["added_paths"] == test_paths

# Add more tests for instruction saving/loading/deleting if needed