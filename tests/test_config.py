# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
The production guard must actually refuse to start.

The failure it prevents is silent: a publicly reachable instance running with
a known session key and a known admin password.
"""
import pytest

from app.config import PLACEHOLDER_PREFIX, Settings
from tests.conftest import REPO_ROOT

REAL = dict(
    SESSION_SECRET="x" * 40,
    BOOTSTRAP_ADMIN_PASSWORD="a-real-password",
    LLM_API_KEY="sk-a-real-key",
)


def test_development_starts_with_placeholders():
    Settings(ENVIRONMENT="development").check_production_readiness()


@pytest.mark.parametrize("field", list(REAL))
def test_production_refuses_each_placeholder(field):
    values = dict(REAL)
    values[field] = f"{PLACEHOLDER_PREFIX}_still_here"
    settings = Settings(ENVIRONMENT="production", **values)
    with pytest.raises(RuntimeError, match=field):
        settings.check_production_readiness()


def test_production_refuses_debug_and_docs():
    settings = Settings(ENVIRONMENT="production", DEBUG=True, DOCS_ENABLED=True, **REAL)
    with pytest.raises(RuntimeError) as excinfo:
        settings.check_production_readiness()
    assert "DEBUG" in str(excinfo.value)
    assert "DOCS_ENABLED" in str(excinfo.value)


def test_production_starts_when_configured():
    Settings(ENVIRONMENT="production", **REAL).check_production_readiness()


def test_safe_defaults():
    """Defaults must be the safe option, not the convenient one."""
    settings = Settings()
    assert settings.debug is False
    assert settings.docs_enabled is False
    assert settings.crawler_respect_robots is True
    assert settings.crawler_verify_ssl is True
    # CORS must default to localhost, not to a deployment-specific domain.
    assert all(o.startswith(("http://localhost", "http://127.0.0.1"))
               for o in settings.cors_allow_origins)


def test_the_shipped_env_example_loads():
    """
    Settings must load from an actual .env file, not only from keyword
    arguments.

    These are different code paths in pydantic-settings. A list-valued setting
    coming from a file is JSON-decoded before any validator runs, so
    CORS_ALLOW_ORIGINS as a comma-separated string aborted startup with a JSON
    parse error. Every test here passed, because they all constructed Settings
    directly.
    """
    env_example = REPO_ROOT / ".env.example"
    settings = Settings(_env_file=str(env_example))
    assert settings.cors_allow_origins == [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    assert settings.crawler_user_agent.startswith("FlexMapping")
    # The example file must still carry its placeholders; a real deployment
    # replaces them, and the production guard is what enforces that.
    assert set(settings.placeholder_settings()) == {
        "SESSION_SECRET",
        "BOOTSTRAP_ADMIN_PASSWORD",
        "LLM_API_KEY",
    }


def test_setup_script_produces_a_startable_env(tmp_path):
    """The generated .env must pass the production guard."""
    import shutil
    import subprocess

    workdir = tmp_path / "project"
    workdir.mkdir()
    shutil.copy(REPO_ROOT / ".env.example", workdir / ".env.example")
    shutil.copytree(REPO_ROOT / "scripts", workdir / "scripts")

    result = subprocess.run(
        ["bash", "scripts/setup.sh", "--no-start",
         "--llm-url", "http://llm.internal:8001/v1", "--llm-model", "test-model"],
        cwd=workdir, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    settings = Settings(_env_file=str(workdir / ".env"), ENVIRONMENT="production")
    assert settings.placeholder_settings() == []
    settings.check_production_readiness()
    assert settings.llm_base_url == "http://llm.internal:8001/v1"
