# Sweet.tv IPTV Proxy Server Dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SWEETTV_DATA_DIR=/app/data \
    HOST=0.0.0.0 \
    PORT=5000 \
    TZ=Europe/Prague

WORKDIR /app

# Install curl, certificates, tzdata, and modern static FFmpeg from BtbN (OpenSSL, CENC DASH)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates tzdata tar xz-utils && \
    ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then \
        curl -fsSL https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz | tar -xJ --strip-components=2 -C /usr/local/bin/ --wildcards '*/bin/ffmpeg' '*/bin/ffprobe'; \
    elif [ "$ARCH" = "arm64" ]; then \
        curl -fsSL https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linuxarm64-gpl.tar.xz | tar -xJ --strip-components=2 -C /usr/local/bin/ --wildcards '*/bin/ffmpeg' '*/bin/ffprobe'; \
    fi && \
    chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe 2>/dev/null || true && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code and example configuration
COPY app/ app/
COPY config.example.json .

# Ensure data directory exists
RUN mkdir -p /app/data

EXPOSE 5000

VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:${PORT:-5000}/health || exit 1

CMD ["python", "-m", "app.main"]
