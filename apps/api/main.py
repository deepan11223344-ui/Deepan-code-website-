"""
DeepanCode Web API entry point.

    uvicorn apps.api.main:app --host 127.0.0.1 --port 8080

Binds loopback by default; set DEEPANCODE_HOST explicitly to expose
(behind TLS + reverse proxy).
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import chat as chat_routes
from .headers import SecurityHeadersMiddleware

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .store import get_web_db
    get_web_db()._ensure_init()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="DeepanCode Web", version="3.0.0", docs_url=None,
                  redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(chat_routes.router)

    static = WEB_DIR / "static"
    if static.exists():
        app.mount("/static", StaticFiles(directory=str(static)), name="static")

    for page in ("index.html", "chat.html"):
        path = WEB_DIR / page

        def _serve(path=path):
            async def _handler():
                resp = FileResponse(str(path))
                resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                resp.headers["Pragma"] = "no-cache"
                resp.headers["Expires"] = "0"
                return resp
            return _handler

        route = "/" if page == "index.html" else f"/{page.replace('.html', '')}"
        app.get(route, include_in_schema=False)(_serve())

    return app


app = create_app()
