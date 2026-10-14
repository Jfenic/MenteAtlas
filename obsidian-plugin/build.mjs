import { build } from 'esbuild';
import { mkdir, copyFile } from 'node:fs/promises';
await mkdir('dist', { recursive: true });
await build({ entryPoints: ['src/main.ts'], bundle: true, platform: 'node', target: 'es2022',
  format: 'cjs', external: ['obsidian', 'electron'], outfile: 'dist/main.js', sourcemap: false });
for (const name of ['manifest.json', 'styles.css']) await copyFile(name, `dist/${name}`);
