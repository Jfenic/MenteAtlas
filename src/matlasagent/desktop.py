"""Local desktop preview. One worker owns all library operations; Tk stays responsive."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess
import uuid

from .library import Library, default_instance
from .storage import LibraryError


def create_demo(parent=None):
    """Create an independent synthetic library; never reuse an existing directory."""
    parent = Path(parent) if parent else Path.home() / "Documents"
    name = "MAtlasAgent-demo-" + uuid.uuid4().hex[:12]
    library = Library.initialize(default_instance().parent / name, parent / name)
    sample = files("matlasagent").joinpath("synthetic-export.json").read_bytes()
    # The original is retained by import; this temporary input is outside Git too.
    source = library.root / "demo-input.json"
    try:
        source.write_bytes(sample)
        library.import_export(source)
    finally:
        source.unlink(missing_ok=True)
    library.tags("register", slug="proyecto")
    library.tags("register", slug="proyecto/atlas")
    library.tags("alias", alias="atlas", value="proyecto/atlas")
    library.create_card("Mi primera idea — ejemplo ficticio", body="Conservar ideas con referencias verificables.",
                        sources=[("demo-atlas-001", "demo-message-user")],
                        from_sources=True, tags=["proyecto/atlas"])
    return library


def source_reference(row):
    # Preserve the version shown in the result even if another client reimports.
    return {"source": "chatgpt", "conversation_id": row["conversation_id"],
            "message_id": row["message_id"], "version": row["version"]}


class Session:
    """A single executor serializes this client's reads and writes."""
    def __init__(self):
        self.library = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="matlas-desktop")

    def open(self, instance):
        candidate = Library(instance)
        candidate.rebuild()
        self.library = candidate
        return candidate.stats()

    def demo(self, parent=None):
        self.library = create_demo(parent)
        return self.library.stats()

    def submit(self, operation):
        return self.executor.submit(operation)

    def close(self):
        self.executor.shutdown(wait=True)


