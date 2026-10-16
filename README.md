# Sweet.tv IPTV Proxy Server & Web TV

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Portainer](https://img.shields.io/badge/Portainer-Stack-13BEBB.svg?logo=portainer&logoColor=white)](https://www.portainer.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A high-performance standalone IPTV proxy server, M3U/M3U8 playlist generator, XMLTV EPG provider, and responsive Web TV player for **Sweet.tv**.

Designed for deployment on home servers, NAS, Docker, or Portainer, and optimized for exposure via **Nginx Proxy Manager (NPM)** with your public IP.

---

## 🌟 Key Features

- 🚀 **Zero-Overhead Direct CDN Streaming**: Employs HTTP 302 redirects directly to Sweet.tv CDN edge nodes (`Access-Control-Allow-Origin: *`). Your server consumes **zero CPU and zero bandwidth** during video playback.
- 📺 **Modern Web TV Player**: Sleek dark-mode dashboard with built-in **Hls.js** video player, live channel guide, channel search, category filters, and EPG progress bars.
- 💎 **Maximum Quality & Bitrate Options**:
  - **Adaptive Multi-bitrate**: Standard master playlist letting clients (TiviMate, Kodi, VLC) pick or auto-adapt.
  - **Forced Highest Bitrate / 4K**: Parameter `?quality=best` automatically locks streams to the maximum available bitrate (up to 3840x2160 UHD @ 17 Mbps or 1080p FHD @ 8 Mbps at 50 FPS).
  - Specific resolution selectors: `1080p`, `720p`, `360p`.
- 🔄 **Hands-Off Automated Authentication**: Automatically tracks JWT token lifetime and refreshes authorization before expiry.
- 📱 **QR Code Device Login**: Simple device activation workflow via `sweet.tv/addDevice` with auto-polling.
- ⏪ **7-Day Catchup Replay (Archive)**: Automatic `catchup="vod"` integration formatted for Kodi PVR IPTV Simple Client and TiviMate.
- 🌐 **Nginx Proxy Manager (NPM) Ready**: Generates correct public HTTPS links behind reverse proxies via `EXTERNAL_URL` or `X-Forwarded-*` headers.
- 📦 **Gzip-Compressed EPG**: Serves `/epg.xml.gz` for instantaneous guide loading in IPTV clients.
- 🐳 **Portainer & Docker Compose Compatible**: Ready-to-run container with persistent named volume for settings and credentials.

---

## 📸 Web Dashboard Preview

The web interface accessible on `http://<server-ip>:5000` features:
1. **Live TV Player**: Stream channels directly in any browser with instant channel zapping and quality switching.
2. **Playlists & EPG Hub**: One-click copy buttons for M3U and XMLTV links.
3. **Status & Diagnostics**: Real-time token countdown, channel counts, and virtual MAC/UUID display.
4. **Settings**: Switch region/language (`cs`, `sk`, `hu`, `pl`, `ro`, `uk`), set external domain, or choose default stream quality.
5. **Interactive Setup Guides**: Clear instructions for all major IPTV platforms.

---

## 🚀 Quick Start (Local Service)

### 1. Prerequisites
- Python 3.10 or higher
- Git

### 2. Clone and Run
```bash
git clone https://github.com/TheLittleRock/SWEETtv.git
cd SWEETtv

# Run startup script (automatically configures .venv and dependencies)
./run.sh
```

Or manually:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 5000
```

Open your browser at **`http://localhost:5000`**.

### 3. Connect Sweet.tv Account
1. Click **Connect Account** on the dashboard.
2. Enter the displayed 4-digit code on [sweet.tv/addDevice](https://sweet.tv/addDevice) or scan the QR code with your phone.
3. The server will detect authorization automatically and load your channels.

---

## 🐳 Docker & Portainer Deployment Guide

### Using Docker Compose
Create a `docker-compose.yml` file:

```yaml
version: '3.8'

services:
  sweettv:
    image: sweettv-proxy:latest
    build:
      context: .
      dockerfile: Dockerfile
    container_name: sweettv-proxy
    restart: unless-stopped
    ports:
      - "5000:5000"
    environment:
      - HOST=0.0.0.0
      - PORT=5000
      - SWEETTV_COUNTRY_CODE=cs            # cs (CZ), sk (SK), hu (HU), pl (PL), uk (UA), ro (RO)
      - EXTERNAL_URL=                      # e.g. https://tv.yourdomain.com (set if using NPM)
      - DEFAULT_QUALITY=auto               # 'auto', 'best', '1080p', '720p'
      - DIRECT_REDIRECT=true               # Direct 302 CDN redirect (recommended)
      - TZ=Europe/Prague
    volumes:
      - sweettv_data:/app/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

volumes:
  sweettv_data:
    name: sweettv_data
```

Start the container:
```bash
docker compose up -d --build
```

### Deploying via Portainer
1. Log into your **Portainer** dashboard.
2. Go to **Stacks** &rarr; **Add stack**.
3. Name the stack: `sweettv-proxy`.
4. Choose **Web editor** and paste the `docker-compose.yml` contents above.
5. (Optional) In Environment variables, set `EXTERNAL_URL` if you already have your NPM domain.
6. Click **Deploy the stack**.
7. Access `http://<server-ip>:5000` to connect your account. All tokens are persisted in the `sweettv_data` volume across updates.

---

## 🌐 Nginx Proxy Manager (NPM) & Public IP Guide

To securely access your M3U playlist, EPG, and Web TV player from outside your home network (on mobile phones, remote Smart TVs, or remote Kodi boxes):

### Architecture
```
[Public Internet]
       │
       ▼ (Ports 80 & 443)
[Home Router] ──Port Forward──► [Nginx Proxy Manager (NPM)]
                                         │ (SSL Termination)
                                         ▼ (Port 5000)
                              [Sweet.tv IPTV Proxy]
                                         │
                                         ▼ (302 Direct Redirect)
                              [Sweet.tv High-Speed CDN]
```

### Step 1: DNS & Public IP
- Point your domain or subdomain (e.g., `tv.yourdomain.com`) to your public IP via an **A record** or **DDNS** (Cloudflare, DuckDNS, etc.).

### Step 2: Router Port Forwarding
- Forward ports `80` (HTTP) and `443` (HTTPS) from your home router to the local IP of your Nginx Proxy Manager host.

### Step 3: Add Proxy Host in NPM
1. Open Nginx Proxy Manager &rarr; **Hosts** &rarr; **Proxy Hosts** &rarr; **Add Proxy Host**.
2. **Details tab**:
   - **Domain Names**: `tv.yourdomain.com`
   - **Scheme**: `http`
   - **Forward Hostname / IP**: IP of your Sweet.tv server or Docker container name (`sweettv-proxy` if on the same Docker network)
   - **Forward Port**: `5000`
   - Turn **ON**: `Cache Assets`
   - Turn **ON**: `Block Common Exploits`
   - Turn **ON**: `Websockets Support`
3. **SSL tab**:
   - Select **Request a new SSL Certificate**.
   - Turn **ON**: `Force SSL`.
   - Turn **ON**: `HTTP/2 Support`.
   - Turn **ON**: `HSTS Enabled`.
   - Enter your email and agree to Let's Encrypt Terms.
4. Click **Save**.

### Step 4: Configure External Domain
Open your Sweet.tv web dashboard (`https://tv.yourdomain.com` or local IP):
1. Go to the **Settings** tab.
2. In **External Domain / Public URL**, enter: `https://tv.yourdomain.com`.
3. Click **Save Configuration**.
4. All M3U and EPG copy links will now automatically use your secure public HTTPS URL!

---

## 📺 Client Configuration

### 1. Kodi (PVR IPTV Simple Client)
1. Install **PVR IPTV Simple Client** in Kodi:
   - *Settings &rarr; Add-ons &rarr; Install from repository &rarr; PVR clients &rarr; PVR IPTV Simple Client*.
2. Open add-on settings:
   - **General**: Set *M3U playlist URL* to `https://tv.yourdomain.com/playlist.m3u` (or `?quality=best` for maximum bitrate).
   - **EPG**: Set *XMLTV URL* to `https://tv.yourdomain.com/epg.xml.gz`.
   - **Catchup**:
     - Enable Catchup: **Yes**
     - Catchup mode: **Default**
     - Query format: `{catchup-id}`
     - Catchup days: `7`

### 2. TiviMate / OTT Navigator (Android TV)
1. Go to **Settings &rarr; Playlists &rarr; Add Playlist &rarr; M3U Playlist**.
2. Enter URL: `https://tv.yourdomain.com/playlist.m3u` (or `?quality=best`).
3. Add TV Guide (EPG): `https://tv.yourdomain.com/epg.xml`.
4. Catchup Type: Set to **Xtream Codes / Flussonic / VOD**.

### 3. VLC Media Player
- Go to **Media &rarr; Open Network Stream...** (Ctrl+N).
- Paste `https://tv.yourdomain.com/playlist.m3u` and click **Play**.

---

## 📡 API & Endpoints Reference

| Endpoint | Method | Description |
| :--- | :---: | :--- |
| `/` | `GET` | Web TV Player & Management Dashboard |
| `/login` | `GET` | Dedicated device activation page with QR code |
| `/playlist.m3u` | `GET` | M3U8 Playlist (Adaptive Multi-Bitrate) |
| `/playlist.m3u?quality=best` | `GET` | M3U8 Playlist (Forces highest available bitrate / 4K UHD) |
| `/playlist.m3u?quality=1080p` | `GET` | M3U8 Playlist (Targets 1080p Full HD) |
| `/epg.xml` | `GET` | XMLTV Electronic Program Guide |
| `/epg.xml.gz` | `GET` | Gzip-compressed XMLTV EPG for fast downloads |
| `/play/{channel_id}` | `GET` | Stream resolver for live channel (302 CDN redirect) |
| `/play/{channel_id}/{epg_id}` | `GET` | Stream resolver for 7-day catchup archive program |
| `/api/status` | `GET` | Server, authentication, and channel status |
| `/api/channels` | `GET` | JSON list of channels with categories and EPG now/next |
| `/api/stream/{channel_id}/info`| `GET` | Stream variant inspector (resolutions, bitrates, codecs) |
| `/api/auth/start` | `POST` | Generates Sweet.tv device activation code and QR URL |
| `/api/auth/status?code=...` | `GET` | Polls authentication status |
| `/api/auth/logout` | `POST` | Clears credentials and logs out |
| `/api/settings` | `POST` | Updates country code, quality preference, or external URL |
| `/api/cache/refresh` | `POST` | Forces instant refresh of channels and EPG |
| `/health` | `GET` | Container and service health check (200 OK) |

---

## 🛠️ Stream Quality & Codecs Under the Hood

When an IPTV client requests a channel via `/play/{id}`:
1. The server asks the Sweet.tv API for the channel's master HLS manifest (`multistream: True`).
2. If **Adaptive (`auto`)** is requested, the client receives the multi-bitrate master manifest and dynamically negotiates quality or lets you choose in the player.
3. If **Highest Bitrate (`best`)** is requested, our stream resolver fetches the master playlist, parses `#EXT-X-STREAM-INF:` tags, and redirects directly to the variant with the **highest bandwidth** (e.g. 2160p 4K @ 17 Mbps, or 1080p @ 8 Mbps AVC/HEVC).
4. Sweet.tv CDN edge nodes deliver TS chunks with `Access-Control-Allow-Origin: *` headers, ensuring smooth in-browser playback without CORS errors.

---

## 🙏 Acknowledgements & Credits

This standalone project was developed by analyzing and extending the original Kodi addon ecosystem:

- **Original Kodi Addon**: [plugin.video.sweettv](https://github.com/david-hazi/plugin.video.sweettv) by **david-hazi**
- **Underlying Kodi Addon Inspiration**: [blomqvist](https://github.com/mbebe/blomqvist) by **mbebe**
- **Earlier Implementations**: `sweettvpl` by **mrdini**
- **Community**: Hungarian online filmek Kodi community

All credit for reverse-engineering the foundational Sweet.tv Kodi addon workflow belongs to the authors above. This project transforms those principles into a standalone modern server architecture with Web TV, Portainer, and NPM support.

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for details.
