FROM python:3.11-slim

LABEL org.opencontainers.image.authors="dejanualex"

WORKDIR /app

# needed so pip can build C extensions when wheels are not available
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN --mount=type=bind,source=requirements.txt,target=/tmp/requirements.txt \
    pip install --no-cache-dir -r  /tmp/requirements.txt

COPY k8s_mcp_server_http.py .

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
ENV PORT=8000

CMD ["python", "k8s_mcp_server_http.py"]
