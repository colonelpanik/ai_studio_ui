#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
REPO_URL="https://github.com/colonelpanik/ai_studio_ui"
VENV_DIR="venv"
ENTRY_POINT="app/main.py" # Relative path to the main script
GIT_BRANCH="main"

# --- Script Logic ---

echo "--- Checking Current Directory ---"
if git rev-parse --is-inside-work-tree > /dev/null 2>&1 && [ -f "$ENTRY_POINT" ]; then
    echo "Current directory is a git repository containing '$ENTRY_POINT'."
    echo "Pulling latest changes from origin/$GIT_BRANCH..."
    git pull origin "$GIT_BRANCH"
else
    echo "ERROR: Script must be run from the root of the cloned '$REPO_URL' repository."
    echo "Please 'cd' into the repository directory or clone it first."
    exit 1
fi

echo "--- Setting up Python Virtual Environment ('$VENV_DIR') in current directory ---"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
else
    echo "Virtual environment '$VENV_DIR' already exists."
fi

echo "--- Activating Virtual Environment ---"
source "$VENV_DIR/bin/activate"

echo "--- Installing/Updating Dependencies from requirements.txt ---"
if [ -f "requirements.txt" ]; then
    # Use python from venv
    "$VENV_DIR/bin/python" -m pip install -r requirements.txt
else
    echo "WARNING: requirements.txt not found. Cannot install dependencies."
fi

echo "--- Running Streamlit Application ($ENTRY_POINT) ---"
# --- MODIFIED LINE ---
# Run using 'python -m streamlit' from the venv to ensure correct python path
"$VENV_DIR/bin/python" -m streamlit run "$ENTRY_POINT"
# --- END MODIFIED LINE ---

echo "--- Streamlit App Closed ---"