#!/usr/bin/env node
// Adapted from the FireFlint dependency-free stdio server.
import { realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createServer, createHttpClient, seg } from './mcp-stdio.mjs';

const routes = [
  [
    "health",
    "/health",
    {},
    []
  ],
  [
    "me",
    "/users/me",
    {},
    []
  ],
  [
    "list_venues",
    "/gastro/venues",
    {},
    []
  ],
  [
    "list_menu",
    "/gastro/venues/{venue_id}/menu",
    {
      "venue_id": {
        "type": "string",
        "format": "uuid"
      }
    },
    [
      "venue_id"
    ]
  ],
  [
    "list_tables",
    "/gastro/venues/{venue_id}/tables",
    {
      "venue_id": {
        "type": "string",
        "format": "uuid"
      }
    },
    [
      "venue_id"
    ]
  ],
  [
    "list_orders",
    "/gastro/venues/{venue_id}/orders",
    {
      "venue_id": {
        "type": "string",
        "format": "uuid"
      },
      "include_closed": {
        "type": "boolean"
      },
      "limit": {
        "type": "integer",
        "minimum": 1,
        "maximum": 500
      },
      "before": {
        "type": "string"
      }
    },
    [
      "venue_id"
    ]
  ],
  [
    "list_reservations",
    "/gastro/venues/{venue_id}/reservations",
    {
      "venue_id": {
        "type": "string",
        "format": "uuid"
      },
      "start": {
        "type": "string",
        "format": "date-time"
      },
      "end": {
        "type": "string",
        "format": "date-time"
      }
    },
    [
      "venue_id"
    ]
  ]
];

export function buildTools(env = process.env) {
  const http = createHttpClient({
    baseUrl: env.FLINTPLATE_BASE_URL,
    headers: () => env.FLINTPLATE_TOKEN ? { authorization: `Bearer ${env.FLINTPLATE_TOKEN}` } : {},
  });
  const tools = routes.map(([name, path, properties, required]) => ({
    name: 'flintplate_' + name,
    description: `FlintPlate: ${name.replaceAll('_', ' ')}. Backend role and tenant permissions apply.`,
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    inputSchema: { type: 'object', properties, required, additionalProperties: false },
    handler: async (args) => {
      if (!args || typeof args !== 'object' || Array.isArray(args)) throw new Error('Expected an object');
      for (const key of Object.keys(args)) {
        const prop = properties[key];
        if (!prop) throw new Error(`Unknown argument: ${key}`);
        if (prop.type === 'integer' ? !Number.isInteger(args[key]) : typeof args[key] !== prop.type) throw new Error(`Invalid ${key}`);
        if (prop.minimum !== undefined && args[key] < prop.minimum || prop.maximum !== undefined && args[key] > prop.maximum) throw new Error(`Out of range: ${key}`);
      }
      const route = path.replace(/\{(\w+)\}/g, (_, key) => {
        if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(args[key] || '')) throw new Error(`Invalid ${key} UUID`);
        return seg(args[key], key);
      });
      const query = Object.fromEntries(Object.entries(args).filter(([key]) => !required.includes(key)));
      return (await http('GET', route, { query })).data;
    },
  }));
  // Read-only by default. This release deliberately exposes no mutation tools.
  const readOnly = String(env.FLINTPLATE_READ_ONLY ?? 'true').toLowerCase() !== 'false';
  return tools.filter(tool => !(readOnly && tool.write));
}

export function buildServer(env = process.env) {
  return createServer({ name: 'flintplate-mcp', version: '0.1.0',
    instructions: 'FlintPlate: inspect health and current user first. Read only the data needed for the task. No write tools are exposed.',
    tools: buildTools(env) });
}

if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { buildServer().listen(); }
  catch { process.stderr.write('flintplate-mcp: configure FLINTPLATE_BASE_URL\n'); process.exitCode = 1; }
}
