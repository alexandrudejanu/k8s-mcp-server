.DEFAULT_GOAL := documentation

MCP_URL ?= https://agentgateway-api.computev2.use1.aws.i.alchemy.com/k8s-mcp/mcp

.PHONY: documentation initialize notifications/initialized

documentation:
	@echo "MCP handshake"
	@echo "  make initialize                 - send MCP initialize request to $(MCP_URL)"
	@echo "  make notifications/initialized  - print notifications/initialized curl command"
	@echo "  make tools/list                 - print tools/list curl command"
	@echo "  make forward-k8smcp             - forward k8s-mcp to localhost:8885"
	@echo "  make inspector                  - inspect with inspector"

initialize:
	curl -s -D - -X POST '$(MCP_URL)' \
		-H 'Content-Type: application/json' \
		-H 'Accept: application/json, text/event-stream' \
		-H 'mcp-protocol-version: 2025-11-25' \
		-d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

notifications/initialized:
	@echo "curl -s -X POST '$(MCP_URL)' \\"
	@echo "  -H 'Content-Type: application/json' \\"
	@echo "  -H 'Accept: application/json, text/event-stream' \\"
	@echo "  -H 'mcp-protocol-version: 2025-11-25' \\"
	@echo "  -H 'mcp-session-id: <SESSION_ID>' \\"
	@echo "  -d '{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}'"

tools/list:
	@echo "curl -s -X POST '$(MCP_URL)' \\"
	@echo "  -H 'Content-Type: application/json' \\"
	@echo "  -H 'Accept: application/json, text/event-stream' \\"
	@echo "  -H 'mcp-protocol-version: 2025-11-25' \\"
	@echo "  -H 'mcp-session-id: <SESSION_ID>' \\"
	@echo "  -d '{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/list\",\"params\":{}}'"

forward-k8smcp:
	@echo "kubectl port-forward -n mcp svc/mcp-k8s 8885:8885"

inspector:
	@echo "npx @modelcontextprotocol/inspector --transport http --server-url  http://localhost:8885/messages"