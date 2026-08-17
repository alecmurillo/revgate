# Dockerfile for the revgate API server.
#
# Build:
#   docker build -t revgate .
# Run (mount your own config and data):
#   docker run -p 8000:8000 \
#     -e REVGATE_API_KEY=your-secret \
#     -v $(pwd)/revgate.toml:/app/revgate.toml:ro \
#     -v $(pwd)/data:/app/data:ro \
#     revgate
#
# Then:
#   curl -X POST http://localhost:8000/v1/lint \
#     -H "Content-Type: application/json" \
#     -H "X-Revgate-Key: your-secret" \
#     -d @data/clay-block.json
#
# The server is stdlib-only (no uvicorn, no gunicorn). For production
# traffic, run behind a reverse proxy (nginx, Caddy, AWS ALB) that handles
# TLS, rate limiting, and request body size limits.

FROM python:3.12-slim

WORKDIR /app

# Copy the package and install in editable mode.
COPY pyproject.toml README.md LICENSE ./
COPY revgate/ ./revgate/
RUN pip install --no-cache-dir -e .

# Create a non-root user and switch to it.
RUN groupadd -r revgate && useradd -r -g revgate -d /app revgate
USER revgate

# No default config or fixtures are baked in. The operator must mount
# their own revgate.toml and data files. The server refuses to start
# without a config.
EXPOSE 8000

# The server is single-process. For higher concurrency, run multiple
# containers behind a load balancer. The server is stateless — each
# request is evaluated independently.
CMD ["python3", "-m", "revgate", "serve", "--port", "8000"]
