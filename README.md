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

## 📸 Web Dashboard & Fast Mode Toggle

The web dashboard at `http://<server-ip>:5000` is built for maximum speed and simplicity:

- **1-Click Quick Switcher**: Toggle instantly between **📺 Live Web TV Player** and **🔗 Copy M3U & EPG Links** with one click.
- **Top Quick Copy Pills**: Copy `playlist.m3u` and `epg.xml` URLs to clipboard directly from the header without leaving your current view.
- **7-Day Catchup Drawer**: Click **Catchup Archive** on any channel to view past shows and replay them instantly.
- **Live Video Player**: Hardware-accelerated Hls.js stream player with adaptive multi-bitrate and quality selectors (`best`, `1080p`, `720p`).
- **Real-Time Status**: Displays connection health, token countdown, active region, and device ID.
- **Settings & Region**: Change region (`cs`, `sk`, `hu`, `pl`, `ro`, `uk`), set external domain, or change default stream quality.

---

## ⏪ 7-Day EPG Catchup (Archive Replay)

Sweet.tv records broadcasts for up to 7 days on supported channels. This server provides full catchup playback support:

### How It Works

1. **In the Web TV Player**:
   - Channels with catchup display a green **Catchup** badge.
   - Click the **⏪ Catchup Archive** button above the player to open the slide-out schedule drawer.
   - Shows from the past 7 days are displayed with friendly timestamps (e.g. *Today 14:00 - 15:30*, *Yesterday 20:00 - 21:45*).
   - Click **Watch** on any show to start streaming the recorded broadcast.
   - An amber notification banner confirms archive playback; click **Return to Live TV** at any time to switch back to the live broadcast.

2. **In External IPTV Apps (Kodi, TiviMate, IPTVnator)**:
   - The M3U playlist automatically includes standard IPTV catchup headers:
     ```m3u
     #EXTINF:-1 tvg-id="123" catchup="vod" catchup-days="7" catchup-source="http://<server-ip>:5000/stream/123/{catchup-id}.m3u8", ČT1 HD
     http://<server-ip>:5000/stream/123.m3u8
     ```
   - Also supports timestamp-based queries automatically for apps that use UTC parameters:
     `/stream/{channel_id}.m3u8?utc={utc}` or `?start={start}`.

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

## 🐳 Portainer Deployment & Automatic GitHub Compilation Guide

### How Portainer Builds Directly from GitHub (No Pre-built Image Required)

A common question is: **"Does Portainer automatically download and compile the Docker image from GitHub?"**

**Yes, absolutely!** Portainer's **Repository** build method handles the entire build process natively on your machine:
1. When you point Portainer to `https://github.com/TheLittleRock/SWEETtv.git`, Portainer clones the latest code from GitHub to your host.
2. It detects the `Dockerfile` and `docker-compose.yml`.
3. Portainer invokes `docker compose build` locally: it pulls the lightweight `python:3.11-slim` base image, installs dependencies from `requirements.txt`, copies the application files, and creates the container image.
4. It starts the container and mounts the persistent volume `sweettv_data` (which preserves your login tokens and settings forever, even when updating).

```
[GitHub Repo] ────(Portainer Clones)────► [Local Docker Engine]
                                                  │
                                          (docker compose build)
                                                  │
                                                  ▼
                                      [Compiled sweettv-proxy Image]
                                                  │
                                                  ▼
                                      [Running Container :5000]
                                                  │
                                                  ▼
                                      [Named Volume: sweettv_data]
```

---

### Step-by-Step Portainer Installation

#### Method 1: Build Directly from GitHub Repository (Recommended)

1. Open your **Portainer** dashboard.
2. Navigate to **Stacks** &rarr; **Add stack**.
3. Set the **Name**: `sweettv`.
4. Under **Build method**, select **Repository**.
5. Fill in the repository details:
   - **Repository URL**: `https://github.com/TheLittleRock/SWEETtv.git`
   - **Repository reference**: `refs/heads/main` (or leave default `main`)
   - **Compose path**: `docker-compose.yml`
6. (Optional) **Automatic updates**:
   - Turn **ON** **Automatic updates**.
   - Choose **Polling** (e.g. check every 15 minutes) or **Webhook** (copy the Portainer webhook URL and paste it into your GitHub repository settings under Webhooks).
   - Whenever you push or update the repository, Portainer will automatically pull the changes, recompile the Docker image, and restart the container seamlessly!
7. Under **Environment variables**, click **Add environment variable**:
   - `EXTERNAL_URL` = `https://tv.yourdomain.com` *(if using Nginx Proxy Manager or public domain)*
   - `SWEETTV_COUNTRY_CODE` = `cs` *(or `sk`, `hu`, `pl`, `ro`, `uk`)*
   - `DEFAULT_QUALITY` = `best` *(or `auto`, `1080p`, `720p`)*
8. Click **Deploy the stack**.
9. Portainer will clone, compile, and start the application. Once finished, visit `http://<your-server-ip>:5000` to activate your Sweet.tv account.

---

#### Method 2: Web Editor (Pasting docker-compose.yml)

If your Docker server has cloned the repository locally or you prefer pasting the compose specification:

1. In Portainer, go to **Stacks** &rarr; **Add stack**.
2. Select **Web editor** and paste:

```yaml
version: '3.8'

services:
  sweettv:
    image: sweettv-proxy:latest
    build:
      context: https://github.com/TheLittleRock/SWEETtv.git#main
      dockerfile: Dockerfile
    container_name: sweettv-proxy
    restart: unless-stopped
    ports:
      - "5000:5000"
    environment:
      - HOST=0.0.0.0
      - PORT=5000
      - SWEETTV_COUNTRY_CODE=cs            # cs, sk, hu, pl, uk, ro
      - EXTERNAL_URL=                      # e.g. https://tv.yourdomain.com (optional)
      - DEFAULT_QUALITY=auto               # 'auto', 'best', '1080p', '720p'
      - DIRECT_REDIRECT=true
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

3. Click **Deploy the stack**. Docker will build the image directly from the GitHub URL context.

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

### 1. IPTVnator (Windows / Mac / Linux)
1. In IPTVnator, click **Add via URL**.
2. Enter the Playlist URL: `http://<server-ip>:5000/playlist.m3u` (or `?quality=best` for highest bitrate).
3. In Playlist Settings, set the EPG URL to: `http://<server-ip>:5000/epg.xml`.
4. Click **Save** and start watching. Streams load automatically with native HLS playback.

### 2. Kodi (PVR IPTV Simple Client)
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

### 3. TiviMate / OTT Navigator (Android TV)
1. Go to **Settings &rarr; Playlists &rarr; Add Playlist &rarr; M3U Playlist**.
2. Enter URL: `https://tv.yourdomain.com/playlist.m3u` (or `?quality=best`).
3. Add TV Guide (EPG): `https://tv.yourdomain.com/epg.xml`.
4. Catchup Type: Set to **Xtream Codes / Flussonic / VOD**.

### 4. VLC Media Player
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
| `/stream/{channel_id}.m3u8` | `GET` | Main HLS stream master manifest endpoint |
| `/stream/{channel_id}/{epg_id}.m3u8` | `GET` | 7-day catchup archive replay stream |
| `/stream/variant.m3u8` | `GET` | HLS variant manifest proxy with absolute TS URLs |
| `/play/{channel_id}` | `GET` | Legacy/shorthand stream resolver |
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
