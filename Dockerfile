FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
COPY pyproject.toml README.md ./
RUN uv pip install --system ".[mcp]"
COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "dr_manhattan.strategies"]
