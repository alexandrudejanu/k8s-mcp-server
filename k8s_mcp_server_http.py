#!/usr/bin/env python3
"""
Kubernetes MCP Server with Streamable HTTP Transport (FastMCP)

Endpoints:
- POST/GET/DELETE /messages: MCP Streamable HTTP protocol
- GET /health: Health check
"""

import os
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from k8s_tools import (
    check_networking as check_networking_impl,
    check_node_health as check_node_health_impl,
    check_pod_health as check_pod_health_impl,
    configure_kubernetes,
    diagnose_cluster as diagnose_cluster_impl,
    get_cluster_info as get_cluster_info_impl,
    get_namespace_summary as get_namespace_summary_impl,
    get_resource_usage as get_resource_usage_impl,
    get_kubeconfig_context as get_kubeconfig_context_impl,
    list_kubeconfig_contexts as list_kubeconfig_contexts_impl,
    set_kubeconfig_context as set_kubeconfig_context_impl,
)

configure_kubernetes(
    kubeconfig_path=os.getenv("KUBECONFIG"),
    default_context=os.getenv("KUBECONFIG_CONTEXT"),
)

P = ParamSpec("P")
T = TypeVar("T")

mcp = FastMCP("kubernetes-mcp-server")


def _handle_tool_errors(
    fn: Callable[P, Awaitable[str]],
) -> Callable[P, Awaitable[str]]:
    @wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            return f"Error: {exc}"

    return wrapper


@mcp.custom_route("/health", methods=["GET"])
async def health_check(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "healthy"})


CONTEXT_PARAM = (
    "Optional one-off context override. "
    "Use set_kubeconfig_context to change the session cluster when the user asks."
)


@mcp.tool(
    description=(
        "List kubeconfig contexts and show which one is active "
        "for this session. Call when the user asks which clusters are available."
    )
)
@_handle_tool_errors
async def list_kubeconfig_contexts() -> str:
    return await list_kubeconfig_contexts_impl()


@mcp.tool(
    description=(
        "Show the active Kubernetes cluster context for this MCP session. "
        "Call when the user asks which cluster is currently selected."
    )
)
@_handle_tool_errors
async def get_kubeconfig_context() -> str:
    return await get_kubeconfig_context_impl()


@mcp.tool(
    description=(
        "Switch the active Kubernetes cluster for this MCP session. "
        "Call when the user asks to change cluster or context. "
        "Use list_kubeconfig_contexts first if you need valid context names."
    )
)
@_handle_tool_errors
async def set_kubeconfig_context(context: str) -> str:
    return await set_kubeconfig_context_impl(context)


@mcp.tool(
    description=(
        "Get basic Kubernetes cluster information including version, API server status, "
        "pods in Pending or Failed phase, and recent Warning events. "
        + CONTEXT_PARAM
    )
)
@_handle_tool_errors
async def get_cluster_info(context: str | None = None) -> str:
    return await get_cluster_info_impl(context)


@mcp.tool(
    description=(
        "Check the health status and resource usage of all nodes in the cluster. "
        + CONTEXT_PARAM
    )
)
@_handle_tool_errors
async def check_node_health(context: str | None = None) -> str:
    return await check_node_health_impl(context)


@mcp.tool(
    description=(
        "Check the health status of pods across all namespaces or a specific namespace. "
        + CONTEXT_PARAM
    )
)
@_handle_tool_errors
async def check_pod_health(
    namespace: str | None = None,
    context: str | None = None,
) -> str:
    return await check_pod_health_impl(namespace, context)


@mcp.tool(
    description=(
        "Get resource usage statistics (CPU and memory) for nodes and pods. "
        + CONTEXT_PARAM
    )
)
@_handle_tool_errors
async def get_resource_usage(
    namespace: str | None = None,
    context: str | None = None,
) -> str:
    return await get_resource_usage_impl(namespace, context)


@mcp.tool(
    description=(
        "Run comprehensive cluster diagnostics including failing pods, "
        "resource pressure, and common issues. "
        + CONTEXT_PARAM
    )
)
@_handle_tool_errors
async def diagnose_cluster(context: str | None = None) -> str:
    return await diagnose_cluster_impl(context)


@mcp.tool(
    description=("Get a summary of resources in each namespace. " + CONTEXT_PARAM)
)
@_handle_tool_errors
async def get_namespace_summary(context: str | None = None) -> str:
    return await get_namespace_summary_impl(context)


@mcp.tool(
    description=(
        "Check cluster networking and Istio service mesh health: control plane status, "
        "sidecar injection coverage, proxy version consistency, Istio config "
        "(VirtualServices, DestinationRules, Gateways), services with missing endpoints, "
        "and NetworkPolicies. "
        + CONTEXT_PARAM
    )
)
@_handle_tool_errors
async def check_networking(
    namespace: str | None = None,
    context: str | None = None,
) -> str:
    return await check_networking_impl(namespace, context)


if __name__ == "__main__":
    # the default MCP path is /mcp 
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8885,
        path="/messages",
    )
