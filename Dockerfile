# Dr. Manhattan MCP Server - SSE Transport
# For Railway deployment

FROM python:3.13-slim

WORKDIR /app

# Install uv for fast dependency management (per CLAUDE.md rule 3)
RUN pip install --no-cache-dir uv

# Copy dependency files first (layer caching optimization)
COPY pyproject.toml README.md ./

# Install dependencies before copying code (changes to code won't invalidate this layer)
RUN uv pip install --system ".[mcp]"

# Copy source code (this layer changes frequently)
COPY dr_manhattan/ ./dr_manhattan/

# Expose port (Railway will set PORT env var)
EXPOSE 8080

# Environment defaults
ENV PORT=8080
ENV LOG_LEVEL=INFO
ENV HOST=0.0.0.0

# Health check using Python (curl not available in python:slim)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# Run SSE server
CMD ["python", "-m", "dr_manhattan.mcp.server_sse"]
