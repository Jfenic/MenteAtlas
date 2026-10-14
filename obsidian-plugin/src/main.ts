import { Plugin, ItemView, WorkspaceLeaf, PluginSettingTab, Setting, Notice, FileSystemAdapter, TFile } from 'obsidian';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { Engine, Config, Reference, Row, vaultNote } from './engine';

const VIEW = 'matlasagent-library';

export default class MAtlasPlugin extends Plugin {
  config!: Config;
  engine = new Engine();

  async onload(): Promise<void> {
    const stored = await this.loadData();
    this.config = { python: 'python', instance: join(homedir(), '.matlasagent', 'instances', randomUUID()), ...stored };
    if (!stored?.instance) await this.saveData(this.config);
    this.registerView(VIEW, leaf => new AtlasView(leaf, this));
    this.addRibbonIcon('brain', 'Abrir MAtlasAgent', () => { void this.openPanel(); });
    this.addCommand({ id: 'open-library', name: 'Abrir biblioteca', callback: () => { void this.openPanel(); } });
    this.addSettingTab(new AtlasSettings(this));
    this.app.workspace.onLayoutReady(() => { if (this.config.openOnStart) void this.openPanel(); });
  }

  onunload(): void { this.engine.dispose(); }

  vaultRoot(): string {
    if (!(this.app.vault.adapter instanceof FileSystemAdapter)) throw new Error('MAtlasAgent requiere un vault local de escritorio.');
    return this.app.vault.adapter.getBasePath();
  }

  async openPanel(): Promise<void> {
    let leaf = this.app.workspace.getLeavesOfType(VIEW)[0];
    if (!leaf) { leaf = this.app.workspace.getLeaf('tab'); await leaf.setViewState({ type: VIEW, active: true }); }
    await this.app.workspace.revealLeaf(leaf);
  }

  async openNote(value: string): Promise<void> {
    const name = vaultNote(this.vaultRoot(), value);
    // The engine writes on disk; wait briefly for Obsidian's file watcher.
    let file = this.app.vault.getAbstractFileByPath(name);
    for (let i = 0; !file && i < 15; i++) { await new Promise(resolve => setTimeout(resolve, 100)); file = this.app.vault.getAbstractFileByPath(name); }
    if (!(file instanceof TFile)) throw new Error('La nota aún no aparece en Obsidian. Vuelve a intentarlo.');
    await this.app.workspace.getLeaf('tab').openFile(file);
  }
}

class AtlasSettings extends PluginSettingTab {
  constructor(private plugin: MAtlasPlugin) { super(plugin.app, plugin); }
  display(): void {
    this.containerEl.empty();
    this.containerEl.createEl('h2', { text: 'MAtlasAgent — motor local' });
    this.containerEl.createEl('p', { text: 'El plugin inicia Python en tu ordenador. No envía conversaciones a servicios externos. Cambia estos ajustes con el motor detenido.' });
    for (const [key, title, description] of [
      ['python', 'Ejecutable de Python', 'Ruta a python.exe del entorno con MAtlasAgent instalado. Sin argumentos.'],
      ['instance', 'Carpeta de instancia privada', 'Archivo de originales y configuración, fuera del vault y de Git. El vault es el que tienes abierto.']
    ] as const) {
      new Setting(this.containerEl).setName(title).setDesc(description).addText(text => text.setValue(this.plugin.config[key]).onChange(async value => {
        if (this.plugin.engine.active) { new Notice('Detén el motor antes de cambiar la configuración.'); return; }
        this.plugin.config[key] = value.trim(); await this.plugin.saveData(this.plugin.config);
      }));
    }
    this.containerEl.createEl('p', { text: 'En un vault vacío usa «Crear biblioteca e iniciar». Si ya tienes biblioteca, indica su instancia y usa «Iniciar motor». No se adoptan notas existentes automáticamente.' });
  }
}

class AtlasView extends ItemView {
  private busy = false;
  private status!: HTMLElement;
  private stats!: HTMLElement;
  private controls: (HTMLButtonElement | HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement)[] = [];
  private results!: HTMLElement;
  private query!: HTMLInputElement;
  private searchScope!: HTMLSelectElement;
  private tag!: HTMLInputElement;
  private title!: HTMLInputElement;
  private kind!: HTMLSelectElement;
  private body!: HTMLTextAreaElement;
  private sources!: HTMLElement;
  private selected = new Map<number, Row>();
  private references: Reference[] = [];

  constructor(leaf: WorkspaceLeaf, private plugin: MAtlasPlugin) { super(leaf); }
  getViewType(): string { return VIEW; }
  getDisplayText(): string { return 'MAtlasAgent'; }
  getIcon(): string { return 'brain'; }

