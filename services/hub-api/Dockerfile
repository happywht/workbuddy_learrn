FROM python:3.12-alpine@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY services/hub-api/requirements.lock ./requirements.lock
RUN pip install --require-hashes --only-binary=:all: -r requirements.lock \
    && python -m pip uninstall --yes pip \
    && addgroup -g 10001 hub \
    && adduser -D -H -u 10001 -G hub -s /sbin/nologin hub

COPY services/hub-api/alembic.ini ./
COPY services/hub-api/migrations ./migrations
COPY services/hub-api/src ./src
COPY contracts/mcp/hub-tools.json ./contracts/mcp/hub-tools.json
COPY workbuddy-hub/data/registry.json ./workbuddy-hub/data/registry.json

EXPOSE 8000
USER 10001:10001
CMD ["sh", "-c", "python -m hub_api.migrate && uvicorn hub_api.main:app --host 0.0.0.0 --port 8000 --http h11"]
