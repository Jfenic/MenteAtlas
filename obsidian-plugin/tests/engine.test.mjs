import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { mkdtemp, mkdir, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { createRequire } from 'node:module';

const temporary = await mkdtemp(join(tmpdir(), 'matlas-engine-test-'));
await build({ entryPoints: ['src/engine.ts'], outfile: join(temporary, 'engine.cjs'), bundle: true, platform: 'node', format: 'cjs' });
const { Engine, vaultNote } = createRequire(import.meta.url)(join(temporary, 'engine.cjs'));
const python = process.env.MATLAS_TEST_PYTHON || (process.platform === 'win32' ? join(process.cwd(), '..', '.venv', 'Scripts', 'python.exe') : 'python');

test('plugin client binds to its vault, imports, creates cited cards and stops gracefully', { timeout: 60_000 }, async () => {
  const vault = join(temporary, 'vault');
  const instance = join(temporary, 'instance');
  await mkdir(join(vault, '.obsidian'), { recursive: true });
  const engine = new Engine();
  try {
    await engine.start({ python, instance }, vault, true);
    const health = await engine.call('/health');
    assert.equal(health.protocol, 1);
    const bytes = await readFile('../examples/synthetic-export.json');
    const counts = await engine.call('/import', undefined, { bytes, format: 'json' });
    assert.equal(counts.new_messages, 2);
    const rows = await engine.call('/search', { scope: 'messages', query: 'atlas' });
    assert.equal(rows.length, 1);
    assert.ok(vaultNote(vault, rows[0].vault_path).startsWith('Conversations/'));
    const row = rows[0];
    const card = await engine.call('/cards', { title: 'Desde el cliente Obsidian', from_sources: true,
      sources: [{ source: 'chatgpt', conversation_id: row.conversation_id, message_id: row.message_id, version: row.version }] });
    assert.ok(vaultNote(vault, card.vault_path).startsWith('Cards/'));
    assert.match(await readFile(join(vault, card.vault_path), 'utf8'), /atlas local/);
    const cards = await engine.call('/search', { scope: 'cards', query: 'cliente' });
    assert.equal(cards.length, 1);
    await assert.rejects(engine.call('/search', { scope: 'messages', query: '' }));
    assert.equal((await engine.call('/stats')).cards, 1);
    engine.stop();
    assert.equal(engine.running, false);
    // The worker exits on private pipe EOF; the archive remains usable on restart.
    const deadline = Date.now() + 10_000;
    while (engine.child && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 25));
    assert.equal(engine.child, null);
    await engine.start({ python, instance }, vault);
    assert.equal((await engine.call('/stats')).cards, 1);
  } finally {
    engine.dispose();
    const deadline = Date.now() + 10_000;
    while (engine.child && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 25));
  }
});

test('a configured instance cannot silently use another vault', { timeout: 30_000 }, async () => {
  const engine = new Engine();
  try {
    await assert.rejects(engine.start({ python, instance: join(temporary, 'instance') }, join(temporary, 'other-vault')));
    assert.equal(engine.running, false);
  } finally { engine.dispose(); }
});

test('note links are confined to Markdown in the current vault', () => {
  const vault = join(temporary, 'vault');
  assert.equal(vaultNote(vault, 'Cards/test.md'), 'Cards/test.md');
  for (const value of ['../secret.md', '../vault-sibling/secret.md', 'Cards/tool.exe', '..']) assert.throws(() => vaultNote(vault, value));
});

test.after(async () => {
  assert.equal(dirname(resolve(temporary)), resolve(tmpdir()));
  assert.ok(temporary.split(/[\\/]/).pop().startsWith('matlas-engine-test-'));
  await rm(temporary, { recursive: true, force: true });
});
