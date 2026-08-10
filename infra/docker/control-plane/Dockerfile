# RoofSpan Control Plane container. Built from /app/backend. HUMAN builds/pushes to ECR (see RUNBOOK.md).
# Build context = repo root:  docker build -f infra/docker/control-plane/Dockerfile -t roofspan-control-plane .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt && pip install boto3 pyjwt

COPY backend /app
COPY infra/docker/control-plane/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080
# entrypoint runs CP Alembic migrations under a single-runner advisory lock, then serves cp_app:app.
ENTRYPOINT ["/entrypoint.sh"]
