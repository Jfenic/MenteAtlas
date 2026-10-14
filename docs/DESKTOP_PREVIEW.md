# Prueba visual de MAtlasAgent

Esta vista previa permite probar el motor antes de integrar el plugin Obsidian. Es una ventana local de Python/Tk, con datos propios fuera de Git. No utiliza un servidor, conexión al historial ni proveedor de IA.

## Abrir

Con Python 3.12+ y desde el repositorio:

```powershell
python -m pip install -e .
python -m matlasagent.desktop --demo
```

Cada `--demo` crea una biblioteca distinta: notas en `Documents/MAtlasAgent-demo-<id>` y archivo privado en el directorio de datos de MAtlasAgent. Usa conversaciones ficticias incluidas en el paquete. Para reutilizar una biblioteca abre su `instance.json` con **Abrir biblioteca**, o indica su carpeta:

```powershell
python -m matlasagent.desktop --instance "C:\ruta\a\la\instancia"
```

En Windows puedes crear un acceso directo a `pythonw.exe` con esos argumentos para abrir sin consola. Debe ser el Python donde instalaste el paquete. En Ubuntu, Tk puede requerir el paquete del sistema `python3-tk`.

## Recorrido de cinco minutos

1. Busca `atlas` en **Conversaciones** y selecciona el resultado. Verás su referencia y versión.
2. Pulsa **Crear ficha con fuentes seleccionadas**, escribe un título y un comentario, y guarda. Se copia la versión exacta de cada fuente como cita. Ctrl permite seleccionar varios mensajes.
3. Busca el título en **Fichas**. Abre la nota para editar el Markdown con tu aplicación habitual.
4. Prueba el filtro de etiqueta `atlas`, alias de `proyecto/atlas` en la demo.
5. Guarda una **Copia de seguridad** con un nombre nuevo. Incluye originales, fichas, catálogo y notas; no está cifrada. La restauración se hace con la CLI descrita en [fichas y recuperación](CARDS_AND_RECOVERY.md).

**Importar JSON / ZIP** permite elegir una exportación local de ChatGPT. El motor conserva originales y cambios humanos. Las propuestas en conflicto se mantienen fuera del vault para resolverlas con la CLI. Para tus datos reales, crea primero una instancia independiente con `matlas init`, según [Windows](WINDOWS.md), y ábrela desde esta ventana.

## Alcance

La ventana ofrece hasta 100 resultados, filtros de etiquetas, fichas manuales o con fuentes, importación, apertura de notas/carpetas y backup. Las operaciones se ejecutan en un único trabajador; al cerrar espera a que termine la operación. Muestra actividad, sin porcentaje estimado.

La edición avanzada, revisión de etiquetas, conflictos y restauración siguen en la CLI. Abrir una nota usa la aplicación asociada a `.md`; para Obsidian abre la carpeta de notas como vault. Plugin Obsidian, API local protegida, MCP, IA y grafos siguen pendientes. Esta entrega es una vista previa utilizable, no el producto completo ni un instalador autónomo.
