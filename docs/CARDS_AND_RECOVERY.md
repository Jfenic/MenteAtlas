# Fichas, conflictos y recuperación

Entrega 2 de MAtlasAgent. Mantiene las transcripciones y añade una biblioteca de conocimiento editable. Usa las carpetas externas creadas en [la guía Windows](WINDOWS.md).

## Preparar los comandos

```powershell
$atlasPython = '.\.venv\Scripts\python.exe'
$atlasInstance = Join-Path $env:LOCALAPPDATA 'MAtlasAgent\demo'
$atlasVault = Join-Path $env:USERPROFILE 'Documents\MAtlasAgent-Demo'
```

Los comandos siguientes usan exclusivamente la conversación ficticia de `examples/synthetic-export.json`. Mantén los cuerpos Markdown fuera de Git cuando sean personales.

## Crear una ficha con fuentes verificables

```powershell
$atlasCard = & $atlasPython -m matlasagent --instance $atlasInstance card create `
  --title 'Idea: atlas local' --type idea --tag 'proyectos/atlas' `
  --source demo-atlas-001 demo-message-user `
  --source demo-atlas-001 demo-message-assistant --from-sources | ConvertFrom-Json

& $atlasPython -m matlasagent --instance $atlasInstance card show $atlasCard.id
& $atlasPython -m matlasagent --instance $atlasInstance search 'atlas' --scope cards --type idea --status draft
& $atlasPython -m matlasagent --instance $atlasInstance card list --tag 'proyectos/atlas'
```

También puedes crear una ficha manual con `--body-file` apuntando a un archivo UTF-8, sin `--source`. `--from-sources` copia extractos de los mensajes seleccionados; no crea un resumen ni acepta como propia una propuesta del asistente. Cada referencia registra la versión exacta. `card show` muestra el texto fuente de esa versión, su autor, el registro y el archivo original, incluso tras una reimportación actualizada.

Tipos: `idea`, `decision`, `information`, `open_question`. Estados: `draft`, `reviewed`, `archived`. La ficha nace en borrador. `origin`, `generated_by`, `reviewed_by` y `reviewed_at` distinguen origen, generación y revisión humana.

## Editar y revisar

En Obsidian, edita el cuerpo y las propiedades YAML de la ficha. Puedes moverla o renombrarla conservando `id` y `matlas_kind`. La búsqueda de fichas actualiza el índice automáticamente. Si la borras, desaparece de la búsqueda y una reimportación no la recrea. `Cards/` está reservada para fichas gestionadas; otros documentos pueden vivir en el resto del vault.

Para editar mediante CLI, revisa primero su versión actual:

```powershell
$atlasCurrent = & $atlasPython -m matlasagent --instance $atlasInstance card show $atlasCard.id | ConvertFrom-Json
& $atlasPython -m matlasagent --instance $atlasInstance card update $atlasCard.id `
  --expect-hash $atlasCurrent.content_hash --status reviewed --reviewer 'usuario-local'
```

`--expect-hash` impide reemplazar una versión que ya ha cambiado. Si hay conflicto, la CLI devuelve código 2 y guarda la propuesta aparte. Si cambias el contenido de una ficha revisada por CLI, vuelve a borrador salvo revisión explícita. Cuando edites directamente en Obsidian, actualiza tú las propiedades de revisión y las fechas. Cierra el editor para aplicar reemplazos por CLI.

Una decisión puede señalar a su sucesora con `card update ... --superseded-by <UUID>`; no se admiten ciclos. Las etiquetas siguen siendo una lista editable; el [catálogo central](TAGS.md) interpreta nombres y alias aprobados y protege los cambios humanos.

## Revisar conflictos

```powershell
& $atlasPython -m matlasagent --instance $atlasInstance conflicts list
# Copia un nombre exacto devuelto por list:
$atlasProposal = 'nombre-devuelto-por-list.md'
& $atlasPython -m matlasagent --instance $atlasInstance conflicts show $atlasProposal
& $atlasPython -m matlasagent --instance $atlasInstance conflicts resolve $atlasProposal --keep-current
```

Para aplicar la propuesta, usa `--apply --expect-hash <hash-actual>` en lugar de `--keep-current`. Para fichas, obtiene el hash con `card show`; para transcripciones, usa `Get-FileHash -Algorithm SHA256` sobre la nota actual y conviértelo a minúsculas. La versión anterior se conserva en la instancia. Una propuesta antigua de transcripción no puede reemplazar una fuente más reciente. No se aplican propuestas a notas borradas.

## Copia completa y restauración en otra ubicación

Cierra Obsidian durante la copia. Elige un nombre nuevo para cada backup fuera de la instancia, del vault y de Git; no se sobrescriben copias existentes. La copia contiene información privada y no está cifrada.

```powershell
$atlasBackupFolder = Join-Path $env:USERPROFILE 'Documents\MAtlasAgent-Backups'
New-Item -ItemType Directory -Force -Path $atlasBackupFolder | Out-Null
$atlasBackup = Join-Path $atlasBackupFolder ('demo-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.zip')
& $atlasPython -m matlasagent --instance $atlasInstance backup $atlasBackup

$atlasRestoredInstance = Join-Path $env:LOCALAPPDATA 'MAtlasAgent\demo-restored'
$atlasRestoredVault = Join-Path $env:USERPROFILE 'Documents\MAtlasAgent-Demo-Restored'
& $atlasPython -m matlasagent --instance $atlasRestoredInstance restore $atlasBackup --vault $atlasRestoredVault
& $atlasPython -m matlasagent --instance $atlasRestoredInstance card show $atlasCard.id
& $atlasPython -m matlasagent --instance $atlasRestoredInstance search 'atlas' --scope cards
& $atlasPython -m matlasagent --instance $atlasRestoredInstance stats
```

La restauración verifica archivos y fuentes en carpetas temporales antes de publicar. El índice se reconstruye con las rutas nuevas; las fichas conservan su ID y contenido y la instancia obtiene una identidad independiente. Se preservan originales, versiones de mensajes, registros, conflictos y configuración de Obsidian; SQLite se reconstruye. No se reemplazan carpetas pobladas. Una interrupción durante la publicación puede dejar carpetas nuevas parcialmente restauradas: consérvalas y vuelve a probar con otras rutas vacías y el backup original.

La copia requiere un sistema de archivos local con hard links, como NTFS. No sincronices SQLite abierto entre dispositivos. Las referencias de MAtlasAgent son portables; los enlaces absolutos que escribas tú o guarde un plugin externo no se reescriben automáticamente.

## English

Cards are canonical safe-YAML/Markdown with stable UUIDs and versioned source references. `card create/show/list/update`, `search --scope cards`, and `conflicts list/show/resolve` provide explicit workflows. Updates require the current content hash; conflicting proposals and preceding bytes are preserved. Card searches discover external edits, moves and deletions.

`backup` captures private vault and durable instance files with SHA-256 checksums; `restore` stages and verifies the archive into empty directories, creates an independent instance identity and rebuilds paths/index. Try the synthetic demonstration first. Backups are unencrypted and never belong in Git. Multi-directory publication can be interrupted, so retain the backup and any partial target directories.
