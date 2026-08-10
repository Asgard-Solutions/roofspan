# RoofSpan Secure Relay container. Built from /app/backend. HUMAN builds/pushes to ECR (see RUNBOOK.md).
# Build context = repo root:  docker build -f infra/docker/relay/Dockerfile -t roofspan-relay .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt && pip install "redis>=5"

COPY backend /app

EXPOSE 8080
# Long-lived WSS relay; ALB idle timeout is raised accordingly (see infra/aws/alb.tf).
CMD ["uvicorn", "relay_app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
