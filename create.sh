#!/bin/bash

# create_structure.sh
# Creates the directory structure and empty files for the Gemini Chat Pro app.

set -e # Exit immediately if a command exits with a non-zero status.

echo "Creating directories..."

# Main app structure
mkdir -p app
mkdir -p app/data
mkdir -p app/logic
mkdir -p app/state
mkdir -p app/static
mkdir -p app/tests
mkdir -p app/ui
mkdir -p app/utils

# Other directories
mkdir -p logs
mkdir -p .github/workflows

echo "Directories created."

echo "Creating empty files..."

# Root files
touch Dockerfile
touch LICENSE.txt
touch README.md
touch requirements.txt
touch run.sh
touch VERSION

# App package markers
touch app/__init__.py
touch app/data/__init__.py
touch app/logic/__init__.py
touch app/state/__init__.py
touch app/static/__init__.py # Although we have style.css, good practice
touch app/tests/__init__.py
touch app/ui/__init__.py
touch app/utils/__init__.py

# Core App files
touch app/main.py

# Data files
touch app/data/database.py

# Logic files
touch app/logic/api_client.py
touch app/logic/context_manager.py
touch app/logic/actions.py

# State files
touch app/state/manager.py

# Static files
touch app/static/style.css

# Test files
touch app/tests/test_database.py
# Note: If you create more tests (e.g., test_api_client.py), add them here

# UI files
touch app/ui/chat_display.py
touch app/ui/parameter_controls.py
touch app/ui/sidebar.py

# Utility files
touch app/utils/logging_config.py

# GitHub workflow files
touch .github/workflows/ci.yaml

echo "Empty files created successfully."
echo "Structure generation complete."

exit 0
