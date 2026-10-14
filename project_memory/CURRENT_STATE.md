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

Instalación editable 0.3.0 comprobada. Suite completa local Windows: 67 pruebas, 66 correctas y una omitida por permisos de symlinks. Incluye Unicode, alias/fusiones, cambios y retiradas humanos, propuesta obsoleta, sensibilidad, filtros de fuente/fichas y backup/restauración del catálogo. La guía es `docs/TAGS.md`; límites en `docs/ARCHITECTURE.md`.

PR #3 en borrador hacia main, sin fusionar: https://github.com/Jfenic/MenteAtlas/pull/3. Commit de implementación `6df659a2597b1b8931d30c98c98535b1d848f43a` verificado con CI Windows/Ubuntu satisfactorio: https://github.com/Jfenic/MenteAtlas/actions/runs/38577388647. Consultar GitHub para cambios posteriores. La autorización de merge de PRs #1/#2 no se interpreta como aprobación automática de nuevas entregas.

Ajuste posterior: salida JSON de la CLI forzada a UTF-8 en Windows; se observó cp1252 en el entorno y se añadió prueba de ida/vuelta con etiqueta japonesa en un stream cp1252. Regresión local correcta y suite de 68 pruebas en CI Windows/Ubuntu satisfactoria para `1493b577ab4f6cc2559f68c56ac0632dc8f4f250`: https://github.com/Jfenic/MenteAtlas/actions/runs/38578976208. Los commits posteriores de documentación no cambian el código comprobado.

Demostración instalada con datos ficticios: una sugerencia aprobada para una ficha y una asignación manual de mensaje; backup/restauración conservaron dos etiquetas y dos asignaciones, búsqueda por alias y por categoría padre, sin propuestas pendientes. Sus datos/rutas locales están fuera de Git.

## Pendiente

Plugin Obsidian y API local, MCP de lectura, IA/semántica opcional, relaciones/grafos, distribución Windows y licencia. Las diez preguntas reales siguen pendientes para evaluar utilidad cotidiana. La búsqueda de mensajes corresponde a las fuentes; las anotaciones de transcripciones no se indexan, pero el contenido de fichas sí.

## Vista previa de escritorio — desarrollo

Ante la petición de probar algo visible, rama `feat/desktop-preview` basada en `feat/tag-catalog` (PR #3 aún sin fusionar). Paquete 0.3.1: ventana Tk local con demo sintética independiente, selección de biblioteca, importación JSON/ZIP, búsqueda de fuentes/fichas por etiquetas, fichas manuales/con citas de versiones exactas, apertura de notas y backup. Un único trabajador serializa operaciones sin bloquear Tk; cerrar espera el trabajo actual. No hay servidor ni llamadas externas. Plugin Obsidian y API siguen pendientes: esta vista previa no completa la entrega 4.

Verificación local: suite completa Windows de 72 pruebas, 71 correctas y una omitida por permisos de symlinks. Incluye cuatro pruebas de demo/recuperación, sesión/errores, serialización y versiones seleccionadas. Smoke real de Tk en Windows: demo, búsqueda, selección de fuente, guardado y búsqueda de ficha con una cita, cierre correcto. Wheel 0.3.1 comprobado con recurso sintético y entrada de escritorio. Demo y acceso directo Windows creados fuera de Git; proceso de ventana lanzado y comprobado con título y respuesta de Windows. La biblioteca se puede reutilizar al reabrir. Guía compartida: `docs/DESKTOP_PREVIEW.md`.

PR #4 en borrador hacia `feat/tag-catalog`: https://github.com/Jfenic/MenteAtlas/pull/4. Implementación `414676453134962a5d0e98725c9e0865d9158d1e` comprobada con CI Windows/Ubuntu satisfactorio: https://github.com/Jfenic/MenteAtlas/actions/runs/38595678936. Los commits posteriores documentan resultados; no cambian ese código. No fusionado. Verificar los checks del head vigente antes de integrar, después de PR #3.

## Entrega 4 — plugin Obsidian inicial

Rama `feat/obsidian-plugin` sobre la vista previa aún no fusionada. Producto 0.4.0: plugin TypeScript de escritorio, panel propio en Obsidian, ajustes de Python/instancia, arranque/parada sin consola, importación JSON/ZIP, búsqueda de fuentes/fichas y etiquetas, selección de versiones exactas para crear fichas, apertura en el editor y backup. El motor Python usa HTTP únicamente en 127.0.0.1/puerto efímero, clave por pipe sin persistir, Host exacto/Origin rechazado, solicitudes limitadas sin logs y operaciones seriales. Desactivar el plugin cierra el pipe y termina después del trabajo activo. Nueva biblioteca solo en vault vacío, permitiendo `.obsidian`; nunca adopta notas existentes ni otra biblioteca silenciosamente.

Verificado localmente: 78 pruebas Python, 77 correctas y una omisión por permisos de symlinks; seis nuevas pruebas de API y ciclo de vida. TypeScript compila; tres pruebas Node del cliente real contra Python correctas (importación, búsqueda, ficha citada, errores, reinicio, otro vault y rutas). CI Windows/Ubuntu correcto para el código final `a674cd7de490ccb529d030855ac66981a5996c8d`: https://github.com/Jfenic/MenteAtlas/actions/runs/38646827262 (Python, build y cliente). La carga visual en Obsidian NO está verificada: la app está instalada, pero su CLI está desactivada; no se cambió esa preferencia. Demo nueva con plugin/configuración/fuentes ficticias preparada fuera de Git; el usuario debe abrirla como bóveda y habilitar el plugin si Obsidian lo solicita. Guía: `docs/OBSIDIAN.md` y script `tools/install_obsidian_demo.py`. IA/MCP/grafos y funciones avanzadas de UI siguen pendientes.

PR #5 en borrador sobre PR #4: https://github.com/Jfenic/MenteAtlas/pull/5. Implementación inicial `6a2602e99d880523dbdd6f65db5e17056f78b3f8`; revisiones hasta `a674cd7` corrigieron rutas cortas Windows y validaron ambas plataformas. Los commits posteriores de documentación no cambian el código probado; comprobar el head vigente antes de integrar. Sin merge. El paquete Python 0.4.0 está instalado localmente y el bundle de plugin contiene solo `main.js`, `manifest.json`, `styles.css`; la configuración privada de la demo está fuera de Git.
