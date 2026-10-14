# MAtlasAgent — inicio en Windows

Esta es la primera entrega de consola. Python 3.12 y Git deben estar instalados; Obsidian sirve para abrir la carpeta de notas. No requiere WSL. Los datos reales se probarán después de implementar backup/restauración.

## Instalar el programa

```powershell
git clone https://github.com/Jfenic/MenteAtlas.git
cd MenteAtlas
# Mientras la primera entrega esté en revisión:
git switch feat/local-library-core
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
- Si editas una transcripción y cambia su fuente, la propuesta se guarda en `conflicts` de la instancia; tu nota permanece intacta. Resolución manual guiada pendiente.
- Una transcripción renombrada conserva su ID; una borrada no se regenera automáticamente. El contenido fuente sigue siendo buscable sin enlace a nota.

## English quick start

Install with the first command block, initialize two empty directories outside Git, and import `examples/synthetic-export.json`. `--instance` selects your private archive and configuration; `--vault` selects the separate Markdown folder. Open the vault in Obsidian. Search citations identify the archived source message. Do not use this prototype as your only copy of real data: verified backup and restore will arrive in delivery 2.
