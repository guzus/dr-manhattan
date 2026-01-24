# Dr. Manhattan MCP Server - SSE Transport
# For Railway deployment

FROM python:3.13-slim

WORKDIR /app

# Install uv for fast dependency management (per CLAUDE.md rule 3)
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml README.md ./
COPY dr_manhattan/ ./dr_manhattan/

# Install dependencies with mcp extras (non-editable for Docker)
RUN uv pip install --system ".[mcp]"

# Expose port (Railway will set PORT env var)
EXPOSE 8080

# Environment defaults
ENV PORT=8080
ENV LOG_LEVEL=INFO
ENV HOST=0.0.0.0

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Run SSE server
CMD ["python", "-m", "dr_manhattan.mcp.server_sse"]
