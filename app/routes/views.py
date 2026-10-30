import logging
import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import (
    SESSION_COOKIE_NAME,
    delete_session,
    get_current_user,
    is_request_https,
)
from app.config import config
from app.routes.iptv import get_effective_base_url
from app.version import APP_NAME, APP_VERSION

logger = logging.getLogger("SweetTV.Routes.Views")
router = APIRouter(include_in_schema=False)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates_dir = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=templates_dir)


@router.get("/", response_class=HTMLResponse)
def index_view(request: Request):
    """Main Web Dashboard and Live TV Player."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    base_url = get_effective_base_url(request)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_version": APP_VERSION,
            "app_name": APP_NAME,
            "logged": config.is_logged,
            "country_code": config.country_code,
            "base_url": base_url,
            "external_url": config.external_url,
            "default_quality": config.default_quality,
            "direct_redirect": config.direct_redirect,
            "m3u_catchup": config.get("m3u_catchup", True),
            "mac": config.get("mac"),
            "uuid": config.get("uuid"),
            # Authenticated user context
            "user_id": user.id,
            "username": user.username,
            "user_role": user.role,
            "is_admin": user.is_admin,
            "user_token": user.token,
            "user_stalker_mac": user.stalker_mac or "",
            "must_change_password": user.must_change_password,
            "xtream_user": user.username,
            "xtream_password": "••••••••",
        }
    )


@router.get("/login", response_class=HTMLResponse)
def login_view(request: Request):
    """Dedicated login view."""
    user = get_current_user(request)
    if user and user.can_access():
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "app_version": APP_VERSION,
            "app_name": APP_NAME,
        }
    )


@router.get("/logout")
def logout_view(request: Request):
    """Logs out user, deletes session from DB, and redirects to login."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        delete_session(session_id)
    response = RedirectResponse("/login", status_code=303)
    is_secure = is_request_https(request)
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=is_secure,
        httponly=True,
        samesite="lax"
    )
    return response


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt():
    """Instructs web crawlers and search engine bots not to index this site."""
    return "User-agent: *\nDisallow: /\n"


@router.get("/health")
def health_check():
    """Healthcheck endpoint for Docker, Portainer, and load balancers."""
    return {"status": "healthy", "logged": config.is_logged}
