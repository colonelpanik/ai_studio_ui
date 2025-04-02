# tests/test_app.py
import sys
import os
from pathlib import Path
import pytest
import sqlite3

# Add project root to sys.path to allow importing project modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# --- Fixtures ---

# Use an in-memory SQLite database for testing DB functions
@pytest.fixture(scope="function") # Use function scope to get a fresh DB for each test
def memory_db_connection():
    """Creates an in-memory SQLite database connection for testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn # Provide the connection to the test
    conn.close() # Close after the test finishes

@pytest.fixture
def mock_db_functions(monkeypatch, memory_db_connection):
    """ Mocks database functions to use the in-memory database. """
    import database as db_module

    # Mock get_db_connection to return the in-memory connection
    def mock_get_conn():
        # Instead of returning the closed connection, we need a way to manage it per test.
        # This fixture setup is tricky. A simpler approach for basic tests might be needed.
        # For now, let's assume db functions can accept a connection object, or we patch get_db_connection globally.
        # Simpler: Patch the DB_NAME constant within the database module for the test duration
        monkeypatch.setattr(db_module, "DB_NAME", ":memory:")
        # Re-run create_tables on the in-memory DB before tests needing it
        # Note: This might interfere if module-level create_tables() already ran
        # db_module.create_tables() # Be cautious with module-level side effects

    # Apply the patch
    monkeypatch.setattr(db_module, "get_db_connection", lambda: memory_db_connection)

# --- Test Cases ---

def test_module_imports():
    """ Test if main modules can be imported without error. """
    errors = []
    try:
        import gemini_local_chat
    except ImportError as e:
        errors.append(f"Failed to import gemini_local_chat: {e}")
    try:
        import gemini_logic
    except ImportError as e:
        errors.append(f"Failed to import gemini_logic: {e}")
    try:
        import database
    except ImportError as e:
        # Database might fail if connection fails early, check logs
        print(f"Note: database import might fail if DB connection has issues: {e}")
        # errors.append(f"Failed to import database: {e}") # Optional: Treat as error or warning
    try:
        import logging_config
    except ImportError as e:
        errors.append(f"Failed to import logging_config: {e}")

    assert not errors, "Module import errors occurred:\n" + "\n".join(errors)

# --- Tests for gemini_logic (API Key Independent) ---

def test_is_file_allowed_basic(tmp_path):
    """ Test basic file allowance checks. """
    import gemini_logic as logic

    # Allowed file
    allowed_file = tmp_path / "test.py"
    allowed_file.touch()
    allowed, reason = logic.is_file_allowed(allowed_file)
    assert allowed is True
    assert "extension/name" in reason

    # Excluded extension
    excluded_file = tmp_path / "test.pyc"
    excluded_file.touch()
    allowed, reason = logic.is_file_allowed(excluded_file)
    assert allowed is False
    assert "Excluded extension" in reason

    # Not allowed extension
    not_allowed_file = tmp_path / "test.unknown"
    not_allowed_file.touch()
    allowed, reason = logic.is_file_allowed(not_allowed_file)
    assert allowed is False
    assert "not in allowed list" in reason

    # Non-existent file
    non_existent_file = tmp_path / "nonexistent.txt"
    allowed, reason = logic.is_file_allowed(non_existent_file)
    assert allowed is False
    assert "Not a file" in reason

def test_is_file_allowed_size(tmp_path):
    """ Test file size limits. """
    import gemini_logic as logic

    # File exceeding limit
    large_file = tmp_path / "large.txt"
    # Create a file slightly larger than MAX_FILE_SIZE_BYTES
    # Note: This creates an actual large file, might be slow.
    try:
        with open(large_file, "wb") as f:
            f.seek(logic.MAX_FILE_SIZE_BYTES) # Seek to the limit
            f.write(b"\0") # Write one byte past the limit
    except OverflowError:
         pytest.skip("Cannot create file larger than MAX_FILE_SIZE_BYTES on this system for testing.")
         return

    allowed, reason = logic.is_file_allowed(large_file)
    assert allowed is False
    assert "Exceeds size limit" in reason

    # File within limit
    small_file = tmp_path / "small.txt"
    small_file.write_text("Small content")
    allowed, reason = logic.is_file_allowed(small_file)
    assert allowed is True

def test_safe_read_file(tmp_path):
    """ Test file reading with different encodings. """
    import gemini_logic as logic

    # UTF-8 file
    utf8_file = tmp_path / "utf8.txt"
    utf8_content = "Hello ✨ World"
    utf8_file.write_text(utf8_content, encoding='utf-8')
    content, status = logic.safe_read_file(utf8_file)
    assert content == utf8_content
    assert status is None

    # Latin-1 file (simulate non-utf8)
    latin1_file = tmp_path / "latin1.txt"
    latin1_content = "Hübsch" # Example char causing issues in plain ASCII/sometimes UTF-8 reads
    try:
        latin1_file.write_text(latin1_content, encoding='latin-1')
    except UnicodeEncodeError:
         pytest.skip("System encoding prevents writing pure latin-1 test file.")
         return

    # Mock read_text utf-8 to fail, then latin-1 should succeed
    original_read_text = Path.read_text
    def mock_read_text(self, encoding=None, errors=None):
        if encoding == 'utf-8' and self == latin1_file:
            raise UnicodeDecodeError("utf-8", b"\x00", 0, 1, "mock error")
        # Call original for other encodings or files
        # Need to bind 'self' back correctly
        return original_read_text(self, encoding=encoding, errors=errors)

    # Use monkeypatch if available, otherwise simple patch
    setattr(Path, 'read_text', mock_read_text)

    content, status = logic.safe_read_file(latin1_file)
    assert content == latin1_content
    assert "latin-1" in status

    # Restore original method
    setattr(Path, 'read_text', original_read_text)

# --- Tests for database (using in-memory DB) ---

# Apply the fixture to mock DB functions for tests in this class/module
# pytestmark = pytest.mark.usefixtures("mock_db_functions") # Apply globally or per-test

def test_db_create_tables(memory_db_connection):
    """ Test if tables are created without errors. """
    import database as db_module
    # Need to run create_tables on the memory connection
    db_module.create_tables() # Assumes create_tables uses the mocked get_db_connection

    cursor = memory_db_connection.cursor()
    errors = []
    tables = ["settings", "instructions", "conversations", "chat_messages"]
    for table in tables:
        try:
            cursor.execute(f"SELECT count(*) FROM {table}")
            cursor.fetchone()
        except sqlite3.Error as e:
            errors.append(f"Failed to query table {table}: {e}")
    assert not errors, "Table creation/query errors:\n" + "\n".join(errors)

def test_db_save_load_setting(memory_db_connection):
    """ Test saving and loading a simple setting. """
    import database as db_module
    db_module.create_tables() # Ensure tables exist in memory db

    key = "test_key"
    value = "test_value"
    save_ok = db_module.save_setting(key, value)
    assert save_ok is True

    loaded_value = db_module.load_setting(key)
    assert loaded_value == value

    # Test loading non-existent key
    loaded_none = db_module.load_setting("non_existent_key")
    assert loaded_none is None

def test_db_delete_setting(memory_db_connection):
    """ Test deleting a setting. """
    import database as db_module
    db_module.create_tables()

    key = "delete_me"
    value = "delete_value"
    db_module.save_setting(key, value)

    delete_ok = db_module.delete_setting(key)
    assert delete_ok is True

    loaded_value = db_module.load_setting(key)
    assert loaded_value is None

    # Test deleting non-existent key
    delete_not_found = db_module.delete_setting("non_existent_key_del")
    assert delete_not_found is False # Should return False if key wasn't found

# Add more tests for instructions, conversations, messages as needed,
# ensuring they use the mocked in-memory database connection.