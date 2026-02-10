#!/usr/bin/env python3

"""
Kubernetes MCP Server
Provides tools for Kubernetes cluster assessment, health checks, and diagnostics
"""

import asyncio
from typing import Any, Sequence

from mcp.server import Server
from mcp.types import Tool, TextContent
from kubernetes import client, config
from kubernetes.client.rest import ApiException


# Initialize MCP server
app = Server("kubernetes-mcp-server")


_k8s_initialized = False


def init_kubernetes():
    """Initialize Kubernetes client (only runs once)"""
    global _k8s_initialized
    if _k8s_initialized:
        return
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    _k8s_initialized = True


def format_resource_usage(cpu, memory):
    """Format resource usage in human-readable format"""
    # Convert CPU to cores
    if 'n' in cpu:
        cpu_cores = float(cpu.rstrip('n')) / 1e9
    elif 'u' in cpu:
        cpu_cores = float(cpu.rstrip('u')) / 1e6
    elif 'm' in cpu:
        cpu_cores = float(cpu.rstrip('m')) / 1000
    else:
        cpu_cores = float(cpu)
    
    # Convert memory
    if 'Ki' in memory:
        mem_gb = float(memory.rstrip('Ki')) / (1024 * 1024)
    elif 'Mi' in memory:
        mem_gb = float(memory.rstrip('Mi')) / 1024
    elif 'Gi' in memory:
        mem_gb = float(memory.rstrip('Gi'))
    else:
        mem_gb = float(memory) / (1024**3)
    
    return f"{cpu_cores:.2f} cores, {mem_gb:.2f} GB"


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available Kubernetes assessment tools"""
    return [
        Tool(
            name="get_cluster_info",
            description="Get basic Kubernetes cluster information including version and API server status",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="check_node_health",
            description="Check the health status and resource usage of all nodes in the cluster",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="check_pod_health",
            description="Check the health status of pods across all namespaces or a specific namespace",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": "Optional: specific namespace to check (default: all namespaces)"
                    }
                }
            }
        ),
        Tool(
            name="get_resource_usage",
            description="Get resource usage statistics (CPU and memory) for nodes and pods",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": "Optional: specific namespace to check (default: all namespaces)"
                    }
                }
            }
        ),
        Tool(
            name="diagnose_cluster",
            description="Run comprehensive cluster diagnostics including failing pods, resource pressure, and common issues",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_namespace_summary",
            description="Get a summary of resources in each namespace",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> Sequence[TextContent]:
    """Handle tool calls"""
    
    try:
        init_kubernetes()
        
        if name == "get_cluster_info":
            return await get_cluster_info()
        elif name == "check_node_health":
            return await check_node_health()
        elif name == "check_pod_health":
            namespace = arguments.get("namespace", None)
            return await check_pod_health(namespace)
        elif name == "get_resource_usage":
            namespace = arguments.get("namespace", None)
            return await get_resource_usage(namespace)
        elif name == "diagnose_cluster":
            return await diagnose_cluster()
        elif name == "get_namespace_summary":
            return await get_namespace_summary()
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
            
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def get_cluster_info() -> Sequence[TextContent]:
    """Get cluster information"""
    def _fetch():
        v1 = client.CoreV1Api()
        version_api = client.VersionApi()
        version_info = version_api.get_code()
        v1.get_api_resources()
        nodes = v1.list_node()
        namespaces = v1.list_namespace()
        return version_info, len(nodes.items), len(namespaces.items)

    version_info, node_count, ns_count = await asyncio.to_thread(_fetch)

    result = f"""Cluster Information:
