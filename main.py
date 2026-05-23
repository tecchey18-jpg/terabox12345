import sys
import logging
from app.config import LOG_LEVEL, LOG_TO_FILE, LOG_FILE, validate_startup
from app.bot import build_app

# Set up logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO)
)
logger = logging.getLogger(__name__)

# Add file logging if configured
if LOG_TO_FILE:
    # Ensure logs folder exists
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logging.getLogger().addHandler(file_handler)


def main():
    logger.info("Starting TeraStreamBot...")
    
    # 1. Run startup validation checks (Token presence, folders, ffmpeg)
    validate_startup()
    
    # 2. Build the Telegram Application
    app = build_app()
    
    # 3. Start the bot in polling mode
    logger.info("Bot is polling. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot execution stopped by user (Ctrl+C).")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Unhandled crash in bot execution: {e}", exc_info=True)
        sys.exit(1)
