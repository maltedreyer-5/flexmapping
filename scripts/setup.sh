#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
#
# Prepare a .env file and start FlexMapping.
#
# Generates the values that have no sensible default and can be generated
# safely: the session secret, the database password and, unless one is given,
# the administrator password. It does not invent an LLM endpoint; that is the
# one thing only you know.
#
# Safe to run again: an existing .env is left alone unless --force is passed.

set -euo pipefail

ENV_FILE=".env"
FORCE=0
START=1
ADMIN_PASSWORD=""

usage() {
    cat <<'USAGE'
Usage: scripts/setup.sh [options]

  --force               overwrite an existing .env
  --no-start            write .env but do not start the containers
  --admin-password PW   use this administrator password instead of a generated one
  --llm-url URL         LLM endpoint, e.g. http://localhost:8001/v1
  --llm-model NAME      model name
  -h, --help            show this text
USAGE
}

LLM_URL=""
LLM_MODEL=""

while [ $# -gt 0 ]; do
    case "$1" in
        --force) FORCE=1 ;;
        --no-start) START=0 ;;
        --admin-password) ADMIN_PASSWORD="${2:?missing value}"; shift ;;
        --llm-url) LLM_URL="${2:?missing value}"; shift ;;
        --llm-model) LLM_MODEL="${2:?missing value}"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
    shift
done

cd "$(dirname "$0")/.."

# --- prerequisites --------------------------------------------------------
# Only checked when the script is going to start something. Writing .env works
# on a machine without Docker, which is useful when preparing a deployment
# elsewhere.
check_prerequisites() {
    local missing=0
    command -v docker >/dev/null 2>&1 || { echo "Missing: docker"; missing=1; }
    docker compose version >/dev/null 2>&1 || { echo "Missing: the docker compose plugin"; missing=1; }
    [ "$missing" -eq 0 ] || { echo; echo "Install the missing tools and run this again."; exit 1; }
}
[ "$START" -eq 1 ] && check_prerequisites

# --- secret generation ----------------------------------------------------
# openssl where available, otherwise Python, otherwise /dev/urandom. One of the
# three exists on any machine that can run this project.
generate() {
    local length="$1"
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 48 | tr -d '\n/+=' | cut -c "1-$length"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "import secrets,sys; print(secrets.token_urlsafe(64)[:int(sys.argv[1])])" "$length"
    else
        LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c "$length"
    fi
}

# --- write .env -----------------------------------------------------------
if [ -f "$ENV_FILE" ] && [ "$FORCE" -eq 0 ]; then
    echo "$ENV_FILE exists. Leaving it untouched; pass --force to regenerate."
else
    [ -f .env.example ] || { echo "ERROR: .env.example not found."; exit 1; }

    SESSION_SECRET="$(generate 48)"
    POSTGRES_PASSWORD="$(generate 24)"
    [ -n "$ADMIN_PASSWORD" ] || ADMIN_PASSWORD="$(generate 20)"

    cp .env.example "$ENV_FILE"
    # Replace in place. The keys are anchored at the start of the line so that
    # a commented example line is not matched.
    replace() {
        local key="$1" value="$2"
        python3 - "$ENV_FILE" "$key" "$value" <<'PY'
import re, sys
path, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(path, encoding="utf-8").read()
text = re.sub(rf"^{re.escape(key)}=.*$", f"{key}={value}", text, flags=re.M)
open(path, "w", encoding="utf-8").write(text)
PY
    }
    replace SESSION_SECRET "$SESSION_SECRET"
    replace POSTGRES_PASSWORD "$POSTGRES_PASSWORD"
    replace BOOTSTRAP_ADMIN_PASSWORD "$ADMIN_PASSWORD"
    replace DATABASE_URL "postgresql+asyncpg://flexmap:${POSTGRES_PASSWORD}@db:5432/flexmap"
    replace DATABASE_URL_SYNC "postgresql://flexmap:${POSTGRES_PASSWORD}@db:5432/flexmap"
    # The LLM key is often unchecked by self-hosted endpoints, but it must not
    # remain a CHANGE_ME placeholder, because that blocks a production start.
    replace LLM_API_KEY "not-checked-by-this-endpoint"
    [ -n "$LLM_URL" ] && replace LLM_BASE_URL "$LLM_URL"
    [ -n "$LLM_MODEL" ] && replace LLM_MODEL "$LLM_MODEL"

    chmod 600 "$ENV_FILE"

    echo "Wrote $ENV_FILE with generated secrets."
    echo
    echo "  Administrator: admin"
    echo "  Password:      $ADMIN_PASSWORD"
    echo
    echo "Write the password down now; it is stored only as a hash after the first start."
fi

# --- remaining manual step ------------------------------------------------
if grep -q '^LLM_BASE_URL=http://localhost:8001/v1$' "$ENV_FILE" && [ -z "$LLM_URL" ]; then
    echo
    echo "LLM_BASE_URL still points at the default http://localhost:8001/v1."
    echo "Set it to your OpenAI-compatible endpoint, together with LLM_MODEL."
    echo "Crawling, extraction and translation need it; the interface and the"
    echo "entity import do not."
fi

# --- start ----------------------------------------------------------------
if [ "$START" -eq 0 ]; then
    echo
    echo "Not starting. Run: docker compose up -d"
    exit 0
fi

echo
echo "Starting the containers..."
docker compose up -d

echo "Waiting for the application to report healthy..."
for _ in $(seq 1 60); do
    if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        echo
        echo "Ready: http://localhost:8000/admin-ui"
        echo "Sign in as 'admin' with the password above, and change it."
        exit 0
    fi
    sleep 2
done

echo
echo "The application did not report healthy within two minutes."
echo "Look at the logs: docker compose logs app"
exit 1
