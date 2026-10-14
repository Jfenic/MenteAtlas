# MAtlasAgent for Obsidian

Desktop plugin for the local Python library. Import ChatGPT JSON/ZIP, search messages/cards, create source-linked cards and open them in the Obsidian editor. No external AI or automatic account access.

Requires Python 3.12+ with `matlasagent` installed. Node.js 22 is a build-time requirement. Run `npm ci && npm run build`, then copy `dist/main.js`, `dist/manifest.json` and `dist/styles.css` into your vault's `.obsidian/plugins/matlasagent/` folder.

Enable the plugin, configure Python and an independent private instance in settings, then run **MAtlasAgent: Abrir biblioteca**. A new instance can be created from the panel in an empty vault (its `.obsidian` folder is allowed). Existing libraries must match the current vault.

See [setup, synthetic demo and transport details](../docs/OBSIDIAN.md). This is an unpublished preview; advanced editing, tag review, conflict resolution and restore still use the Python CLI. The repository's redistribution license remains undecided.
