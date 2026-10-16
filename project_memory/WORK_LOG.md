# Registro

- 2026-10-16: usuario confirmó el recorrido de ficha tras mostrar captura real del panel Obsidian conectado. Preparada biblioteca personal independiente, vacía y configurada, con plugin instalado fuera de Git. Copia inicial y restauración temporal comprobadas; sin exportaciones personales leídas/importadas. Guía para abrir la carpeta como bóveda y seleccionar exportación local.

- 2026-10-14: CI final del código Obsidian correcto en Windows y Ubuntu, incluyendo Python, compilación y cliente real: `a674cd7`, https://github.com/Jfenic/MenteAtlas/actions/runs/38646827262. Corregidos aliases 8.3 con resolución nativa. PR #5 sigue en borrador, sin merge. La verificación visual en la aplicación sigue pendiente.

- 2026-10-14: comprobación local específica con `C:\PROGRA~1` confirmó que la variante JS de `realpathSync` conserva el alias; cambiada a `realpathSync.native`, que devuelve `C:\Program Files`. La prueba cliente completa de CI usa precisamente rutas temporales con alias en Windows.

- 2026-10-14: CI Ubuntu correcto; Windows detectó comparación textual de ruta temporal con alias 8.3 `RUNNER~1`. Ajustado el assert Python a ruta resuelta y la comprobación del vault en el cliente a `realpathSync`, manteniendo rechazo de otra biblioteca. Revalidación pendiente.

- 2026-10-14: PR #5 creado en borrador sobre PR #4: https://github.com/Jfenic/MenteAtlas/pull/5. Paquete Python 0.4.0 instalado; plugin compilado copiado a la demo y bundle ZIP preparado localmente, sin configuración privada. CI pendiente. Sin merge.

- 2026-10-14: tras aclaración de que el usuario quiere trabajar dentro de Obsidian, implementado plugin TypeScript + API local autenticada en `feat/obsidian-plugin` (0.4.0), sobre PR #4. Suite Python de 78 pruebas correcta (una omisión por symlinks), seis pruebas API y tres pruebas Node del cliente real correctas; compilación TypeScript correcta. Demo nueva con plugin preparada fuera de Git. Obsidian instalado, CLI desactivada; la carga visual queda pendiente y no se declara verificada. CI/PR pendientes.

- 2026-10-14: CI de vista previa satisfactorio en Windows/Ubuntu para `4146764`: https://github.com/Jfenic/MenteAtlas/actions/runs/38595678936. PR #4 sigue en borrador, sin fusionar. Commits posteriores registran resultados y no cambian la implementación probada.

- 2026-10-14: PR #4 creado en borrador sobre PR #3: https://github.com/Jfenic/MenteAtlas/pull/4. Wheel 0.3.1 comprobado con recurso de demo y entrada de escritorio. Sin merge automático; CI pendiente.

- 2026-10-14: vista previa verificada con suite completa de 72 pruebas en Windows (71 correctas, una omisión por permisos de symlinks). Ventana de la demo lanzada desde el mismo comando del acceso directo y comprobada como proceso con ventana y respuesta. CI por comprobar.

- 2026-10-14: el usuario pidió continuar y poder ver/probar el progreso. Añadida vista previa Tk en `feat/desktop-preview` (0.3.1), con demo sintética fuera de Git y acceso directo Windows reutilizable. Comprobadas cuatro pruebas de orquestación y smoke gráfico real de búsqueda, fuente seleccionada, creación/búsqueda de ficha y cierre. Suite completa/CI pendientes; plugin/API siguen como siguiente trabajo.

- 2026-10-14: nuevo repositorio y nombre MAtlasAgent confirmados; documentada separación entre programa e instancias.
- 2026-10-14: entrega 1 en rama propia; instalación Python editable y 17 pruebas ejecutadas en Windows (16 correctas, una omisión por permiso de symlinks). Idempotencia de 100 conversaciones, conflictos, cambios, reconstrucción y recuperación de interrupción comprobados con datos ficticios.
- 2026-10-14: PR #1 en borrador, sin merge. CI Windows/Ubuntu satisfactorio para `7c492c3`: https://github.com/Jfenic/MenteAtlas/actions/runs/38562604161. Demostración CLI local instalada con originales sintéticos y búsqueda verificable. Biblioteca editable y backup/restauración son la siguiente entrega.
- 2026-10-14: entrega 2 implementada en rama independiente basada en entrega 1: fichas y búsqueda, referencias a versiones exactas, revisión/sucesión, conflictos, backup completo y restauración en otra ubicación. Instalación editable actualizada a 0.2.0 con PyYAML 6.0.3. Suite Windows: 44 pruebas (43 correctas, una omisión por permisos de symlinks). Se corrigió fsync de la copia en Windows antes de la verificación final; CI remoto pendiente.
- 2026-10-14: demostración instalada con una ficha de dos fuentes sintéticas; backup y restauración completos en carpetas diferentes, búsqueda y referencias originales verificadas. Los datos y rutas privadas de la demo se conservan fuera de Git.
- 2026-10-14: PR #2 creado en borrador hacia la rama de PR #1, sin merge. CI Windows/Ubuntu correcto para `57b435f`: https://github.com/Jfenic/MenteAtlas/actions/runs/38567434636. Añadida regresión de renombrado a `.MD`, comprobada localmente. Siguiente entrega: catálogo central de etiquetas.

- 2026-10-14: el usuario pidió merge y continuación. PR #1 fusionado en `1e2b8ee`; PR #2 retargeteado a main y fusionado en `9adec56`, después de verificar los SHA y los checks de ambas plataformas. Las ramas anteriores se conservaron.
- 2026-10-14: entrega 3 implementada en `feat/tag-catalog`: jerarquías, alias, propuestas, fusiones, reglas literales, aprobación/rechazos y asignaciones humanas protegidas. Pruebas específicas de Unicode, conflictos, filtros, sensibilidad, reimportación y restauración; suite completa en curso. Sin datos personales ni IA externa.
- 2026-10-14: instalación editable 0.3.0 y suite completa comprobadas en Windows: 67 pruebas (66 correctas, una omisión por permisos de symlinks). CI remoto de entrega 3 pendiente.
- 2026-10-14: demostración local de catálogo: aprobar una sugerencia, asignar una etiqueta a un mensaje, backup/restauración y búsqueda por alias/padre comprobados con fixtures ficticios. No se guardan rutas personales de esa demo en el repo.
- 2026-10-14: PR #3 abierto en borrador hacia main. CI Windows/Ubuntu correcto para `6df659a`: https://github.com/Jfenic/MenteAtlas/actions/runs/38577388647. No fusionado automáticamente. Próximo bloque: interfaz Obsidian y API local protegida.
- 2026-10-14: observado stdout cp1252 en Windows; ajustada la CLI a UTF-8 para preservar JSON multilingüe, con regresión de una etiqueta japonesa. CI del ajuste por comprobar.
- 2026-10-14: regresión UTF-8 correcta y suite completa de 68 pruebas en CI Windows/Ubuntu satisfactoria para `1493b57`: https://github.com/Jfenic/MenteAtlas/actions/runs/38578976208. PR #3 sigue en borrador; PRs #1/#2 permanecen fusionados.
