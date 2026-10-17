import { cp, mkdir } from 'node:fs/promises';
const source = new URL('../node_modules/pdfjs-dist/', import.meta.url);
const target = new URL('../public/pdfjs/', import.meta.url);
await mkdir(target, { recursive: true });
for (const entry of ['cmaps', 'standard_fonts', 'wasm', 'iccs', 'LICENSE']) await cp(new URL(entry, source), new URL(entry, target), { recursive: true });
