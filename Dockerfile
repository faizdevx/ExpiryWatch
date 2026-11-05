FROM python:3.12-slim

# Logs reach "docker logs" immediately, and no .pyc files are written by the non-root user.
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Requirements first: code changes then reuse this cached layer instead of reinstalling.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

RUN useradd --create-home --shell /usr/sbin/nologin appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health', timeout=4)"

# exec makes uvicorn PID 1, so it receives SIGTERM from "docker stop" and shuts down cleanly.
# shortcut: migrations run on every start, which is safe for one instance only; move them to a release step before scaling out.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
