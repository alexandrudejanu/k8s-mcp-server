# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A read-only Kubernetes MCP (Model Context Protocol) server that exposes cluster health and diagnostic tools to AI clients. It runs as a pod in  `mcp` namespace and queries **remote** target clusters via a multi-context kubeconfig mounted from the `k8s-mcp-kubeconfig` Secret.

## Running locally

```bash
# Install dependencies
uv sync

# Start the HTTP server (port 8885)
uv run fastmcp run k8s_mcp_server_http.py --transport http --host 0.0.0.0 --port 8885
# or equivalently
uv run python k8s_mcp_server_http.py

# Run with Docker Compose (mounts ~/.kube/config for multi-cluster mode)
docker compose up --build

# Inspect via MCP Inspector
npx @modelcontextprotocol/inspector --transport http --server-url http://localhost:8885/messages

# Health check
curl http://localhost:8885/health
```

## Building and pushing the image

```bash
docker build --platform linux/amd64,linux/arm64 -t dejanualex/k8s-mcp-server:3.0 .
docker push dejanualex/k8s-mcp-server:3.0
```

## Environment variables

| Variable | Purpose |
|---|---|
| `KUBECONFIG` | Path to kubeconfig file — enables multi-cluster mode |
| `KUBECONFIG_CONTEXT` | Default context name at startup |
| `PORT` | Server port (default `8885`) |

Without `KUBECONFIG`, the server falls back to in-cluster config (hosting cluster only).

## Architecture

Two source files contain all the logic:

- **`k8s_mcp_server_http.py`** — FastMCP server entry point. Registers MCP tools, applies the `_handle_tool_errors` decorator to return errors as strings instead of exceptions, and exposes a `/health` endpoint. Calls `configure_kubernetes()` at module load time from env vars.

- **`k8s_tools.py`** — All tool implementations. Manages kubeconfig state in module-level globals (`_k8s_initialized`, `_loaded_context`, etc.). Since the `kubernetes` Python client is synchronous, all API calls are wrapped with `asyncio.to_thread()`. Every tool accepts an optional `context` parameter for a one-off cluster override; `set_kubeconfig_context` changes the session-level context for all subsequent calls.

**`k8s_resources/`** contains the production Kubernetes manifests:
- `deployment.yaml` — pod spec with kubeconfig Secret volume mount
- `rbac.yaml` — ServiceAccount and ClusterRole for the hosting cluster
- `remote_cluster_rbac.yaml` — read-only RBAC for target clusters
- `kubeconfig-secret.yaml` — template for the multi-context kubeconfig Secret

## Key design patterns

- **Context switching is session-global**: `set_kubeconfig_context` mutates module-level state in `k8s_tools.py`. There is no per-request isolation.
- **Error handling at the tool boundary**: `_handle_tool_errors` in the HTTP server catches all exceptions and returns them as plain strings. Tool implementations in `k8s_tools.py` do not need their own try/except.
- **Optional CRDs**: `check_networking` silently skips Istio CRD queries when they return 404 — Istio is treated as optional.
- **Metrics-server optional**: `get_resource_usage` degrades gracefully when the metrics API is unavailable (404 → informational message).

## Production deployment

- **Hosting cluster**: `ai-aws-prod-use1-0`, namespace `mcp`
- **MCP endpoint**: `http://k8s-mcp-server.mcp.svc.cluster.local:8885/messages`
- **Kubeconfig**: Secret `k8s-mcp-kubeconfig` mounted at `/etc/kubeconfig/config`
- To add a new target cluster: update the Secret and rollout-restart the pod — no image rebuild needed.
