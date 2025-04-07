# app/tests/test_context_manager.py
# Simple tests for context management utilities.

import sys
import os
from pathlib import Path
import pytest

# --- Setup Project Path ---
# Get the directory of the current test file (app/tests/)
test_dir = Path(__file__).parent
# Get the project root directory (parent of app/)
project_root = test_dir.parent.parent
# Add project root to sys.path to allow imports like 'from app.logic import context_manager'
sys.path.insert(0, str(project_root))
print(f"Project root added to sys.path: {project_root}")

# --- Import Target Module ---
try:
    # Import specific functions and constants needed for testing
    from app.logic.context_manager import (
        is_file_allowed,
        format_context,
        reconstruct_gemini_history,
        ALLOWED_EXTENSIONS,
        EXCLUDE_EXTENSIONS,
        MAX_FILE_SIZE_BYTES
    )
except ImportError as e:
    pytest.fail(f"Failed to import target module 'app.logic.context_manager': {e}\nSys.path: {sys.path}")

# --- Test Cases ---

# == Test is_file_allowed ==

@pytest.mark.parametrize(
    "filename, create_content, expected_allowed, expected_reason_part",
    [
        # Allowed cases
        ("test.py", "print('hello')", True, "Allowed by extension/name"),
        ("README.md", "# Test", True, "Allowed by extension/name"),
        ("Dockerfile", "FROM python", True, "Allowed by extension/name"), # Specific filename (check case-insensitivity)
        ("dockerfile", "FROM python", True, "Allowed by extension/name"), # Specific filename (lowercase)
        ("temp.log", "Log entry", True, "Allowed by extension/name"), # .log is now in ALLOWED_EXTENSIONS
        ("small_enough.txt", "a" * (MAX_FILE_SIZE_BYTES - 1), True, "Allowed by extension/name"),
        (".gitignore", "node_modules/", True, "Allowed by extension/name"), # Specific dotfile name

        # Disallowed by extension/name list
        ("no_extension", "Some text", False, "Extension/name not in allowed list"),

        # Disallowed by explicit EXCLUDE_EXTENSIONS
        ("image.png", "dummy data", False, "Excluded extension (.png)"), # FIX: Correct expected reason
        ("archive.zip", "dummy data", False, "Excluded extension (.zip)"), # FIX: Correct expected reason
        ("compiled.pyc", "dummy data", False, "Excluded extension (.pyc)"), # FIX: Correct expected reason
        ("backup.txt.bak", "backup data", False, "Excluded extension (.bak)"), # FIX: Correct expected reason

        # Disallowed by explicit EXCLUDE_EXTENSIONS (filename match)
        ("package-lock.json", "{}", False, "Excluded filename (package-lock.json)"), # FIX: Correct expected reason

        # Disallowed by size
        ("too_large.txt", "a" * (MAX_FILE_SIZE_BYTES + 1), False, "Exceeds size limit"),

        # Non-existent files (create_content=None) should return "Not a file"
        ("non_existent.png", None, False, "Not a file"),
        ("non_existent.zip", None, False, "Not a file"),
        ("non_existent.pyc", None, False, "Not a file"),
    ]
)
def test_is_file_allowed_various_cases(tmp_path, filename, create_content, expected_allowed, expected_reason_part):
    """ Test is_file_allowed with various file names, extensions, and sizes. """
    p = tmp_path / filename
    if create_content is not None:
        try:
            p.write_text(create_content, encoding='utf-8')
            # Ensure file actually exists after writing, needed for is_file() check
            if not p.is_file():
                 pytest.fail(f"Test setup failed: File {p} not created or not a file after write.")
        except OSError as e:
            pytest.skip(f"Skipping test due to OS error creating file '{filename}': {e}")
            return

    # Create a Path object
    file_path = Path(p)

    allowed, reason = is_file_allowed(file_path)

    assert allowed == expected_allowed
    # Use 'in' assertion for reason as it might contain extra details (like encoding)
    assert expected_reason_part in reason

def test_is_file_allowed_non_existent_file(tmp_path):
     """ Test is_file_allowed returns False for a non-existent file. """
     p = tmp_path / "non_existent.txt"
     allowed, reason = is_file_allowed(p)
     assert allowed is False
     assert "Not a file" in reason

# == Test format_context ==

def test_format_context_simple():
    """ Test the basic structure of the formatted context string. """
    # Using Posix paths for consistency in test strings
    test_contents = {
        "/project/main.py": "print('main')",
        "/project/utils/helpers.py": "def helper():\n  pass"
    }
    test_roots = {"/project"} # Root is a directory
    expected_start = "--- Local File Context ---\n\n"
    expected_end = "\n--- End Local File Context ---\n\n"
    expected_file1_header = "--- File: main.py ---"
    expected_file1_content = "```\nprint('main')\n```"
    expected_file2_header = "--- File: utils/helpers.py ---" # Expecting relative path now
    expected_file2_content = "```\ndef helper():\n  pass\n```"

    formatted_string = format_context(test_contents, test_roots)

    assert formatted_string.startswith(expected_start)
    assert formatted_string.endswith(expected_end)
    assert expected_file1_header in formatted_string
    assert expected_file1_content in formatted_string
    assert expected_file2_header in formatted_string, f"Expected '{expected_file2_header}' not found in output:\n{formatted_string}"
    assert expected_file2_content in formatted_string
    assert formatted_string.find(expected_file1_header) < formatted_string.find(expected_file2_header)

def test_format_context_root_is_file():
    """ Test formatting when the root path added is a file itself. """
    test_contents = {"/project/main.py": "print('main')"}
    test_roots = {"/project/main.py"} # Root is the file itself
    expected_file_header = "--- File: main.py ---" # Expect just the filename
    expected_file_content = "```\nprint('main')\n```"

    formatted_string = format_context(test_contents, test_roots)

    assert expected_file_header in formatted_string
    assert expected_file_content in formatted_string
    assert "--- File: /project/main.py ---" not in formatted_string # Should not show absolute


def test_format_context_empty():
    """ Test format_context returns an empty string for empty input. """
    formatted_string = format_context({}, set())
    assert formatted_string == ""

# == Test reconstruct_gemini_history ==

def test_reconstruct_gemini_history_basic():
    """ Test basic conversion of user/assistant messages. """
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "How are you?"},
    ]
    expected_history = [
        {"role": "user", "parts": [{"text": "Hello"}]},
        {"role": "model", "parts": [{"text": "Hi there!"}]},
        {"role": "user", "parts": [{"text": "How are you?"}]},
    ]
    history = reconstruct_gemini_history(messages)
    assert history == expected_history

def test_reconstruct_gemini_history_empty():
    """ Test empty input list results in empty history. """
    history = reconstruct_gemini_history([])
    assert history == []

def test_reconstruct_gemini_history_invalid_role():
    """ Test messages with invalid roles are skipped. """
    messages = [
        {"role": "user", "content": "Valid user"},
        {"role": "system", "content": "Invalid system message"},
        {"role": "assistant", "content": "Valid assistant"},
    ]
    expected_history = [
        {"role": "user", "parts": [{"text": "Valid user"}]},
        {"role": "model", "parts": [{"text": "Valid assistant"}]},
    ]
    history = reconstruct_gemini_history(messages)
    assert history == expected_history

def test_reconstruct_gemini_history_missing_content():
    """ Test messages with missing content are skipped. """
    messages = [
        {"role": "user", "content": "Valid user"},
        {"role": "assistant"}, # Missing content
    ]
    expected_history = [
        {"role": "user", "parts": [{"text": "Valid user"}]},
    ]
    history = reconstruct_gemini_history(messages)
    assert history == expected_history