  async onOpen(): Promise<void> {
    const content = this.contentEl;
    content.empty(); content.addClass('matlas-panel');
    content.createEl('h1', { text: 'MAtlasAgent' });
    content.createEl('p', { text: 'Tu biblioteca de conversaciones y fichas, dentro de este vault.' });
    const toolbar = content.createDiv({ cls: 'matlas-toolbar' });
    this.button(toolbar, 'Iniciar motor', () => this.start(false));
    this.button(toolbar, 'Crear biblioteca e iniciar', () => this.start(true));
    this.button(toolbar, 'Detener motor', async () => { this.plugin.engine.stop(); this.stats.setText('Motor detenido.'); });
    this.status = content.createDiv({ cls: 'matlas-status', text: 'Inicia el motor para conectar tu biblioteca. Configuración en Ajustes → MAtlasAgent.' });
    this.status.setAttribute('role', 'status'); this.status.setAttribute('aria-live', 'polite');
    this.stats = content.createDiv({ cls: 'matlas-stats' });
    const importRow = content.createDiv({ cls: 'matlas-toolbar' });
    this.button(importRow, 'Importar JSON / ZIP…', () => this.pickImport());
    const upload = importRow.createEl('input', { type: 'file', attr: { accept: '.json,.zip', 'aria-label': 'Exportación de ChatGPT' } });
    upload.hidden = true;
    upload.onchange = () => {
      const file = upload.files?.[0];
      if (file) void this.task('Importando… Los originales y los cambios humanos se conservan.', () => this.importFile(file));
      upload.value = '';
    };
    this.upload = upload;
    content.createEl('h2', { text: 'Buscar' });
    const filters = content.createDiv({ cls: 'matlas-toolbar' });
    this.query = this.input(filters, 'Texto o expresión de búsqueda');
    this.query.value = 'atlas';
    this.searchScope = filters.createEl('select', { attr: { 'aria-label': 'Buscar en' } });
    this.searchScope.createEl('option', { value: 'messages', text: 'Conversaciones' });
    this.searchScope.createEl('option', { value: 'cards', text: 'Fichas' }); this.controls.push(this.searchScope);
    this.tag = this.input(filters, 'Etiqueta o alias (opcional)');
    this.button(filters, 'Buscar', () => this.search());
    this.results = content.createDiv({ cls: 'matlas-results' });
    this.button(content, 'Usar fuentes seleccionadas en una ficha', async () => {
      if (!this.selected.size) throw new Error('Selecciona uno o más mensajes de conversación.');
      this.references = [...this.selected.values()].map(row => ({ source: 'chatgpt', conversation_id: row.conversation_id!, message_id: row.message_id!, version: row.version! }));
      this.sources.setText(`${this.references.length} fuentes seleccionadas. Se conservarán sus versiones exactas como citas.`);
      this.title.focus();
    });
    content.createEl('h2', { text: 'Crear ficha' });
    this.title = this.input(content, 'Título de la ficha');
    this.kind = content.createEl('select', { attr: { 'aria-label': 'Tipo de ficha' } });
    for (const [value, text] of [['idea', 'Idea'], ['decision', 'Decisión'], ['information', 'Información'], ['open_question', 'Pregunta abierta']]) this.kind.createEl('option', { value, text });
    this.controls.push(this.kind);
    this.body = content.createEl('textarea', { attr: { placeholder: 'Escribe tu idea o comentario…', rows: '5', 'aria-label': 'Contenido de la ficha' } });
    this.controls.push(this.body);
    this.sources = content.createDiv({ text: 'Sin fuentes: se creará una ficha manual.' });
    const cardActions = content.createDiv({ cls: 'matlas-toolbar' });
    this.button(cardActions, 'Guardar y abrir ficha', () => this.createCard());
    this.button(cardActions, 'Quitar fuentes', async () => { this.references = []; this.sources.setText('Sin fuentes: se creará una ficha manual.'); });
    content.createEl('h2', { text: 'Copia de seguridad' });
    const backup = this.input(content, 'Ruta completa a un ZIP nuevo, fuera del vault y de Git');
    this.button(content, 'Guardar copia completa', async () => {
      if (!backup.value.trim()) throw new Error('Escribe una ruta de destino para la copia.');
      await this.plugin.engine.call('/backup', { path: backup.value.trim() });
      new Notice('Copia completa guardada. Contiene tus datos sin cifrar.');
    });
    content.createEl('small', { text: 'Vista previa de escritorio. Edición en Markdown; revisión de etiquetas, conflictos y restauración siguen en la consola. IA externa desactivada.' });
    if (this.plugin.config.autoStart) await this.task('Iniciando el motor local…', () => this.start(false));
  }
  private upload!: HTMLInputElement;

