import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { build } from 'vite';

// Private test output includes standalone fixture pages; the shipped dist stays separate.
const output = process.env.CIPHER_BROWSER_BUILD_DIR;
if (!output || existsSync(resolve(output)) || resolve(output) === resolve('.')) {
  throw new Error('Choose a new CIPHER_BROWSER_BUILD_DIR for the private browser build.');
}
const entries = ['index.html', 'tests/company-activity.html', 'tests/company-takeoff.html', 'tests/cost-permission.html'];
for (const entry of entries) if (!existsSync(entry)) throw new Error(`Missing browser entry: ${entry}`);
await build({ build: { outDir: resolve(output), emptyOutDir: false, sourcemap: false,
  rollupOptions: { input: Object.fromEntries(entries.map(entry => [entry, resolve(entry)])) } } });
