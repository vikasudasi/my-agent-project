# =============================================================================
# AI Task Management System — Docker Image
#
# All-in-one container running the MCP server in HTTP/SSE mode.
# SQLite database is persisted via /data volume.
#
# Build:
#   docker build -t task-manager .
#
# Run (with persistent DB volume):
#   docker run -d -p 8000:8000 -v tm-data:/data --name task-manager task-manager
#
# Run (ephemeral, for testing):
#   docker run --rm -p 8000:8000 task-manager
#
# Agents connect via SSE at   http://<host>:8000/sse
# =============================================================================

FROM python:3.12-slim

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TM_DB_PATH=/data/task_manager.db

# ---------------------------------------------------------------------------
# System deps
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Install Python dependencies
# ---------------------------------------------------------------------------
WORKDIR /app
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Copy application code
# ---------------------------------------------------------------------------
COPY server/ ./server/
COPY skill/ ./skill/

# ---------------------------------------------------------------------------
# Volume for persistent SQLite database
# ---------------------------------------------------------------------------
VOLUME /data

# ---------------------------------------------------------------------------
# Port: MCP server (HTTP/SSE)
# ---------------------------------------------------------------------------
EXPOSE 8000

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
WORKDIR /app/server
CMD ["python", "mcp_server.py", "--http", "--host", "0.0.0.0", "--port", "8000"]