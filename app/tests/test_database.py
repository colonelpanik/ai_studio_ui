# app/tests/test_database.py
# Adapted tests focusing on database interactions, mimicking original structure.

import sys
import os
from pathlib import Path
import pytest
import sqlite3
import time
import datetime # Needed for timestamp tests
import json     # Needed for conversation metadata tests

# --- Setup Project Path ---
# Get the directory of the current test file (app/tests/)
test_dir = Path(__file__).parent
# Get the project root directory (parent of app/)
project_root = test_dir.parent.parent
# Add project root to sys.path to allow imports like 'from app.data import database'
sys.path.insert(0, str(project_root))
print(f"Project root added to sys.path: {project_root}")

# --- Import Target Module ---
# Now we can import the database module using its new path
try:
    from app.data import database as db_module
except ImportError as e:
    pytest.fail(f"Failed to import target module 'app.data.database': {e}\nSys.path: {sys.path}")

# --- Constants ---
# The variable *within the database module* that holds the DB path string.
# Important: Use the actual variable name from app/data/database.py
DB_VARIABLE_TO_PATCH = "DB_NAME"
# Verify the variable exists in the imported module
if not hasattr(db_module, DB_VARIABLE_TO_PATCH):
     pytest.fail(f"The variable '{DB_VARIABLE_TO_PATCH}' does not exist in the imported db_module '{db_module.__name__}'. Check the variable name in app/data/database.py.")


