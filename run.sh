#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status.
set -e

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
    LOCAL_VERSION=$(head -n 1 "$VERSION_FILE")
    echo "ℹ️ Local version: $LOCAL_VERSION"
else
    echo "⚠️ Warning: Local '$VERSION_FILE' not found. Assuming update is needed."
fi

echo "📡 Checking remote version from $REMOTE_VERSION_URL..."
# Fetch remote version using curl, handle potential errors
# -s: silent, -f: fail fast (non-zero exit on server error), -L: follow redirects
REMOTE_VERSION_OUTPUT=$(curl -sfL "$REMOTE_VERSION_URL")
CURL_EXIT_CODE=$? # Capture curl's exit code

REMOTE_VERSION="fetch_failed"
if [ $CURL_EXIT_CODE -eq 0 ]; then
    # Extract the first line in case of extra whitespace/newlines
    REMOTE_VERSION=$(echo "$REMOTE_VERSION_OUTPUT" | head -n 1)
    echo "ℹ️ Remote version: $REMOTE_VERSION"
else
    echo "⚠️ Warning: Failed to fetch remote version (curl exit code: $CURL_EXIT_CODE). Proceeding with git pull."
    # Force REMOTE_VERSION to be different to trigger pull
    REMOTE_VERSION="fetch_failed_$RANDOM"
fi

# Compare versions and pull if different or fetch failed
if [ "$LOCAL_VERSION" != "$REMOTE_VERSION" ]; then
    echo "🚀 Versions differ (Local: '$LOCAL_VERSION', Remote: '$REMOTE_VERSION') or fetch failed. Pulling latest changes..."
    if git pull; then
        echo "✅ Git pull successful."
        # Update local version variable after successful pull if file exists
        if [ -f "$VERSION_FILE" ]; then
             LOCAL_VERSION=$(head -n 1 "$VERSION_FILE")
             echo "ℹ️ Updated local version: $LOCAL_VERSION"
        fi
    else
        echo "❌ Error: Git pull failed. Attempting to continue with local version."
        # Decide if this should be a fatal error
        # exit 1 # Uncomment this line to make git pull failure fatal
    fi
else
    echo "✅ Local version ($LOCAL_VERSION) matches remote. Skipping git pull."
fi


# --- 2. Check/Setup Virtual Environment ---
if ! command -v $PYTHON_CMD &> /dev/null; then
    echo "❌ Error: '$PYTHON_CMD' command not found. Please install Python 3."
    exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "🔧 Virtual environment '$VENV_DIR' not found. Creating..."
  if $PYTHON_CMD -m venv "$VENV_DIR"; then
      echo "✅ Virtual environment created."
  else
      echo "❌ Error: Failed to create virtual environment."
      exit 1
  fi
else
  echo "✅ Virtual environment '$VENV_DIR' found."
fi

# --- 3. Activate Virtual Environment ---
ACTIVATE_SCRIPT="$VENV_DIR/bin/activate"
if [ ! -f "$ACTIVATE_SCRIPT" ]; then
    echo "❌ Error: Activate script not found at '$ACTIVATE_SCRIPT'."
    exit 1
fi

echo "🐍 Activating virtual environment..."
source "$ACTIVATE_SCRIPT"
if [ $? -ne 0 ]; then
    echo "❌ Error: Failed to activate virtual environment."
    exit 1
fi
echo "   Active Python: $(which python)"


# --- 4. Install/Update Dependencies Conditionally ---
if [ ! -f "$REQUIREMENTS_FILE" ]; then
    echo "❌ Error: Dependency file '$REQUIREMENTS_FILE' not found!"
    exit 1
fi

echo "📦 Checking Python dependencies..."
NEEDS_INSTALL=false
# Ensure pip is available
if ! command -v pip &> /dev/null; then
    echo "❌ Error: 'pip' command not found in the virtual environment."
    exit 1
fi

# Check each requirement
# Use python to parse requirements for better handling of comments/versions
# This requires installing pip-requirements-parser temporarily if needed,
# or use a simpler grep approach if versions are not strict.

# Simpler grep approach (less robust for complex version specs but avoids extra deps):
MISSING_COUNT=0
while IFS= read -r requirement || [[ -n "$requirement" ]]; do
    # Skip empty lines and comments
    if [[ -z "$requirement" || "$requirement" =~ ^# ]]; then
        continue
    fi
    # Extract package name (handle version specifiers like ==, >=, etc.)
    package_name=$(echo "$requirement" | sed -E 's/([<>!=~]=?|#).*//')
    # Check if package is installed using pip show
    if ! pip show "$package_name" > /dev/null 2>&1; then
        echo "   -> Dependency '$package_name' (from line '$requirement') seems missing."
        NEEDS_INSTALL=true
        MISSING_COUNT=$((MISSING_COUNT + 1))
        # Optional: break on first missing package for speed
        # break
    # else
    #     echo "   -> Dependency '$package_name' found." # Verbose: uncomment if needed
    fi
done < "$REQUIREMENTS_FILE"


if [ "$NEEDS_INSTALL" = true ]; then
    echo "🔧 $MISSING_COUNT missing dependencies found. Installing/Updating from '$REQUIREMENTS_FILE'..."
    if pip install -r "$REQUIREMENTS_FILE"; then
        echo "✅ Dependencies installed successfully."
    else
        echo "❌ Error: Failed to install dependencies via pip."
        exit 1
    fi
else
    echo "✅ All dependencies from '$REQUIREMENTS_FILE' seem to be installed."
fi


# --- 5. Run the Application ---
if [ ! -f "$APP_SCRIPT" ]; then
    echo "❌ Error: Application script '$APP_SCRIPT' not found!"
    exit 1
fi

echo "🎉 Starting AI Studio UI ('$APP_SCRIPT')..."
echo "   (Press Ctrl+C in the terminal to stop the application)"
streamlit run "$APP_SCRIPT"

# --- Script End ---
echo "👋 Streamlit application stopped. Exiting script."

exit 0