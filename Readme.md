## MCP What's the health of my Kubernetes cluster?

Assessment-only,  no mutations to the cluster:

```
✅ get_cluster_info - Version, node count, namespace count
✅ check_node_health - Node conditions, capacity, allocatable resources
✅ check_pod_health - Pod status across namespaces, problem detection
✅ get_resource_usage - CPU/memory usage (requires metrics-server)
✅ diagnose_cluster - Comprehensive health check with issue detection
✅ get_namespace_summary - Resource counts per namespace
[WIP] check_networking - Istio networking overview
```


* Server:
    
    - Tools: `get_cluster_info, check_node_health, check_pod_health, get_resource_usage, diagnose_cluster, get_namespace_summary`
    - Tool Handler
    - MCP server setup: [Clients SHOULD support stdio whenever possible](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#streamable-http)
    - Two transport modes:
        - STDIO (k8s_mcp_server_local.py) — for direct Claude Code integration via .mcp.json
        - Streamable HTTP (k8s_mcp_server_http.py) — containerized deployment on port 8000, with SSE streaming and stateful sessions

## Test the MCP server

* MCP inspector

```bash
# setup a kubeconfig 
export KUBECONFIG=~/.kube/config

# install inspector and run server
npm install -g @modelcontextprotocol/inspector

mcp-inspector python k8s_mcp_server.py
npx @modelcontextprotocol/inspector --transport streamablehttp http://localhost:8000/messages
```

### Prompts 

* Prompts

```
Is the cluster healthy?
Are all nodes ready? 
Show me any pods that are not running  
Diagnose the cluster and explain what needs attention

Are there any nodes under resource pressure?
Show resource usage and identify which nodes are overloaded
Which pods are consuming the most CPU and memory?
Is there enough capacity to schedule more workloads?

Give me a summary of all namespaces

Give me a full cluster assessment — nodes, pods, resource usage, and any issues
Compare resource usage across nodes , is the workload balanced?

Diagnose the cluster and explain what needs attention
What's the overall state of the cluster and what should I fix first?
```

* mcp.json

```json

{
  "mcpServers": {
    "kubernetes": {
      "command": "/Users/alexandru.dejanu/tools/k8s-mcp-server/venv/bin/python",
      "args": [
        "/Users/alexandru.dejanu/tools/k8s-mcp-server/k8s_mcp_server_local.py"
      ],
      "env": {
        "KUBECONFIG": "/abs/path/to/kubeconfig"
      }
    }
  }
}
```


```json
{
  "mcpServers": {
    "kubernetes": {
      "type": "http",
      "url": "http://localhost:8000/messages"
    }
  }
}
```