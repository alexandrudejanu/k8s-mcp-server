"""Kubernetes cluster assessment tool implementations."""

import asyncio
import os
from collections import defaultdict

from kubernetes import client, config
from kubernetes.client.rest import ApiException


_k8s_initialized = False
_kubeconfig_path: str | None = None
_external_kubeconfig_enabled = False
_default_context: str | None = None
_loaded_context: str | None = None


def _context_name(context: object) -> str | None:
    """Normalize kubeconfig context to a context name string."""
    if context is None:
        return None
    if isinstance(context, dict):
        name = context.get("name")
        return name if isinstance(name, str) else None
    return str(context)


def configure_kubernetes(
    *,
    kubeconfig_path: str | None = None,
    default_context: str | None = None,
) -> None:
    """Set kubeconfig file path and optional default context name."""
    global _kubeconfig_path, _external_kubeconfig_enabled, _default_context
    _kubeconfig_path = kubeconfig_path
    _external_kubeconfig_enabled = bool(
        kubeconfig_path and os.path.exists(kubeconfig_path)
    )
    _default_context = default_context


def _kubeconfig_file() -> str:
    if not _kubeconfig_path:
        raise FileNotFoundError("KUBECONFIG path not configured")
    if not os.path.exists(_kubeconfig_path):
        raise FileNotFoundError(f"Kubeconfig not found at {_kubeconfig_path}")
    return _kubeconfig_path


def init_kubernetes(
    use_external_kubeconfig: bool = False,
    context: str | None = None,
) -> None:
    """Initialize or switch Kubernetes client configuration."""
    global _k8s_initialized, _loaded_context

    target_context = context if context is not None else _default_context
    if _k8s_initialized and target_context == _loaded_context:
        return

    if use_external_kubeconfig:
        kubeconfig = _kubeconfig_file()
        _, active_context = config.list_kube_config_contexts(kubeconfig)
        config.load_kube_config(
            config_file=kubeconfig,
            context=target_context,
        )
        _loaded_context = target_context or _context_name(active_context)
    else:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config(context=target_context)
        _loaded_context = target_context

    _k8s_initialized = True


def _init_kubernetes(context: str | None = None) -> None:
    init_kubernetes(use_external_kubeconfig=_external_kubeconfig_enabled, context=context)


def _available_context_names() -> list[str]:
    contexts, _ = config.list_kube_config_contexts(_kubeconfig_file())
    return [entry["name"] for entry in contexts]


def _cluster_for_context(context_name: str) -> str:
    contexts, _ = config.list_kube_config_contexts(_kubeconfig_file())
    for entry in contexts:
        if entry["name"] == context_name:
            return entry["context"]["cluster"]
    return "unknown"


async def get_kubeconfig_context() -> str:
    """Return the active session kubeconfig context."""
    if not _external_kubeconfig_enabled:
        return (
            "Session context switching requires KUBECONFIG pointing to a mounted kubeconfig file. "
            "In in-cluster mode the server uses the hosting cluster only."
        )

    _, file_active = config.list_kube_config_contexts(_kubeconfig_file())
    active = _loaded_context or _default_context or _context_name(file_active)
    if not active:
        return "No active context. Call set_kubeconfig_context to select a cluster."

    return (
        f"Active session context: {active}\n"
        f"Cluster: {_cluster_for_context(active)}"
    )


async def set_kubeconfig_context(context: str) -> str:
    """Set the active kubeconfig context for this MCP server session."""
    global _default_context, _k8s_initialized, _loaded_context

    if not _external_kubeconfig_enabled:
        return (
            "Context switching requires KUBECONFIG pointing to a mounted kubeconfig file. "
            "In in-cluster mode the server uses the hosting cluster only."
        )
    _kubeconfig_file()

    names = _available_context_names()
    if context not in names:
        available = "\n".join(f"  - {name}" for name in names)
        return f"Unknown context '{context}'.\n\nAvailable contexts:\n{available}"

    _default_context = context
    _k8s_initialized = False
    _loaded_context = None
    init_kubernetes(use_external_kubeconfig=True, context=context)

    return (
        f"Active context set to: {context}\n"
        f"Cluster: {_cluster_for_context(context)}\n\n"
        "Subsequent cluster tools will use this context until you change it again."
    )


