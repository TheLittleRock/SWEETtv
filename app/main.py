import logging
import os
import threading
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import config
from app.epg import get_cached_channels
from app.routes.api import router as api_router
from app.routes.iptv import router as iptv_router
from app.routes.stalker import router as stalker_router
from app.routes.views import router as views_router
from app.routes.xtream import router as xtream_router
from app.version import APP_NAME, APP_VERSION

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("SweetTV.App")

import asyncio
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("==================================================")
    logger.info(f"  {APP_NAME} v{APP_VERSION} Starting")
    logger.info(f"  Country Code: {config.country_code}")
    logger.info(f"  Sweet.tv Auth: {'Logged In' if config.is_logged else 'Not Logged In'}")
    logger.info(f"  Oneplay Status: {'Logged In' if config.is_oneplay_logged else 'Not Logged In' if config.oneplay_enabled else 'Disabled'}")
    logger.info(f"  Default Quality: {config.default_quality}")
    logger.info(f"  Direct Stream Redirect: {config.direct_redirect}")
    logger.info("==================================================")

    # Pre-fetch channels in background thread on startup if authenticated
    if config.is_logged:
        def prefetch():
            try:
                logger.info("Pre-warming channel list in background...")
                get_cached_channels(force_refresh=True, need_epg=True)
                logger.info("Pre-warming channels complete.")
            except Exception as e:
                logger.warning(f"Failed pre-warming channels: {e}")

        t = threading.Thread(target=prefetch, daemon=True)
        t.start()

    # Scheduled Oneplay VOD & series catalog auto-sync (1-hour interval)
    sync_task = None
    if config.oneplay_enabled:
        async def oneplay_catalog_sync_loop():
            # Initial wait 10s after startup to allow server to bind ports cleanly
            await asyncio.sleep(10)
            while True:
                try:
                    if config.is_oneplay_logged:
                        from app.routes.xtream import sync_oneplay_vod_catalog
                        logger.info("Executing periodic Oneplay VOD & series catalog sync...")
                        await sync_oneplay_vod_catalog()
                except Exception as err:
                    logger.warning(f"Error in scheduled Oneplay catalog sync loop: {err}")
                await asyncio.sleep(3600)

        sync_task = asyncio.create_task(oneplay_catalog_sync_loop())

    try:
        yield
    finally:
        if sync_task:
            sync_task.cancel()


app = FastAPI(
    title=APP_NAME,
    description="High-performance IPTV proxy, M3U/EPG generator, Xtream Codes API, and Web TV player for Sweet.tv.",
    version=APP_VERSION,
    lifespan=lifespan,
)

# Version and security headers middleware for hardening and deployment verification
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-App-Version"] = APP_VERSION
    response.headers["X-Application"] = APP_NAME
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    return response

# Enable CORS for IPTV web players & browsers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static assets
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Include routes
app.include_router(views_router)
app.include_router(iptv_router)
app.include_router(xtream_router)
app.include_router(stalker_router)
app.include_router(api_router)


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
