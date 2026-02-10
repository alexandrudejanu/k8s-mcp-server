#!/usr/bin/env python3
"""
Kubernetes MCP Server with Streamable HTTP Transport
Provides tools for Kubernetes cluster assessment via MCP protocol

Endpoints:
- POST /messages: Send MCP requests and receive streaming responses
- GET /messages: Establish SSE stream for server-initiated messages
- DELETE /messages: Terminate MCP session
- GET /health: Health check
"""

import asyncio
from typing import Any, Sequence
from contextlib import asynccontextmanager

from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
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
        ),
        Tool(
            name="check_networking",
            description="Check cluster networking and Istio service mesh health: control plane status, sidecar injection coverage, proxy version consistency, Istio config (VirtualServices, DestinationRules, Gateways), services with missing endpoints, and NetworkPolicies",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": "Optional: specific namespace to check (default: all namespaces)"
                    }
                }
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
        elif name == "check_networking":
            namespace = arguments.get("namespace", None)
            return await check_networking(namespace)
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
        result += f"\n Problem Pods ({len(problem_pods)}):\n"
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


async def check_networking(namespace: str = None) -> Sequence[TextContent]:
    """Check cluster networking and Istio service mesh health"""
    from collections import defaultdict

    def _fetch():
        v1 = client.CoreV1Api()
        custom_api = client.CustomObjectsApi()
        networking_api = client.NetworkingV1Api()

        # --- Istio control plane ---
        istio_pods = []
        try:
            istio_pods = v1.list_namespaced_pod("istio-system").items
        except ApiException:
            pass

        # --- All pods (for sidecar analysis) ---
        if namespace:
            all_pods = v1.list_namespaced_pod(namespace).items
        else:
            all_pods = v1.list_pod_for_all_namespaces().items

        # --- Services and Endpoints (missing endpoints check) ---
        if namespace:
            services = v1.list_namespaced_service(namespace).items
            endpoints = v1.list_namespaced_endpoints(namespace).items
        else:
            services = v1.list_service_for_all_namespaces().items
            endpoints = v1.list_endpoints_for_all_namespaces().items

        # --- NetworkPolicies ---
        if namespace:
            net_policies = networking_api.list_namespaced_network_policy(namespace).items
        else:
            net_policies = networking_api.list_network_policy_for_all_namespaces().items

        # --- Istio CRDs (VirtualService, DestinationRule, Gateway) ---
        istio_resources = {}
        istio_crds = [
            ("networking.istio.io", "v1", "virtualservices"),
            ("networking.istio.io", "v1", "destinationrules"),
            ("networking.istio.io", "v1", "gateways"),
            ("networking.istio.io", "v1", "serviceentries"),
            ("security.istio.io", "v1", "peerauthentications"),
        ]
        for group, version, plural in istio_crds:
            try:
                if namespace:
                    items = custom_api.list_namespaced_custom_object(
                        group=group, version=version, namespace=namespace, plural=plural
                    ).get("items", [])
                else:
                    items = custom_api.list_cluster_custom_object(
                        group=group, version=version, plural=plural
                    ).get("items", [])
                istio_resources[plural] = items
            except ApiException:
                istio_resources[plural] = None  # CRD not installed

        return istio_pods, all_pods, services, endpoints, net_policies, istio_resources

    (istio_pods, all_pods, services, endpoints,
     net_policies, istio_resources) = await asyncio.to_thread(_fetch)

    scope = f"Namespace: {namespace}" if namespace else "All Namespaces"
    result = f"Networking & Istio Diagnostics ({scope}):\n"
    result += "═" * 60 + "\n\n"

    # ── 1. Istio Control Plane ──
    result += "Istio Control Plane:\n"
    result += "─" * 60 + "\n"
    if not istio_pods:
        result += "  ⚠ No pods found in istio-system (Istio may not be installed)\n"
    else:
        for pod in istio_pods:
            phase = pod.status.phase
            indicator = "✓" if phase == "Running" else "✗"
            result += f"  {indicator} {pod.metadata.name}: {phase}\n"
    result += "\n"

    # ── 2. Sidecar Injection Coverage ──
    result += "Sidecar Injection Coverage:\n"
    result += "─" * 60 + "\n"
    ns_total = defaultdict(int)
    ns_injected = defaultdict(int)
    proxy_versions = defaultdict(int)

    for pod in all_pods:
        ns_name = pod.metadata.namespace
        ns_total[ns_name] += 1
        containers = pod.spec.containers or []
        for c in containers:
            if c.name == "istio-proxy":
                ns_injected[ns_name] += 1
                # Extract proxy version from image tag
                if c.image and ":" in c.image:
                    version = c.image.rsplit(":", 1)[1]
                    proxy_versions[version] += 1
                break

    total_pods = sum(ns_total.values())
    total_injected = sum(ns_injected.values())

    if total_injected == 0:
        result += "  ⚠ No istio-proxy sidecars detected in any pod\n"
    else:
        result += f"  Total: {total_injected}/{total_pods} pods have sidecar "
        result += f"({total_injected * 100 // total_pods}%)\n\n"
        for ns_name in sorted(ns_total.keys()):
            injected = ns_injected.get(ns_name, 0)
            total = ns_total[ns_name]
            pct = injected * 100 // total if total else 0
            indicator = "✓" if injected == total else ("~" if injected > 0 else "✗")
            result += f"  {indicator} {ns_name}: {injected}/{total} ({pct}%)\n"
    result += "\n"

    # ── 3. Proxy Version Consistency ──
    result += "Proxy Version Consistency:\n"
    result += "─" * 60 + "\n"
    if not proxy_versions:
        result += "  N/A (no sidecars detected)\n"
    elif len(proxy_versions) == 1:
        ver, count = next(iter(proxy_versions.items()))
        result += f"  ✓ All {count} proxies running version: {ver}\n"
    else:
        result += f"  ⚠ Mixed versions detected ({len(proxy_versions)} versions):\n"
        for ver, count in sorted(proxy_versions.items(), key=lambda x: -x[1]):
            result += f"    - {ver}: {count} proxies\n"
    result += "\n"

    # ── 4. Services with Missing Endpoints ──
    result += "Services with Missing Endpoints:\n"
    result += "─" * 60 + "\n"
    ep_map = {}
    for ep in endpoints:
        key = f"{ep.metadata.namespace}/{ep.metadata.name}"
        addresses = []
        for subset in (ep.subsets or []):
            addresses.extend(subset.addresses or [])
        ep_map[key] = len(addresses)

    no_endpoint_svcs = []
    for svc in services:
        # Skip headless and ExternalName services
        if svc.spec.type == "ExternalName":
            continue
        if svc.spec.cluster_ip == "None":
            continue
        key = f"{svc.metadata.namespace}/{svc.metadata.name}"
        if ep_map.get(key, 0) == 0:
            no_endpoint_svcs.append(key)

    if no_endpoint_svcs:
        result += f"  ⚠ {len(no_endpoint_svcs)} service(s) with no ready endpoints:\n"
        for svc_name in no_endpoint_svcs[:20]:
            result += f"    - {svc_name}\n"
        if len(no_endpoint_svcs) > 20:
            result += f"    ... and {len(no_endpoint_svcs) - 20} more\n"
    else:
        result += "  ✓ All services have ready endpoints\n"
    result += "\n"

    # ── 5. Istio Configuration Summary ──
    result += "Istio Configuration:\n"
    result += "─" * 60 + "\n"
    crd_labels = {
        "virtualservices": "VirtualServices",
        "destinationrules": "DestinationRules",
        "gateways": "Gateways",
        "serviceentries": "ServiceEntries",
        "peerauthentications": "PeerAuthentications",
    }
    istio_installed = False
    for plural, label in crd_labels.items():
        items = istio_resources.get(plural)
        if items is None:
            result += f"  - {label}: CRD not installed\n"
        else:
            istio_installed = True
            if items:
                # Count per namespace
                ns_counts = defaultdict(int)
                for item in items:
                    ns_counts[item["metadata"].get("namespace", "<cluster>")] += 1
                parts = [f"{ns}: {c}" for ns, c in sorted(ns_counts.items())]
                result += f"  {label} ({len(items)}): {', '.join(parts)}\n"
            else:
                result += f"  {label}: 0\n"
    if not istio_installed:
        result += "  ⚠ No Istio CRDs found — Istio is not installed\n"
    result += "\n"

    # ── 6. NetworkPolicies ──
    result += "NetworkPolicies:\n"
    result += "─" * 60 + "\n"
    if not net_policies:
        result += "No NetworkPolicies defined (all pod-to-pod traffic is allowed)\n"
    else:
        np_by_ns = defaultdict(int)
        for np in net_policies:
            np_by_ns[np.metadata.namespace] += 1
        result += f"  Total: {len(net_policies)}\n"
        for ns_name, count in sorted(np_by_ns.items()):
            result += f"    {ns_name}: {count}\n"
    result += "\n"

    return [TextContent(type="text", text=result)]


