import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { preview } from 'vite';

const output = process.env.CIPHER_BROWSER_BUILD_DIR;
const port = Number(process.env.CIPHER_BROWSER_PORT || '5180');
if (!output || !existsSync(resolve(output, 'index.html')) || !Number.isSafeInteger(port) || port < 1024 || port > 65535) {
  throw new Error('The private browser build and a valid local port are required.');
}
const server = await preview({ configFile: false, build: { outDir: resolve(output) },
  preview: { host: '127.0.0.1', port, strictPort: true } });
server.printUrls();
