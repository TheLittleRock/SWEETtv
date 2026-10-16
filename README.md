# Sweet.tv IPTV Proxy Server & Web TV

[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![GHCR Image](https://img.shields.io/badge/GHCR-Multi--Arch%20(amd64%20%2F%20arm64)-orange.svg?logo=github)](https://github.com/TheLittleRock/SWEETtv/pkgs/container/sweettv)
[![Portainer](https://img.shields.io/badge/Portainer-Stack-13BEBB.svg?logo=portainer&logoColor=white)](https://www.portainer.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A high-performance standalone IPTV proxy server, M3U/M3U8 playlist generator, XMLTV EPG provider, and responsive Web TV player for **Sweet.tv**.

Designed for deployment on home servers, NAS, Docker, or Portainer, and optimized for exposure via **Nginx Proxy Manager (NPM)** with your public IP.

---

## 🌟 Key Features

- 🚀 **Zero-Overhead Direct CDN Streaming**: Employs HTTP 302 redirects directly to Sweet.tv CDN edge nodes (`Access-Control-Allow-Origin: *`). Your server consumes **zero CPU and zero bandwidth** during video playback.
- 📺 **Modern Web TV Player**: Sleek dark-mode dashboard with built-in **Hls.js** video player, live channel guide, channel search, category filters, and EPG progress bars.
- ⚡ **1-Click Quick Mode Switcher**: Instantly toggle between **Live Web TV Player** and **M3U/EPG Links & Setup Guides** with one click.
- ⏪ **7-Day EPG Catchup (Archive Replay)**: Full catchup replay support both in the Web Player (interactive 7-day drawer) and in external IPTV clients (Kodi `catchup="vod"`, TiviMate, IPTVnator).
- 💎 **Maximum Quality & Bitrate Options**:
  - **Adaptive Multi-bitrate (`auto`)**: Standard master playlist letting clients (TiviMate, Kodi, VLC) pick or auto-adapt.
  - **Forced Highest Bitrate / 4K (`best`)**: Parameter `?quality=best` automatically locks streams to the maximum available bitrate (up to 3840x2160 UHD @ 17 Mbps or 1080p FHD @ 8 Mbps at 50 FPS).
  - Specific resolution selectors: `1080p`, `720p`, `360p`.
- 🔄 **Hands-Off Automated Authentication**: Automatically tracks JWT token lifetime and refreshes authorization before expiry.
- 📱 **QR Code Device Login**: Simple device activation workflow via `sweet.tv/addDevice` with auto-polling.
- 🌐 **Nginx Proxy Manager (NPM) Ready**: Generates correct public HTTPS links behind reverse proxies via `EXTERNAL_URL` or `X-Forwarded-*` headers.
- 📦 **Gzip-Compressed EPG**: Serves `/epg.xml.gz` for instantaneous guide loading in IPTV clients.
- 🐳 **Portainer & Docker Compose Compatible**: Ready-to-run multi-arch container (`linux/amd64`, `linux/arm64`) with persistent volume for settings and credentials.

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

## 🐳 Docker & Portainer Deployment Guide

### Deployment Options Overview

You can deploy this application using any of the following 3 verified methods:
- **Method 1: Portainer Repository Stack** — Portainer automatically clones the GitHub repository and builds the image locally.
- **Method 2: Portainer Web Editor (Pre-built GHCR Image)** — Instant 1-click deployment using the automated multi-arch GitHub Container Registry image (`ghcr.io/thelittlerock/sweettv:latest`). **No compilation required!**
- **Method 3: Local Docker Compose CLI** — Clone and run with `docker compose up -d`.

---

### Method 1: Portainer Repository Stack (Automatic GitHub Build)

When you choose **Repository** in Portainer:
1. Portainer clones the latest code from `https://github.com/TheLittleRock/SWEETtv.git` onto your Docker host.
2. It detects the `Dockerfile` and `docker-compose.yml`.
3. Portainer automatically compiles the image using the `python:3.11-slim` base image and launches the container.
4. It attaches the persistent named volume `sweettv_data` (preserving your login tokens and settings forever, even when rebuilding).

#### Steps:
1. Open your **Portainer** dashboard.
2. Go to **Stacks** &rarr; **Add stack**.
3. Name: `sweettv`.
4. Build method: Select **Repository**.
5. Fill in the repository settings:
   - **Repository URL**: `https://github.com/TheLittleRock/SWEETtv.git`
   - **Repository reference**: `refs/heads/main`
   - **Compose path**: `docker-compose.yml`
6. *(Optional)* **Automatic updates**:
   - Turn **ON** **Automatic updates**.
   - Choose **Polling** (e.g. check every 15 minutes) or **Webhook**.
   - Whenever a new commit is pushed to GitHub, Portainer will automatically pull changes, rebuild the image, and restart the container!
7. Click **Deploy the stack**.

---

### Method 2: Portainer Web Editor (Instant Pre-built Image)

If you prefer not to compile code on your server and want instantaneous deployment in seconds, use the pre-built multi-arch image (`linux/amd64` for Intel/AMD and `linux/arm64` for Raspberry Pi / ARM NAS):

1. In Portainer, go to **Stacks** &rarr; **Add stack**.
2. Name: `sweettv`.
3. Select **Web editor** and paste:

```yaml
services:
  sweettv:
    image: ghcr.io/thelittlerock/sweettv:latest
    container_name: sweettv-proxy
    restart: unless-stopped
    ports:
      - "5000:5000"
    environment:
      - HOST=0.0.0.0
      - PORT=5000
      - TZ=Europe/Prague
      # Optional environment overrides (uncomment only if you want to hardcode them via Docker instead of the Web UI):
      # - SWEETTV_COUNTRY_CODE=cs          # Options: cs, sk, hu, pl, uk, ro
      # - EXTERNAL_URL=https://tv.yourdomain.com
      # - DEFAULT_QUALITY=best             # Options: auto, best, 1080p, 720p
      # - DIRECT_REDIRECT=true
    volumes:
      - sweettv_data:/app/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://127.0.0.1:5000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

volumes:
  sweettv_data:
    name: sweettv_data
```

4. Click **Deploy the stack**. Docker pulls the image from GHCR and starts in seconds.

---

### Method 3: Local Docker Compose CLI

```bash
git clone https://github.com/TheLittleRock/SWEETtv.git
cd SWEETtv

# Build and start in detached mode
docker compose up -d --build
```

View logs:
```bash
docker compose logs -f
```

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
   - **Forward Hostname / IP**: Local IP of your Sweet.tv host (e.g. `192.168.1.100`), or `sweettv-proxy` if NPM and Sweet.tv share a Docker network.
   - **Forward Port**: `5000`
   - **Cache Assets**: **OFF** *(⚠️ CRITICAL: Do NOT enable Cache Assets in NPM! Caching live HLS playlists will cause video playback to freeze after a few seconds).*
   - **Block Common Exploits**: **ON**
   - **Websockets Support**: **ON**
3. **SSL tab**:
   - Select **Request a new SSL Certificate**.
   - Turn **ON**: `Force SSL`.
   - Turn **ON**: `HTTP/2 Support`.
   - Turn **ON**: `HSTS Enabled`.
   - Enter your email and agree to Let's Encrypt Terms.
4. **Advanced tab** (Recommended for video streaming):
   Add the following snippet to prevent proxy buffering timeouts during HLS streaming and EPG downloads:
   ```nginx
   proxy_buffering off;
   proxy_read_timeout 300s;
   proxy_connect_timeout 300s;
   proxy_send_timeout 300s;
   ```
5. Click **Save**.

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
2. Playlist URL: `http://<server-ip>:5000/playlist.m3u` (or `https://tv.yourdomain.com/playlist.m3u?quality=best`).
3. TV Guide (EPG) URL: `http://<server-ip>:5000/epg.xml`.
4. Click **Save** and start watching.

### 2. Kodi (PVR IPTV Simple Client)
1. Install **PVR IPTV Simple Client** in Kodi:
   - *Settings &rarr; Add-ons &rarr; Install from repository &rarr; PVR clients &rarr; PVR IPTV Simple Client*.
2. Open add-on settings:
   - **General**: Set *M3U playlist URL* to `https://tv.yourdomain.com/playlist.m3u` (or `?quality=best` for maximum bitrate).
   - **EPG**: Set *XMLTV URL* to `https://tv.yourdomain.com/epg.xml.gz` (fast compressed format).
   - **Catchup**:
     - Enable Catchup: **Yes**
     - Catchup mode: **Default**
     - Query format: `{catchup-id}`
     - Catchup days: `7`

### 3. TiviMate / OTT Navigator (Android TV & Fire TV)
1. Go to **Settings &rarr; Playlists &rarr; Add Playlist &rarr; M3U Playlist**.
2. Enter URL: `https://tv.yourdomain.com/playlist.m3u` (or `?quality=best`).
3. Add TV Guide (EPG): `https://tv.yourdomain.com/epg.xml`.
4. Catchup: Set Catchup Type to **Xtream Codes / Flussonic / VOD**.

### 4. Apple TV & iOS (UHF, iPlayTV, IPTVX)
1. Add new M3U playlist with URL: `https://tv.yourdomain.com/playlist.m3u`.
2. Add EPG URL: `https://tv.yourdomain.com/epg.xml`.
3. Catchup archive playback will work automatically using the embedded `catchup-source` tag.

### 5. VLC Media Player
- Go to **Media &rarr; Open Network Stream...** (Ctrl+N).
- Paste `https://tv.yourdomain.com/playlist.m3u` and click **Play**.

---

## ⚙️ Environment Variables Reference

All settings can be configured via the Web UI Settings tab, or passed as environment variables in Docker:

| Variable | Default | Description |
| :--- | :---: | :--- |
| `HOST` | `0.0.0.0` | Listen host address |
| `PORT` | `5000` | Listen port |
| `SWEETTV_DATA_DIR` | `/app/data` (Docker) / `data` | Directory where `config.json` and cache are stored |
| `SWEETTV_COUNTRY_CODE` | `cs` | Sweet.tv country region code (`cs`, `sk`, `hu`, `pl`, `ro`, `uk`) |
| `EXTERNAL_URL` | *None* | Public domain URL e.g. `https://tv.yourdomain.com` (used for M3U/EPG links) |
| `DEFAULT_QUALITY` | `auto` | Default stream quality: `auto` (adaptive), `best` (highest bitrate / 4K), `1080p`, `720p` |
| `DIRECT_REDIRECT` | `true` | When `true`, redirects stream clients directly to Sweet.tv CDN (zero server CPU/bandwidth) |
| `TZ` | `Europe/Prague` | Container timezone |

> [!TIP]
> Settings updated in the Web UI are stored in `/app/data/config.json`. Thanks to the named volume `sweettv_data`, your settings, device registration, and tokens will persist forever across container updates.

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
| `/play/{channel_id}` | `GET` | Shorthand stream resolver |
| `/api/status` | `GET` | Server, authentication, and channel status |
| `/api/channels` | `GET` | JSON list of channels with categories and EPG now/next |
| `/api/channel/{id}/epg` | `GET` | 7-day program schedule with catchup replay availability |
| `/api/stream/{channel_id}/info`| `GET` | Stream variant inspector (resolutions, bitrates, codecs) |
| `/api/auth/start` | `POST` | Generates Sweet.tv device activation code and QR URL |
| `/api/auth/status?code=...` | `GET` | Polls authentication status |
| `/api/auth/logout` | `POST` | Clears credentials and logs out |
| `/api/settings` | `POST` | Updates country code, quality preference, or external URL |
| `/api/cache/refresh` | `POST` | Forces instant refresh of channels and EPG |
| `/health` | `GET` | Container and service health check (200 OK) |

---

## 🛠️ Stream Quality & Codecs Under the Hood

When an IPTV client requests a channel via `/stream/{id}.m3u8`:
1. The server requests the Sweet.tv API for the channel's master HLS manifest (`multistream: True`).
2. If **Adaptive (`auto`)** is requested, the client receives the multi-bitrate master manifest and dynamically negotiates quality or lets you choose in the player.
3. If **Highest Bitrate (`best`)** is requested, our stream resolver fetches the master playlist, parses `#EXT-X-STREAM-INF:` tags, and redirects directly to the variant with the **highest bandwidth** (e.g. 2160p 4K @ 17 Mbps, or 1080p @ 8 Mbps AVC/HEVC).
4. Sweet.tv CDN edge nodes deliver TS chunks with `Access-Control-Allow-Origin: *` headers, ensuring smooth in-browser playback without CORS errors.

---

## ❓ Frequently Asked Questions & Troubleshooting

### Q: Port 5000 is already in use on my host. How can I change it?
In `docker-compose.yml`, change the host port mapping:
```yaml
ports:
  - "5055:5000"
```
The internal container port remains `5000`, while the host accesses it at `http://<server-ip>:5055`.

### Q: Why do my live streams freeze after 6 seconds behind Nginx Proxy Manager?
Check your NPM Proxy Host settings: **Cache Assets** must be turned **OFF**. If Nginx caches live `.m3u8` manifests, the player keeps reloading the same cached chunk list instead of fetching new live video segments.

### Q: Do my settings and login get deleted when updating the container?
No. All configuration, tokens, device UUID, and MAC address are saved in `/app/data/config.json`, which is mounted to the persistent Docker named volume `sweettv_data`. When you pull a new image or rebuild the stack, your session is completely preserved.

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
