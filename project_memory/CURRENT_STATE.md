# Estado — 2026-10-14

Repositorio nuevo e independiente. MAtlasAgent es el nombre acordado; MenteAtlas se mantiene en la URL. No se migran experimentos del repositorio anterior.

Entrega 1 implementada en `feat/local-library-core`: paquete Python 3.12+, CLI, instancias/vaults separados de Git, importador JSON/ZIP, originales y versiones, transcripciones protegidas, FTS5 con citas y reconstrucción. Instalación editable verificada en Windows. Suite local: 17 pruebas, 16 pasan y una de symlinks omitida por permisos del sistema.

PR en borrador sin fusionar: https://github.com/Jfenic/MenteAtlas/pull/1. Commit de código comprobado: `7c492c3edb1b1192597d42b473a1073414ac225f`. CI Windows/Ubuntu completado con éxito: https://github.com/Jfenic/MenteAtlas/actions/runs/38562604161. Este resultado corresponde a ese commit; consultar GitHub para cambios posteriores.

Demostración instalada localmente con el ejemplo sintético: una conversación, dos mensajes, segunda importación sin duplicados, búsqueda con fuente y reconstrucción verificadas. Las ubicaciones personales de esa demo no se registran en Git.

Pendiente: fichas de conocimiento, backup/restauración completa, etiquetas, plugin Obsidian, MCP, IA, grafos y distribución/licencia. La búsqueda actual corresponde a mensajes fuente, no a anotaciones humanas de las transcripciones. Datos utilizados: exclusivamente sintéticos.