async def list_kubeconfig_contexts() -> str:
    """List contexts in the kubeconfig file and show the active one."""
    if not _external_kubeconfig_enabled:
        return (
            "Context listing requires KUBECONFIG pointing to a mounted kubeconfig file. "
            "In in-cluster mode the server uses the hosting cluster only."
        )
    kubeconfig = _kubeconfig_file()

    contexts, file_active = config.list_kube_config_contexts(kubeconfig)
    active = _loaded_context or _context_name(file_active)

    result = "Available kubeconfig contexts:\n"
    result += "═" * 60 + "\n\n"
    for entry in contexts:
        name = entry["name"]
        cluster = entry["context"]["cluster"]
        marker = " ← active" if name == active else ""
        result += f"  {name}\n    cluster: {cluster}{marker}\n\n"

    result += (
        "Use set_kubeconfig_context to switch the active cluster for this session. "
        "Or pass context=<name> on a single tool call to override temporarily."
    )
    return result


def format_resource_usage(cpu, memory):
    """Format resource usage in human-readable format."""
    if "n" in cpu:
        cpu_cores = float(cpu.rstrip("n")) / 1e9
    elif "u" in cpu:
        cpu_cores = float(cpu.rstrip("u")) / 1e6
    elif "m" in cpu:
        cpu_cores = float(cpu.rstrip("m")) / 1000
    else:
        cpu_cores = float(cpu)

    if "Ki" in memory:
        mem_gb = float(memory.rstrip("Ki")) / (1024 * 1024)
    elif "Mi" in memory:
        mem_gb = float(memory.rstrip("Mi")) / 1024
    elif "Gi" in memory:
        mem_gb = float(memory.rstrip("Gi"))
    else:
        mem_gb = float(memory) / (1024**3)

    return f"{cpu_cores:.2f} cores, {mem_gb:.2f} GB"


async def get_cluster_info(context: str | None = None) -> str:
    """Get cluster information."""

    def _fetch():
        v1 = client.CoreV1Api()
        version_api = client.VersionApi()
        version_info = version_api.get_code()
        v1.get_api_resources()
        nodes = v1.list_node()
        namespaces = v1.list_namespace()
        pods = v1.list_pod_for_all_namespaces()
        events = v1.list_event_for_all_namespaces()
        return version_info, nodes, namespaces, pods, events

    _init_kubernetes(context)
    version_info, nodes, namespaces, pods, events = await asyncio.to_thread(_fetch)

    pending_pods = []
    failed_pods = []
    for pod in pods.items:
        phase = pod.status.phase
        entry = f"{pod.metadata.namespace}/{pod.metadata.name}"
        if phase == "Pending":
            pending_pods.append(entry)
        elif phase == "Failed":
            failed_pods.append(entry)

    warning_events = []
    for event in events.items:
        if event.type != "Warning":
            continue
        involved = event.involved_object
        resource = (
            f"{involved.namespace}/{involved.kind}/{involved.name}"
            if involved.namespace
            else f"{involved.kind}/{involved.name}"
        )
        warning_events.append(
            {
                "resource": resource,
                "reason": event.reason or "Unknown",
                "message": (event.message or "").replace("\n", " "),
                "timestamp": event.last_timestamp or event.event_time or event.first_timestamp,
            }
        )

    warning_events.sort(key=lambda e: e["timestamp"] or "", reverse=True)

    result = f"""Cluster Information:
─────────────────────
Kubernetes Version: {version_info.git_version}
Platform: {version_info.platform}
API Server: Healthy
Total Nodes: {len(nodes.items)}
Total Namespaces: {len(namespaces.items)}
"""

    result += "\nPods Not Running:\n"
    result += "─" * 60 + "\n"
    if not pending_pods and not failed_pods:
        result += "✓ No Pending or Failed pods\n"
    else:
        if pending_pods:
            result += f"Pending ({len(pending_pods)}):\n"
            for pod_name in pending_pods[:15]:
                result += f"  - {pod_name}\n"
            if len(pending_pods) > 15:
                result += f"  ... and {len(pending_pods) - 15} more\n"
        if failed_pods:
            result += f"Failed ({len(failed_pods)}):\n"
            for pod_name in failed_pods[:15]:
                result += f"  - {pod_name}\n"
            if len(failed_pods) > 15:
                result += f"  ... and {len(failed_pods) - 15} more\n"

    result += "\nRecent Warning Events:\n"
    result += "─" * 60 + "\n"
    if not warning_events:
        result += "✓ No warning events found\n"
    else:
        result += f"Total: {len(warning_events)} (showing latest 20)\n\n"
        for event in warning_events[:20]:
            ts = event["timestamp"]
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S UTC") if ts else "unknown"
            result += f"  [{ts_str}] {event['resource']}\n"
            result += f"    {event['reason']}: {event['message'][:200]}\n"

    return result


