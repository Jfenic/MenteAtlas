# MAtlasAgent

Your personal knowledge atlas. A local knowledge library for Windows, with portable Markdown notes and a rebuildable SQLite search index.

Nombre de producto: **MAtlasAgent**. Repositorio: **Jfenic/MenteAtlas**.

Application code is shared; every person keeps their own library and settings outside Git. Personal conversation exports never belong in this repository. The application does not connect to your ChatGPT account or send data to AI providers.

**Status: first CLI prototype, not the complete product.** Import ChatGPT JSON/ZIP exports, preserve source versions, render Obsidian transcripts, search using SQLite FTS5 and rebuild the index. Human transcript edits are preserved and conflicting generated proposals are stored separately. Knowledge cards, tags, backup/restore, Obsidian plugin, MCP and AI are planned deliveries, not implemented features.

- [Inicio en Windows / Windows quick start](docs/WINDOWS.md)
- [Architecture, data model and limitations](docs/ARCHITECTURE.md)
- [Plan completo / Roadmap](docs/ROADMAP.md)

Python 3.12+ is required. Runtime dependencies: standard library only. Installation downloads the setuptools build backend. See `python -m matlasagent --help` after installing with `python -m pip install -e .`.

Every library uses `--instance` to select its configuration and private source archive, plus a separate Obsidian vault. The same installation can serve several libraries. Application updates do not replace instance directories.

No redistribution license has been chosen yet. A repository's visibility alone does not grant an open-source license; license selection is part of the publication milestone.
