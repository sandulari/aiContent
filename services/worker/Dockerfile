FROM python:3.12-slim
WORKDIR /app

# System dependencies + ffmpeg + browser libs for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev ffmpeg wget curl unzip \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2t64 libatspi2.0-0 libwayland-client0 \
    fonts-liberation fonts-noto-color-emoji fonts-unifont \
    fonts-dejavu-core fonts-dejavu-extra fontconfig fonts-inter \
    fonts-roboto fonts-open-sans fonts-lato fonts-dejavu \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install deno (required by yt-dlp for YouTube JS extraction)
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh
ENV DENO_DIR=/tmp/deno_cache

# The `fonts-inter` apt package above installs Inter into
# /usr/share/fonts/opentype/inter/. Refresh the fontconfig cache so
# Pillow finds them.
RUN fc-cache -f 2>/dev/null || true

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install latest yt-dlp (override pinned version for YouTube compatibility)
RUN pip install --no-cache-dir --upgrade yt-dlp

# Playwright browser
RUN pip install playwright && playwright install chromium

COPY . .
CMD ["celery", "-A", "celery_app", "worker", "--loglevel=info"]
