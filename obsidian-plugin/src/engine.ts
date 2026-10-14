import { spawn, ChildProcessWithoutNullStreams } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { request } from 'node:http';
import { resolve, relative, isAbsolute } from 'node:path';
import { realpathSync } from 'node:fs';

export interface Config { python: string; instance: string; openOnStart?: boolean; autoStart?: boolean; }
export interface Reference { source: string; conversation_id: string; message_id: string; version: number; }
export interface Row {
  title: string; snippet: string; role?: string; type?: string; status?: string;
  conversation_id?: string; message_id?: string; version?: number; vault_path: string | null;
}

export function vaultNote(vault: string, value: string): string {
  const note = relative(resolve(vault), resolve(vault, value));
  if (!note || note === '..' || note.startsWith('../') || note.startsWith('..\\') || isAbsolute(note) || !note.toLowerCase().endsWith('.md')) {
    throw new Error('La nota no pertenece a este vault.');
  }
  return note.replace(/\\/g, '/');
}

export class Engine {
  private child: ChildProcessWithoutNullStreams | null = null;
  private port = 0;
  private token = '';
  private starting: Promise<void> | null = null;
  private requests = 0;
  private stopping = false;
  get running(): boolean { return this.port !== 0 && this.child !== null; }
  get active(): boolean { return this.child !== null || this.starting !== null || this.stopping; }

  async start(config: Config, vault: string, initialize = false): Promise<void> {
    if (this.stopping) throw new Error('El motor se está deteniendo.');
    if (this.starting) return this.starting;
    if (this.running) return;
    if (!config.python.trim() || !config.instance.trim()) throw new Error('Configura Python y la carpeta de instancia en Ajustes → MAtlasAgent.');
    this.starting = this.launch(config, vault, initialize);
    try { await this.starting; } finally { this.starting = null; }
  }

  private async launch(config: Config, vault: string, initialize: boolean): Promise<void> {
    const token = randomBytes(32).toString('hex');
    const args = ['-m', 'matlasagent.api', '--instance', config.instance, '--vault', vault];
    if (initialize) args.push('--initialize');
    const child = spawn(config.python, args, { windowsHide: true, shell: false, stdio: 'pipe' });
    this.child = child;
    this.token = token;
    child.stdin.on('error', () => { /* Reported by exit/startup handler, never log credentials. */ });
    // Drain private diagnostics without exposing exports or machine paths to the console.
    child.stderr.on('data', () => {});
    child.once('close', () => { if (this.child === child) { this.child = null; this.port = 0; this.token = ''; this.stopping = false; } });
    await new Promise<void>((accept, reject) => {
      let pending = '';
      let done = false;
      const finish = (error?: Error) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        child.stdout.off('data', receive);
        child.off('error', failed);
        child.off('exit', exited);
        if (error) { this.stopping = true; child.stdin.end(); reject(error); } else accept();
      };
      const failed = () => finish(new Error('No se pudo ejecutar Python. Revisa la ruta en los ajustes.'));
      const exited = () => finish(new Error('El motor no pudo abrir la biblioteca. Comprueba instancia, vault y permisos. Para un vault nuevo, debe estar vacío de notas.'));
      const receive = (chunk: Buffer) => {
        pending += chunk.toString('utf8');
        if (pending.length > 4096) { finish(new Error('Respuesta de inicio no válida.')); return; }
        if (!pending.includes('\n')) return;
        try {
          const info = JSON.parse(pending.split('\n')[0]);
          // Windows temp/user paths may use 8.3 aliases; compare filesystem identities.
          const actual = realpathSync(info.vault), expected = realpathSync(vault);
          const sameVault = process.platform === 'win32' ? actual.toLowerCase() === expected.toLowerCase() : actual === expected;
          if (info.protocol !== 1 || !Number.isInteger(info.port) || info.port < 1 || info.port > 65535 || !sameVault) throw new Error();
          this.port = info.port;
          finish();
        } catch { finish(new Error('El motor no corresponde a este vault o versión.')); }
      };
      const timer = setTimeout(() => finish(new Error('El inicio está tardando demasiado. Espera a que termine antes de reintentar.')), 120_000);
      child.stdout.on('data', receive);
      child.once('error', failed);
      child.once('exit', exited);
      child.stdin.write(JSON.stringify({ token }) + '\n');
    });
    // Ignore any additional stdout; the only protocol message is the startup handshake.
    child.stdout.resume();
  }

  async call<T = unknown>(endpoint: string, data?: unknown, upload?: { bytes: Buffer; format: string }): Promise<T> {
    if (!this.running || this.stopping) throw new Error('Inicia el motor desde el panel MAtlasAgent.');
    const bytes = upload?.bytes ?? (data === undefined ? null : Buffer.from(JSON.stringify(data), 'utf8'));
    const headers: Record<string, string | number> = { Authorization: 'Bearer ' + this.token };
    if (bytes) {
      headers['Content-Type'] = upload ? 'application/octet-stream' : 'application/json';
      headers['Content-Length'] = bytes.length;
      if (upload) headers['X-MAtlas-Format'] = upload.format;
    }
    this.requests++;
    try {
      return await new Promise<T>((accept, reject) => {
        const req = request({ hostname: '127.0.0.1', port: this.port, path: endpoint, method: bytes ? 'POST' : 'GET', headers }, res => {
          const chunks: Buffer[] = [];
          let size = 0;
          res.on('data', (chunk: Buffer) => { size += chunk.length; if (size > 16 * 1024 * 1024) { req.destroy(); reject(new Error('La respuesta excede el límite local. Refina la búsqueda.')); } else chunks.push(chunk); });
          res.on('error', () => reject(new Error('La respuesta local se interrumpió.')));
          res.on('end', () => {
            try {
              const result = JSON.parse(Buffer.concat(chunks).toString('utf8'));
              if (res.statusCode !== 200) reject(new Error(typeof result.error === 'string' ? result.error : 'Operación local rechazada.'));
              else accept(result as T);
            } catch { reject(new Error('Respuesta local no válida.')); }
          });
        });
        req.setTimeout(600_000, () => req.destroy(new Error('La operación local agotó el tiempo de espera.')));
        req.on('error', () => reject(new Error('No se pudo completar la conexión local. El motor puede seguir terminando la operación.')));
        req.end(bytes);
      });
    } finally { this.requests--; }
  }

  stop(): void {
    if (this.requests || this.starting) throw new Error('Espera a que termine la operación antes de detener el motor.');
    this.dispose();
  }

  dispose(): void {
    // EOF is a graceful stop. Never kill a process writing a user's archive.
    this.stopping = this.child !== null;
    this.child?.stdin.end();
    this.port = 0;
    this.token = '';
  }
}
