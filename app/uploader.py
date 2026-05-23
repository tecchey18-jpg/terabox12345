import os
import time
import shutil
import logging
import asyncio
import subprocess
from pathlib import Path
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

# Import configuration
from app.config import AUTO_DELETE_FILES, VIDEO_UPLOAD_MODE, TEMP_FOLDER

logger = logging.getLogger(__name__)

# Target split size: 49MB (Telegram Bot API limit is 50MB)
SPLIT_SIZE_BYTES = 49 * 1024 * 1024


def get_video_duration(file_path: Path) -> float:
    """
    Retrieves the duration of a video using ffprobe.
    """
    ffprobe_path = shutil.which("ffprobe")
    if not ffprobe_path:
        raise Exception("ffprobe was not found on the system path.")
        
    cmd = [
        ffprobe_path,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nocut=1",
        "-of", "csv=p=0",
        str(file_path)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    duration_str = result.stdout.strip()
    if not duration_str:
        raise Exception("ffprobe returned empty duration.")
    return float(duration_str)


def split_video_ffmpeg(file_path: Path, part_duration: float) -> list[Path]:
    """
    Splits a video file into chunks using FFmpeg segmentation.
    This copies the codecs without re-encoding (extremely fast and preserves quality).
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise Exception("ffmpeg was not found on the system path.")
        
    # Output pattern: app/temp/filename_part_000.mp4
    output_pattern = file_path.parent / f"{file_path.stem}_part_%03d{file_path.suffix}"
    
    cmd = [
        ffmpeg_path,
        "-y",
        "-i", str(file_path),
        "-c", "copy",
        "-map", "0",
        "-f", "segment",
        "-segment_time", str(part_duration),
        "-reset_timestamps", "1",
        str(output_pattern)
    ]
    
    logger.info(f"Running FFmpeg video split command: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, capture_output=True)
    
    # Locate output parts
    parts = sorted(list(file_path.parent.glob(f"{file_path.stem}_part_*")))
    return parts


def split_binary(file_path: Path) -> list[Path]:
    """
    Splits any file into generic binary chunks of SPLIT_SIZE_BYTES.
    Use this for non-video files or when FFmpeg is unavailable.
    """
    logger.info(f"Splitting file binarily: {file_path}")
    parts = []
    part_num = 1
    
    with open(file_path, "rb") as infile:
        while True:
            chunk = infile.read(SPLIT_SIZE_BYTES)
            if not chunk:
                break
            # Example: app/temp/filename.mp4.part1
            part_path = file_path.parent / f"{file_path.name}.part{part_num}"
            with open(part_path, "wb") as outfile:
                outfile.write(chunk)
            parts.append(part_path)
            part_num += 1
            
    return parts


async def keep_chat_action_alive(chat_id: int, action: ChatAction, context: ContextTypes.DEFAULT_TYPE, stop_event: asyncio.Event):
    """
    Periodically sends the chat action (e.g. UPLOAD_VIDEO) to Telegram
    so the user sees the 'typing/uploading' status in their client.
    """
    while not stop_event.is_set():
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=action)
        except Exception as e:
            logger.debug(f"Failed to send chat action: {e}")
        await asyncio.sleep(4)


async def upload_file(file_path: Path, update: Update, context: ContextTypes.DEFAULT_TYPE) -> list[Path]:
    """
    Handles uploading a file to Telegram.
    Checks file size and splits it if it exceeds the 50MB limit.
    """
    chat_id = update.effective_chat.id # type: ignore
    file_size = file_path.stat().st_size
    filename = file_path.name
    
    status_msg = await update.message.reply_text( # type: ignore
        f"⚙️ Preparing to upload:\n`{filename}` ({file_size / (1024*1024):.1f} MB)"
    )
    
    uploaded_files = []
    
    # Define file extension categories
    video_extensions = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".webm", ".m3u8"}
    is_video = file_path.suffix.lower() in video_extensions
    
    # 1. Simple upload if file is under 50MB limit
    if file_size < SPLIT_SIZE_BYTES:
        await status_msg.edit_text("📤 Uploading file to Telegram...")
        
        # Start chat action keep-alive
        stop_event = asyncio.Event()
        action = ChatAction.UPLOAD_VIDEO if is_video else ChatAction.UPLOAD_DOCUMENT
        action_task = asyncio.create_task(keep_chat_action_alive(chat_id, action, context, stop_event))
        
        try:
            if is_video:
                # Upload as Video so it can be streamed directly in Telegram
                with open(file_path, "rb") as f:
                    msg = await context.bot.send_video(
                        chat_id=chat_id,
                        video=f,
                        filename=filename,
                        supports_streaming=True,
                        write_timeout=300
                    )
            else:
                # Upload as Document
                with open(file_path, "rb") as f:
                    msg = await context.bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        filename=filename,
                        write_timeout=300
                    )
            uploaded_files.append(file_path)
            await status_msg.edit_text("✅ Upload completed successfully!")
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            await status_msg.edit_text(f"❌ Upload failed: {str(e)}")
            raise e
        finally:
            stop_event.set()
            await action_task
            
    # 2. File exceeds 50MB limit -> Needs Splitting
    else:
        parts = []
        await status_msg.edit_text("⚡ File size exceeds 50MB limit. Splitting file into parts...")
        
        try:
            ffmpeg_available = shutil.which("ffmpeg") is not None
            if is_video and ffmpeg_available:
                try:
                    duration = get_video_duration(file_path)
                    # Calculate segment duration
                    # average_bitrate = size / duration
                    # segment_duration = split_limit / average_bitrate = (split_limit * duration) / size
                    segment_duration = (SPLIT_SIZE_BYTES * duration) / file_size
                    # Pad slightly to be safe (under 49MB)
                    segment_duration = max(10.0, segment_duration * 0.95)
                    
                    parts = split_video_ffmpeg(file_path, segment_duration)
                    logger.info(f"Video successfully split into {len(parts)} parts using FFmpeg.")
                except Exception as e:
                    logger.warning(f"FFmpeg split failed, falling back to binary split: {e}")
                    parts = split_binary(file_path)
            else:
                parts = split_binary(file_path)
                
            total_parts = len(parts)
            await status_msg.edit_text(f"📦 Split completed. Uploading {total_parts} parts sequentially...")
            
            for index, part in enumerate(parts, 1):
                part_size = part.stat().st_size
                await status_msg.edit_text(
                    f"📤 Uploading part {index}/{total_parts}:\n"
                    f"`{part.name}` ({part_size / (1024*1024):.1f} MB)"
                )
                
                stop_event = asyncio.Event()
                action = ChatAction.UPLOAD_VIDEO if is_video and not part.name.endswith(".part") else ChatAction.UPLOAD_DOCUMENT
                action_task = asyncio.create_task(keep_chat_action_alive(chat_id, action, context, stop_event))
                
                try:
                    with open(part, "rb") as f:
                        if action == ChatAction.UPLOAD_VIDEO:
                            await context.bot.send_video(
                                chat_id=chat_id,
                                video=f,
                                filename=part.name,
                                supports_streaming=True,
                                caption=f"Part {index} of {total_parts}",
                                write_timeout=300
                            )
                        else:
                            await context.bot.send_document(
                                chat_id=chat_id,
                                document=f,
                                filename=part.name,
                                caption=f"Part {index} of {total_parts}",
                                write_timeout=300
                            )
                    uploaded_files.append(part)
                except Exception as upload_err:
                    logger.error(f"Failed to upload part {index}: {upload_err}")
                    await status_msg.reply_text(f"⚠️ Failed to upload part {index}/{total_parts}: {str(upload_err)}")
                finally:
                    stop_event.set()
                    await action_task
                    
            await status_msg.edit_text(f"✅ Successfully uploaded all {total_parts} parts!")
            
        except Exception as split_err:
            logger.error(f"Splitting/upload process failed: {split_err}")
            await status_msg.edit_text(f"❌ Splitting process failed: {str(split_err)}")
            raise split_err
        finally:
            # Clean up generated parts immediately
            if AUTO_DELETE_FILES:
                for part in parts:
                    if part.exists() and part != file_path:
                        try:
                            os.remove(part)
                            logger.info(f"Cleaned up part file: {part}")
                        except Exception as cleanup_err:
                            logger.warning(f"Could not delete part file {part}: {cleanup_err}")
                            
    return uploaded_files
