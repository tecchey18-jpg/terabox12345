import re
import os
import asyncio
import logging
from pathlib import Path
import aiohttp
import aiofiles
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# Import configuration
from app.config import PLAYWRIGHT_HEADLESS, BROWSER_TIMEOUT, TEMP_FOLDER

logger = logging.getLogger(__name__)

# Fallback or directly imported cookie from env
TERABOX_COOKIE = os.getenv("TERABOX_COOKIE", "").strip()

def extract_surl(url: str) -> str | None:
    """
    Extracts the surl (short URL key) from any TeraBox link format.
    Examples:
      - https://www.terabox.com/s/1r2-pB52xU1zL-w4_G2VdAQ -> r2-pB52xU1zL-w4_G2VdAQ
      - https://teraboxapp.com/s/1r2-pB52xU1zL-w4_G2VdAQ -> r2-pB52xU1zL-w4_G2VdAQ
      - https://www.terabox.com/sharing/link?surl=r2-pB52xU1zL-w4_G2VdAQ -> r2-pB52xU1zL-w4_G2VdAQ
    """
    if "surl=" in url:
        match = re.search(r"surl=([^&]+)", url)
        if match:
            return match.group(1)
    # Match the part after /s/ or /s/1
    match = re.search(r"/s/(?:1)?([a-zA-Z0-9_-]+)", url)
    if match:
        return match.group(1)
    return None


async def resolve_redirects(url: str) -> str:
    """
    Resolves any redirects of a URL to ensure we find the final surl.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, allow_redirects=True, timeout=15) as response:
                return str(response.url)
    except Exception as e:
        logger.warning(f"Failed to resolve redirects for {url}: {e}")
        return url


async def extract_via_api(surl: str, cookie: str) -> dict:
    """
    Fetches file details and direct download link using TeraBox's unofficial API.
    Does not launch a browser, saving massive amounts of CPU and RAM.
    """
    url = f"https://www.terabox.com/share/list?app_id=250528&shorturl={surl}&root=1"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"https://www.terabox.com/sharing/link?surl={surl}",
        "Cookie": f"ndus={cookie}; lang=en;"
    }
    
    logger.info(f"Extracting Terabox file metadata via API for surl: {surl}")
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=15) as response:
            if response.status != 200:
                raise Exception(f"API request failed with status code {response.status}")
                
            data = await response.json()
            errno = data.get("errno")
            if errno != 0:
                raise Exception(f"TeraBox API returned error errno={errno}. Check if link is expired or if cookie is invalid.")
                
            file_list = data.get("list", [])
            if not file_list:
                raise Exception("No files found in this shared folder/link.")
                
            file_item = file_list[0]
            dlink = file_item.get("dlink")
            if not dlink:
                raise Exception("API did not return a direct download link (dlink).")
                
            return {
                "url": dlink,
                "filename": file_item.get("server_filename", "video.mp4"),
                "size": int(file_item.get("size", 0)),
                "mode": "api"
            }


async def extract_via_playwright(url: str, timeout: int = 45) -> dict:
    """
    Launches Chromium headless via Playwright, navigates to the page,
    bypasses anti-bot with stealth, and captures the direct download URL.
    """
    logger.info(f"Extracting Terabox file metadata via Playwright for: {url}")
    result = {"url": None, "filename": "video.mp4", "size": 0, "mode": "playwright", "error": None}
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=PLAYWRIGHT_HEADLESS,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-setuid-sandbox",
                "--no-first-run"
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        page = await context.new_page()
        Stealth().apply_stealth_async(page)
        
        direct_urls = []
        filename = None
        filesize = 0
        
        async def handle_response(response):
            nonlocal filename, filesize
            req_url = response.url
            
            # Match known direct download / stream domains
            if "pcs.baidu.com" in req_url or "d.pcs.baidu.com" in req_url or "terabox.com/file" in req_url:
                direct_urls.append(req_url)
                
            # Intercept metadata request response
            if "share/list" in req_url and response.status == 200:
                try:
                    data = await response.json()
                    if data.get("errno") == 0 and data.get("list"):
                        file_item = data["list"][0]
                        filename = file_item.get("server_filename")
                        filesize = int(file_item.get("size", 0))
                        if file_item.get("dlink"):
                            direct_urls.insert(0, file_item["dlink"])
                except Exception:
                    pass
                    
        page.on("response", handle_response)
        
        try:
            # Navigate to the sharing link
            await page.goto(url, wait_until="load", timeout=timeout * 1000)
            
            # Wait for content to render and trigger background requests
            await page.wait_for_timeout(6000)
            
            # Scrape file name from DOM if the network request didn't capture it
            if not filename:
                title_selectors = [".filename", ".file-name", "h1.file-title", "h1"]
                for selector in title_selectors:
                    title_el = await page.query_selector(selector)
                    if title_el:
                        val = await title_el.text_content()
                        if val and val.strip():
                            filename = val.strip()
                            break
            
            # Check if a video tag src is already loaded
            video_src = await page.eval_on_selector("video", "el => el.src", default=None)
            if video_src and video_src.startswith("http"):
                result["url"] = video_src
                
            # If no direct link extracted, trigger click on Download button
            if not result["url"] and not direct_urls:
                download_btn = await page.query_selector(".download-btn, button:has-text('Download')")
                if download_btn:
                    await download_btn.click()
                    await page.wait_for_timeout(5000)
                    
            if not result["url"] and direct_urls:
                result["url"] = direct_urls[0]
                
            if filename:
                result["filename"] = filename
            else:
                title = await page.title()
                result["filename"] = title.replace(" - TeraBox", "").strip() if title else "video.mp4"
                
            result["size"] = filesize
            
            if not result["url"]:
                result["error"] = "Direct stream URL not found in network capture."
                
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Playwright scraping error: {e}")
        finally:
            await browser.close()
            
    return result


async def download_file(dlink: str, save_path: Path, cookie: str | None = None, progress_callback = None) -> Path:
    """
    Downloads the file from the direct link.
    Supports resuming or chunked downloading with an async progress callback.
    """
    headers = {
        "User-Agent": "LogStatistic", # Baidu netdisk requires this to fetch file without limit or error
        "Referer": "https://www.terabox.com/sharing/link"
    }
    if cookie:
        headers["Cookie"] = f"ndus={cookie}; lang=en;"
        
    logger.info(f"Starting download to: {save_path}")
    
    # Ensure parent folders exist
    save_path.parent.mkdir(parents=True, exist_ok=True)
    
    # We use a custom connection limit to avoid timeouts
    connector = aiohttp.TCPConnector(limit=1)
    timeout = aiohttp.ClientTimeout(total=600) # 10 mins download limit
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        async with session.get(dlink, headers=headers) as response:
            if response.status != 200:
                raise Exception(f"Download failed. Server returned HTTP {response.status}")
                
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            
            async with aiofiles.open(save_path, "wb") as f:
                async for chunk in response.content.iter_chunked(2 * 1024 * 1024): # 2MB chunk buffer
                    await f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        await progress_callback(downloaded, total_size)
                        
    return save_path
