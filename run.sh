#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status.
# set -e # <-- IMPORTANT: Comment out or remove this line to prevent exiting on curl failure

# --- Configuration ---
VENV_DIR=".venv"                     # Directory name for the virtual environment
REQUIREMENTS_FILE="requirements.txt" # Dependency file
APP_SCRIPT="gemini_local_chat.py"    # Main Streamlit application script
PYTHON_CMD="python3"                 # Command to use for Python 3
VERSION_FILE="VERSION"               # Local version file
# !!! REPLACE THIS URL with the raw URL to your VERSION file on GitHub !!!
REMOTE_VERSION_URL="YOUR_GITHUB_REPO_RAW_URL/VERSION"

# --- Get Script Directory ---
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

echo "📂 Current directory: $(pwd)"

# --- 1. Check Version and Update Code Conditionally ---
LOCAL_VERSION="unknown"
if [ -f "$VERSION_FILE" ]; then
    LOCAL_VERSION=$(head -n 1 "$VERSION_FILE" | tr -d '[:space:]') # Read and trim whitespace
    echo "ℹ️ Local version: $LOCAL_VERSION"
else
    echo "⚠️ Warning: Local '$VERSION_FILE' not found. Cannot compare versions."
    # Optional: Decide if you want to force a git pull if local version file is missing
    # NEEDS_PULL=true
fi

echo "📡 Checking remote version from $REMOTE_VERSION_URL..."
# Fetch remote version using curl, handle potential errors
# -s: silent, -f: fail fast (non-zero exit on server error), -L: follow redirects, --connect-timeout 5: timeout
REMOTE_VERSION_OUTPUT=$(curl -sfL --connect-timeout 5 "$REMOTE_VERSION_URL")
CURL_EXIT_CODE=$? # Capture curl's exit code

NEEDS_PULL=false # Flag to track if git pull is needed

if [ $CURL_EXIT_CODE -eq 0 ]; then
    # Curl succeeded, extract and trim version
    REMOTE_VERSION=$(echo "$REMOTE_VERSION_OUTPUT" | head -n 1 | tr -d '[:space:]')
    echo "ℹ️ Remote version: $REMOTE_VERSION"
    # Compare versions only if local version is known
    if [ "$LOCAL_VERSION" != "unknown" ] && [ "$LOCAL_VERSION" != "$REMOTE_VERSION" ]; then
        echo "🚀 Versions differ (Local: '$LOCAL_VERSION', Remote: '$REMOTE_VERSION'). Scheduling git pull."
        NEEDS_PULL=true
    elif [ "$LOCAL_VERSION" == "$REMOTE_VERSION" ]; then
         echo "✅ Local version ($LOCAL_VERSION) matches remote. Skipping git pull."
    fi
else
    # Curl failed
    echo "⚠️ Warning: Failed to fetch remote version (curl exit code: $CURL_EXIT_CODE). Cannot compare versions."
    echo "   Skipping version check. Will proceed without git pull based on version."
    # Do not set NEEDS_PULL = true here
fi

# Perform git pull only if the flag was set
if [ "$NEEDS_PULL" = true ]; then
    echo "⏳ Pulling latest changes from Git..."
    # Check if git pull succeeds
    if git pull; then
        echo "✅ Git pull successful."
        # Update local version variable after successful pull if file exists
        if [ -f "$VERSION_FILE" ]; then
             LOCAL_VERSION=$(head -n 1 "$VERSION_FILE" | tr -d '[:space:]')
             echo "ℹ️ Updated local version: $LOCAL_VERSION"
        fi
    else
        echo "❌ Error: Git pull failed. Attempting to continue with local version."
        # Continue execution as error is not fatal here
    fi
fi


# --- 2. Check/Setup Virtual Environment ---
# ... (rest of the script remains the same) ...

if ! command -v $PYTHON_CMD &> /dev/null; then
    echo "❌ Error: '$PYTHON_CMD' command not found. Please install Python 3."
    exit 1 # Exit here is okay as Python is essential
fi

# ... (rest of venv setup) ...
if [ ! -d "$VENV_DIR" ]; then
  echo "🔧 Virtual environment '$VENV_DIR' not found. Creating..."
  if $PYTHON_CMD -m venv "$VENV_DIR"; then
      echo "✅ Virtual environment created."
  else
      echo "❌ Error: Failed to create virtual environment."
      exit 1 # Exit here is okay
  fi
else
  echo "✅ Virtual environment '$VENV_DIR' found."
fi

# --- 3. Activate Virtual Environment ---
ACTIVATE_SCRIPT="$VENV_DIR/bin/activate"
if [ ! -f "$ACTIVATE_SCRIPT" ]; then
    echo "❌ Error: Activate script not found at '$ACTIVATE_SCRIPT'."
    exit 1 # Exit here is okay
fi

echo "🐍 Activating virtual environment..."
source "$ACTIVATE_SCRIPT"
if [ $? -ne 0 ]; then
    echo "❌ Error: Failed to activate virtual environment."
    exit 1 # Exit here is okay
fi
echo "   Active Python: $(which python)"


# --- 4. Install/Update Dependencies Conditionally ---
# ... (rest of the script remains the same) ...
if [ ! -f "$REQUIREMENTS_FILE" ]; then
    echo "❌ Error: Dependency file '$REQUIREMENTS_FILE' not found!"
    exit 1 # Exit here is okay
fi

echo "📦 Checking Python dependencies..."
NEEDS_INSTALL=false
if ! command -v pip &> /dev/null; then
    echo "❌ Error: 'pip' command not found in the virtual environment."
    exit 1 # Exit here is okay
fi

MISSING_COUNT=0
while IFS= read -r requirement || [[ -n "$requirement" ]]; do
    if [[ -z "$requirement" || "$requirement" =~ ^# ]]; then
        continue
    fi
    package_name=$(echo "$requirement" | sed -E 's/([<>!=~]=?|#).*//')
    if ! pip show "$package_name" > /dev/null 2>&1; then
        echo "   -> Dependency '$package_name' (from line '$requirement') seems missing."
        NEEDS_INSTALL=true
        MISSING_COUNT=$((MISSING_COUNT + 1))
    fi
done < "$REQUIREMENTS_FILE"


if [ "$NEEDS_INSTALL" = true ]; then
    echo "🔧 $MISSING_COUNT missing dependencies found. Installing/Updating from '$REQUIREMENTS_FILE'..."
    if pip install -r "$REQUIREMENTS_FILE"; then
        echo "✅ Dependencies installed successfully."
    else
        echo "❌ Error: Failed to install dependencies via pip."
        exit 1 # Exit here is okay
    fi
else
    echo "✅ All dependencies from '$REQUIREMENTS_FILE' seem to be installed."
fi


# --- 5. Run the Application ---
if [ ! -f "$APP_SCRIPT" ]; then
    echo "❌ Error: Application script '$APP_SCRIPT' not found!"
    exit 1 # Exit here is okay
fi

echo "🎉 Starting AI Studio UI ('$APP_SCRIPT')..."
echo "   (Press Ctrl+C in the terminal to stop the application)"
streamlit run "$APP_SCRIPT"

# --- Script End ---
echo "👋 Streamlit application stopped. Exiting script."

exit 0