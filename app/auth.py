# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Authentication and role enforcement for the admin interface and admin API.

One mechanism serves both consumers. A request is accepted if it carries
either a valid session cookie (set by the browser login form) or HTTP Basic
credentials (used by scripts and curl). Both resolve against the same users
table, so there is no second credential store to keep in sync.

Deliberately out of scope, and documented as such in SECURITY.md:
single sign-on, password reset by mail, two-factor authentication,
per-category permissions, and account lockout after repeated failures.
"""
import asyncio
import base64
import binascii
import secrets
from datetime import datetime, timezone
from typing import Optional

import structlog
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError, VerificationError
from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_async_session
from app.models import Role, User

logger = structlog.get_logger()
settings = get_settings()

_hasher = PasswordHasher()

SESSION_USER_KEY = "username"

# A pre-computed hash of a value nobody will guess. Verifying against it when
# the username does not exist keeps the response time of "unknown user" and
# "wrong password" comparable, so the login form does not leak which usernames
# are valid.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    """Return an encoded Argon2 hash, including the parameters used."""
    return _hasher.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    """Check a password against an encoded hash without raising on mismatch."""
    try:
        return _hasher.verify(encoded_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(encoded_hash: str) -> bool:
    """True if the hash was produced with weaker parameters than the current ones."""
    try:
        return _hasher.check_needs_rehash(encoded_hash)
    except InvalidHashError:
        return True


async def authenticate(session: AsyncSession, username: str, password: str) -> Optional[User]:
    """
    Resolve a username and password to an active user, or None.

    On success the stored hash is upgraded in place if the hashing parameters
    have since been strengthened, so existing accounts benefit without anyone
    having to change their password.
    """
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        # Spend roughly the same time as a real verification would.
        verify_password(password, _DUMMY_HASH)
        return None

    if not verify_password(password, user.password_hash):
        return None

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    user.last_login_at = datetime.now(timezone.utc)
    await session.flush()
    return user


def _basic_auth_credentials(request: Request) -> Optional[tuple[str, str]]:
    """Extract username and password from an HTTP Basic Authorization header."""
    header = request.headers.get("Authorization", "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    username, separator, password = decoded.partition(":")
    if not separator:
        return None
    return username, password


async def resolve_current_user(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> Optional[User]:
    """
    Identify the caller from the session cookie or from HTTP Basic credentials.

    Returns None for anonymous callers; the role dependencies below decide what
    that means for a given route.
    """
    username = request.session.get(SESSION_USER_KEY) if "session" in request.scope else None

    if username:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if user is not None and user.is_active:
            return user
        # Stale cookie: the account was deleted or disabled since login.
        request.session.clear()

    credentials = _basic_auth_credentials(request)
    if credentials:
        user = await authenticate(session, *credentials)
        if user is None:
            await asyncio.sleep(settings.login_failure_delay)
        return user

    return None


def require_role(required: Role, *, redirect_to_login: bool = False):
    """
    Build a dependency that admits callers holding at least the required role.

    redirect_to_login is used for the browser-facing admin UI, where sending a
    human to a login page is more useful than a 401 body. The REST API keeps
    the status codes so that scripts can react to them.
    """

    async def dependency(
        request: Request,
        user: Optional[User] = Depends(resolve_current_user),
    ) -> User:
        if user is None:
            if redirect_to_login:
                target = request.url.path
                raise _RedirectToLogin(target)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": 'Basic realm="FlexMapping"'},
            )

        if not Role(user.role).covers(required):
            logger.warning(
                "authorization_denied",
                username=user.username,
                role=user.role,
                required=required.value,
                path=request.url.path,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This operation requires the '{required.value}' role.",
            )

        request.state.user = user
        return user

    return dependency


class _RedirectToLogin(Exception):
    """Raised by the UI dependencies; translated into a redirect in main.py."""

    def __init__(self, next_path: str):
        self.next_path = next_path
        super().__init__(next_path)


def redirect_to_login_response(exc: _RedirectToLogin) -> RedirectResponse:
    """Build the redirect that sends an anonymous browser to the login form."""
    return RedirectResponse(
        url=f"/admin-ui/login?next={exc.next_path}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# Ready-made dependencies. Import these rather than calling require_role at
# each use site, so the set of access levels stays visible in one place.
require_viewer = require_role(Role.VIEWER)
require_editor = require_role(Role.EDITOR)
require_admin = require_role(Role.ADMIN)

require_viewer_ui = require_role(Role.VIEWER, redirect_to_login=True)
require_editor_ui = require_role(Role.EDITOR, redirect_to_login=True)
require_admin_ui = require_role(Role.ADMIN, redirect_to_login=True)


async def ensure_bootstrap_admin(session: AsyncSession) -> Optional[str]:
    """
    Create the first administrator if the users table is empty.

    Returns the username that was created, or None if accounts already exist.
    Startup in production already refuses to proceed while the bootstrap
    password is still a placeholder, so this cannot quietly create a
    well-known account on a public instance.
    """
    result = await session.execute(select(User).limit(1))
    if result.scalar_one_or_none() is not None:
        return None

    username = settings.bootstrap_admin_username
    user = User(
        username=username,
        password_hash=hash_password(settings.bootstrap_admin_password),
        role=Role.ADMIN.value,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    logger.warning(
        "bootstrap_admin_created",
        username=username,
        hint="Log in and change this password before exposing the instance.",
    )
    return username
