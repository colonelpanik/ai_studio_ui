# tests/test_app.py

import sys
import os
from pathlib import Path
import pytest
import sqlite3
import time
# No need for uuid anymore

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# --- Constants ---
# The name of the variable in database.py that holds the database Path object
DB_VARIABLE_TO_PATCH = "DB_NAME"

# --- Fixtures ---
@pytest.fixture(scope="function")
def temp_db_file_connection(tmp_path):
    """
    Provides a connection to a TEMPORARY FILE database.

    This fixture does the following:
    1. Creates a unique temporary database file path using pytest's tmp_path.
    2. Connects to this temporary file database.
    3. Ensures all necessary tables are created on this connection.
    4. Yields BOTH the connection object AND the path to the temporary db file.
       - The connection is for direct setup/verification in tests.
       - The path is used to patch database.DB_NAME.
    5. Closes the connection during teardown. The temp file is automatically
       cleaned up by pytest.
    """
    # Create a unique path for the database file within the temp directory
    db_file_path = tmp_path / f"test_db_{time.time_ns()}.sqlite"
    # print(f"\n[Fixture] Using temp DB file: {db_file_path}") # Debug

    conn = None
    try:
        # Connect to the temporary file database
        conn = sqlite3.connect(db_file_path, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        # Create tables on this connection
        create_tables_on_connection(conn)
        # print("[Fixture] Tables created on temp file connection.") # Debug

        # Yield both the connection and the path
        yield conn, db_file_path

    finally:
        # print("[Fixture] Tearing down temp DB connection...") # Debug
        if conn:
            try:
                conn.close()
                # print("[Fixture] Temp file connection closed.") # Debug
            except Exception as e:
                # print(f"[Fixture] Ignoring error during connection close: {e}") # Debug
                pass
        # tmp_path directory and its contents are cleaned up automatically by pytest

# --- Helper to Create Tables ---
# (Keep create_tables_on_connection exactly as it was in the previous good version)
def create_tables_on_connection(conn):
    """ Executes the necessary CREATE TABLE statements on the given connection. """
    try:
        import database as db_module
        # Getting logger is optional here, only needed if create_tables logs itself
        # logger = db_module.logging.getLogger(db_module.__name__)
    except ImportError as e:
        pytest.fail(f"Failed to import 'database' module in create_tables helper: {e}")

    # print(f"[Helper] Creating tables on connection: {conn}") # Debug
    cursor = conn.cursor()
    try:
        # Use the exact schema expected by the application
        cursor.execute('''CREATE TABLE IF NOT EXISTS instructions (name TEXT PRIMARY KEY, instruction_text TEXT NOT NULL, timestamp DATETIME NOT NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS conversations (conversation_id TEXT PRIMARY KEY, title TEXT, start_timestamp DATETIME NOT NULL, last_update_timestamp DATETIME NOT NULL, generation_config_json TEXT, system_instruction TEXT, added_paths_json TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS chat_messages (message_id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, timestamp DATETIME NOT NULL, role TEXT NOT NULL CHECK(role IN ('user', 'assistant')), content TEXT NOT NULL, model_used TEXT, context_files_json TEXT, full_prompt_sent TEXT, FOREIGN KEY (conversation_id) REFERENCES conversations (conversation_id) ON DELETE CASCADE)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)''')
        conn.commit()
        # print("[Helper] Tables committed.") # Debug
    except sqlite3.Error as e:
        # logger.error(f"Error creating tables on connection {conn}: {e}", exc_info=True) # Use logger if defined
        print(f"[Helper] ERROR creating tables: {e}") # Simple print fallback
        conn.rollback()
        raise # Re-raise the exception to fail the test appropriately


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
            print(f"Warning: Failed to import {module_name}: {e}")
            errors.append(f"Failed to import {module_name}: {e}")
    filtered_errors = [e for e in errors if "database" not in e]
    assert not filtered_errors, "Critical module import errors occurred:\n" + "\n".join(filtered_errors)


def test_reconstruct_history():
    """ Test the history reconstruction logic in gemini_logic. """
    # Ensure gemini_logic can be imported for the test
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
    ]
    expected_history = [
        {"role": "user", "parts": [{"text": "Hello"}]},
        {"role": "model", "parts": [{"text": "Hi there!"}]}, # Gemini API uses 'model' role
        {"role": "user", "parts": [{"text": "How are you?"}]},
    ]
    # *** THE FIX IS HERE: Changed double underscore to single underscore ***
    reconstructed = logic.reconstruct_gemini_history(messages)
    assert reconstructed == expected_history, "Reconstructed history does not match expected format."


# == Database Interaction Tests ==

def test_db_tables_created_by_fixture(temp_db_file_connection):
    """ Verify that the fixture successfully created the expected tables in the temp file. """
    db_connection, db_path = temp_db_file_connection # Unpack tuple from fixture
    # We just need to verify the tables exist using the provided connection.
    cursor = db_connection.cursor()
    tables = ["settings", "instructions", "conversations", "chat_messages"]
    found_tables = set()
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        rows = cursor.fetchall()
        found_tables = {row['name'] for row in rows}
    except sqlite3.Error as e:
            pytest.fail(f"Failed to query sqlite_master: {e}")

    for table in tables:
        assert table in found_tables, f"Table '{table}' was not found in the database file: {db_path}"