# --- Fixtures ---
@pytest.fixture(scope="function")
def temp_db_file_connection(tmp_path):
    """ Provides connection AND path to a TEMPORARY FILE database with tables created. """
    # Use a unique filename for each test function run
    db_file_path = tmp_path / f"test_db_{time.time_ns()}.sqlite"
    print(f"\n[Fixture] Creating temp DB at: {db_file_path}")
    conn = None
    try:
        # Connect using the path
        conn = sqlite3.connect(db_file_path, check_same_thread=False, timeout=10,
                               detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # Create tables directly on this connection
        create_tables_on_connection(conn)
        print("[Fixture] Tables created.")
        yield conn, db_file_path # Provide connection and path to the test
    finally:
        if conn:
            try:
                conn.close()
                print(f"[Fixture] Closed connection to {db_file_path}")
            except Exception as e:
                print(f"[Fixture] Error closing connection: {e}")
        # Optionally delete the file, but tmp_path fixture handles cleanup
        # if db_file_path.exists():
        #     db_file_path.unlink()
        #     print(f"[Fixture] Deleted temp DB file: {db_file_path}")

# --- Helper to Create Tables (Copied Verbatim) ---
def create_tables_on_connection(conn):
    """ Executes the necessary CREATE TABLE statements on the given connection. """
    cursor = conn.cursor()
    try:
        # Instructions
        cursor.execute('''CREATE TABLE IF NOT EXISTS instructions (name TEXT PRIMARY KEY, instruction_text TEXT NOT NULL, timestamp DATETIME NOT NULL)''')
        # Conversations (including migration columns for compatibility)
        cursor.execute('''CREATE TABLE IF NOT EXISTS conversations ( conversation_id TEXT PRIMARY KEY, title TEXT, start_timestamp DATETIME NOT NULL, last_update_timestamp DATETIME NOT NULL, generation_config_json TEXT, system_instruction TEXT, added_paths_json TEXT )''')
        # Chat Messages
        cursor.execute('''CREATE TABLE IF NOT EXISTS chat_messages ( message_id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, timestamp DATETIME NOT NULL, role TEXT NOT NULL CHECK(role IN ('user', 'assistant')), content TEXT NOT NULL, model_used TEXT, context_files_json TEXT, full_prompt_sent TEXT, FOREIGN KEY (conversation_id) REFERENCES conversations (conversation_id) ON DELETE CASCADE )''')
        # Settings
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings ( key TEXT PRIMARY KEY, value TEXT NOT NULL )''')
        conn.commit()
    except sqlite3.Error as e:
        print(f"[Helper] ERROR creating tables: {e}")
        conn.rollback()
        raise # Fail the setup if tables can't be created


# --- Test Cases ---

# == Basic Setup Tests ==
def test_db_tables_created_by_fixture(temp_db_file_connection):
    """ Verify that the fixture successfully created the expected tables. """
    db_connection, db_path = temp_db_file_connection # Unpack fixture result
    cursor = db_connection.cursor()
    expected_tables = {"settings", "instructions", "conversations", "chat_messages"}
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        rows = cursor.fetchall()
        found_tables = {row['name'] for row in rows if not row['name'].startswith('sqlite_')} # Exclude sqlite internal tables
    except sqlite3.Error as e:
        pytest.fail(f"Failed to query sqlite_master: {e}")

    missing_tables = expected_tables - found_tables
    extra_tables = found_tables - expected_tables
    assert not missing_tables, f"Tables not found in the database file {db_path}: {', '.join(missing_tables)}"
    assert not extra_tables, f"Unexpected tables found in the database file {db_path}: {', '.join(extra_tables)}"


# == Settings Tests (Copied Verbatim - Should work with MonkeyPatch) ==
def test_db_save_setting(temp_db_file_connection):
    """ Test database.save_setting function using a temporary file DB. """
    db_connection, db_path = temp_db_file_connection
    key_to_save, value_to_save = "theme", "dark"

    save_ok = False
    with pytest.MonkeyPatch.context() as mp:
        # Patch the DB_NAME variable *within the db_module*
        mp.setattr(db_module, DB_VARIABLE_TO_PATCH, db_path, raising=True)
        try: save_ok = db_module.save_setting(key_to_save, value_to_save)
        except Exception as e: pytest.fail(f"db_module.save_setting raised unexpected exception: {e}")

    assert save_ok is True
    # Verify directly using the fixture's connection
    cursor = db_connection.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key_to_save,))
    row = cursor.fetchone(); assert row is not None and row['value'] == value_to_save

# (test_db_load_setting, test_db_load_non_existent_setting, test_db_delete_setting, test_db_delete_non_existent_setting omitted for brevity - assume identical structure using MonkeyPatch)
def test_db_load_setting(temp_db_file_connection):
    db_connection, db_path = temp_db_file_connection
    key, val = "api_key", "test_123"; cursor = db_connection.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, val)); db_connection.commit()
    loaded_val = None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(db_module, DB_VARIABLE_TO_PATCH, db_path, raising=True)
        loaded_val = db_module.load_setting(key)
    assert loaded_val == val

# == Conversation and Message Tests (Copied Verbatim - Should work with MonkeyPatch) ==
CONVO_ID_1 = "conv-test-1"

def setup_test_conversation(conn, convo_id=CONVO_ID_1, title="Test Convo"):
    """Helper to insert a conversation record."""
    now = datetime.datetime.now(); cursor = conn.cursor()
    cursor.execute("INSERT INTO conversations (conversation_id, title, start_timestamp, last_update_timestamp) VALUES (?, ?, ?, ?)", (convo_id, title, now, now)); conn.commit()
    return now

def setup_test_messages(conn, convo_id=CONVO_ID_1, messages_data=None):
    """Helper to insert messages, returns list of inserted message details."""
    if messages_data is None: messages_data = [{"role": "user", "content": "M1"}, {"role": "assistant", "content": "M2"}, {"role": "user", "content": "M3"}]
    inserted = []; cursor = conn.cursor(); base_time = datetime.datetime.now(); delta = datetime.timedelta(seconds=1)
    for i, msg in enumerate(messages_data):
        ts = base_time + (i * delta)
        cursor.execute("INSERT INTO chat_messages (conversation_id, timestamp, role, content) VALUES (?, ?, ?, ?)", (convo_id, ts, msg["role"], msg["content"]))
        inserted.append({"id": cursor.lastrowid, "timestamp": ts, "role": msg["role"], "content": msg["content"]})
    conn.commit(); return inserted

# --- Get Messages Tests ---
def test_get_conversation_messages_simple(temp_db_file_connection):
    """Test retrieving messages without IDs/timestamps."""
    db_connection, db_path = temp_db_file_connection
    setup_test_conversation(db_connection, CONVO_ID_1); setup_test_messages(db_connection, CONVO_ID_1)
    messages = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(db_module, DB_VARIABLE_TO_PATCH, db_path, raising=True)
        messages = db_module.get_conversation_messages(CONVO_ID_1)
    assert len(messages) == 3
    assert messages[0] == {"role": "user", "content": "M1"}
    assert messages[1] == {"role": "assistant", "content": "M2"}

# (test_get_conversation_messages_with_ids, test_get_conversation_messages_empty omitted for brevity)
# (test_delete_message_by_id, test_delete_message_by_id_non_existent omitted for brevity)
# (test_delete_messages_after_timestamp, test_delete_messages_after_timestamp_no_delete omitted for brevity)
# (test_update_message_content, test_update_message_content_non_existent omitted for brevity)
# (test_get_messages_after_timestamp, test_get_messages_after_timestamp_none_after omitted for brevity)
# (test_update_and_get_conversation_metadata omitted for brevity)

