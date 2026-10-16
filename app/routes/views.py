import logging
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import config
from app.routes.iptv import get_effective_base_url

logger = logging.getLogger("SweetTV.Routes.Views")
router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def index_view(request: Request):
    """Main Web Dashboard and Live TV Player."""
    base_url = get_effective_base_url(request)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "logged": config.is_logged,
            "country_code": config.country_code,
            "base_url": base_url,
            "external_url": config.external_url,
            "default_quality": config.default_quality,
            "direct_redirect": config.direct_redirect,
            "mac": config.get("mac"),
            "uuid": config.get("uuid"),
        }
    )


@router.get("/login", response_class=HTMLResponse)
def login_view(request: Request):
    """Dedicated login view."""
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "logged": config.is_logged,
        }
    )


@router.get("/health")
def health_check():
    """Healthcheck endpoint for Docker, Portainer, and load balancers."""
    return {"status": "healthy", "logged": config.is_logged}