─────────────────────
Kubernetes Version: {version_info.git_version}
Platform: {version_info.platform}
API Server: Healthy
Total Nodes: {node_count}
Total Namespaces: {ns_count}
"""

    return [TextContent(type="text", text=result)]


async def check_node_health() -> Sequence[TextContent]:
    """Check health of all nodes"""
    def _fetch():
        v1 = client.CoreV1Api()
        return v1.list_node()

    nodes = await asyncio.to_thread(_fetch)
    
    result = "Node Health Status:\n═══════════════════\n\n"
    
    for node in nodes.items:
        node_name = node.metadata.name
        result += f"Node: {node_name}\n"
        result += "─" * 50 + "\n"
        
        # Check conditions
        conditions = node.status.conditions
        for condition in conditions:
            if condition.type in ["Ready", "MemoryPressure", "DiskPressure", "PIDPressure"]:
                status = "✓" if (condition.type == "Ready" and condition.status == "True") or \
                               (condition.type != "Ready" and condition.status == "False") else "✗"
                result += f"  {status} {condition.type}: {condition.status}\n"
        
        # Capacity and allocatable resources
        capacity = node.status.capacity
        allocatable = node.status.allocatable
        
        result += f"\nCapacity:\n"
        result += f"  CPU: {capacity.get('cpu', 'N/A')}\n"
        result += f"  Memory: {capacity.get('memory', 'N/A')}\n"
        result += f"  Pods: {capacity.get('pods', 'N/A')}\n"
        
        result += f"\nAllocatable:\n"
        result += f"  CPU: {allocatable.get('cpu', 'N/A')}\n"
        result += f"  Memory: {allocatable.get('memory', 'N/A')}\n"
        result += f"  Pods: {allocatable.get('pods', 'N/A')}\n"
        
        result += "\n"
    
    return [TextContent(type="text", text=result)]


async def check_pod_health(namespace: str = None) -> Sequence[TextContent]:
    """Check health of pods"""
    def _fetch():
        v1 = client.CoreV1Api()
        if namespace:
            return v1.list_namespaced_pod(namespace)
        return v1.list_pod_for_all_namespaces()

    pods = await asyncio.to_thread(_fetch)

    if namespace:
        result = f"Pod Health Status (Namespace: {namespace}):\n"
    else:
        result = "Pod Health Status (All Namespaces):\n"
    
    result += "═" * 60 + "\n\n"
    
    # Organize by status
    status_counts = {
        "Running": 0,
        "Pending": 0,
        "Failed": 0,
        "Succeeded": 0,
        "Unknown": 0
    }
    
    problem_pods = []
    
    for pod in pods.items:
        phase = pod.status.phase
        status_counts[phase] = status_counts.get(phase, 0) + 1
        
        # Check for problems
        if phase in ["Failed", "Unknown"] or phase == "Pending":
            container_statuses = pod.status.container_statuses or []
            issues = []
            
            for container_status in container_statuses:
                if not container_status.ready:
                    if container_status.state.waiting:
                        issues.append(f"{container_status.name}: {container_status.state.waiting.reason}")
                    elif container_status.state.terminated:
                        issues.append(f"{container_status.name}: Terminated - {container_status.state.terminated.reason}")
            
            problem_pods.append({
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "phase": phase,
                "issues": issues
            })
    
    # Summary
    result += "Summary:\n"
    for status, count in status_counts.items():
        if count > 0:
            indicator = "✓" if status in ["Running", "Succeeded"] else "✗"
            result += f"  {indicator} {status}: {count}\n"
    
    # Problem pods
    if problem_pods:
        result += f"\n⚠ Problem Pods ({len(problem_pods)}):\n"
        result += "─" * 60 + "\n"
        for pod in problem_pods:
            result += f"\n  Pod: {pod['namespace']}/{pod['name']}\n"
            result += f"  Status: {pod['phase']}\n"
            if pod['issues']:
                result += "  Issues:\n"
                for issue in pod['issues']:
                    result += f"    - {issue}\n"
    else:
        result += "\n✓ No problem pods detected\n"
    
    return [TextContent(type="text", text=result)]


async def get_resource_usage(namespace: str = None) -> Sequence[TextContent]:
    """Get resource usage statistics"""

    def _fetch():
        from kubernetes.client import CustomObjectsApi
        custom_api = CustomObjectsApi()
        node_metrics = custom_api.list_cluster_custom_object(
            group="metrics.k8s.io", version="v1beta1", plural="nodes"
        )
        if namespace:
            pod_metrics = custom_api.list_namespaced_custom_object(
                group="metrics.k8s.io", version="v1beta1",
                namespace=namespace, plural="pods"
            )
        else:
            pod_metrics = custom_api.list_cluster_custom_object(
                group="metrics.k8s.io", version="v1beta1", plural="pods"
            )
        return node_metrics, pod_metrics

    try:
        node_metrics, pod_metrics = await asyncio.to_thread(_fetch)

        result = "Resource Usage:\n"
        result += "═" * 60 + "\n\n"
        result += "Nodes:\n"
        result += "─" * 60 + "\n"

        for node in node_metrics['items']:
            name = node['metadata']['name']
            usage = node['usage']
            result += f"  {name}: {format_resource_usage(usage['cpu'], usage['memory'])}\n"

        if namespace:
            result += f"\n\nPods (Namespace: {namespace}):\n"
        else:
            result += "\n\nTop Pods by Resource Usage:\n"
        result += "─" * 60 + "\n"

        # Sort pods by CPU usage (normalize to nanocores / Ki)
        pods_with_usage = []
        for pod in pod_metrics['items']:
            total_cpu = 0  # nanocores
            total_mem = 0  # Ki

            for container in pod['containers']:
                cpu = container['usage']['cpu']
                mem = container['usage']['memory']
                # Normalize CPU to nanocores
                if 'n' in cpu:
                    total_cpu += float(cpu.rstrip('n'))
                elif 'u' in cpu:
                    total_cpu += float(cpu.rstrip('u')) * 1e3
                elif 'm' in cpu:
                    total_cpu += float(cpu.rstrip('m')) * 1e6
                else:
                    total_cpu += float(cpu) * 1e9
                # Normalize memory to Ki
                if 'Ki' in mem:
                    total_mem += float(mem.rstrip('Ki'))
                elif 'Mi' in mem:
                    total_mem += float(mem.rstrip('Mi')) * 1024
                elif 'Gi' in mem:
                    total_mem += float(mem.rstrip('Gi')) * 1024 * 1024
                else:
                    total_mem += float(mem) / 1024

            pods_with_usage.append({
                'name': pod['metadata']['name'],
                'namespace': pod['metadata']['namespace'],
                'cpu': total_cpu,
                'memory': total_mem
            })

        pods_with_usage.sort(key=lambda x: x['cpu'], reverse=True)
        for pod in pods_with_usage[:10]:
            cpu_str = f"{pod['cpu']}n" if pod['cpu'] < 1000000 else f"{pod['cpu']/1000000:.2f}m"
            mem_str = f"{pod['memory']:.0f}Ki"
            result += f"  {pod['namespace']}/{pod['name']}: {format_resource_usage(cpu_str, mem_str)}\n"

    except ApiException as e:
        if e.status == 404:
            result = "Resource Usage:\n"
            result += "═" * 60 + "\n\n"
            result += "Metrics Server not available\n"
        else:
            result = f"Error getting metrics: {str(e)}"

    return [TextContent(type="text", text=result)]


async def diagnose_cluster() -> Sequence[TextContent]:
    """Run comprehensive cluster diagnostics"""
    def _fetch():
        v1 = client.CoreV1Api()
        return v1.list_node(), v1.list_pod_for_all_namespaces()

    nodes, pods = await asyncio.to_thread(_fetch)

    result = "Cluster Diagnostics:\n"
    result += "═" * 60 + "\n\n"

    issues = []

    for node in nodes.items:
        for condition in node.status.conditions:
            if condition.type == "Ready" and condition.status != "True":
                issues.append(f"Node {node.metadata.name} is not Ready")
            elif condition.type in ["MemoryPressure", "DiskPressure", "PIDPressure"] and condition.status == "True":
                issues.append(f"Node {node.metadata.name} has {condition.type}")

    # Check for failing pods
    failing_pods = []
    pending_pods = []
    
    for pod in pods.items:
        if pod.status.phase == "Failed":
            failing_pods.append(f"{pod.metadata.namespace}/{pod.metadata.name}")
        elif pod.status.phase == "Pending":
            pending_pods.append(f"{pod.metadata.namespace}/{pod.metadata.name}")
    
    # Check for pods with restarts
    high_restart_pods = []
    for pod in pods.items:
        if pod.status.container_statuses:
            for container in pod.status.container_statuses:
                if container.restart_count > 5:
                    high_restart_pods.append(
                        f"{pod.metadata.namespace}/{pod.metadata.name} "
                        f"(container: {container.name}, restarts: {container.restart_count})"
                    )
    
    # Report findings
    if not issues and not failing_pods and not pending_pods and not high_restart_pods:
        result += "✓ No critical issues detected\n\n"
        result += "Cluster appears healthy!\n"
    else:
        result += "⚠ Issues Detected:\n"
        result += "─" * 60 + "\n\n"
        
        if issues:
            result += "Node Issues:\n"
            for issue in issues:
                result += f"  - {issue}\n"
            result += "\n"
        
        if failing_pods:
            result += f"Failed Pods ({len(failing_pods)}):\n"
            for pod in failing_pods[:10]:  # Limit to 10
                result += f"  - {pod}\n"
            if len(failing_pods) > 10:
                result += f"  ... and {len(failing_pods) - 10} more\n"
            result += "\n"
        
        if pending_pods:
            result += f"Pending Pods ({len(pending_pods)}):\n"
            for pod in pending_pods[:10]:
                result += f"  - {pod}\n"
            if len(pending_pods) > 10:
                result += f"  ... and {len(pending_pods) - 10} more\n"
            result += "\n"
        
        if high_restart_pods:
            result += f"Pods with High Restart Count ({len(high_restart_pods)}):\n"
            for pod in high_restart_pods[:10]:
                result += f"  - {pod}\n"
            if len(high_restart_pods) > 10:
                result += f"  ... and {len(high_restart_pods) - 10} more\n"
    
    return [TextContent(type="text", text=result)]


async def get_namespace_summary() -> Sequence[TextContent]:
    """Get summary of resources per namespace"""
    def _fetch():
        v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        namespaces = v1.list_namespace()
        all_pods = v1.list_pod_for_all_namespaces()
        all_services = v1.list_service_for_all_namespaces()
        all_deployments = apps_v1.list_deployment_for_all_namespaces()
        return namespaces, all_pods, all_services, all_deployments

    namespaces, all_pods, all_services, all_deployments = await asyncio.to_thread(_fetch)

    # Group by namespace
    from collections import defaultdict
    pods_by_ns = defaultdict(list)
    for p in all_pods.items:
        pods_by_ns[p.metadata.namespace].append(p)
    svcs_by_ns = defaultdict(list)
    for s in all_services.items:
        svcs_by_ns[s.metadata.namespace].append(s)
    deps_by_ns = defaultdict(list)
    for d in all_deployments.items:
        deps_by_ns[d.metadata.namespace].append(d)

    result = "Namespace Summary:\n"
    result += "═" * 60 + "\n\n"

    for ns in namespaces.items:
        ns_name = ns.metadata.name
        ns_pods = pods_by_ns.get(ns_name, [])

        running = sum(1 for p in ns_pods if p.status.phase == "Running")
        failed = sum(1 for p in ns_pods if p.status.phase == "Failed")
        pending = sum(1 for p in ns_pods if p.status.phase == "Pending")

        result += f"Namespace: {ns_name}\n"
        result += "─" * 60 + "\n"
        result += f"  Pods: {len(ns_pods)} (Running: {running}, Pending: {pending}, Failed: {failed})\n"
        result += f"  Deployments: {len(deps_by_ns.get(ns_name, []))}\n"
        result += f"  Services: {len(svcs_by_ns.get(ns_name, []))}\n"
        result += "\n"

    return [TextContent(type="text", text=result)]


async def main():
    """Main entry point"""
    from mcp.server.stdio import stdio_server
    
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())