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
from app.routes.views import router as views_router

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("SweetTV.App")

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("==================================================")
    logger.info("  Sweet.tv IPTV Proxy Server Starting")
    logger.info(f"  Country Code: {config.country_code}")
    logger.info(f"  Authentication Status: {'Logged In' if config.is_logged else 'Not Logged In'}")
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

    yield


app = FastAPI(
    title="Sweet.tv IPTV Proxy Server",
    description="High-performance IPTV proxy, M3U/EPG generator, and Web TV player for Sweet.tv.",
    version="1.0.0",
    lifespan=lifespan,
)

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
app.include_router(api_router)


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
