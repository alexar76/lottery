// Minimal static server for the lottery showcase (no deps). `node serve.mjs [port]`.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join, normalize } from 'node:path';

const DIR = dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || process.argv[2] || 5182);
// '.woff2' is here because the page now serves its own webfonts instead of fetching them from
// Google, and the fallthrough below would have typed them application/octet-stream.
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.woff2': 'font/woff2' };

createServer(async (req, res) => {
  try {
    let p = decodeURIComponent((req.url || '/').split('?')[0]);
    if (p === '/' || p === '') p = '/index.html';
    const full = normalize(join(DIR, p));
    if (!full.startsWith(DIR)) { res.writeHead(403).end('forbidden'); return; }
    const body = await readFile(full);
    const ext = full.slice(full.lastIndexOf('.'));
    res.writeHead(200, { 'content-type': TYPES[ext] || 'application/octet-stream' });
    res.end(body);
  } catch {
    res.writeHead(404, { 'content-type': 'text/plain' }).end('not found');
  }
}).listen(PORT, () => console.log(`lottery showcase on http://localhost:${PORT}`));
