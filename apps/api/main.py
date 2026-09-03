"""
DeepanCode Web API entry point.

    uvicorn apps.api.main:app --host 127.0.0.1 --port 8080

Fail-closed startup: refuses to serve authenticated traffic without
DEEPANCODE_JWT_SECRET (>=32 chars). Binds loopback by default; set
DEEPANCODE_HOST explicitly to expose (behind TLS + reverse proxy).
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import auth as auth_routes
from . import chat as chat_routes
from .headers import SecurityHeadersMiddleware

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .store import get_web_db
    get_web_db()._ensure_init()
    get_web_db().prune_sessions()
    yield


def create_app() -> FastAPI:
    # Fail fast on missing JWT secret so no authed route can misbehave.
    from .crypto import jwt_secret
    jwt_secret()

    app = FastAPI(title="DeepanCode Web", version="3.0.0", docs_url=None,
                  redoc_url=None, openapi_url=None, lifespan=lifespan)  # no API explorer exposed
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(auth_routes.router)
    app.include_router(chat_routes.router)

    static = WEB_DIR / "static"
    if static.exists():
        app.mount("/static", StaticFiles(directory=str(static)), name="static")

    for page in ("index.html", "login.html", "chat.html"):
        path = WEB_DIR / page

        def _serve(path=path):
            async def _handler():
                return FileResponse(str(path))
            return _handler

        route = "/" if page == "index.html" else f"/{page.replace('.html', '')}"
        app.get(route, include_in_schema=False)(_serve())

    # Serve chat.html for deep links handled client-side is intentionally
    # absent: unknown paths 404 instead of leaking the app shell.

    return app


app = create_app()
