# Use the official Microsoft Playwright Python base image
# This contains Python, Node, and all OS-level dependencies for Chromium pre-installed.
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install FFmpeg for video splitting and streaming conversions
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set up permissions for Hugging Face Spaces (runs as user 1000)
# Ensure the pre-installed browsers are readable/executable by the non-root user
RUN chmod -R 777 /ms-playwright

# Create a non-root user and set up working directory
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

# Copy requirements and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY --chown=user:user . .

# Change ownership of app directory
RUN chown -R user:user /home/user/app

# Switch to the non-root user
USER user

# Create temp and logs directories and ensure they are writable
RUN mkdir -p app/temp logs

# Command to run the bot
CMD ["python", "main.py"]
