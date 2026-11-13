"""Khởi tạo ứng dụng FastAPI.

Chạy:  uvicorn app.main:create_app --factory --reload
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .ai import build_provider
from .config import Settings, get_settings
from .db import create_tables, init_engine
from .utils.timeutil import set_default_timezone
from .web import auth, bank, classes, courses, dashboard, exams, experiment, materials, public, student
from .web.deps import LoginRequired, StudentLoginRequired, redirect, render

log = logging.getLogger("app")
APP_DIR = Path(__file__).resolve().parent


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    settings.ensure_dirs()
    set_default_timezone(settings.timezone)
    init_engine(settings.resolved_database_url)
    create_tables()

    app = FastAPI(title=settings.app_name, version=__version__, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.ai = build_provider(settings)
    log.info("%s v%s – AI: %s", settings.app_name, __version__, app.state.ai.name)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.get_secret_key(),
        session_cookie="goimo_session",
        max_age=30 * 24 * 3600,
        same_site="lax",
    )
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

    for module in (public, auth, dashboard, courses, materials, bank, exams, classes, experiment, student):
        app.include_router(module.router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return redirect(f"/login?next={quote(target)}")

    @app.exception_handler(StudentLoginRequired)
    async def _student_login_required(request: Request, exc: StudentLoginRequired):
        if request.url.path.startswith("/hs/api/"):
            return JSONResponse({"detail": "Em cần đăng nhập lại."}, status_code=401)
        return redirect("/hs/dang-nhap")

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        wants_json = "/api/" in request.url.path or "application/json" in request.headers.get("accept", "")
        if wants_json:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return render(request, "error.html", status=exc.status_code, detail=exc.detail, status_code=exc.status_code)

    return app
