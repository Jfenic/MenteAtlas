# Estado — 2026-10-14

Repositorio nuevo e independiente. MAtlasAgent es el nombre acordado; MenteAtlas se mantiene en la URL. No se migran experimentos del repositorio anterior.

Entrega 1 implementada en `feat/local-library-core`: paquete Python 3.12+, CLI, instancias/vaults separados de Git, importador JSON/ZIP, originales y versiones, transcripciones protegidas, FTS5 con citas y reconstrucción. Instalación editable verificada en Windows. Suite local: 17 pruebas, 16 pasan y una de symlinks omitida por permisos del sistema.

PR en borrador sin fusionar: https://github.com/Jfenic/MenteAtlas/pull/1. Commit de código comprobado: `7c492c3edb1b1192597d42b473a1073414ac225f`. CI Windows/Ubuntu completado con éxito: https://github.com/Jfenic/MenteAtlas/actions/runs/38562604161. Este resultado corresponde a ese commit; consultar GitHub para cambios posteriores.

Demostración instalada localmente con el ejemplo sintético: una conversación, dos mensajes, segunda importación sin duplicados, búsqueda con fuente y reconstrucción verificadas. Las ubicaciones personales de esa demo no se registran en Git.

## Entrega 2 — en rama propia

Implementada en `feat/cards-and-recovery`, apoyada en entrega 1 sin fusionarla. Fichas Markdown/YAML editables con UUID, tipos/estados, fuentes múltiples y versiones exactas; búsquedas con filtros y detección de cambios/movimientos/borrados. Actualizaciones con hash esperado y propuestas preservadas; revisión humana explícita y sucesión de decisiones sin ciclos. Resolución de conflictos, historial y auditoría. Backup completo con manifest/checksums y restauración verificada en otra ubicación, sin sobrescribir destinos y reconstruyendo rutas/índice. PyYAML 6.0.3 fijado para propiedades Obsidian; migración SQLite 1→2.

Suite local Windows: 44 pruebas, 43 correctas y una omitida por permisos de symlinks. Demostración instalada: ficha con dos fuentes, copia completa y restauración en otra ubicación verificadas, preservando UUID y referencias y usando rutas nuevas. CI remoto de entrega 2 y enlace de PR pendientes de registrar. No equivale a publicación ni a aprobación humana. Ver `docs/CARDS_AND_RECOVERY.md` para uso y limitaciones de reemplazo concurrente, backup sin cifrado y publicación de restauración en dos carpetas.

Pendiente: catálogo central de etiquetas, plugin Obsidian, MCP, IA, grafos y distribución/licencia. La búsqueda de mensajes corresponde a fuentes; las anotaciones de transcripciones no se indexan, pero el contenido de fichas sí. Datos utilizados: exclusivamente sintéticos. Las diez preguntas reales siguen pendientes para validar utilidad cotidiana.