def open_local(path):
    path = Path(path)
    if not path.exists():
        raise LibraryError("La nota ya no está en esa ubicación. Actualiza la búsqueda.")
    if os.name == "nt":
        os.startfile(str(path))
    else:
        subprocess.Popen(["open" if __import__("sys").platform == "darwin" else "xdg-open", str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Desktop:
    def __init__(self, root, instance=None, demo=False):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk, self.root = tk, ttk, root
        self.session = Session()
        self.future = None
        self.closing = False
        self.rows = []
        self.controls = []
        root.title("MAtlasAgent — tu atlas local")
        root.geometry("1050x720")
        root.minsize(850, 600)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TButton", padding=6)
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="MAtlasAgent", font=("Segoe UI", 23, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Tus conversaciones e ideas, guardadas en tu ordenador. Vista previa local.").pack(anchor="w")
        self.library_label = tk.StringVar(value="Abre una biblioteca o crea una demostración con datos ficticios.")
        ttk.Label(frame, textvariable=self.library_label, wraplength=950).pack(anchor="w", pady=8)
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill="x")
        self.button(toolbar, "Abrir biblioteca…", self.choose_instance, requires_library=False)
        self.button(toolbar, "Nueva demo ficticia", lambda: self.run("Preparando demo…", self.session.demo, self.ready), requires_library=False)
        self.button(toolbar, "Importar JSON / ZIP…", self.import_file)
        self.button(toolbar, "Copia de seguridad…", self.backup)
        self.button(toolbar, "Abrir carpeta de notas", self.open_vault)
        self.stats_label = tk.StringVar()
        ttk.Label(frame, textvariable=self.stats_label).pack(anchor="w", pady=8)
        self.tabs = ttk.Notebook(frame)
        self.tabs.pack(fill="both", expand=True)
        search = ttk.Frame(self.tabs, padding=12)
        create = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(search, text="Buscar y consultar")
        self.tabs.add(create, text="Crear ficha")
        fields = ttk.Frame(search)
        fields.pack(fill="x")
        self.query, self.scope, self.tag = tk.StringVar(value="atlas"), tk.StringVar(value="Conversaciones"), tk.StringVar()
        ttk.Entry(fields, textvariable=self.query, width=30).pack(side="left", fill="x", expand=True)
        scopes = ttk.Combobox(fields, textvariable=self.scope, values=["Conversaciones", "Fichas"], state="readonly", width=16)
        scopes.pack(side="left", padx=6)
        self.controls.append((scopes, "readonly", True))
        ttk.Label(fields, text="Etiqueta:").pack(side="left")
        ttk.Entry(fields, textvariable=self.tag, width=18).pack(side="left", padx=6)
        self.button(fields, "Buscar", self.search)
        self.results = ttk.Treeview(search, columns=("title", "kind", "snippet"), show="headings", selectmode="extended", height=8)
        for name, title, width in (("title", "Título", 240), ("kind", "Autor / tipo", 100), ("snippet", "Extracto", 480)):
            self.results.heading(name, text=title)
            self.results.column(name, width=width, minwidth=60)
        self.results.pack(fill="both", expand=True, pady=10)
        self.results.bind("<<TreeviewSelect>>", self.select)
        self.details = tk.Text(search, height=6, wrap="word", state="disabled")
        self.details.pack(fill="x")
        actions = ttk.Frame(search)
        actions.pack(fill="x", pady=(8, 0))
        self.button(actions, "Abrir nota seleccionada", self.open_note)
        self.button(actions, "Crear ficha con fuentes seleccionadas", self.from_selection)
        ttk.Label(search, text="Hasta 100 resultados. Selecciona varias fuentes con Ctrl. Las fichas se editan en Markdown.").pack(anchor="w", pady=6)
        self.title, self.kind, self.card_tags = tk.StringVar(), tk.StringVar(value="idea"), tk.StringVar()
        self.references = []
        for label, variable in (("Título", self.title), ("Etiquetas separadas por comas (opcional)", self.card_tags)):
            ttk.Label(create, text=label).pack(anchor="w")
            ttk.Entry(create, textvariable=variable).pack(fill="x", pady=(0, 8))
        ttk.Label(create, text="Tipo").pack(anchor="w")
        kinds = ttk.Combobox(create, textvariable=self.kind, values=["idea", "decision", "information", "open_question"], state="readonly")
        kinds.pack(anchor="w", pady=(0, 8))
        self.controls.append((kinds, "readonly", True))
        ttk.Label(create, text="Contenido").pack(anchor="w")
        self.body = tk.Text(create, height=8, wrap="word")
        self.body.pack(fill="both", expand=True)
        self.source_label = tk.StringVar(value="Sin fuentes seleccionadas. Puedes crear una ficha manual.")
        ttk.Label(create, textvariable=self.source_label).pack(anchor="w", pady=6)
        create_actions = ttk.Frame(create)
        create_actions.pack(fill="x")
        self.button(create_actions, "Guardar ficha", self.create_card)
        self.button(create_actions, "Quitar fuentes", self.clear_sources)
        for container in (fields, create):
            for widget in container.winfo_children():
                if isinstance(widget, ttk.Entry):
                    self.controls.append((widget, "normal", True))
        self.controls.append((self.body, "normal", True))
        self.status = tk.StringVar(value="Listo. Sin conexión a servicios externos ni IA.")
        ttk.Label(frame, textvariable=self.status, wraplength=950).pack(anchor="w", pady=(10, 0))
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.pack(fill="x", pady=(5, 0))
        self.enable_controls()
        if demo:
            self.run("Preparando demo…", self.session.demo, self.ready)
        elif instance:
            self.run("Abriendo biblioteca…", lambda: self.session.open(instance), self.ready)

    def button(self, parent, label, command, requires_library=True):
        widget = self.ttk.Button(parent, text=label, command=command)
        widget.pack(side="left", padx=(0, 6))
        self.controls.append((widget, "normal", requires_library))
        return widget

    def enable_controls(self):
        for widget, normal, requires in self.controls:
            enabled = self.future is None and not self.closing and (not requires or self.session.library is not None)
            widget.configure(state=normal if enabled else "disabled")

    def run(self, label, operation, callback):
        if self.future is not None or self.closing:
            return
        self.status.set(label)
        self.future = self.session.submit(operation)
        self.enable_controls()
        self.progress.start()
        self.root.after(75, lambda: self.poll(callback))

    def poll(self, callback):
        if not self.future.done():
            self.root.after(75, lambda: self.poll(callback))
            return
        future, self.future = self.future, None
        self.progress.stop()
        self.enable_controls()
        try:
            result = future.result()
            if not self.closing:
                callback(result)
        except Exception as error:
            from tkinter import messagebox
            message = str(error) if isinstance(error, LibraryError) else "No se pudo completar la operación. Comprueba permisos y espacio disponible."
            self.status.set(message)
            if not self.closing:
                messagebox.showerror("MAtlasAgent", message, parent=self.root)
        if self.closing:
            self.session.close()
            self.root.destroy()

    def ready(self, stats):
        self.rows = []
        self.results.delete(*self.results.get_children())
        self.show_details("")
        self.clear_sources()
        lib = self.session.library
        self.library_label.set("Biblioteca: " + str(lib.vault))
        self.stats_label.set(f"{stats['conversations']} conversaciones · {stats['messages']} mensajes · {stats['cards']} fichas · {stats['tags']} etiquetas")
        self.status.set("Biblioteca preparada. Busca «atlas» o crea tu primera ficha.")

    def choose_instance(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root, title="Selecciona instance.json de tu biblioteca", filetypes=[("Configuración de biblioteca", "instance.json")])
        if path:
            self.run("Abriendo biblioteca…", lambda: self.session.open(Path(path).parent), self.ready)

    def import_file(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root, title="Selecciona una exportación de ChatGPT", filetypes=[("Exportaciones", "*.json *.zip")])
        if path:
            def operation():
                counts = self.session.library.import_export(Path(path))
                return counts, self.session.library.stats()
            def imported(result):
                counts, stats = result
                self.ready(stats)
                self.status.set("Importación terminada: " + json.dumps(counts, ensure_ascii=False))
            self.run("Importando… Los originales se conservan y los cambios humanos se protegen.", operation, imported)

    def backup(self):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(parent=self.root, title="Nueva copia de seguridad (contiene tus datos, sin cifrar)", defaultextension=".zip", initialfile="MAtlasAgent-backup.zip", filetypes=[("Copia ZIP", "*.zip")])
        if path:
            self.run("Guardando copia de seguridad…", lambda: self.session.library.backup(Path(path)),
                     lambda _: self.status.set("Copia completa guardada. La restauración sigue disponible en la consola."))

    def search(self):
        query, tag, scope = self.query.get().strip(), self.tag.get().strip() or None, self.scope.get()
        def operation():
            lib = self.session.library
            if scope == "Fichas":
                return lib.search_cards(query or None, tag=tag, limit=100)
            return lib.search(query, tag=tag, limit=100)
        def found(rows):
            self.rows = rows
            self.results.delete(*self.results.get_children())
            for i, row in enumerate(rows):
                self.results.insert("", "end", iid=str(i), values=(row["title"], row.get("role", row.get("type", "")), row["snippet"]))
            self.show_details("")
            self.status.set(f"{len(rows)} resultados. " + ("Refina la búsqueda si necesitas más." if len(rows) == 100 else ""))
        self.run("Buscando…", operation, found)

    def selected(self):
        return [self.rows[int(i)] for i in self.results.selection()]

    def show_details(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def select(self, event=None):
        rows = self.selected()
        if rows:
            row = rows[0]
            text = row["title"] + "\n\n" + row["snippet"]
            if "message_id" in row:
                text += f"\n\nFuente: {row['conversation_id']} / {row['message_id']} · versión {row['version']}"
            else:
                text += "\n\nEstado: " + row["status"] + " · Fuentes: " + str(len(row["citations"]))
            self.show_details(text)

    def open_note(self):
        rows = self.selected()
        if rows and rows[0].get("note_path"):
            self.open_path(rows[0]["note_path"])

    def open_vault(self):
        self.open_path(self.session.library.vault)

    def open_path(self, path):
        from tkinter import messagebox
        try:
            open_local(path)
        except (LibraryError, OSError):
            messagebox.showerror("MAtlasAgent", "No se pudo abrir la nota o carpeta. Actualiza la búsqueda y comprueba la aplicación asociada.", parent=self.root)

    def from_selection(self):
        rows = self.selected()
        if not rows or any("message_id" not in r for r in rows):
            self.status.set("Selecciona mensajes de conversaciones para crear una ficha con fuentes.")
            return
        self.references = [source_reference(row) for row in rows]
        self.source_label.set(f"{len(self.references)} fuentes seleccionadas; se copiarán sus versiones exactas como citas.")
        self.tabs.select(1)

    def clear_sources(self):
        self.references = []
        self.source_label.set("Sin fuentes seleccionadas. Puedes crear una ficha manual.")

    def create_card(self):
        title, body, kind = self.title.get().strip(), self.body.get("1.0", "end-1c"), self.kind.get()
        tags, sources = [t.strip() for t in self.card_tags.get().split(",") if t.strip()], list(self.references)
        if not title:
            self.status.set("Escribe un título para la ficha.")
            return
        def operation():
            card = self.session.library.create_card(title, body=body, kind=kind, tags=tags,
                                                     sources=sources, from_sources=bool(sources))
            return card, self.session.library.stats()
        def saved(result):
            card, stats = result
            self.ready(stats)
            self.title.set("")
            self.body.delete("1.0", "end")
            self.card_tags.set("")
            self.status.set("Ficha guardada en Cards: " + card["title"] + ". Puedes buscarla en Fichas y abrirla para editarla.")
        self.run("Guardando ficha…", operation, saved)

    def close(self):
        self.closing = True
        self.enable_controls()
        if self.future is not None:
            self.status.set("Terminando la operación antes de cerrar…")
        else:
            self.session.close()
            self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="MAtlasAgent local desktop preview")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--instance", type=Path)
    group.add_argument("--demo", action="store_true", help="Create a new synthetic library outside Git")
    args = parser.parse_args(argv)
    import tkinter as tk
    root = tk.Tk()
    Desktop(root, instance=args.instance, demo=args.demo)
    root.mainloop()


if __name__ == "__main__":
    main()
