# app/utils/logging_config.py
import logging
import sys
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True) # Create logs directory if it doesn't exist
LOG_FILE = LOG_DIR / "gemini_chat_app.log"
LOG_LEVEL = logging.INFO # Set default log level

def setup_logging():
    """Configures logging to file and console."""
    # IN: None; OUT: None # Configures logging to file/console.
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s - %(levelname)s - %(name)s - %(filename)s:%(lineno)d - %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ],
        force=True # Force reconfig if already configured (e.g., in tests)
    )
    # Silence overly verbose libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("google.api_core").setLevel(logging.WARNING)
    logging.getLogger("google.auth").setLevel(logging.WARNING)

    logging.info(f"Logging configured. Level: {logging.getLevelName(LOG_LEVEL)}. Log file: {LOG_FILE}")

# Call setup when this module is imported
setup_logging()