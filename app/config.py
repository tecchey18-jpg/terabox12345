"""
app/config.py
=============
Central configuration module for TeraStreamBot.

Loads all settings from the .env file using python-dotenv.
Every configurable value in the bot lives here.
Beginners: edit .env to change settings — do NOT hardcode values here.
"""

import os
import sys
import shutil
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from the project root (two levels up from app/)
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)


def _get_env(key: str, default: str | None = None, required: bool = False) -> str | None:
    """
    Helper: fetch an environment variable.
    Raises an error if the variable is required but missing.
    """
    value = os.getenv(key, default)
    if required and not value:
        print(f"[FATAL] Missing required environment variable: {key}")
        print(f"        Please set it in your .env file at: {ENV_PATH}")
        sys.exit(1)
    return value


# ──────────────────────────────────────────────
# TELEGRAM
# ──────────────────────────────────────────────
BOT_TOKEN: str = _get_env("BOT_TOKEN", required=True)  # type: ignore[assignment]

# Optional: restrict bot to specific user IDs
_raw_allowed = _get_env("ALLOWED_USERS", default="")
ALLOWED_USERS: list[int] = (
    [int(uid.strip()) for uid in _raw_allowed.split(",") if uid.strip()]
    if _raw_allowed
    else []
)

# ──────────────────────────────────────────────
# BROWSER / PLAYWRIGHT
# ──────────────────────────────────────────────
MAX_CONCURRENT_BROWSERS: int = int(_get_env("MAX_CONCURRENT_BROWSERS", "2"))  # type: ignore[arg-type]
PLAYWRIGHT_HEADLESS: bool = _get_env("PLAYWRIGHT_HEADLESS", "true").lower() == "true"  # type: ignore[union-attr]
BROWSER_TIMEOUT: int = int(_get_env("BROWSER_TIMEOUT", "30"))  # type: ignore[arg-type]

# ──────────────────────────────────────────────
# FILE MANAGEMENT
# ──────────────────────────────────────────────
TEMP_FOLDER: Path = Path(_get_env("TEMP_FOLDER", "app/temp"))  # type: ignore[arg-type]
AUTO_DELETE_FILES: bool = _get_env("AUTO_DELETE_FILES", "true").lower() == "true"  # type: ignore[union-attr]
MAX_FILE_AGE_MINUTES: int = int(_get_env("MAX_FILE_AGE_MINUTES", "60"))  # type: ignore[arg-type]

# ──────────────────────────────────────────────
# DOWNLOAD / UPLOAD
# ──────────────────────────────────────────────
DOWNLOAD_TIMEOUT: int = int(_get_env("DOWNLOAD_TIMEOUT", "300"))  # type: ignore[arg-type]
UPLOAD_TIMEOUT: int = int(_get_env("UPLOAD_TIMEOUT", "600"))  # type: ignore[arg-type]
MAX_RETRIES: int = int(_get_env("MAX_RETRIES", "3"))  # type: ignore[arg-type]
RETRY_DELAY: float = float(_get_env("RETRY_DELAY", "5"))  # type: ignore[arg-type]

# ──────────────────────────────────────────────
# VIDEO PROCESSING
# ──────────────────────────────────────────────
VIDEO_UPLOAD_MODE: str = _get_env("VIDEO_UPLOAD_MODE", "telegram")  # type: ignore[assignment]
CONVERT_M3U8: bool = _get_env("CONVERT_M3U8", "true").lower() == "true"  # type: ignore[union-attr]
FFMPEG_VIDEO_CODEC: str = _get_env("FFMPEG_VIDEO_CODEC", "copy")  # type: ignore[assignment]
FFMPEG_AUDIO_CODEC: str = _get_env("FFMPEG_AUDIO_CODEC", "aac")  # type: ignore[assignment]

# ──────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────
LOG_LEVEL: str = _get_env("LOG_LEVEL", "INFO")  # type: ignore[assignment]
LOG_TO_FILE: bool = _get_env("LOG_TO_FILE", "false").lower() == "true"  # type: ignore[union-attr]
LOG_FILE: Path = Path(_get_env("LOG_FILE", "logs/bot.log"))  # type: ignore[arg-type]


# ──────────────────────────────────────────────
# STARTUP VALIDATION
# ──────────────────────────────────────────────
def validate_startup() -> None:
    """
    Run pre-flight checks before the bot starts.
    Checks:
      - FFmpeg is installed and accessible
      - Temp folder exists (creates it if not)
      - Log folder exists (if file logging is on)
      - Bot token is not the placeholder value
    """
    logger = logging.getLogger(__name__)

    # 1. Token sanity check
    if BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.critical(
            "BOT_TOKEN is still the placeholder value!\n"
            "  → Open your .env file and replace it with the real token from @BotFather."
        )
        sys.exit(1)

    # 2. FFmpeg check
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        logger.warning(
            "FFmpeg not found in PATH.\n"
            "  → m3u8 → mp4 conversion will be DISABLED.\n"
            "  → Install FFmpeg: https://ffmpeg.org/download.html\n"
            "  → On Linux: sudo apt install ffmpeg"
        )
    else:
        logger.info(f"FFmpeg found at: {ffmpeg_path}")

    # 3. Temp folder
    TEMP_FOLDER.mkdir(parents=True, exist_ok=True)
    logger.info(f"Temp folder ready: {TEMP_FOLDER.resolve()}")

    # 4. Log folder (if file logging enabled)
    if LOG_TO_FILE:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Log file: {LOG_FILE.resolve()}")
