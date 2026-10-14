# MAtlasAgent dentro de Obsidian

El plugin de escritorio abre un panel en el vault para importar exportaciones JSON/ZIP, buscar conversaciones y fichas por texto/etiqueta, crear fichas manuales o con fuentes versionadas y guardar backups. Las fichas se abren en el editor de Obsidian para editar su Markdown.

## Instalar desde el repositorio

Requisitos: Obsidian de escritorio 1.8+, Python 3.12+ y Node.js 22 para compilar. Python sigue siendo necesario durante el uso; Node solo durante la compilación. No es todavía un instalador autónomo ni un plugin publicado en el catálogo comunitario.

```powershell
python -m pip install -e .
cd obsidian-plugin
npm ci
npm run build
```

Copia los tres archivos de `obsidian-plugin/dist` (`main.js`, `manifest.json`, `styles.css`) a `<vault>/.obsidian/plugins/matlasagent/`. En Obsidian, habilita plugins de comunidad y MAtlasAgent. Sigue el [procedimiento oficial para plugins en desarrollo](https://docs.obsidian.md/Plugins/Getting%20started/Build%20a%20plugin).

En **Ajustes → MAtlasAgent**, indica:

- **Ejecutable de Python:** ruta al Python que tiene instalado el paquete. Para un entorno virtual de Windows será `<proyecto>/.venv/Scripts/python.exe`. No incluyas argumentos ni comillas adicionales.
- **Carpeta de instancia privada:** originales/configuración, fuera del vault y de Git. Para una biblioteca existente usa su carpeta de `instance.json`.

Abre **MAtlasAgent: Abrir biblioteca** con Ctrl+P o el icono del cerebro. **Iniciar motor** abre una biblioteca existente. **Crear biblioteca e iniciar** inicializa una instancia nueva únicamente si el vault no contiene notas: se permite la carpeta `.obsidian` que crea la aplicación. Un vault con notas existentes requiere usar otra carpeta vacía; no se adopta ni modifica automáticamente.

Si el motor indica que la instancia pertenece a otro vault, corrige la configuración. Un vault restaurado debe apuntar a su instancia restaurada; el backup puede contener los ajustes del plugin anterior y debe reconfigurarse antes de conectar.

## Demo preparada automáticamente

Después de compilar y desde la raíz del proyecto:

```powershell
python tools/install_obsidian_demo.py
```

El script crea una biblioteca ficticia nueva, instala el plugin y escribe configuración de Python/instancia solo en ella. Imprime la carpeta del vault. En Obsidian elige **Abrir carpeta como bóveda** y selecciona esa carpeta. Si la app solicita activar plugins de comunidad, activa MAtlasAgent. El panel intenta abrirse y conectar automáticamente en esta demo; fuera de ella el arranque es manual. `EMPIEZA-AQUI.md` contiene el recorrido.

## Prueba de uso

1. Busca `atlas` en **Conversaciones** y marca una o varias fuentes.
2. Pulsa **Usar fuentes seleccionadas en una ficha**. Escribe un título, tipo y comentario.
3. **Guardar y abrir ficha** conserva las versiones seleccionadas como citas y abre Markdown en Obsidian.
4. Busca el título en **Fichas**. Los resultados se limitan a 100; refina la consulta si alcanzas el límite.
5. Importa JSON/ZIP de hasta 64 MiB con el selector de archivos. No hay conexión automática a tu cuenta ni scraping.
6. Guarda una copia en una ruta ZIP nueva, fuera de instancia/vault/Git. Contiene datos sin cifrar; [restauración y conflictos](CARDS_AND_RECOVERY.md) siguen en la consola.

El filtro acepta etiquetas o alias existentes. Las reglas/revisiones de etiquetas siguen en la CLI. El panel no edita propiedades avanzadas, resuelve conflictos ni restaura copias todavía. La IA, MCP y grafos siguen pendientes.

## Conexión y cierre

El plugin inicia `python -m matlasagent.api` sin shell ni ventana de consola. Solo escucha en `127.0.0.1` y un puerto efímero. Cada sesión usa una clave aleatoria enviada por un pipe privado; no se guarda en archivos ni aparece en argumentos. La API exige autenticación, Host local exacto y ausencia de Origin; no ofrece CORS. No permite elegir un servidor remoto.

El motor valida la correspondencia del vault antes de reconstruir el índice. Un único servidor procesa operaciones en serie, con límites de entrada y sin logs de solicitudes/contenido. La UI muestra actividad y bloquea acciones durante una operación; no inventa porcentajes. Al desactivar el plugin/cerrar Obsidian, cierra el pipe y el motor termina después de la operación activa. No se fuerza la terminación de una importación o backup. El cierre forzado del sistema conserva los límites de recuperación documentados del motor.

Este mecanismo protege el acceso desde otras páginas y sesiones casuales; no aísla el proceso de otro software con los mismos permisos del usuario. Otros plugins de Obsidian ya tienen permisos locales sobre el vault.

## Verificación

Las pruebas Python cubren autorización/Host/Origin, límites, errores sin eco de contenido, importación/búsqueda/fichas/backup/restauración, vínculo entre vault e instancia e inicio/cierre por pipe. Las pruebas Node ejecutan el cliente real contra Python y comprueban fuentes, reinicio y rechazo de otro vault. Se compila TypeScript contra las declaraciones oficiales de Obsidian. Los resultados de CI y las comprobaciones de la aplicación instalada se registran por separado en `project_memory/CURRENT_STATE.md`; compilar o probar el cliente no equivale a verificar la carga visual en Obsidian.
