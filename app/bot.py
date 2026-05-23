import os
import re
import asyncio
import logging
from pathlib import Path
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# Import configurations and local modules
from app.config import (
    BOT_TOKEN,
    ALLOWED_USERS,
    MAX_CONCURRENT_BROWSERS,
    TEMP_FOLDER,
    AUTO_DELETE_FILES,
    DOWNLOAD_TIMEOUT,
    validate_startup
)
from app.downloader import (
    extract_surl,
    resolve_redirects,
    extract_via_api,
    extract_via_playwright,
    download_file,
    TERABOX_COOKIE
)
from app.uploader import upload_file

logger = logging.getLogger(__name__)

# Semaphore to control concurrent Playwright browser sessions
browser_semaphore = asyncio.Semaphore(MAX_CONCURRENT_BROWSERS)

# Regular expression to match any Terabox-related domain name
TERABOX_DOMAINS_RE = re.compile(
    r'(1024terabox|terabox|nephobox|mirrobox|tibibox|momot|teraboxapp|freeterabox|4funbox|terafileshare|terasharelink|1024tera)\.[a-z]{2,}'
)


def user_is_allowed(user_id: int) -> bool:
    """
    Checks if a user ID is allowed to use the bot.
    """
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for /start.
    """
    user = update.effective_user
    if not user_is_allowed(user.id): # type: ignore
        await update.message.reply_text("⛔ Sorry, you are not authorized to use this bot.") # type: ignore
        return
        
    await update.message.reply_text( # type: ignore
        f"👋 Hello {user.first_name}!\n\n" # type: ignore
        "Welcome to **TeraStreamBot**.\n"
        "Send me any TeraBox link (e.g. video or file share link), "
        "and I will extract, download, and upload it directly to you!\n\n"
        "ℹ️ Send /help to see more commands."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for /help.
    """
    if not user_is_allowed(update.effective_user.id): # type: ignore
        return
        
    help_text = (
        "📚 **TeraStreamBot Help**\n\n"
        "🤖 **How to use me:**\n"
        "Simply send or forward any TeraBox link to this chat. I will automatically detect, download, and stream it back to you.\n\n"
        "🔧 **Commands:**\n"
        "/start - Start the bot\n"
        "/help - Show this help guide\n"
        "/status - View system status and config\n\n"
        "⚠️ **Note on large files:**\n"
        "Due to Telegram Bot API limits, files larger than 50MB will be automatically split into smaller parts."
    )
    await update.message.reply_text(help_text) # type: ignore


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for /status.
    """
    if not user_is_allowed(update.effective_user.id): # type: ignore
        return
        
    has_cookie = "Enabled (Fast API Mode)" if TERABOX_COOKIE else "Disabled (Playwright Scraper Mode)"
    status_text = (
        "📊 **System Status**\n\n"
        f"🔑 **Terabox Auth:** `{has_cookie}`\n"
        f"🤖 **Max Concurrency (Playwright):** `{MAX_CONCURRENT_BROWSERS}`\n"
        f"📂 **Temp Directory:** `{TEMP_FOLDER}`\n"
        f"🔒 **Access Restriction:** `{'Restricted' if ALLOWED_USERS else 'Public'}`\n"
        f"⚡ **Auto Cleanup:** `{'Enabled' if AUTO_DELETE_FILES else 'Disabled'}`"
    )
    await update.message.reply_text(status_text) # type: ignore


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Analyzes messages, extracts TeraBox links, and downloads files.
    """
    message_text = update.message.text if update.message else ""
    user_id = update.effective_user.id # type: ignore
    
    if not user_is_allowed(user_id):
        return
        
    # Extract links from the message
    urls = re.findall(r'https?://[^\s]+', message_text)
    terabox_urls = [u for u in urls if TERABOX_DOMAINS_RE.search(u)]
    
    if not terabox_urls:
        # If the user sends a non-link message, just guide them
        if not message_text.startswith("/"):
            await update.message.reply_text("❓ Please send a valid TeraBox share link.") # type: ignore
        return
        
    # Process only the first Terabox URL found to prevent spam/abuse
    target_url = terabox_urls[0]
    
    # Send initial status update
    processing_msg = await update.message.reply_text( # type: ignore
        "🔍 TeraBox link detected. Resolving redirects..."
    )
    
    # 1. Resolve redirects to get final URL
    resolved_url = await resolve_redirects(target_url)
    surl = extract_surl(resolved_url)
    
    if not surl:
        await processing_msg.edit_text("❌ Could not extract shorturl identifier (surl) from the link.")
        return
        
    metadata = None
    
    # 2. Extract download URL and metadata
    # If cookie is present, always prioritize high-speed API mode
    if TERABOX_COOKIE:
        await processing_msg.edit_text("⚡ Extracting link metadata via Terabox API...")
        try:
            metadata = await extract_via_api(surl, TERABOX_COOKIE)
        except Exception as e:
            logger.warning(f"API extraction failed: {e}. Attempting Playwright fallback...")
            await processing_msg.edit_text("⚠️ API extraction failed. Falling back to Playwright scraper...")
            
    # Fallback to Playwright if API mode is disabled or failed
    if not metadata:
        await processing_msg.edit_text("🌐 Launching browser to extract streaming URL (this can take ~30s)...")
        # Acquire browser semaphore to restrict concurrent Chromium instances
        async with browser_semaphore:
            try:
                metadata = await extract_via_playwright(resolved_url, DOWNLOAD_TIMEOUT)
                if metadata.get("error"):
                    raise Exception(metadata["error"])
            except Exception as e:
                logger.error(f"Playwright extraction failed: {e}")
                await processing_msg.edit_text(f"❌ Failed to extract direct link: {str(e)}")
                return
                
    # 3. Downloader execution
    dlink = metadata.get("url")
    filename = metadata.get("filename", "video.mp4")
    filesize = metadata.get("size", 0)
    
    # Clean file name from invalid characters
    filename = re.sub(r'[\\/*?:"<>|]', "", filename)
    if not filename:
        filename = "video.mp4"
        
    # Construct local download path inside app/temp
    temp_path = Path(TEMP_FOLDER) / f"{int(time.time())}_{filename}"
    
    await processing_msg.edit_text(
        f"📥 Direct Link Found!\n"
        f"📄 Name: `{filename}`\n"
        f"⚖️ Size: `{filesize / (1024*1024):.1f} MB`\n\n"
        f"⏳ Starting download..."
    )
    
    # Throttled status updates for downloading
    last_update_time = asyncio.get_event_loop().time()
    
    async def download_progress(downloaded, total):
        nonlocal last_update_time
        now = asyncio.get_event_loop().time()
        # Update progress at most every 4 seconds to avoid Telegram rate limiting
        if now - last_update_time > 4 or downloaded == total:
            last_update_time = now
            pct = (downloaded / total) * 100 if total > 0 else 0
            bar = "".join(["■" if i < int(pct / 10) else "□" for i in range(10)])
            try:
                await processing_msg.edit_text(
                    f"📥 Downloading file...\n"
                    f"Progress: {bar} {pct:.1f}%\n"
                    f"[{downloaded / (1024*1024):.1f}MB / {total / (1024*1024):.1f}MB]"
                )
            except Exception:
                pass
                
    try:
        # Start file download
        await download_file(dlink, temp_path, TERABOX_COOKIE if TERABOX_COOKIE else None, download_progress)
        
        # Verify file download is complete and not empty
        if not temp_path.exists() or temp_path.stat().st_size == 0:
            raise Exception("Downloaded file is empty or missing.")
            
        # Delete the download progress message
        try:
            await processing_msg.delete()
        except Exception:
            pass
            
        # 4. Upload file to Telegram
        await upload_file(temp_path, update, context)
        
    except Exception as e:
        logger.error(f"Failed to process Terabox link: {e}")
        try:
            await processing_msg.edit_text(f"❌ Error occurred: {str(e)}")
        except Exception:
            await update.message.reply_text(f"❌ Error occurred: {str(e)}") # type: ignore
    finally:
        # Clean up the main downloaded file
        if AUTO_DELETE_FILES and temp_path.exists():
            try:
                os.remove(temp_path)
                logger.info(f"Cleaned up downloaded file: {temp_path}")
            except Exception as cleanup_err:
                logger.warning(f"Could not delete temp file {temp_path}: {cleanup_err}")


def build_app() -> Application:
    """
    Initializes the python-telegram-bot Application.
    """
    logger.info("Initializing Telegram Bot application...")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Register command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    
    # Register text message handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    return app
