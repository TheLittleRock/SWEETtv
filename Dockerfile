# Sweet.tv IPTV Proxy Server Dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SWEETTV_DATA_DIR=/app/data \
    HOST=0.0.0.0 \
    PORT=5000

WORKDIR /app

# Install curl, certificates, and modern static FFmpeg 7 with CENC decryption support
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates tzdata tar xz-utils ffmpeg && \
    ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then \
        curl -fsSL https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz | tar -xJ --strip-components=1 -C /usr/local/bin/ ffmpeg-*-amd64-static/ffmpeg ffmpeg-*-amd64-static/ffprobe 2>/dev/null || true; \
    elif [ "$ARCH" = "arm64" ]; then \
        curl -fsSL https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz | tar -xJ --strip-components=1 -C /usr/local/bin/ ffmpeg-*-arm64-static/ffmpeg ffmpeg-*-arm64-static/ffprobe 2>/dev/null || true; \
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
