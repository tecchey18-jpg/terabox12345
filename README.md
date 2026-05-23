---
title: TeraStreamBot
emoji: 🤖
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
app_port: 7860
---

# TeraStreamBot

A high-performance, asynchronous Telegram bot to download and stream files/videos from **TeraBox** links. Designed to run seamlessly in low-memory containerized environments (like Koyeb or Render) and optimized for deployment on **Hugging Face Spaces** (Free 16GB RAM tier).

## Features
- **Dual Extraction Modes:** 
  - **API Mode (Fast & Low RAM):** Resolves links using Terabox API (requires `ndus` cookie). Only uses ~30MB RAM.
  - **Playwright Scraper Mode (Bypass & Fallback):** Uses headless Chromium to automatically load the page and extract the streaming links.
- **Telegram File Splitting:** Automatically splits files larger than 50MB into playable video segments (using FFmpeg copy) or binary parts to comply with Telegram Bot API upload limits.
- **Progress Tracking:** Informs the user of the download and upload states.
- **Access Control:** Restrict bot usage to specific Telegram User IDs.
- **Auto Cleanup:** Automatically deletes temporary downloaded files and parts after upload to save disk space.

---

## 🚀 How to Deploy on Hugging Face Spaces (Free Tier)

Hugging Face Spaces provides a **completely free** environment with **16GB RAM and 2 vCPUs**, making it the absolute best place to host Playwright browser automation without OOM issues.

### Step 1: Create a Space on Hugging Face
1. Log in to [Hugging Face](https://huggingface.co/) (create an account if you don't have one).
2. Click on your profile picture in the top-right and select **New Space**.
3. Fill in the details:
   - **Space Name:** `terastream-bot` (or any name you prefer)
   - **License:** Open Source (e.g., MIT)
   - **SDK:** Select **Docker** (very important!)
   - **Docker Template:** Select **Blank** (do not select other templates)
   - **Space Hardware:** Keep the default **CPU basic (Free • 2 vCPUs • 16GB RAM • 50GB Storage)**
   - **Visibility:** Public or Private (Private is recommended to keep your bot details hidden).
4. Click **Create Space**.

### Step 2: Configure Environment Variables
You should never hardcode your bot tokens. Hugging Face allows you to inject them securely:
1. In your newly created Space, click on the **Settings** tab (gear icon at the top right).
2. Scroll down to the **Variables and Secrets** section.
3. Click **New secret** and add:
   - **Name:** `BOT_TOKEN`
   - **Value:** *Your Telegram Bot Token (from @BotFather)*
4. Click **New variable** (or **New secret** if you want it hidden) and add:
   - **Name:** `ALLOWED_USERS`
   - **Value:** *Your Telegram User ID (comma-separated if multiple, e.g. `123456789,987654321`)*. Leave blank to make the bot public.
5. (Optional but highly recommended) Click **New secret** and add:
   - **Name:** `TERABOX_COOKIE`
   - **Value:** *Your Terabox account `ndus` cookie value* (this enables fast API downloading instead of browser emulation).

### Step 3: Upload the Code
You can push your files using Git or upload them directly via the Hugging Face web interface:

#### Method A: Git Push (Recommended)
Clone the Hugging Face Space repository to your computer, copy these files inside, and push:
```bash
# Clone your Hugging Face Space (replace username/space-name with yours)
git clone https://huggingface.co/spaces/YOUR_USERNAME/YOUR_SPACE_NAME

# Copy the following files into the cloned folder:
# - app/
# - Dockerfile
# - main.py
# - requirements.txt

# Commit and push
git add .
git commit -m "Deploy TeraStreamBot"
git push
```

#### Method B: Web Upload
1. In your Hugging Face Space, click the **Files** tab.
2. Click **Add file** -> **Upload files**.
3. Drag and drop `Dockerfile`, `main.py`, `requirements.txt`, and the entire `app/` folder.
4. Click **Commit changes** at the bottom.

Hugging Face will automatically detect your `Dockerfile`, build the container, install Chrome, and launch the Telegram Bot. You can monitor the logs in the **Logs** tab of your Space!

---

## 🛠️ Local Running & Verification

If you want to run the bot on your computer first:

1. Copy `.env.example` to `.env` and fill in your `BOT_TOKEN`.
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Install Playwright browser binaries:
   ```bash
   playwright install chromium
   ```
4. Start the bot:
   ```bash
   python main.py
   ```

---

## 🍪 How to extract your Terabox `ndus` cookie
To get fast API downloads, find your `ndus` session cookie:
1. Log in to [TeraBox](https://www.terabox.com) in your web browser.
2. Press `F12` (or right-click -> **Inspect**) to open Developer Tools.
3. Go to the **Application** tab (on Chrome/Edge) or **Storage** tab (on Firefox).
4. Expand **Cookies** on the left menu and click `https://www.terabox.com`.
5. Look for the cookie named `ndus` in the table. Copy its **Value** and paste it as `TERABOX_COOKIE` in your `.env` or Hugging Face secrets.
