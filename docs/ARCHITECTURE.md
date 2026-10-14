# Architecture — delivery 1

## Application and independent instances

Shared Python package `matlasagent`, CLI `matlas`. An instance directory contains `instance.json` (UUID, absolute vault path, schema version), preserved `originals/`, atomic per-conversation `sources/`, import journals in `imports/`, generated transcript versions, conflict proposals, and `index.sqlite3`. A separate vault contains user-visible Markdown transcripts. Both directories must be outside every Git checkout and must not overlap. Initialization requires empty directories.

No network, telemetry or AI runtime calls. Installation may access the package index for build dependencies. Source identifiers never form path components: filenames use SHA-256, avoiding Windows reserved names, title collisions and path traversal. Linked/junction directories inside managed trees are rejected. Private files are not encrypted by this application.

## Canonical and derived data

Original export bytes are immutable evidence, addressed by SHA-256. Source records retain normalized conversations and cumulative message versions with origin hashes and observation times. Empty nodes and all branch parents/children are preserved; rendered messages follow mapping insertion order, not a claim that every branch was a single chronological conversation. Missing messages in later exports are retained. Original bytes preserve unsupported metadata and attachments.

Source records and import journals are durable state, not disposable indices. SQLite is derived from them and can be rebuilt transactionally. Markdown transcript edits are independent human content and never copied back into original messages. Search currently indexes archived source messages, **not user annotations or knowledge cards**. Citation results therefore expose both source-file provenance and an optional transcript location. Deleted notes remain absent even after reimport; source results can still be found with a null note location.

Future knowledge cards will be canonical editable Markdown, with JSON-compatible YAML front matter: stable UUID, `type` (`idea`, `decision`, `information`, `open_question`), `status` (`draft`, `reviewed`, `archived`), timestamps, author/proposal/reviewer distinctions, tags and a list of source/conversation/message references. These are designed but not implemented in delivery 1. They must have an independent index and survive movement/deletion without regeneration.

## Migration 1

`PRAGMA user_version=1`, transactional DDL in `Library.connect`:

- `conversations`: ID, title, creation/update time, optional note path, source record path.
- `messages`: composite conversation/message ID, mapping node, parent, role, timestamp, text, version.
- `message_versions`: composite conversation/message/version key and source payload.
- `message_fts`: FTS5 with Unicode tokenization and accent-insensitive matching.
- `import_batches`: journal ID, export hash, timestamp, status and aggregate counters.

Foreign keys, composite keys and date index are created explicitly. Newer index versions are rejected; subsequent versions need explicit migrations. Batch journals are outside SQLite so rebuilding keeps operational records.

## Interruption and conflicts

A single OS-owned writer lock prevents simultaneous writers and releases on process termination. Files use temporary writes, flush/fsync and replacement. Per-conversation source checkpoints precede index rebuilding; retry or rebuild repairs an interrupted index update. Original exports remain available to retry parsing. The transcript/source pair is not a multi-file atomic transaction: if interrupted after writing a transcript, retry recognizes its ID/hash and resumes without replacing human edits. Import statuses include running, interrupted, partial and completed.

Before replacing an unedited generated transcript, its preceding bytes are saved outside the vault. A note with a human edit is never replaced; a changed source produces a separate proposal. Duplicate canonical conversation IDs in vault notes block import/rebuild until resolved. Renaming a note is detected via its front matter. Preserve `matlas_kind` and `conversation_id` for tracking.

## Bounded input and current limitations

64 MiB input/JSON, 512 MiB total declared ZIP contents, 10,000 ZIP entries/conversations, 100,000 nodes per conversation, ZIP ratio <=200. ZIP entries are never extracted; absolute paths, traversal, encrypted entries and symlinks are rejected. Exactly one `conversations.json` is required. Limits can reject large legitimate exports; streaming import is future work. Unsupported/non-text parts warn and remain in original bytes. Malformed conversations are counted and skipped, while invalid outer JSON/ZIP aborts parsing.

The index rebuilds fully after each import; suited to validating the first prototype, not yet optimized for large libraries. Source records accumulate versions; space quotas and archival policies are pending. Do not synchronize a live SQLite file. This prototype has no verified complete backup/restore, tag center, knowledge-card CRUD, Obsidian plugin, MCP, semantic search, graph, automatic account sync, installer or chosen distribution license. All are tracked in the roadmap.
