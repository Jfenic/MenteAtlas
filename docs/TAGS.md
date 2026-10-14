# Centro de etiquetas de MAtlasAgent

Cada instancia tiene su catálogo privado; no se comparte con otras personas ni con GitHub. Las carpetas del vault y la jerarquía de etiquetas son independientes. No hay llamadas a IA ni servicios externos.

## Crear una jerarquía y sinónimos

```powershell
$atlasPython = '.\.venv\Scripts\python.exe'
$atlasInstance = Join-Path $env:LOCALAPPDATA 'MAtlasAgent\demo'
& $atlasPython -m matlasagent --instance $atlasInstance tags add proyectos --label 'Proyectos'
& $atlasPython -m matlasagent --instance $atlasInstance tags add proyectos/atlas --label 'Atlas personal'
& $atlasPython -m matlasagent --instance $atlasInstance tags alias mapas proyectos/atlas
& $atlasPython -m matlasagent --instance $atlasInstance tags tree
```

Los nombres se normalizan con Unicode NFKC y sin distinguir mayúsculas; se mantienen las diferencias de acentos. Los espacios se convierten en guiones. Una subetiqueta requiere que su padre exista y esté aprobado. Los alias reutilizan la etiqueta canónica; no pueden colisionar con otro nombre o sinónimo.

Para proponer un concepto nuevo sin aprobarlo:

```powershell
& $atlasPython -m matlasagent --instance $atlasInstance tags suggest proyectos/documentacion --label 'Documentación'
& $atlasPython -m matlasagent --instance $atlasInstance tags list --status proposed
& $atlasPython -m matlasagent --instance $atlasInstance tags approve proyectos/documentacion
# Alternativa a approve: tags reject proyectos/documentacion
```

Se reutiliza un nombre/alias conocido antes de proponer otro. Un rechazo queda registrado y no se vuelve a proponer silenciosamente. Puedes revertirlo explícitamente mediante `approve`. No se intenta adivinar equivalencias semánticas que no hayas aprobado.

## Reglas locales y revisión de asignaciones

```powershell
& $atlasPython -m matlasagent --instance $atlasInstance tags rule-add proyectos/atlas --term atlas --scope cards
& $atlasPython -m matlasagent --instance $atlasInstance tags classify --scope cards
$atlasPending = @(& $atlasPython -m matlasagent --instance $atlasInstance tags proposals | ConvertFrom-Json)
```

Las reglas solo proponen etiquetas aprobadas; no cambian fichas ni crean nuevas categorías. Los términos se interpretan literalmente y respetan límites de palabras. `--scope` admite `cards`, `messages`, `conversations` o `all`; las propuestas de cada ámbito son independientes. Dos clasificaciones idénticas no duplican propuestas.

Después de revisar una propuesta de ficha, usa sus IDs reales:

```powershell
$atlasProposal = $atlasPending[0]
$atlasCurrent = & $atlasPython -m matlasagent --instance $atlasInstance card show $atlasProposal.target.card_id | ConvertFrom-Json
& $atlasPython -m matlasagent --instance $atlasInstance tags accept $atlasProposal.id --expect-hash $atlasCurrent.content_hash
# Alternativa: tags reject-proposal <ID>
```

El ejemplo requiere que exista al menos una propuesta pendiente para una ficha. Para propuestas de mensajes/conversaciones no hace falta `--expect-hash`, pero se verifica que la evidencia observada no haya cambiado. Si cambió el texto o se borró la ficha, vuelve a clasificar: la propuesta antigua queda obsoleta. Una clasificación no confirma preferencias ni decisiones del autor; solo informa de coincidencias literales.

Para generar propuestas durante una importación elegida explícitamente:

```powershell
& $atlasPython -m matlasagent --instance $atlasInstance import .\examples\synthetic-export.json --suggest-tags
```

## Asignaciones humanas y búsqueda

```powershell
# Asignar a una conversación conservando los originales:
& $atlasPython -m matlasagent --instance $atlasInstance tags assign mapas --conversation demo-atlas-001
# Solo a un mensaje:
& $atlasPython -m matlasagent --instance $atlasInstance tags assign mapas --conversation demo-atlas-001 --message demo-message-user
& $atlasPython -m matlasagent --instance $atlasInstance search atlas --tag mapas
& $atlasPython -m matlasagent --instance $atlasInstance search atlas --scope cards --tag proyectos
& $atlasPython -m matlasagent --instance $atlasInstance tags assignments --conversation demo-atlas-001
```

La búsqueda reconoce alias y descendientes. Una etiqueta de conversación se aplica a sus mensajes al filtrar. Para fichas, usa `tags assign <nombre> --card <UUID> --expect-hash <hash-actual>`; `tags remove` acepta los mismos argumentos.

Las etiquetas de fichas siguen en Markdown. Puedes editar su lista en Obsidian: las adiciones se reconocen como manuales y las retiradas se registran como bloqueos. Un rechazo o retirada no se deshace al reimportar, reconstruir el índice o volver a clasificar. Una reasignación manual explícita revierte ese bloqueo. Las etiquetas libres que aún no estén en el catálogo se conservan y siguen disponibles por filtro literal; no se aprueban automáticamente.

## Fusiones, sensibilidad y copias

`tags merge <origen> <destino>` mantiene IDs históricos, fuentes y alias, y combina asignaciones sin duplicarlas. No reescribe las fichas humanas. Los hijos pasan al destino y conservan sus nombres históricos; el árbol real se determina por IDs de padre. Se rechazan fusiones que creen ciclos.

Para categorías que consideres sensibles, usa `tags add <nombre> --sensitive`; también refuerza esa condición en una categoría existente. Sus descendientes la heredan y las reglas requieren `--allow-sensitive` explícito. Las propuestas previas de reglas sin ese permiso quedan obsoletas al reclasificar. No existe un catálogo personal sensible preinstalado ni clasificación automática sin reglas configuradas.

`tags rules`, `tags rule-remove <ID>` y `tags audit` permiten inspeccionar y mantener las decisiones. El catálogo, los alias, las reglas, las propuestas y los rechazos forman parte de la copia completa de la instancia. Restaurar o borrar SQLite conserva esas decisiones porque su almacenamiento duradero es `tags.json`.

## English

The per-instance tag center keeps an approved hierarchy, normalized names, aliases, reviewed proposals, merge redirects and assignment audit. Card tags stay canonical Markdown; source assignments and human rejection blocks are durable catalog state. Literal rules propose existing approved tags for review, never create vocabulary or overwrite human choices. Searches resolve aliases and descendants. Full backups preserve catalog decisions through index rebuilding and restore.