  private input(parent: HTMLElement, placeholder: string): HTMLInputElement {
    const field = parent.createEl('input', { type: 'text', attr: { placeholder, 'aria-label': placeholder } });
    this.controls.push(field); return field;
  }

  private button(parent: HTMLElement, text: string, operation: () => Promise<void>): void {
    const button = parent.createEl('button', { text });
    this.controls.push(button);
    button.onclick = () => { void this.task(text + '…', operation); };
  }

  private async task(label: string, operation: () => Promise<void>): Promise<void> {
    if (this.busy) return;
    this.busy = true; this.status.setText(label); this.contentEl.setAttribute('aria-busy', 'true');
    this.controls.forEach(control => { control.disabled = true; });
    try { await operation(); this.status.setText('Listo.'); }
    catch (error) { const text = error instanceof Error ? error.message : 'No se pudo completar la operación.'; this.status.setText(text); new Notice(text); }
    finally { this.busy = false; this.contentEl.setAttribute('aria-busy', 'false'); this.controls.forEach(control => { control.disabled = false; }); }
  }

  private async start(initialize: boolean): Promise<void> {
    await this.plugin.engine.start(this.plugin.config, this.plugin.vaultRoot(), initialize);
    await this.refresh();
  }

  private async refresh(): Promise<void> {
    const data = await this.plugin.engine.call<Record<string, number>>('/stats');
    this.stats.setText(`${data.conversations} conversaciones · ${data.messages} mensajes · ${data.cards} fichas · ${data.tags} etiquetas`);
  }

  private async pickImport(): Promise<void> {
    if (!this.plugin.engine.running) throw new Error('Inicia primero el motor.');
    this.upload.click();
  }

  private async importFile(file: File): Promise<void> {
    const format = file.name.split('.').pop()?.toLowerCase();
    if (!['json', 'zip'].includes(format ?? '') || file.size > 64 * 1024 * 1024 || !file.size) throw new Error('Elige un archivo JSON o ZIP de hasta 64 MiB.');
    const bytes = Buffer.from(await file.arrayBuffer());
    const result = await this.plugin.engine.call<Record<string, unknown>>('/import', undefined, { bytes, format: format! });
    await this.refresh();
    new Notice(`Importación terminada. ${result.new_messages ?? 0} mensajes nuevos. Las propuestas en conflicto se conservan para revisión.`);
  }

  private async search(): Promise<void> {
    const data = { scope: this.searchScope.value, query: this.query.value.trim(), limit: 100, ...(this.tag.value.trim() ? { tag: this.tag.value.trim() } : {}) };
    const rows = await this.plugin.engine.call<Row[]>('/search', data);
    this.results.empty(); this.selected.clear();
    this.controls = this.controls.filter(control => control.isConnected);
    this.results.createEl('p', { text: `${rows.length} resultados (máximo 100).` });
    rows.forEach((row, index) => {
      const item = this.results.createDiv({ cls: 'matlas-result' });
      const heading = item.createDiv({ cls: 'matlas-toolbar' });
      if (row.message_id) {
        const check = heading.createEl('input', { type: 'checkbox', attr: { 'aria-label': 'Seleccionar fuente: ' + row.title } });
        check.onchange = () => { if (check.checked) this.selected.set(index, row); else this.selected.delete(index); };
        this.controls.push(check);
      }
      heading.createEl('strong', { text: row.title });
      item.createEl('small', { text: row.message_id ? `${row.role} · versión ${row.version} · ${row.conversation_id} / ${row.message_id}` : `${row.type} · ${row.status}` });
      // Export text is untrusted: render as text, never innerHTML or executable Markdown.
      item.createEl('p', { text: row.snippet });
      if (row.vault_path) this.button(item, 'Abrir nota', () => this.plugin.openNote(row.vault_path!));
    });
  }

  private async createCard(): Promise<void> {
    if (!this.title.value.trim()) throw new Error('Escribe un título para la ficha.');
    const result = await this.plugin.engine.call<{ vault_path: string }>('/cards', { title: this.title.value.trim(), body: this.body.value, kind: this.kind.value, sources: this.references, from_sources: this.references.length > 0 });
    this.title.value = ''; this.body.value = ''; this.references = []; this.sources.setText('Sin fuentes: se creará una ficha manual.');
    await this.refresh(); await this.plugin.openNote(result.vault_path);
  }
}

