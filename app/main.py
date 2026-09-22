# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
FastAPI application entry point.

Startup and shutdown run through a lifespan context manager: the database
connection, the bootstrap administrator and the production readiness check all
have to complete before the first request is served.

The generated static site is served dynamically under /public rather than
mounted, because the directory is rewritten on every generation run and a
mount would hold stale file handles.
"""
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import (
    _RedirectToLogin,
    ensure_bootstrap_admin,
    redirect_to_login_response,
    require_admin,
    require_editor,
    require_viewer_ui,
)
from app import __version__
from app.config import get_settings
from app.database import AsyncSessionLocal, init_db

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events
    """
    # Startup
    logger.info(
        "Starting FlexMapping application",
        version=__version__,
    )

    # Refuse to start a production instance that still carries development
    # defaults. This is checked before anything binds to a port.
    settings.check_production_readiness()

    # Wait for database and initialize
    await init_db()

    # Create the first administrator if no account exists yet.
    try:
        async with AsyncSessionLocal() as session:
            await ensure_bootstrap_admin(session)
            await session.commit()
    except Exception as e:
        logger.error("Failed to ensure bootstrap admin", error=str(e), exc_info=True)

    # Ensure public directory exists for static file mounting
    public_dir = Path(settings.public_site_dir)
    if not public_dir.exists():
        public_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Created public directory", path=str(public_dir))
    else:
        logger.info("Public directory exists", path=str(public_dir))

    yield

    # Shutdown
    logger.info("Shutting down FlexMapping application")


# Create FastAPI app with lifespan
app = FastAPI(
    title="FlexMapping",
    description="LLM-based information extraction system",
    version=__version__,
    # The interactive docs list every endpoint, including the destructive ones,
    # so they follow DOCS_ENABLED rather than being always on.
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
    lifespan=lifespan
)

# Signed session cookie for the browser login. Rotating SESSION_SECRET
# invalidates all sessions, which is the intended way to log everyone out.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=settings.session_max_age,
    https_only=settings.session_cookie_secure,
    same_site="lax",
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_media_type(file_path: Path) -> str:
    """Determine media type based on file extension"""
    suffix = file_path.suffix.lower()
    media_types = {
        '.html': 'text/html; charset=utf-8',
        '.css': 'text/css; charset=utf-8',
        '.js': 'application/javascript; charset=utf-8',
        '.json': 'application/json; charset=utf-8',
        '.xml': 'application/xml; charset=utf-8',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.svg': 'image/svg+xml',
        '.ico': 'image/x-icon',
        '.woff': 'font/woff',
        '.woff2': 'font/woff2',
        '.ttf': 'font/ttf',
    }
    return media_types.get(suffix, 'application/octet-stream')


# Serve the generated site under /public/*
# This handles all requests to /public/ and serves from public_site_dir

@app.get("/public/{path:path}")
async def serve_public(path: str):
    """
    Serve public site files dynamically
    Maps /public/X to {public_site_dir}/X
    """
    public_dir = Path(settings.public_site_dir)

    # Handle empty path or root - serve index.html
    if not path or path == '':
        file_path = public_dir / "index.html"
    # Handle directory requests - serve index.html
    elif path.endswith('/'):
        file_path = public_dir / path / "index.html"
    else:
        file_path = public_dir / path

    # Security check: ensure path doesn't escape public_dir
    try:
        file_path = file_path.resolve()
        public_dir_resolved = public_dir.resolve()
        if not str(file_path).startswith(str(public_dir_resolved)):
            logger.warning("Path escape attempt", requested_path=path)
            return JSONResponse({"error": "Access denied"}, status_code=403)
    except Exception as e:
        logger.error("Path resolution error", path=path, error=str(e))
        return JSONResponse({"error": "Invalid path"}, status_code=400)

    # Check if file exists
    if file_path.exists() and file_path.is_file():
        media_type = get_media_type(file_path)
        logger.debug("Serving file", path=str(file_path), media_type=media_type)
        return FileResponse(file_path, media_type=media_type)

    # Try adding .html extension for clean URLs
    if not file_path.suffix and (file_path.with_suffix('.html')).exists():
        html_path = file_path.with_suffix('.html')
        return FileResponse(html_path, media_type='text/html; charset=utf-8')

    # Try serving index.html from directory
    index_path = file_path / "index.html"
    if index_path.exists():
        return FileResponse(index_path, media_type='text/html; charset=utf-8')

    logger.warning("File not found", path=str(file_path))
    return JSONResponse({"error": "File not found", "path": path}, status_code=404)


