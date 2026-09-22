# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
API Routes Package
"""
from .admin import router as admin_router
from .public import router as public_router

__all__ = ["admin_router", "public_router"]