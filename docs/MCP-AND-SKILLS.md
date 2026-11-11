# FlintPlate MCP and skills

The local dependency-free Node.js server wraps existing FastAPI read routes.
[Tool reference](../mcp/README.md). No writes are exposed in this version.
`FLINTPLATE_READ_ONLY=true` is the default and hides any future write tools.
An API bearer token is supplied by the operator; the server does not store credentials or bypass roles.

## Claude Desktop, Cursor and generic MCP JSON

Place this entry in your client's MCP configuration (for Cursor, `.cursor/mcp.json`).
Replace the absolute path and token locally, never in committed files.

```json
{
  "mcpServers": {
    "flintplate": {
      "command": "node",
      "args": [
        "/absolute/path/to/flintplate-oss/mcp/src/server.mjs"
      ],
      "env": {
        "FLINTPLATE_BASE_URL": "http://127.0.0.1:8012",
        "FLINTPLATE_TOKEN": "<access-token>",
        "FLINTPLATE_READ_ONLY": "true"
      }
    }
  }
}
```

## Claude Code

```sh
claude mcp add flintplate --env FLINTPLATE_BASE_URL=http://127.0.0.1:8012 --env FLINTPLATE_TOKEN='<access-token>' --env FLINTPLATE_READ_ONLY=true -- node /absolute/path/to/flintplate-oss/mcp/src/server.mjs
```

## Codex

Add to your local MCP configuration:

```toml
[mcp_servers.flintplate]
command = "node"
args = ["/absolute/path/to/flintplate-oss/mcp/src/server.mjs"]
env = { FLINTPLATE_BASE_URL = "http://127.0.0.1:8012", FLINTPLATE_TOKEN = "<access-token>", FLINTPLATE_READ_ONLY = "true" }
```

## Agent skill

Copy [skills/flintplate](../skills/flintplate/SKILL.md) into your agent's skill directory
(e.g. `~/.claude/skills/flintplate` or `~/.codex/skills/flintplate`). Other agents can load
`SKILL.md` as instructions alongside the MCP tool definitions. A local model uses the same tools.
The skill establishes identity and scope before reading, minimizes personal data, and requires
explicit human approval before any future destructive/publish operation plus `confirmed=true`.

Test without a backend: `cd mcp && npm test`. For direct use from the repository root:

```sh
FLINTPLATE_BASE_URL=http://127.0.0.1:8012 FLINTPLATE_READ_ONLY=true node mcp/src/server.mjs
```

The process speaks newline-delimited JSON-RPC on stdio; it is not a web server.
