# MAtlasAgent

Your personal knowledge atlas. A local knowledge library for Windows, with portable Markdown notes and a rebuildable SQLite search index.

Nombre de producto: **MAtlasAgent**. Repositorio: **Jfenic/MenteAtlas**.

Application code is shared; every person keeps their own library and settings outside Git. Personal conversation exports never belong in this repository. The application does not connect to your ChatGPT account or send data to AI providers.

**Status: CLI prototype, deliveries 1–3, not the complete product.** Import ChatGPT JSON/ZIP exports, preserve source versions, render Obsidian transcripts, create editable knowledge cards, search messages/cards with citations, resolve preserved proposals, and back up/restore independent libraries. Central tags support hierarchies, synonyms, proposals, merges and human-protected assignments. Deterministic rules suggest existing approved tags for review. Obsidian plugin, MCP, AI and graphs remain planned.

- [Inicio en Windows / Windows quick start](docs/WINDOWS.md)
- [Architecture, data model and limitations](docs/ARCHITECTURE.md)
- [Fichas, conflictos y recuperación / Cards and recovery](docs/CARDS_AND_RECOVERY.md)
- [Centro de etiquetas / Tag center](docs/TAGS.md)
- [Plan completo / Roadmap](docs/ROADMAP.md)

Python 3.12+ is required. Runtime dependency: **PyYAML 6.0.3**, pinned for safe, editable YAML front matter compatible with Obsidian property edits; remaining runtime code uses the standard library. Installation downloads this dependency and the setuptools build backend. See `python -m matlasagent --help` after installing with `python -m pip install -e .`.

Every library uses `--instance` to select its configuration and private source archive, plus a separate Obsidian vault. The same installation can serve several libraries. Application updates do not replace instance directories.

No redistribution license has been chosen yet. A repository's visibility alone does not grant an open-source license; license selection is part of the publication milestone.
