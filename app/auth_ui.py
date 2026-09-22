# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Login and logout pages.

These live on their own router, mounted without the role dependency that
protects the rest of the admin UI. Putting them on the protected router would
redirect an anonymous visitor from the login page back to the login page.
"""
import asyncio
from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import SESSION_USER_KEY, authenticate
from app.config import get_settings
from app.database import get_async_session

logger = structlog.get_logger()
settings = get_settings()

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _safe_next(candidate: Optional[str]) -> str:
    """
    Restrict the post-login redirect to paths inside this application.

    Without this check, a crafted link could carry an absolute URL and send a
    freshly authenticated operator to another site.
    """
    if not candidate or not candidate.startswith("/") or candidate.startswith("//"):
        return "/admin-ui"
    return candidate


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next: str = "/admin-ui"):
    """Render the login form."""
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "next": _safe_next(next), "error": None},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/admin-ui"),
    session: AsyncSession = Depends(get_async_session),
):
    """Verify credentials and open a session."""
    user = await authenticate(session, username, password)

    if user is None:
        # A fixed delay on failure slows down password guessing. It is not a
        # lockout; see SECURITY.md for what is deliberately not covered.
        await asyncio.sleep(settings.login_failure_delay)
        logger.warning("login_failed", username=username)
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "next": _safe_next(next),
                "error": "Unknown username or wrong password.",
            },
            status_code=401,
        )

    request.session[SESSION_USER_KEY] = user.username
    logger.info("login_succeeded", username=user.username, role=user.role)
    return RedirectResponse(url=_safe_next(next), status_code=303)


@router.get("/logout")
async def logout(request: Request):
    """Clear the session and return to the login form."""
    request.session.clear()
    return RedirectResponse(url="/admin-ui/login", status_code=303)
