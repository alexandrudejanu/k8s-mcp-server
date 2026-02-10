# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python MCP (Model Context Protocol) server that exposes Kubernetes cluster health and diagnostics tools. Implements MCP spec 2025-11-25 with two transport variants: STDIO (local) and Streamable HTTP (containerized).

## Development Setup

```bash
# Create and activate virtualenv (Python 3.10+)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Requires a valid kubeconfig (defaults to `~/.kube/config`).

## Running

```bash
# Local STDIO mode (used by Claude Code via .mcp.json)
python k8s_mcp_server_local.py

# HTTP mode
python k8s_mcp_server_http.py  # listens on port 8000

# Docker
docker compose -f docker-compose.yml up --build -d

# Test with MCP Inspector
npx @modelcontextprotocol/inspector python k8s_mcp_server_local.py
```

## Architecture

Two server files share identical tool implementations but differ in transport:

- **k8s_mcp_server_local.py** — STDIO transport for direct Claude Code integration. Communicates via stdin/stdout JSON-RPC.
- **k8s_mcp_server_http.py** — Streamable HTTP transport using Starlette/Uvicorn. Exposes `/messages` (POST/GET/DELETE) and `/health` endpoints. Uses `StreamableHTTPSessionManager` for stateful sessions.

Both files follow the same internal structure:
1. `init_kubernetes()` — tries in-cluster config, falls back to kubeconfig
2. `@app.list_tools()` — registers 6 tools with JSON schemas
3. `@app.call_tool()` — routes tool name to async handler function
4. Individual async tool functions (`get_cluster_info`, `check_node_health`, `check_pod_health`, `get_resource_usage`, `diagnose_cluster`, `get_namespace_summary`)

The tool implementations are duplicated across both files (not shared via a common module).

## Key Dependencies

- `mcp` — MCP protocol framework (server, tools, transports)
- `kubernetes` — Official Python client for Kubernetes API
- `starlette` + `uvicorn` — ASGI server (HTTP variant only)

## Docker

The Dockerfile builds the HTTP variant only. The docker-compose mounts `~/.kube/config` read-only into the container. Health check hits `GET /health` on port 8000.
