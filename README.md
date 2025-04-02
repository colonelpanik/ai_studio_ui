# ✨ AI Studio UI ✨

[![Version](https://img.shields.io/badge/version-2.2.0-blue)](https://github.com/colonelpanik/ai_studio_ui) [![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Framework](https://img.shields.io/badge/Framework-Streamlit-red)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI Status](https://github.com/colonelpanik/ai_studio_ui/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/colonelpanik/ai_studio_ui/actions/workflows/ci.yaml)

A versatile Streamlit-based chat interface designed for interacting with Google Gemini models, specifically built for text inferencing.

---

## Table of Contents

-   [About The Project](#about-the-project)
-   [Key Features](#key-features-)
-   [Built With](#built-with-)
-   [Getting Started](#getting-started-)
    -   [Prerequisites](#prerequisites)
    -   [Installation](#installation)
-   [Usage](#usage-)
-   [Running with Docker](#running-with-docker-%EF%B8%8F)
-   [Configuration](#configuration-%EF%B8%8F)
-   [Database Information](#database-information-)
-   [Contributing](#contributing-)
-   [License](#license-)
-   [Acknowledgements](#acknowledgements-)

---

##About The Project

AI Studio UI provides a powerful yet user-friendly web interface, named "Gemini Chat Pro", built with Streamlit to leverage the capabilities of Google's Gemini large language models. Its primary goal is to facilitate effective interaction with the AI, particularly for development tasks, code analysis, or any scenario where providing local context (files, code snippets) is crucial.

#Why use AI Studio UI instead of the official Google AI Studio?

While Google AI Studio offers a broad range of features (like multimodal capabilities, model tuning options, etc.), AI Studio UI focuses on solving specific pain points encountered during development and context-heavy interactions:

    🧱 Robust Local Context Handling: Select specific files or entire folders from your local machine. The app intelligently scans, filters (based on size and type), and includes the content of relevant files directly into the prompt context. Unlike web UIs where file management can be manual and static, AI Studio UI:

        Handles recursive directory scanning.

        Dynamically reflects changes made to local files when context is refreshed or rebuilt (Note: requires manually triggering a refresh/update action, not automatic background watching).

    💾 Persistent & Private Conversations: Chats aren't lost when you close the browser. Full conversation history, messages, and associated settings (parameters, instructions, context paths) are stored locally in an SQLite database (gemini_chat_history.db), ensuring privacy and persistence without relying on cloud storage.

    🚀 Performance with Large Context: Based on user feedback, this interface aims to remain responsive and usable even when dealing with large context sizes (e.g., >150k tokens), which can sometimes cause slowdowns or instability in purely web-based environments. (Performance still depends on your local machine and the Gemini API itself).

    ⚙️ Fine-grained Configuration & Control: Easily adjust generation parameters (Temperature, Top-K, Top-P, Max Tokens, JSON mode), switch between available Gemini models, manage system instructions, and now, even manipulate individual messages within a conversation (see Key Features).

    🔧 Open Source & Customizable: As an open-source Streamlit application, you can inspect the code, customize it to your specific needs, and contribute improvements.

This tool is ideal for developers, researchers, or anyone needing a robust, private, local interface for Gemini that excels at integrating extensive, dynamic local file context and offers persistent, manageable chat histories.
---

## Key Features 🚀

* **🤖 Google Gemini Integration:** Connects to the Google Generative AI API to use various Gemini models (e.g., `gemini-1.5-flash-latest`).
* **📄 Local Context Injection:** Add local files or folders; the app automatically reads and includes text-based content (code, markdown, config files, etc.).
* **⚙️ Configurable File Handling:** Define allowed/excluded file extensions, ignored directories, and maximum file size limits.
* **💾 Persistent History:** SQLite database stores conversations, messages, saved system instructions, and the API key securely locally.
* **📌 Pinned Settings:** Each conversation saves the generation parameters, system instruction, and context paths used when it started, restoring them when the conversation is loaded.
* **🎛️ Parameter Control:** Adjust Temperature, Top-P, Top-K, Max Output Tokens (with dynamic limits based on the selected model), Stop Sequences, and request JSON output via UI controls.
* **📜 Instruction Management:** Save frequently used system instructions by name and quickly load them into the chat.
* **🔄 Dynamic Model Selection:** Fetches available Gemini models based on your API key and allows switching between them.
* **📊 Token Counting:** Calculates and displays the token count for the combined system instruction and injected file context.
* **🔐 Secure API Key Handling:** Stores the API key locally in the SQLite database (not in code or session state directly accessible via browser). Option to clear the saved key.
* **✨ Streamlit Interface:** Clean, reactive, and easy-to-use web UI.
* **⚡ Smart Startup Script:** Includes `run.sh` for checking versions, conditionally pulling updates, and installing dependencies only when needed.
* **📄 Logging:** Configurable logging to file and console for better debugging.

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

* **Python:** Version 3.9 or higher is recommended. Check with `python --version` or `python3 --version`.
* **Pip:** Python package installer. Usually comes with Python. Check with `pip --version` or `pip3 --version`.
* **Git:** Required for cloning the repository and for the update functionality in `run.sh`.
* **Google Gemini API Key:** You need an API key from Google AI Studio. [Get an API key](https://aistudio.google.com/app/apikey).
* **(For run.sh):** A Unix-like environment (Linux, macOS, WSL on Windows) with `bash`, `curl`, `git`, and standard command-line utilities.

### Installation

**Option 1: Quick Start using `run.sh` (Recommended for Linux/macOS/WSL)**

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/colonelpanik/ai_studio_ui.git](https://github.com/colonelpanik/ai_studio_ui.git) # Replace with your repo URL if forked
    cd ai_studio_ui
    ```
2.  **Create `VERSION` file:** Create a file named `VERSION` containing only the current version string (e.g., `2.2.0`). Commit and push this to your repository if you haven't already.
3.  **Set Remote URL in `run.sh`:** Edit the `run.sh` script and replace `YOUR_GITHUB_REPO_RAW_URL/VERSION` with the actual raw URL to your `VERSION` file on GitHub.
4.  **Make `run.sh` executable:**
    ```bash
    chmod +x run.sh
    ```
5.  **Run the script:**
    ```bash
    ./run.sh
    ```
    This script will automatically:
    * Check local vs remote version using the `VERSION` file.
    * Pull updates via `git pull` if versions differ.
    * Create/activate a Python virtual environment (`.venv`).
    * Check and install dependencies from `requirements.txt` only if needed.
    * Start the Streamlit application.

**Option 2: Manual Installation (Detailed Steps)**

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/colonelpanik/ai_studio_ui.git](https://github.com/colonelpanik/ai_studio_ui.git) # Replace with your repo URL if forked
    cd ai_studio_ui
    ```
2.  **Create `VERSION` file:** (Optional but recommended for `run.sh` later) Create `VERSION` file with the version string (e.g., `2.2.0`).
3.  **Create a virtual environment (Recommended):**
    ```bash
    python3 -m venv .venv # Or use python instead of python3 if appropriate
    # Activate it (Linux/macOS/WSL)
    source .venv/bin/activate
    # Or (Windows)
    # .venv\Scripts\activate
    ```
4.  **Install dependencies:**
    Ensure `requirements.txt` exists[cite: 1].
    ```bash
    pip install -r requirements.txt
    ```

---

## Usage 🚀

1.  **Run the Streamlit app:**
    * If using `run.sh`, it will start automatically.
    * If installed manually, make sure your virtual environment is activated and run:
        ```bash
        streamlit run gemini_local_chat.py
        ```
2.  **Open your browser:** Streamlit will typically open the app automatically, or provide a local URL (e.g., `http://localhost:8501`).
3.  **Enter API Key:** In the sidebar, enter your Google Gemini API Key. It will be saved locally in the `gemini_chat_history.db` file for future sessions. You can clear it using the link provided.
4.  **Select Model:** Once the API key is configured, choose an available Gemini model from the dropdown.
5.  **Manage Context (Optional):** Use the "Manage Context" section in the sidebar to add paths to local files or folders you want the AI to consider.
6.  **Set System Instruction (Optional):** Use the "System Instructions" expander to provide overall guidance to the model, or load/save named instructions.
7.  **Adjust Parameters (Optional):** Use the right-hand column to tweak generation parameters like Temperature, Max Output Tokens, etc.
8.  **Chat:** Type your questions or prompts in the chat input at the bottom of the main area!

When you start a new chat and send the first message:
* The message content (truncated) becomes the conversation title.
* The current settings (parameters, instruction, context paths) are saved with that conversation.
* Loading the conversation later restores these settings.

---


## Running with Docker 🐳

You can also build and run the application inside a Docker container using the included `Dockerfile`.

# Pre-built image

1.  ```docker pull ghcr.io/colonelpanik/ai_studio_ui:main``` (or use the Packages link on the right - https://github.com/colonelpanik/ai_studio_ui/pkgs/container/ai_studio_ui)

# Build your own

1.  **Create a `Dockerfile`:**
    Create or use the included file named `Dockerfile`(no extension) in the project root with the content provided in the "Dockerfile Content" section below.
2.  **Build the Docker image:**
    Open a terminal in the project root directory and run:
    ```bash
    docker build -t gemini-chat-ui .
    ```
    *(You can replace `gemini-chat-ui` with your preferred image name)*
3.  **Run the Docker container:**
    ```bash
    docker run -p 8501:8501 --rm --name gemini-chat-app -v "$(pwd)/gemini_chat_history.db:/app/gemini_chat_history.db" -v "$(pwd)/logs:/app/logs" gemini-chat-ui
    ```
    **Explanation:**
    * `-p 8501:8501`: Maps the container's port 8501 (Streamlit default) to your host machine's port 8501.
    * `--rm`: Automatically removes the container when it exits.
    * `--name gemini-chat-app`: Assigns a name to the running container.
    * `-v "$(pwd)/gemini_chat_history.db:/app/gemini_chat_history.db"`: **(Important)** Mounts the local database file into the container. This ensures your chat history persists even after the container stops. It creates the file locally if it doesn't exist on the first run.
    * `-v "$(pwd)/logs:/app/logs"`: Mounts the local `logs` directory into the container so log files are saved on your host machine.
    * `gemini-chat-ui`: The name of the image you built.

4.  **Access the app:** Open your browser to `http://localhost:8501`.

**Note on Context Paths in Docker:** When running inside Docker, adding local context paths from your host machine directly via the UI won't work as the container has its own filesystem. To provide context, you would need to mount specific host directories into the container using additional `-v` flags in the `docker run` command (e.g., `-v "/path/on/host:/data/context"`) and then add the corresponding path *inside the container* (e.g., `/data/context`) via the UI.

---

## Configuration ⚙️

Most configuration is done directly through the UI:

* **API Key:** Set in the sidebar. Stored locally in `gemini_chat_history.db`.
* **Model:** Select from the dropdown in the sidebar (populates after valid API key).
* **Context Paths:** Add/remove local file/folder paths in the "Manage Context" section. Note limitations when running in Docker. File filtering rules (extensions, size, excluded dirs) are defined as constants within `gemini_logic.py`.
* **System Instructions:** Enter directly, or save/load named instructions using the controls in the "System Instructions" expander. Saved instructions are stored in the database.
* **Generation Parameters:** Adjust sliders and controls in the right-hand column (Temperature, Top-P, Top-K, Max Tokens, Stop Sequences, JSON Mode). These settings are saved per conversation when the *first* message is sent.

---

## Database Information 💾

* **File:** `gemini_chat_history.db` (will be created in the project root directory on first run or mounted if using Docker).
* **Type:** SQLite.
* **Tables:**
    * `conversations`: Stores conversation metadata, including ID, title, timestamps, and saved settings (generation config, system instruction, context paths as JSON).
    * `chat_messages`: Stores individual user and assistant messages linked to a conversation.
    * `instructions`: Stores user-saved named system instructions.
    * `settings`: Stores application-level settings (currently just the API key).
* **Note on Database Migration:** The application includes a basic mechanism to add new columns. If major schema changes occur between versions, manual database adjustments or deleting the database file (erasing all history) might be needed.

---

## Contributing 🤝

Contributions are welcome! If you have suggestions for improvements or encounter issues, please feel free to:

1.  **Fork** the Project
2.  Create your **Feature Branch** (`git checkout -b feature/AmazingFeature`)
3.  **Commit** your Changes (`git commit -m 'Add some AmazingFeature'`)
4.  **Push** to the Branch (`git push origin feature/AmazingFeature`)
5.  Open a **Pull Request**

Please also check the [Issue Tracker](https://github.com/colonelpanik/ai_studio_ui/issues) for existing bugs or feature requests.

---

## License 📄

Distributed under the MIT License. Create a `LICENSE.txt` file if one doesn't exist.

---

## Acknowledgements 🙏

* [Google Gemini](https://deepmind.google/technologies/gemini/) for the powerful language models.
* [Streamlit](https://streamlit.io/) for the awesome Python web framework.
* [Google Generative AI Python SDK](https://github.com/google/generative-ai-python) developers.

---
