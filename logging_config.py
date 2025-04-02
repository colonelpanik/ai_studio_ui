# logging_config.py
import logging
import sys
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True) # Create logs directory if it doesn't exist
LOG_FILE = LOG_DIR / "gemini_chat_app.log"

def setup_logging():
    """Configures logging to file and console."""
    logging.basicConfig(
        level=logging.INFO, # Set the minimum level to log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format="%(asctime)s - %(levelname)s - %(name)s - %(filename)s:%(lineno)d - %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'), # Log to file
            logging.StreamHandler(sys.stdout) # Also log to console (optional)
        ]
    )
    # Optionally silence overly verbose libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    print(f"📝 Logging configured. Log file: {LOG_FILE}") # Confirm setup

# Call setup when this module is imported
setup_logging()