def test_db_save_setting(temp_db_file_connection):
    """ Test database.save_setting function using a temporary file DB. """
    db_connection, db_path = temp_db_file_connection # Unpack path from fixture
    import database as db_module
    key_to_save = "theme"
    value_to_save = "dark"

    save_ok = False
    with pytest.MonkeyPatch.context() as mp:
        # Patch the DB_NAME variable in database.py to use the temporary file path
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        try:
            # Call the function under test. It will connect to the temp file.
            save_ok = db_module.save_setting(key_to_save, value_to_save)
        except AttributeError:
             pytest.fail(f"Failed to patch database.{DB_VARIABLE_TO_PATCH}. Check name/accessibility.")
        except Exception as e:
            pytest.fail(f"db_module.save_setting raised unexpected exception: {e}")

    # Verification 1: Check the return value.
    assert save_ok is True, "save_setting function should return True on success."

    # Verification 2: Use the fixture's connection to the same temp file to check the data.
    try:
        cursor = db_connection.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key_to_save,))
        row = cursor.fetchone()
        assert row is not None, "Setting key was not found in temp DB after save."
        assert row['value'] == value_to_save, "Saved value in temp DB does not match."
    except sqlite3.Error as e:
        pytest.fail(f"SQLite error during save verification query on temp DB: {e}")


def test_db_load_setting(temp_db_file_connection):
    """ Test database.load_setting function using a temporary file DB. """
    db_connection, db_path = temp_db_file_connection # Unpack
    import database as db_module
    key_to_load = "api_key"
    value_to_load = "test_api_12345"

    # Setup: Directly insert test data using the fixture's connection.
    try:
        cursor = db_connection.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key_to_load, value_to_load))
        db_connection.commit()
    except sqlite3.Error as e:
        pytest.fail(f"Failed to insert test data for load setting test into temp DB: {e}")

    # Action: Call the function under test, patching DB_NAME to the temp file path.
    loaded_value = None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        try:
            loaded_value = db_module.load_setting(key_to_load)
        except AttributeError:
             pytest.fail(f"Failed to patch database.{DB_VARIABLE_TO_PATCH}. Check name/accessibility.")
        except Exception as e:
             pytest.fail(f"db_module.load_setting raised unexpected exception: {e}")

    # Verification: Check the loaded value.
    assert loaded_value == value_to_load


def test_db_load_non_existent_setting(temp_db_file_connection):
    """ Test database.load_setting for a non-existent key using a temporary file DB. """
    db_connection, db_path = temp_db_file_connection # Unpack
    import database as db_module
    key_to_load = "non_existent_key_abc"

    # Action
    loaded_value = "initial_dummy_value"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        try:
            loaded_value = db_module.load_setting(key_to_load)
        except AttributeError:
             pytest.fail(f"Failed to patch database.{DB_VARIABLE_TO_PATCH}. Check name/accessibility.")
        except Exception as e:
             pytest.fail(f"db_module.load_setting raised unexpected exception: {e}")

    # Verification
    assert loaded_value is None


def test_db_delete_setting(temp_db_file_connection):
    """ Test database.delete_setting for an existing key using a temporary file DB. """
    db_connection, db_path = temp_db_file_connection # Unpack
    import database as db_module
    key_to_delete = "font_size"
    value_to_delete = "12"

    # Setup: Insert data to be deleted using the fixture's connection.
    try:
        cursor = db_connection.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key_to_delete, value_to_delete))
        db_connection.commit()
    except sqlite3.Error as e:
        pytest.fail(f"Failed to insert test data for delete setting test into temp DB: {e}")

    # Action
    delete_ok = False
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        try:
            delete_ok = db_module.delete_setting(key_to_delete)
        except AttributeError:
             pytest.fail(f"Failed to patch database.{DB_VARIABLE_TO_PATCH}. Check name/accessibility.")
        except Exception as e:
             pytest.fail(f"db_module.delete_setting raised unexpected exception: {e}")

    # Verification 1: Check return value.
    assert delete_ok is True, "delete_setting should return True on successful deletion."

    # Verification 2: Query the temp DB directly to ensure the row is gone.
    try:
        cursor = db_connection.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key_to_delete,))
        row = cursor.fetchone()
        assert row is None, "Setting key was found in temp DB after delete."
    except sqlite3.Error as e:
        pytest.fail(f"SQLite error during delete verification query on temp DB: {e}")


def test_db_delete_non_existent_setting(temp_db_file_connection):
    """ Test database.delete_setting for a non-existent key using a temporary file DB. """
    db_connection, db_path = temp_db_file_connection # Unpack
    import database as db_module
    key_to_delete = "key_that_never_existed_xyz"

    # Action
    delete_ok = True # Default to True
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(f"database.{DB_VARIABLE_TO_PATCH}", db_path, raising=False)
        try:
            delete_ok = db_module.delete_setting(key_to_delete)
        except AttributeError:
             pytest.fail(f"Failed to patch database.{DB_VARIABLE_TO_PATCH}. Check name/accessibility.")
        except Exception as e:
             pytest.fail(f"db_module.delete_setting raised unexpected exception: {e}")

    # Verification
    assert delete_ok is False


# Add more tests for other tables/functions following the same pattern...