async def check_node_health(context: str | None = None) -> str:
    """Check health of all nodes."""

    def _fetch():
        v1 = client.CoreV1Api()
        return v1.list_node()

    _init_kubernetes(context)
    nodes = await asyncio.to_thread(_fetch)

    result = "Node Health Status:\n═══════════════════\n\n"

    for node in nodes.items:
        node_name = node.metadata.name
        result += f"Node: {node_name}\n"
        result += "─" * 50 + "\n"

        for condition in node.status.conditions:
            if condition.type in ["Ready", "MemoryPressure", "DiskPressure", "PIDPressure"]:
                status = (
                    "✓"
                    if (condition.type == "Ready" and condition.status == "True")
                    or (condition.type != "Ready" and condition.status == "False")
                    else "✗"
                )
                result += f"  {status} {condition.type}: {condition.status}\n"

        capacity = node.status.capacity
        allocatable = node.status.allocatable

        result += "\nCapacity:\n"
        result += f"  CPU: {capacity.get('cpu', 'N/A')}\n"
        result += f"  Memory: {capacity.get('memory', 'N/A')}\n"
        result += f"  Pods: {capacity.get('pods', 'N/A')}\n"

        result += "\nAllocatable:\n"
        result += f"  CPU: {allocatable.get('cpu', 'N/A')}\n"
        result += f"  Memory: {allocatable.get('memory', 'N/A')}\n"
        result += f"  Pods: {allocatable.get('pods', 'N/A')}\n"
        result += "\n"

    return result


async def check_pod_health(
    namespace: str | None = None,
    context: str | None = None,
) -> str:
    """Check health of pods."""

    def _fetch():
        v1 = client.CoreV1Api()
        if namespace:
            return v1.list_namespaced_pod(namespace)
        return v1.list_pod_for_all_namespaces()

    _init_kubernetes(context)
    pods = await asyncio.to_thread(_fetch)

    if namespace:
        result = f"Pod Health Status (Namespace: {namespace}):\n"
    else:
        result = "Pod Health Status (All Namespaces):\n"

    result += "═" * 60 + "\n\n"

    status_counts = {
        "Running": 0,
        "Pending": 0,
        "Failed": 0,
        "Succeeded": 0,
        "Unknown": 0,
    }

    problem_pods = []

    for pod in pods.items:
        phase = pod.status.phase
        status_counts[phase] = status_counts.get(phase, 0) + 1

        if phase in ["Failed", "Unknown"] or phase == "Pending":
            container_statuses = pod.status.container_statuses or []
            issues = []

            for container_status in container_statuses:
                if not container_status.ready:
                    if container_status.state.waiting:
                        issues.append(
                            f"{container_status.name}: {container_status.state.waiting.reason}"
                        )
                    elif container_status.state.terminated:
                        issues.append(
                            f"{container_status.name}: Terminated - "
                            f"{container_status.state.terminated.reason}"
                        )

            problem_pods.append(
                {
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "phase": phase,
                    "issues": issues,
                }
            )

    result += "Summary:\n"
    for status, count in status_counts.items():
        if count > 0:
            indicator = "✓" if status in ["Running", "Succeeded"] else "✗"
            result += f"  {indicator} {status}: {count}\n"

    if problem_pods:
        result += f"\n Problem Pods ({len(problem_pods)}):\n"
        result += "─" * 60 + "\n"
        for pod in problem_pods:
            result += f"\n  Pod: {pod['namespace']}/{pod['name']}\n"
            result += f"  Status: {pod['phase']}\n"
            if pod["issues"]:
                result += "  Issues:\n"
                for issue in pod["issues"]:
                    result += f"    - {issue}\n"
    else:
        result += "\n✓ No problem pods detected\n"

    return result


