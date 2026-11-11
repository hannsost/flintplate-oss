import http from 'node:http';

/** Forward browser API requests to the isolated test process without another
 * Compose stack or TCP listener. Never log request headers, tokens or bodies. */
export function requestIsolatedApi(request, socketPath, overrideUrl) {
  if (!socketPath) throw new Error('An isolated API socket is required.');
  const url = new URL(overrideUrl ?? request.url());
  if (!url.pathname.startsWith('/api/')) throw new Error('Only application API requests may use the test proxy.');
  const headers = { ...request.headers(), 'accept-encoding': 'identity' };
  delete headers.host;
  delete headers.connection;
  delete headers['content-length'];
  const body = request.postDataBuffer();
  return new Promise((resolve, reject) => {
    const client = http.request({ socketPath, path: url.pathname.slice(4) + url.search, method: request.method(), headers }, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('error', reject);
      response.on('end', () => {
        const responseHeaders = Object.fromEntries(Object.entries(response.headers).filter(([key, value]) => !['content-length', 'transfer-encoding', 'connection'].includes(key) && value !== undefined).map(([key, value]) => [key, Array.isArray(value) ? value.join(', ') : String(value)]));
        resolve({ status: response.statusCode ?? 502, headers: responseHeaders, body: Buffer.concat(chunks) });
      });
    });
    client.setTimeout(45000, () => client.destroy(new Error('Isolated API request timed out.')));
    client.on('error', reject);
    client.end(body ?? undefined);
  });
}

export async function fulfillFromIsolatedApi(route, socketPath, overrideUrl) {
  try {
    const response = await requestIsolatedApi(route.request(), socketPath, overrideUrl);
    await route.fulfill(response);
  } catch (error) {
    console.error('Isolated API transport failed:', error.code ?? 'transport');
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Die isolierte Test-API ist nicht erreichbar.' }) }).catch(() => undefined);
  }
}