# Initialize session manager
session_manager = StreamableHTTPSessionManager(
    app=app,  # MCP Server instance
    stateless=False,  # Maintain sessions across requests
    json_response=False,  # Use SSE streaming (recommended)
    retry_interval=1000,  # SSE retry in milliseconds
)


def main():
    """Main entry point for Streamable HTTP transport"""
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from starlette.responses import JSONResponse
    import uvicorn

    @asynccontextmanager
    async def lifespan(starlette_app):
        """Manage session manager lifecycle"""
        async with session_manager.run():
            yield

    # Health check endpoint
    async def health_check(request):
        return JSONResponse({"status": "healthy"})

    # Create Starlette app with lifespan
    starlette_app = Starlette(
        routes=[
            Route("/health", endpoint=health_check, methods=["GET"]),
            Mount("/messages", app=session_manager.handle_request),
        ],
        lifespan=lifespan,
    )

    print("🚀 Kubernetes MCP Server (Streamable HTTP) starting on http://0.0.0.0:8000")
    print("📋 MCP Protocol Endpoints:")
    print("   POST   /messages          - Send MCP requests")
    print("   GET    /messages          - Establish SSE stream for server messages")
    print("   DELETE /messages          - Terminate session")
    print("   GET    /health            - Health check")
    print("")
    print("Protocol: MCP Streamable HTTP (2025-11-25)")
    print("Session Mode: Stateful")
    print("")
    print("Example MCP initialization:")
    print('   curl -X POST http://localhost:8000/messages \\')
    print('        -H "Content-Type: application/json" \\')
    print('        -H "Accept: text/event-stream" \\')
    print('        -H "mcp-protocol-version: 2025-11-25" \\')
    print('        -d \'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}\'')

    # Run with uvicorn
    uvicorn.run(
        starlette_app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )


if __name__ == "__main__":
    main()