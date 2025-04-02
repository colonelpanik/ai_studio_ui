#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
REPO_URL="https://github.com/colonelpanik/ai_studio_ui"
REPO_DIR="ai_studio_ui" # The directory name the repo will be cloned into
VENV_DIR="venv"         # Name for the virtual environment directory
# Corrected entry point based on the repository structure
ENTRY_POINT="app/main.py"

# --- Script Logic ---

echo "--- Checking for/Cloning Repository: $REPO_URL ---"
if [ -d "$REPO_DIR" ]; then
    echo "Directory '$REPO_DIR' already exists. Entering directory."
    cd "$REPO_DIR"
    # Optional: Uncomment the next lines to pull the latest changes if the directory exists
    # echo "Pulling latest changes..."
    # git pull origin main # Or specify the correct default branch if not 'main'
else
    echo "Cloning repository..."
    git clone "$REPO_URL"
    cd "$REPO_DIR"
fi

echo "--- Setting up Python Virtual Environment ('$VENV_DIR') ---"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
else
    echo "Virtual environment '$VENV_DIR' already exists."
fi

echo "--- Activating Virtual Environment ---"
# This activates it for the current script execution
source "$VENV_DIR/bin/activate"

echo "--- Installing/Updating Dependencies from requirements.txt ---"
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    echo "WARNING: requirements.txt not found in the repository root. Cannot install dependencies."
    # Exit or continue depending on whether dependencies are critical
    # exit 1 # Uncomment this to stop if requirements are missing
fi

echo "--- Running Streamlit Application ($ENTRY_POINT) ---"
# Run streamlit using the python from the virtual environment
"$VENV_DIR/bin/streamlit" run "$ENTRY_POINT"

echo "--- Streamlit App Closed ---"

# Deactivation happens automatically when the script exits.
# You can uncomment 'deactivate' if needed for specific workflows, but it's usually not required here.
# deactivate