# MCPHub

Run MCPHub inside Home Assistant and manage multiple MCP servers from one central dashboard.

The add-on supports MCPHub Market / Registry discovery, stdio and remote MCP servers,
persistent settings and package caches, Home Assistant Ingress, and an optional
OpenAI Secure MCP Tunnel for connecting a unified MCP endpoint to ChatGPT.

MCPHub itself is restricted to the add-on container loopback interface. No host port,
Docker socket, Supervisor API, Home Assistant API, privileged mode, or host networking
is required.

See [DOCS.md](DOCS.md) for installation, configuration, security, and troubleshooting.
