# RoofSpan Central Control Plane - Railway production image.
# Focused CLOUD image: only the FastAPI Control Plane (cp_asgi:app) + its Python deps. It intentionally
# excludes every Windows/desktop packaging artifact (the Office frontend build, the desktop shell + its
# native runtime, the Windows service bundler, the bundled database installer, and the relay/updater
# services). Build context = repo root (see railway.json).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Linux/cloud-safe backend deps only (backend/requirements.txt contains no Windows-only packages).
COPY backend/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Control Plane application code (the whole backend package; only cp_asgi:app is served).
COPY backend/ /app/

# Railway injects $PORT at runtime; never hard-code a production port.
CMD ["sh", "-c", "uvicorn cp_asgi:app --host 0.0.0.0 --port ${PORT:-8080}"]