async def get_resource_usage(
    namespace: str | None = None,
    context: str | None = None,
) -> str:
    """Get resource usage statistics."""

    def _fetch():
        from kubernetes.client import CustomObjectsApi

        custom_api = CustomObjectsApi()
        node_metrics = custom_api.list_cluster_custom_object(
            group="metrics.k8s.io", version="v1beta1", plural="nodes"
        )
        if namespace:
            pod_metrics = custom_api.list_namespaced_custom_object(
                group="metrics.k8s.io",
                version="v1beta1",
                namespace=namespace,
                plural="pods",
            )
        else:
            pod_metrics = custom_api.list_cluster_custom_object(
                group="metrics.k8s.io", version="v1beta1", plural="pods"
            )
        return node_metrics, pod_metrics

    _init_kubernetes(context)

    try:
        node_metrics, pod_metrics = await asyncio.to_thread(_fetch)

        result = "Resource Usage:\n"
        result += "═" * 60 + "\n\n"
        result += "Nodes:\n"
        result += "─" * 60 + "\n"

        for node in node_metrics["items"]:
            name = node["metadata"]["name"]
            usage = node["usage"]
            result += f"  {name}: {format_resource_usage(usage['cpu'], usage['memory'])}\n"

        if namespace:
            result += f"\n\nPods (Namespace: {namespace}):\n"
        else:
            result += "\n\nTop Pods by Resource Usage:\n"
        result += "─" * 60 + "\n"

        pods_with_usage = []
        for pod in pod_metrics["items"]:
            total_cpu = 0
            total_mem = 0

            for container in pod["containers"]:
                cpu = container["usage"]["cpu"]
                mem = container["usage"]["memory"]
                if "n" in cpu:
                    total_cpu += float(cpu.rstrip("n"))
                elif "u" in cpu:
                    total_cpu += float(cpu.rstrip("u")) * 1e3
                elif "m" in cpu:
                    total_cpu += float(cpu.rstrip("m")) * 1e6
                else:
                    total_cpu += float(cpu) * 1e9
                if "Ki" in mem:
                    total_mem += float(mem.rstrip("Ki"))
                elif "Mi" in mem:
                    total_mem += float(mem.rstrip("Mi")) * 1024
                elif "Gi" in mem:
                    total_mem += float(mem.rstrip("Gi")) * 1024 * 1024
                else:
                    total_mem += float(mem) / 1024

            pods_with_usage.append(
                {
                    "name": pod["metadata"]["name"],
                    "namespace": pod["metadata"]["namespace"],
                    "cpu": total_cpu,
                    "memory": total_mem,
                }
            )

        pods_with_usage.sort(key=lambda x: x["cpu"], reverse=True)
        for pod in pods_with_usage[:10]:
            cpu_str = (
                f"{pod['cpu']}n" if pod["cpu"] < 1000000 else f"{pod['cpu']/1000000:.2f}m"
            )
            mem_str = f"{pod['memory']:.0f}Ki"
            result += (
                f"  {pod['namespace']}/{pod['name']}: "
                f"{format_resource_usage(cpu_str, mem_str)}\n"
            )

    except ApiException as e:
        if e.status == 404:
            result = "Resource Usage:\n"
            result += "═" * 60 + "\n\n"
            result += "Metrics Server not available\n"
        else:
            result = f"Error getting metrics: {str(e)}"

    return result


async def diagnose_cluster(context: str | None = None) -> str:
    """Run comprehensive cluster diagnostics."""

    def _fetch():
        v1 = client.CoreV1Api()
        return v1.list_node(), v1.list_pod_for_all_namespaces()

    _init_kubernetes(context)
    nodes, pods = await asyncio.to_thread(_fetch)

    result = "Cluster Diagnostics:\n"
    result += "═" * 60 + "\n\n"

    issues = []

    for node in nodes.items:
        for condition in node.status.conditions:
            if condition.type == "Ready" and condition.status != "True":
                issues.append(f"Node {node.metadata.name} is not Ready")
            elif (
                condition.type in ["MemoryPressure", "DiskPressure", "PIDPressure"]
                and condition.status == "True"
            ):
                issues.append(f"Node {node.metadata.name} has {condition.type}")

    failing_pods = []
    pending_pods = []

    for pod in pods.items:
        if pod.status.phase == "Failed":
            failing_pods.append(f"{pod.metadata.namespace}/{pod.metadata.name}")
        elif pod.status.phase == "Pending":
            pending_pods.append(f"{pod.metadata.namespace}/{pod.metadata.name}")

    high_restart_pods = []
    for pod in pods.items:
        if pod.status.container_statuses:
            for container in pod.status.container_statuses:
                if container.restart_count > 5:
                    high_restart_pods.append(
                        f"{pod.metadata.namespace}/{pod.metadata.name} "
                        f"(container: {container.name}, restarts: {container.restart_count})"
                    )

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
            for pod in failing_pods[:10]:
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

    return result


