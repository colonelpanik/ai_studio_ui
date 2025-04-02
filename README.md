# ✨ AI Studio UI ✨

[![Version](https://img.shields.io/badge/version-2.2.0-blue)](https://github.com/colonelpanik/ai_studio_ui) [![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Framework](https://img.shields.io/badge/Framework-Streamlit-red)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI Status](https://github.com/colonelpanik/ai_studio_ui/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/colonelpanik/ai_studio_ui/actions/workflows/ci.yaml)

A versatile Streamlit-based chat interface named "Gemini Chat Pro", designed for interacting with Google Gemini models, specifically enhancing text inferencing with robust local context integration and persistent history.

---

## Table of Contents

-   [About The Project](#about-the-project)
-   [Key Features](#key-features-)
-   [Getting Started](#getting-started-)
    -   [Prerequisites](#prerequisites)
    -   [Installation](#installation)
-   [Usage](#usage-)
-   [Configuration](#configuration-%EF%B8%8F)
-   [Database Information](#database-information-)
-   [Contributing](#contributing-)
-   [License](#license-)
-   [Acknowledgements](#acknowledgements-)

---

## About The Project

AI Studio UI provides a powerful yet user-friendly web interface, "Gemini Chat Pro", built with Streamlit to leverage Google's Gemini large language models. Its primary goal is to facilitate effective AI interaction, particularly for development tasks, code analysis, or any scenario where providing local context (files, code snippets) is crucial.

**Why use AI Studio UI instead of the official Google AI Studio?**

While Google AI Studio offers a broad range of features (like multimodal capabilities and model tuning), AI Studio UI focuses on solving specific pain points for developers and users needing deep local context integration and persistent, private chat management:

* **Robust Local Context Handling:** Select specific files or entire folders from your local machine. The app intelligently scans, filters (based on size and type), and includes the content of relevant files directly into the prompt context. Unlike web UIs where file management can be manual and static, AI Studio UI:
    * Handles recursive directory scanning.
    * Dynamically reflects changes made to local files when context is refreshed or rebuilt (Note: requires manually triggering a refresh/update action).
* **Persistent & Private Conversations:** Chats aren't lost when you close the browser. Full conversation history, messages, and associated settings (parameters, instructions, context paths) are stored locally in an SQLite database (`gemini_chat_history.db`), ensuring privacy and persistence without relying on cloud storage.
* **Performance with Large Context:** Designed to remain responsive and usable even when dealing with large context sizes (e.g., >150k tokens), which can sometimes challenge purely web-based environments (performance still depends on your local machine and the Gemini API itself).
* **Fine-grained Configuration & Control:** Easily adjust generation parameters (Temperature, Top-K, Top-P, Max Tokens, JSON mode), switch between available Gemini models, manage system instructions, and manipulate individual messages within a conversation.
* **Open Source & Customizable:** As an open-source Streamlit application, you can inspect the code, customize it to your specific needs, and contribute improvements.

This tool is ideal for developers, researchers, or anyone needing a robust, private, local interface for Gemini that excels at integrating extensive, dynamic local file context and offers persistent, manageable chat histories.

---

## Key Features 🚀

* **🤖 Google Gemini Integration:** Connects to the Google Generative AI API to utilize various Gemini models (e.g., `gemini-1.5-flash-latest`).
* **📄 Local Context Injection:** Add local files or folders; the app automatically reads and includes text-based content (code, markdown, config files, etc.).
* **⚙️ Configurable File Handling:** Define allowed/excluded file extensions, ignored directories, and maximum file size limits via configuration constants.
* **💾 Persistent History:** Uses a local SQLite database (`gemini_chat_history.db`) to store conversations, messages, saved system instructions, and the API key securely.
* **📌 Pinned Settings per Conversation:** Each chat saves its initial generation parameters, system instruction, and context paths, restoring them automatically when the conversation is loaded.
* **🎛️ Parameter Control:** Adjust Temperature, Top-P, Top-K, Max Output Tokens (with dynamic model-based limits), Stop Sequences, and request JSON output via UI controls.
* **📜 Instruction Management:** Save frequently used system instructions by name and quickly load them into the chat interface.
* **🔄 Dynamic Model Selection:** Fetches available Gemini models based on your API key and allows easy switching between them.
* **📊 Token Counting:** Calculates and displays the token count for the combined system instruction and injected file context.
* **🔐 Secure API Key Handling:** Stores the API key locally in the SQLite database (not in code or easily accessible browser session state). Provides an option to clear the saved key.
* **✨ Streamlit Interface:** Clean, reactive, and easy-to-use web UI.
* **⚡ Smart Startup Script:** Includes `run.sh` for checking versions, conditionally pulling updates, and installing dependencies only when necessary.
* **📄 Logging:** Configurable logging to file and console for improved debugging and monitoring.

---

## Built With 🛠️

* [Python](https://www.python.org/) (3.9+ Recommended)
* [Streamlit](https://streamlit.io/) - Web framework
* [Google Generative AI SDK for Python](https://github.com/google/generative-ai-python) - Gemini API interaction
* [SQLite](https://www.sqlite.org/index.html) (via Python's built-in `sqlite3` module) - Local database storage

---

## Getting Started 🏁

Follow these steps to get AI Studio UI running on your local machine.

### Prerequisites

* **Python:** Version 3.9 or higher recommended (`python --version` or `python3 --version`).
* **Pip:** Python package installer (`pip --version` or `pip3 --version`).
* **Git:** Required for cloning the repository and the `run.sh` update functionality.
* **Google Gemini API Key:** Obtainable from [Google AI Studio](https://aistudio.google.com/app/apikey).
* **(For `run.sh`):** A Unix-like environment (Linux, macOS, WSL on Windows) with `bash`, `curl`, `git`, and standard command-line utilities.

### Installation

**Option 1: Quick Start using `run.sh` (Recommended for Linux/macOS/WSL)**

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/colonelpanik/ai_studio_ui.git](https://github.com/colonelpanik/ai_studio_ui.git) # Replace with your repo URL if forked
    cd ai_studio_ui
    ```
2.  **Create `VERSION` file:** Create a file named `VERSION` containing only the current version string (e.g., `2.2.0`). Commit and push this to your repository.
3.  **Set Remote URL in `run.sh`:** Edit `run.sh` and replace `YOUR_GITHUB_REPO_RAW_URL/VERSION` with the actual raw URL to your `VERSION` file on GitHub.
4.  **Make `run.sh` executable:**
    ```bash
    chmod +x run.sh
    ```
5.  **Run the script:**
    ```bash
    ./run.sh
    ```
    This script automatically handles:
    * Version checking (local vs remote).
    * Pulling updates (`git pull`).
    * Creating/activating a Python virtual environment (`.venv`).
    * Installing dependencies from `requirements.txt` (only if needed).
    * Starting the Streamlit application.

**Option 2: Manual Installation**

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/colonelpanik/ai_studio_ui.git](https://github.com/colonelpanik/ai_studio_ui.git) # Replace with your repo URL if forked
    cd ai_studio_ui
    ```
2.  **Create `VERSION` file:** (Optional, but needed for `run.sh`) Create a `VERSION` file with the version string (e.g., `2.2.0`).
3.  **Create a virtual environment (Recommended):**
    ```bash
    # Linux/macOS/WSL
    python3 -m venv .venv
    source .venv/bin/activate

    # Windows
    # python -m venv .venv
    # .venv\Scripts\activate
    ```
4.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

---

## Usage 🚀

1.  **Run the Streamlit app:**
    * If using `run.sh`, it starts automatically.
    * If installed manually (ensure virtual env is active):
        ```bash
        streamlit run gemini_local_chat.py
        ```
2.  **Open your browser:** Navigate to the local URL provided by Streamlit (e.g., `http://localhost:8501`).
3.  **Enter API Key:** Provide your Google Gemini API Key in the sidebar. It's saved locally in `gemini_chat_history.db`. You can clear it later via the sidebar link.
4.  **Select Model:** Choose a Gemini model from the dropdown (appears after valid API key).
5.  **Manage Context (Optional):** Use the "Manage Context" sidebar section to add paths to local files or folders for the AI to reference.
6.  **Set System Instruction (Optional):** Use the "System Instructions" expander to give the model high-level guidance, or load/save named instructions.
7.  **Adjust Parameters (Optional):** Fine-tune generation settings (Temperature, Max Tokens, etc.) in the right-hand column.
8.  **Chat:** Enter your prompts in the chat input at the bottom!

**Conversation Workflow:**
* Sending the first message in a new chat uses its content (truncated) as the conversation title.
* The current settings (parameters, instruction, context paths) are saved with that conversation.
* Loading an existing conversation restores its specific settings.

---

## Running with Docker 🐳

Build and run the application inside a Docker container.

**Option 1: Use Pre-built Image**

1.  Pull the image from GitHub Container Registry:
    ```bash
    docker pull ghcr.io/colonelpanik/ai_studio_ui:main
    ```
    (Find it also via the "Packages" link on the GitHub repo page: [https://github.com/colonelpanik/ai_studio_ui/pkgs/container/ai_studio_ui](https://github.com/colonelpanik/ai_studio_ui/pkgs/container/ai_studio_ui))

**Option 2: Build Your Own Image**

1.  **Ensure `Dockerfile` exists:** Use the `Dockerfile` provided in the project root.
2.  **Build the image:**
    ```bash
    # In the project root directory
    docker build -t gemini-chat-ui .
    ```
    *(Replace `gemini-chat-ui` with your desired image tag)*
3.  **Run the container:**
    ```bash
    docker run -p 8501:8501 --rm --name gemini-chat-app \
      -v "$(pwd)/gemini_chat_history.db:/app/gemini_chat_history.db" \
      -v "$(pwd)/logs:/app/logs" \
      ghcr.io/colonelpanik/ai_studio_ui:main # Or your custom image tag
    ```
    **Explanation:**
    * `-p 8501:8501`: Maps host port 8501 to container port 8501.
    * `--rm`: Removes the container on exit.
    * `--name gemini-chat-app`: Names the container.
    * `-v "$(pwd)/gemini_chat_history.db:/app/gemini_chat_history.db"`: **(Crucial)** Mounts the local database file into the container for history persistence. Creates the file locally on first run if it doesn't exist.
    * `-v "$(pwd)/logs:/app/logs"`: Mounts the local `logs` directory into the container for persistent logs.
    * `ghcr.io/colonelpanik/ai_studio_ui:main`: The image to run.

4.  **Access the app:** Open `http://localhost:8501` in your browser.

**Note on Context Paths in Docker:** Adding host machine paths directly via the UI won't work inside Docker. You must mount specific host directories into the container using additional `-v` flags (e.g., `-v "/path/on/host:/data/context"`) and then add the corresponding *container path* (e.g., `/data/context`) in the UI.

---

## Configuration ⚙️

Configuration is primarily managed through the UI:

* **API Key:** Set in the sidebar; stored locally in `gemini_chat_history.db`.
* **Model:** Select from the sidebar dropdown (populates after valid API key).
* **Context Paths:** Add/remove local file/folder paths in the "Manage Context" section. *Note Docker limitations.*
* **File Filtering:** Rules for context scanning (extensions, size, excluded dirs) are defined as constants within `gemini_logic.py` (or relevant config file if refactored).
* **System Instructions:** Enter directly or manage saved instructions via the "System Instructions" expander. Saved instructions are stored in the database.
* **Generation Parameters:** Adjust sliders/controls (Temperature, Top-P/K, Max Tokens, Stop Sequences, JSON Mode) in the right-hand column. Settings are saved per conversation upon the first message.

---

## Database Information 💾

* **File:** `gemini_chat_history.db` (created in the project root or mounted path).
* **Type:** SQLite.
* **Tables:**
    * `conversations`: Stores conversation metadata (ID, title, timestamps, saved settings as JSON).
    * `chat_messages`: Stores individual user/assistant messages linked to a conversation.
    * `instructions`: Stores user-saved named system instructions.
    * `settings`: Stores application-level settings (primarily the API key).
* **Schema Changes:** Basic column addition is handled automatically. Major schema updates might require manual adjustments or deleting the `gemini_chat_history.db` file (which erases all history).

---

## Contributing 🤝

Contributions are welcome!

1.  **Fork** the Project
2.  Create your **Feature Branch** (`git checkout -b feature/AmazingFeature`)
3.  **Commit** your Changes (`git commit -m 'Add some AmazingFeature'`)
4.  **Push** to the Branch (`git push origin feature/AmazingFeature`)
5.  Open a **Pull Request**

Please also check the [Issue Tracker](https://github.com/colonelpanik/ai_studio_ui/issues) for existing bugs or feature requests.

---

## License 📄

Distributed under the MIT License. See `LICENSE.txt` (or create one if missing) for more information.

---

## Acknowledgements 🙏

* [Google Gemini](https://deepmind.google/technologies/gemini/) Team
* [Streamlit](https://streamlit.io/) Team
* [Google Generative AI Python SDK](https://github.com/google/generative-ai-python) Developers

---
