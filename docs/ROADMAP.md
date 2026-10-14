# Plan de MAtlasAgent

## Decisiones confirmadas — 2026-10-14

- Repositorio dedicado Jfenic/MenteAtlas; producto MAtlasAgent.
- Windows primero, Python 3.12+, SQLite FTS5, Markdown y Obsidian.
- Programa reutilizable e instancias independientes con datos fuera de Git.
- Exportaciones proporcionadas por el usuario, sin conexión automática al historial.
- Originales conservados; fichas editables y referencias estables; nunca sobrescribir cambios humanos silenciosamente.
- IA externa desactivada por defecto; ejemplos y CI exclusivamente sintéticos.
- Código por ramas y PRs en borrador; sin merge automático.

## Entregas

1. Motor y CLI, instancias, importación JSON/ZIP, transcripciones, búsqueda con citas, reconstrucción y pruebas Windows/Ubuntu.
2. Biblioteca: fichas idea/decision/information/open_question, estados draft/reviewed/archived, fuentes múltiples, movimientos, borrados, conflictos y backup/restauración.
3. Etiquetas: jerarquías, alias, propuestas, aprobación, fusiones y asignaciones humanas protegidas.
4. Interfaz: plugin Obsidian, API local protegida, configuración, progreso y arranque sin terminal.
5. MCP local de lectura, consultas limitadas, instrucciones para clientes compatibles.
6. IA opcional, propuestas revisables, búsqueda semántica y respuestas con referencias.
7. Relaciones y grafos, diferenciando sugerencias de relaciones confirmadas.
8. Distribución Windows, actualizaciones, piloto, documentación bilingüe, licencia elegida por el propietario y publicación.

La importación incremental y preservación de versiones se diseñan desde la primera entrega. Backup/restauración es obligatorio antes del uso habitual con datos reales; no se pospone a una extensión opcional.

## Modelo de conocimiento

Cada ficha tendrá ID UUID independiente del nombre y carpeta; tipo, estado, título, creación/modificación, etiquetas y referencias source/conversation_id/message_id. Autor fuente, generación automática y revisión humana serán campos distintos. Una decisión sustituida podrá enlazar a su sucesora.

Markdown será canónico para fichas humanas; originales y registros normalizados conservarán evidencia de las conversaciones. SQLite será reconstruible. Catálogo de etiquetas, decisiones humanas, trabajos y registros no reconstruibles se guardarán fuera del índice y se incluirán en copias.

## Evaluación

Importar 100 conversaciones sintéticas dos veces sin duplicados; conservar versiones editadas y mensajes ausentes; proteger notas humanas; reconstruir índice; restaurar en otra carpeta. Las diez preguntas reales del propietario quedan pendientes y no bloquean desarrollar con ejemplos ficticios.
