"""Install only into a newly created synthetic demo vault, never a user's vault."""
import json
from pathlib import Path
import shutil
import sys

from matlasagent.desktop import create_demo
from matlasagent.storage import atomic_write, encoded


def main():
    project = Path(__file__).resolve().parents[1]
    bundle = project / "obsidian-plugin" / "dist"
    for name in ("main.js", "manifest.json", "styles.css"):
        if not (bundle / name).is_file():
            raise SystemExit("Build the plugin first: cd obsidian-plugin && npm ci && npm run build")
    library = create_demo()
    plugin = library.vault / ".obsidian" / "plugins" / "matlasagent"
    plugin.mkdir(parents=True)
    for name in ("main.js", "manifest.json", "styles.css"):
        shutil.copyfile(bundle / name, plugin / name)
    atomic_write(plugin / "data.json", encoded({"python": sys.executable, "instance": str(library.root),
                                               "openOnStart": True, "autoStart": True}))
    atomic_write(library.vault / ".obsidian" / "community-plugins.json", encoded(["matlasagent"]))
    atomic_write(library.vault / "EMPIEZA-AQUI.md", """# Prueba de MAtlasAgent dentro de Obsidian

Este vault solo contiene datos ficticios. Tu vault habitual no cambia.

1. Si el panel no aparece, activa MAtlasAgent en Ajustes → Plugins de comunidad.
2. Abre el comando **MAtlasAgent: Abrir biblioteca** con Ctrl+P, o pulsa el icono del cerebro.
3. Pulsa **Iniciar motor** si no se ha conectado automáticamente.
4. Busca **atlas** en Conversaciones y marca la fuente.
5. Pulsa **Usar fuentes seleccionadas en una ficha**, escribe un título y guarda.
6. La ficha se abre en el editor de Obsidian; puedes editar su Markdown.

También puedes importar JSON/ZIP y guardar una copia completa. El ZIP contiene tus datos sin cifrar.
La IA externa está desactivada. Revisión de etiquetas, conflictos y restauración siguen en la consola.
""".encode("utf-8"))
    print(json.dumps({"vault": str(library.vault), "instance": str(library.root)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
