FROM python:3.12-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

LABEL org.opencontainers.image.authors="dejanualex@gmail.com"

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PORT=8885

# needed so uv can build C extensions when wheels are not available
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
COPY k8s_mcp_server_http.py k8s_tools.py ./
COPY kubeconfig/ ./kubeconfig/

RUN uv sync --frozen --no-dev

EXPOSE 8885

CMD ["uv", "run", "python", "k8s_mcp_server_http.py"]
