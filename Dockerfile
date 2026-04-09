# Use the official Playwright Python image — includes Chromium and all its
# system dependencies out of the box.
FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app

# Install Python dependencies first (layer cache friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright browsers are already baked into the base image; this ensures
# the version installed by pip matches what's in the image.
RUN playwright install chromium

# Copy application source
COPY sonnenbatterie_scraper.py server.py ./

# Expose the API port
EXPOSE 8099

# All configuration is passed at runtime via --env-file .env
ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=8099

CMD ["python", "server.py"]
