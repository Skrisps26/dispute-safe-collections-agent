FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY prompts ./prompts
COPY data ./data
RUN uv sync --frozen --no-dev && uv run --no-sync python -m collections_agent.worker download-files
RUN useradd --create-home --uid 10001 agent && chown -R agent:agent /app
USER agent
CMD ["uv", "run", "--no-sync", "python", "-m", "collections_agent.worker", "start"]
