## MCP What's the health of my Kubernetes cluster?

Assessment-only,  no mutations to the cluster:

```
✅ get_cluster_info - Version, node count, namespace count
✅ check_node_health - Node conditions, capacity, allocatable resources
✅ check_pod_health - Pod status across namespaces, problem detection
✅ get_resource_usage - CPU/memory usage (requires metrics-server)
✅ diagnose_cluster - Comprehensive health check with issue detection
✅ get_namespace_summary - Resource counts per namespace
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

### Integrate with Claude: 

* As a process that is expecting JSON-RPC messages at STDIN: `python k8s_mcp_server.py`

```bash

# stdio Transport: Claude launches your Python script as a subprocess
cat<<EOF>~/.claude/code_config.json
{
  "mcpServers": {
    "kubernetes": {
      "command": "/Users/alexandru.dejanu/tools/k8s-mcp-server/venv/bin/python",
      "args": [
        "${HOME}/tools/k8s-mcp-server/k8s_mcp_server_local.py"
      ],
      "env": {
        "KUBECONFIG": "${HOME}/.kube/config"
      }
    }
  }
}
EOF
```
* As Streamable HTTP server: Streamable HTTP replaces the HTTP+SSE transport 

```bash
docker compose -f docker-compose.yml up --build -d
docker compose -f docker-compose.yml down --remove-orphans

 docker run -d \
        --name k8s-mcp-server \
        -p 8000:8000 \
        -v "${HOME}/.kube/config:/root/.kube/config:ro" \
        -e KUBECONFIG=/root/.kube/config \
        dejanualex/k8s-mcp-server:0.1.0

# HTTP/SSE Transport: web server on port 8000 accesible at /mcp endpoint
claude mcp add --transport http my-server http://localhost:8000/mcp
claude mcp add --transport http kubernetes http://localhost:8000/messages
claude mcp reset-project-choices   

cat > ~/.claude/code_config.json<<EOF
{
  "mcpServers": {
    "kubernetes": {
    "transport": "http",                                                                              
    "url": "http://localhost:8000/messages"  
    }
  }
}
EOF


```

### Prompts and stuff

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