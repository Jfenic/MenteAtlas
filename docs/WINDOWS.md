# MAtlasAgent — inicio en Windows

Este es el prototipo de consola. Las entregas 1–2 ya están integradas en `main`; el catálogo de etiquetas es la entrega 3. Python 3.12 y Git deben estar instalados; Obsidian sirve para abrir la carpeta de notas. No requiere WSL. Empieza con la demostración sintética y comprueba backup/restauración en otra carpeta antes de importar tus exportaciones reales.

## Instalar el programa

```powershell
git clone https://github.com/Jfenic/MenteAtlas.git
cd MenteAtlas
# Para probar la entrega 3 mientras esté en revisión:
git switch feat/tag-catalog
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m matlasagent --help
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Crear tu instancia de demostración

El programa y sus dependencias están en el clon. La instancia (configuración, originales y SQLite) y el vault (Markdown) están fuera del clon y separados entre sí. Las rutas deben ser carpetas nuevas o vacías; `init` no adopta una bóveda existente.

```powershell
$atlasInstance = Join-Path $env:LOCALAPPDATA 'MAtlasAgent\demo'
$atlasVault = Join-Path $env:USERPROFILE 'Documents\MAtlasAgent-Demo'
$atlasPython = '.\.venv\Scripts\python.exe'
& $atlasPython -m matlasagent --instance $atlasInstance init --vault $atlasVault
& $atlasPython -m matlasagent --instance $atlasInstance import .\examples\synthetic-export.json
& $atlasPython -m matlasagent --instance $atlasInstance import .\examples\synthetic-export.json
& $atlasPython -m matlasagent --instance $atlasInstance stats
& $atlasPython -m matlasagent --instance $atlasInstance search 'atlas'
& $atlasPython -m matlasagent --instance $atlasInstance search '"atlas local"' --role user
& $atlasPython -m matlasagent --instance $atlasInstance rebuild-index
```

Abre `$atlasVault` como bóveda en Obsidian. Verás una conversación ficticia y los IDs/ancoras de sus mensajes. Las rutas de los resultados señalan la transcripción y el registro fuente local. La segunda importación informa cero mensajes nuevos.

`--instance` va antes del subcomando. Si lo omites, se usa `%LOCALAPPDATA%\MAtlasAgent\default`. Cada instancia tiene un vault independiente configurable; puedes repetir el procedimiento con otras dos carpetas vacías. El índice queda dentro de la instancia, fuera del vault y de Git.

## Búsqueda y errores

- `search` admite expresiones FTS5, frases entre comillas, `--role`, `--from AAAA-MM-DD`, `--to AAAA-MM-DD` y paginación `--limit`/`--offset`.
- Fechas en UTC; `--to` es exclusivo. El fragmento y la versión representan el mensaje fuente archivado, no tus anotaciones posteriores sobre la transcripción.
- Importación parcial devuelve código 2 y contadores de errores; importa los chats válidos y permite reintentar. No imprime conversaciones ni rutas personales en los errores.
- Mensajes no textuales se conservan en el export original y se cuentan como advertencias; los adjuntos aún no se renderizan.
- Si editas una transcripción y cambia su fuente, la propuesta se guarda en `conflicts` de la instancia; tu nota permanece intacta. Usa `conflicts list/show/resolve` para revisarla explícitamente.
- Una transcripción renombrada conserva su ID; una borrada no se regenera automáticamente. El contenido fuente sigue siendo buscable sin enlace a nota.

## English quick start

Install with the first command block, initialize two empty directories outside Git, and import `examples/synthetic-export.json`. `--instance` selects your private archive and configuration; `--vault` selects the separate Markdown folder. Open the vault in Obsidian. Search citations identify the archived source message. Delivery 2 adds editable knowledge cards, explicit conflict resolution and checksum-verified complete backup/restore. See [cards and recovery](CARDS_AND_RECOVERY.md) and try restoring the demonstration into another location before using real exports.
