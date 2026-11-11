# FlintPlate MCP server

Dependency-free Node.js 20+ stdio server, adapted from FireFlint. Install locally with `npm link`
if you want the `flintplate-mcp` executable; the package name is `@flintplate/mcp`.
The package is not published to npm. Run directly with `node src/server.mjs`.

Set `FLINTPLATE_BASE_URL` to the API origin (no `/api` suffix), `FLINTPLATE_TOKEN` to a bearer
access token and `FLINTPLATE_READ_ONLY=true` (the default). Use a least-privilege account.
The API enforces roles and tenant membership. Expired tokens must be replaced by the operator.
All tools in this release are read-only; setting read-only to false does not add writes.
Future write tools must be hidden in read-only mode; destructive/publish tools must additionally
require literal `confirmed=true` and explicit human approval in the skill.

| Tool | FastAPI route |
| --- | --- |
| `flintplate_health` | `GET /health` |
| `flintplate_me` | `GET /users/me` |
| `flintplate_list_venues` | `GET /gastro/venues` |
| `flintplate_list_menu` | `GET /gastro/venues/{venue_id}/menu` |
| `flintplate_list_tables` | `GET /gastro/venues/{venue_id}/tables` |
| `flintplate_list_orders` | `GET /gastro/venues/{venue_id}/orders` |
| `flintplate_list_reservations` | `GET /gastro/venues/{venue_id}/reservations` |


FlintPlate venue tools require `venue_id`; orders support `limit` (1–500), `before`,
and `include_closed`; reservations support timezone-aware `start` and `end` (maximum 93 days).
Other tools take no arguments. Results follow the API response shape; role restrictions still apply.

`npm test` runs mock HTTP tests without a backend. stdout is reserved for newline-delimited
JSON-RPC; errors expose HTTP status without backend payloads. Requests time out after 30 seconds
and do not follow redirects. Only expose the process to trusted local MCP clients.

See [client configurations](../docs/MCP-AND-SKILLS.md) and the [skill](../skills/flintplate/SKILL.md).