async def get_namespace_summary(context: str | None = None) -> str:
    """Get summary of resources per namespace."""

    def _fetch():
        v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        namespaces = v1.list_namespace()
        all_pods = v1.list_pod_for_all_namespaces()
        all_services = v1.list_service_for_all_namespaces()
        all_deployments = apps_v1.list_deployment_for_all_namespaces()
        return namespaces, all_pods, all_services, all_deployments

    _init_kubernetes(context)
    namespaces, all_pods, all_services, all_deployments = await asyncio.to_thread(_fetch)

    pods_by_ns = defaultdict(list)
    for pod in all_pods.items:
        pods_by_ns[pod.metadata.namespace].append(pod)
    svcs_by_ns = defaultdict(list)
    for service in all_services.items:
        svcs_by_ns[service.metadata.namespace].append(service)
    deps_by_ns = defaultdict(list)
    for deployment in all_deployments.items:
        deps_by_ns[deployment.metadata.namespace].append(deployment)

    result = "Namespace Summary:\n"
    result += "═" * 60 + "\n\n"

    for ns in namespaces.items:
        ns_name = ns.metadata.name
        ns_pods = pods_by_ns.get(ns_name, [])

        running = sum(1 for pod in ns_pods if pod.status.phase == "Running")
        failed = sum(1 for pod in ns_pods if pod.status.phase == "Failed")
        pending = sum(1 for pod in ns_pods if pod.status.phase == "Pending")

        result += f"Namespace: {ns_name}\n"
        result += "─" * 60 + "\n"
        result += (
            f"  Pods: {len(ns_pods)} "
            f"(Running: {running}, Pending: {pending}, Failed: {failed})\n"
        )
        result += f"  Deployments: {len(deps_by_ns.get(ns_name, []))}\n"
        result += f"  Services: {len(svcs_by_ns.get(ns_name, []))}\n"
        result += "\n"

    return result


async def check_networking(
    namespace: str | None = None,
    context: str | None = None,
) -> str:
    """Check cluster networking and Istio service mesh health."""

    def _fetch():
        v1 = client.CoreV1Api()
        custom_api = client.CustomObjectsApi()
        networking_api = client.NetworkingV1Api()

        istio_pods = []
        try:
            istio_pods = v1.list_namespaced_pod("istio-system").items
        except ApiException:
            pass

        if namespace:
            all_pods = v1.list_namespaced_pod(namespace).items
        else:
            all_pods = v1.list_pod_for_all_namespaces().items

        if namespace:
            services = v1.list_namespaced_service(namespace).items
            endpoints = v1.list_namespaced_endpoints(namespace).items
        else:
            services = v1.list_service_for_all_namespaces().items
            endpoints = v1.list_endpoints_for_all_namespaces().items

        if namespace:
            net_policies = networking_api.list_namespaced_network_policy(namespace).items
        else:
            net_policies = networking_api.list_network_policy_for_all_namespaces().items

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
                istio_resources[plural] = None

        return istio_pods, all_pods, services, endpoints, net_policies, istio_resources

    _init_kubernetes(context)
    (
        istio_pods,
        all_pods,
        services,
        endpoints,
        net_policies,
        istio_resources,
    ) = await asyncio.to_thread(_fetch)

    scope = f"Namespace: {namespace}" if namespace else "All Namespaces"
    result = f"Networking & Istio Diagnostics ({scope}):\n"
    result += "═" * 60 + "\n\n"

    result += "Istio Control Plane:\n"
    result += "─" * 60 + "\n"
    if not istio_pods:
        result += " No pods found in istio-system (Istio may not be installed)\n"
    else:
        for pod in istio_pods:
            phase = pod.status.phase
            indicator = "✓" if phase == "Running" else "✗"
            result += f"  {indicator} {pod.metadata.name}: {phase}\n"
    result += "\n"

    result += "Sidecar Injection Coverage:\n"
    result += "─" * 60 + "\n"
    ns_total = defaultdict(int)
    ns_injected = defaultdict(int)
    proxy_versions = defaultdict(int)

    for pod in all_pods:
        ns_name = pod.metadata.namespace
        ns_total[ns_name] += 1
        containers = pod.spec.containers or []
        for container in containers:
            if container.name == "istio-proxy":
                ns_injected[ns_name] += 1
                if container.image and ":" in container.image:
                    version = container.image.rsplit(":", 1)[1]
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

    result += "Services with Missing Endpoints:\n"
    result += "─" * 60 + "\n"
    ep_map = {}
    for ep in endpoints:
        key = f"{ep.metadata.namespace}/{ep.metadata.name}"
        addresses = []
        for subset in ep.subsets or []:
            addresses.extend(subset.addresses or [])
        ep_map[key] = len(addresses)

    no_endpoint_svcs = []
    for svc in services:
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
                ns_counts = defaultdict(int)
                for item in items:
                    ns_counts[item["metadata"].get("namespace", "<cluster>")] += 1
                parts = [f"{ns}: {count}" for ns, count in sorted(ns_counts.items())]
                result += f"  {label} ({len(items)}): {', '.join(parts)}\n"
            else:
                result += f"  {label}: 0\n"
    if not istio_installed:
        result += "  ⚠ No Istio CRDs found — Istio is not installed\n"
    result += "\n"

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

    return result
