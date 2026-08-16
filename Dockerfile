# Dockerfile for the revgate API server.
#
# Build:
#   docker build -t revgate .
# Run:
#   docker run -p 8000:8000 -e REVGATE_API_KEY=your-secret revgate
#
# Then:
#   curl -X POST http://localhost:8000/v1/lint \
#     -H "Content-Type: application/json" \
#     -H "X-Revgate-Key: your-secret" \
#     -d @fixtures/api/clay-block.json
#
# The server is stdlib-only (no uvicorn, no gunicorn). For production
# traffic, run behind a reverse proxy (nginx, Caddy, AWS ALB) that handles
# TLS, rate limiting, and request body size limits.

FROM python:3.12-slim

WORKDIR /app

# Copy the package and install in editable mode.
COPY pyproject.toml README.md ./
COPY revgate/ ./revgate/
RUN pip install --no-cache-dir -e .

# Default config. Override by mounting a volume:
#   docker run -v $(pwd)/revgate.toml:/app/revgate.toml revgate
COPY revgate.toml ./revgate.toml

EXPOSE 8000

ENV REVGATE_PORT=8000

# The server is single-process. For higher concurrency, run multiple
# containers behind a load balancer. The server is stateless — each
# request is evaluated independently.
CMD ["python3", "-m", "revgate", "serve", "--port", "8000"]
