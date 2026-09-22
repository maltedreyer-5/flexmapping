# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Shared fixtures.

The checks in this directory run without PostgreSQL, Redis or an LLM backend,
so that they work in CI and on a fresh checkout. Anything that needs a live
service belongs in a separate suite; see CONTRIBUTING.md.
"""
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
