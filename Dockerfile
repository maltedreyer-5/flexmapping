# FlexMapping application image.
FROM python:3.11-slim AS base

WORKDIR /app

# gcc/g++ are needed to build wheels that have no prebuilt binary for slim;
# postgresql-client provides pg_isready and psql for maintenance work inside
# the container; curl backs the HEALTHCHECK below.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first so that dependency layers stay cached when only
# application code changes.
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY generate_site.py .
COPY public_templates/ ./public_templates/

# Output directory for the generated static site. docker-compose mounts a
# host directory here and sets PUBLIC_SITE_DIR to match.
RUN mkdir -p /var/www/flexmap

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Run as a non-root user. UID 1000 matches the `user:` setting in
# docker-compose.yml, so files written into the mounted volume stay readable
# on the host.
RUN useradd -m -u 1000 flexmap && \
    chown -R flexmap:flexmap /app /var/www/flexmap

USER flexmap

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
