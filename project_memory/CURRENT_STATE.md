# Estado — 2026-10-14

Producto: MAtlasAgent. Repositorio dedicado: Jfenic/MenteAtlas. Programa compartido e instancias privadas fuera de Git; ejemplos y pruebas ficticios.

## Implementado en main

El usuario autorizó explícitamente fusionar las entregas existentes y continuar. Se comprobaron los SHA y los últimos checks Windows/Ubuntu antes de fusionar en orden:

- PR #1 fusionado: https://github.com/Jfenic/MenteAtlas/pull/1. Merge `1e2b8ee97e51f951f0eefbe7634bde464247409b`.
- PR #2 retargeteado a main y fusionado: https://github.com/Jfenic/MenteAtlas/pull/2. Merge `9adec56b92fc16b3dc4d8a8346c41e5d4e194c47`.
- Main contiene motor Python/CLI, importación JSON/ZIP, originales/versiones, Obsidian Markdown, FTS5 con citas, fichas editables, conflictos y backup/restauración completa.
- CI de código de entrega 2 comprobado: https://github.com/Jfenic/MenteAtlas/actions/runs/38567780155 (Windows/Ubuntu satisfactorio).

No se cambió el repositorio de experimentos ni se fusionaron propuestas nuevas automáticamente.

## Entrega 3 — desarrollo

Rama `feat/tag-catalog`, basada en main ya fusionado. Catálogo central privado `tags.json`: jerarquía, IDs, alias, propuestas/revisión, fusiones, reglas literales, asignaciones y auditoría. Las reglas proponen etiquetas aprobadas y no crean vocabulario ni reescriben fichas. Los cambios y retiradas humanos en Markdown se protegen, y los rechazos persisten tras reimportación/reindexado. Filtros por alias y descendientes para mensajes y fichas; etiquetas de conversación heredadas al filtrar sus mensajes. Catálogo incluido en backup y restore. Migración SQLite 2→3; paquete 0.3.0.

Instalación editable 0.3.0 comprobada. Suite completa local Windows: 67 pruebas, 66 correctas y una omitida por permisos de symlinks. Incluye Unicode, alias/fusiones, cambios y retiradas humanos, propuesta obsoleta, sensibilidad, filtros de fuente/fichas y backup/restauración del catálogo. CI y PR de entrega 3 pendientes de registrar. La guía es `docs/TAGS.md`; límites en `docs/ARCHITECTURE.md`.

Demostración instalada con datos ficticios: una sugerencia aprobada para una ficha y una asignación manual de mensaje; backup/restauración conservaron dos etiquetas y dos asignaciones, búsqueda por alias y por categoría padre, sin propuestas pendientes. Sus datos/rutas locales están fuera de Git.

## Pendiente

Plugin Obsidian y API local, MCP de lectura, IA/semántica opcional, relaciones/grafos, distribución Windows y licencia. Las diez preguntas reales siguen pendientes para evaluar utilidad cotidiana. La búsqueda de mensajes corresponde a las fuentes; las anotaciones de transcripciones no se indexan, pero el contenido de fichas sí.
