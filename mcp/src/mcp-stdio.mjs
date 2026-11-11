// Minimal, dependency-free Model Context Protocol (MCP) server over stdio.
// Implements the subset needed for tool servers: initialize, ping,
// tools/list and tools/call (JSON-RPC 2.0, newline-delimited messages).
// Spec: https://modelcontextprotocol.io/specification
import { createInterface } from 'node:readline';

const SUPPORTED = ['2025-06-18', '2025-03-26', '2024-11-05'];

export function createServer({ name, version, instructions, tools }) {
  const byName = new Map(tools.map((tool) => [tool.name, tool]));

  async function handle(message) {
    const { id, method, params } = message;
    const isRequest = id !== undefined && id !== null;
    try {
      switch (method) {
        case 'initialize': {
          const requested = params?.protocolVersion;
          return reply(id, {
            protocolVersion: SUPPORTED.includes(requested) ? requested : SUPPORTED[0],
            capabilities: { tools: { listChanged: false } },
            serverInfo: { name, version },
            ...(instructions ? { instructions } : {}),
          });
        }
        case 'notifications/initialized':
        case 'notifications/cancelled':
          return undefined;
        case 'ping':
          return reply(id, {});
        case 'tools/list':
          return reply(id, {
            tools: tools.map(({ name: toolName, description, inputSchema, annotations }) => ({
              name: toolName, description, inputSchema, ...(annotations ? { annotations } : {}),
            })),
          });
        case 'tools/call': {
          const tool = byName.get(params?.name);
          if (!tool) return error(id, -32602, `Unknown tool: ${params?.name}`);
          try {
            const result = await tool.handler(params.arguments ?? {});
            const text = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
            return reply(id, { content: [{ type: 'text', text }], isError: false });
          } catch (err) {
            // Tool errors are reported to the model, not as protocol errors.
            return reply(id, { content: [{ type: 'text', text: `Error: ${err?.message ?? String(err)}` }], isError: true });
          }
        }
        default:
          return isRequest ? error(id, -32601, `Method not found: ${method}`) : undefined;
      }
    } catch (err) {
      return isRequest ? error(id, -32603, err?.message ?? 'Internal error') : undefined;
    }
  }

  function reply(id, result) { return { jsonrpc: '2.0', id, result }; }
  function error(id, code, message) { return { jsonrpc: '2.0', id, error: { code, message } }; }

  function listen(input = process.stdin, output = process.stdout) {
    const rl = createInterface({ input, crlfDelay: Infinity });
    rl.on('line', async (line) => {
      if (!line.trim()) return;
      let message;
      try { message = JSON.parse(line); } catch {
        output.write(JSON.stringify(error(null, -32700, 'Parse error')) + '\n');
        return;
      }
      const response = await handle(message);
      if (response) output.write(JSON.stringify(response) + '\n');
    });
    return rl;
  }

  return { handle, listen };
}

/** Small JSON HTTP client with base URL, timeout and redacted errors. */
export function createHttpClient({ baseUrl, headers = () => ({}), timeoutMs = 30000 }) {
  if (!baseUrl) throw new Error('Base URL is not configured');
  const base = baseUrl.replace(/\/+$/, '');
  return async function request(method, path, { body, query, extraHeaders } = {}) {
    const url = new URL(base + path);
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
    }
    const response = await fetch(url, {
      method,
      headers: {
        accept: 'application/json',
        ...(body !== undefined ? { 'content-type': 'application/json' } : {}),
        ...(await headers()),
        ...(extraHeaders ?? {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(timeoutMs),
      redirect: 'error',
    });
    const text = await response.text();
    let data;
    try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    if (!response.ok) {
      throw new Error(`Request failed with HTTP ${response.status}`);
    }
    return { data, response };
  };
}

export const seg = (value, label) => {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${label} is required`);
  return encodeURIComponent(value.trim());
};