@app.get("/public")
async def serve_public_root():
    """Redirect /public to /public/"""
    public_dir = Path(settings.public_site_dir)
    index_file = public_dir / "index.html"

    if index_file.exists():
        return FileResponse(index_file, media_type='text/html; charset=utf-8')

    return JSONResponse({"error": "Index not found"}, status_code=404)


@app.exception_handler(_RedirectToLogin)
async def redirect_to_login_handler(request: Request, exc: _RedirectToLogin):
    """Send anonymous browsers to the login form instead of a bare 401."""
    return redirect_to_login_response(exc)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.debug else "An error occurred"
        }
    )


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    from app.database import check_db_connection

    health = {
        "status": "healthy",
        "version": __version__
    }

    # Check database connection
    if check_db_connection():
        health["database"] = "connected"
        return health

    health["database"] = "disconnected"
    health["status"] = "unhealthy"
    # Returned with a 503 rather than a 200 carrying an "unhealthy" body.
    # Everything that only inspects the status code -- the container
    # healthcheck in docker-compose, load balancers, uptime monitors -- would
    # otherwise treat a database outage as a healthy instance.
    return JSONResponse(status_code=503, content=health)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "name": "FlexMapping API",
        "version": __version__,
        "endpoints": {
            "admin_ui": "/admin-ui (browser UI)",
            "admin_api": "/admin (REST API)",
            "public_api": "/api",
            "public_site": "/public (static site)",
            "docs": "/docs",
            "redoc": "/redoc",
            "health": "/health"
        }
    }


# Import and register routers
from app.api.admin import router as admin_router
from app.recovery_endpoints import router as recovery_router
from app.api.public import router as public_router
from app.admin_ui import router as admin_ui_router
from app.auth_ui import router as auth_ui_router

# Admin REST API. EDITOR is the floor for the whole router; the routes that
# change configuration or destroy data raise the bar to ADMIN individually
# (see app/api/admin.py).
app.include_router(
    admin_router,
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_editor)],
)

# Recovery endpoints for stuck sources and jobs. Mounted under /admin so they
# share the prefix with the rest of the management API; the router carries its
# own admin-role dependency.
app.include_router(
    recovery_router,
    prefix="/admin",
    tags=["admin", "recovery"],
    dependencies=[Depends(require_editor)],
)

# Public REST API: read-only, and the data source for the generated static
# site. Intentionally unauthenticated.
app.include_router(public_router, prefix="/api", tags=["public"])

# Vendored frontend assets (htmx, Alpine.js, Tailwind). These are served from
# the application rather than a CDN so that the admin interface works on a
# machine with no outbound internet access, and so that the exact versions are
# pinned in the repository instead of resolved at page load.
app.mount(
    "/admin-ui/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="admin-static",
)

# Login and logout. Mounted before the protected UI router and without its
# dependency, so an anonymous visitor can actually reach the form.
app.include_router(auth_ui_router, prefix="/admin-ui", tags=["auth"])

# Admin UI. Anonymous browsers are redirected to the login form rather than
# receiving a 401 body.
app.include_router(
    admin_ui_router,
    prefix="/admin-ui",
    tags=["admin-ui"],
    dependencies=[Depends(require_viewer_ui)],
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
        log_level=settings.log_level.lower()
    )