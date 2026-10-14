# Architecture — local library and Obsidian preview

## Application and independent instances

Shared Python package `matlasagent`, CLI `matlas`. An instance directory contains `instance.json` (UUID, absolute vault path, schema version), preserved `originals/`, atomic per-conversation `sources/`, import journals in `imports/`, generated transcript versions, conflict proposals, and `index.sqlite3`. A separate vault contains user-visible Markdown transcripts. Both directories must be outside every Git checkout and must not overlap. Initialization requires empty directories; the plugin's explicit new-library action also permits a vault containing only `.obsidian` configuration.

No external network, telemetry or AI runtime calls. The Obsidian plugin explicitly starts an authenticated loopback-only Python transport; the CLI/desktop preview does not start a server. See [Obsidian transport and lifecycle](OBSIDIAN.md). Installation may access package indices for dependencies. Source identifiers never form path components: filenames use SHA-256, avoiding Windows reserved names, title collisions and path traversal. Linked/junction directories inside managed trees are rejected. Private files are not encrypted by this application.

## Canonical and derived data

Original export bytes are immutable evidence, addressed by SHA-256. Source records retain normalized conversations and cumulative message versions with origin hashes and observation times. Empty nodes and all branch parents/children are preserved; rendered messages follow mapping insertion order, not a claim that every branch was a single chronological conversation. Missing messages in later exports are retained. Original bytes preserve unsupported metadata and attachments.

Source records and import journals are durable state, not disposable indices. SQLite is derived from them and can be rebuilt transactionally. Markdown transcript edits are independent human content and never copied back into original messages. Message search indexes archived source messages, **not user annotations on transcripts**; card search separately indexes canonical card titles/bodies. Message citation results therefore expose both source-file provenance and an optional transcript location. Deleted notes remain absent even after reimport; source results can still be found with a null note location.

Knowledge cards are canonical editable Markdown with safe YAML front matter: stable UUID, `type` (`idea`, `decision`, `information`, `open_question`), `status` (`draft`, `reviewed`, `archived`), timestamps, origin/generator/reviewer distinctions, tags and a list of source/conversation/message/**version** references. Source-excerpt cards remain draft, including assistant proposals. References preserve the selected version through later imports; `card show` returns its text, author role, provenance and original-export location. Cards have an independent FTS index, and are never regenerated when deleted or moved.

PyYAML 6.0.3 is pinned to support Obsidian's block-YAML property edits as well as existing JSON-style YAML. The loader is safe, rejects duplicate/non-string keys and explicit YAML tags/anchors/aliases, and bounds cards to 1 MiB and headers to 64 KiB. Unknown extra metadata must be JSON-compatible. Preserve `matlas_kind`, `id` and required metadata; invalid/duplicate managed cards stop a rebuild and roll back the index rather than being silently skipped. `Cards/` is reserved for managed cards; ordinary Markdown can live elsewhere. Card queries refresh the index to discover external edits, movement and deletion. `stats` describes the last indexed state.

## Migration 1

`PRAGMA user_version=1`, transactional DDL in `Library.connect`:

- `conversations`: ID, title, creation/update time, optional note path, source record path.
- `messages`: composite conversation/message ID, mapping node, parent, role, timestamp, text, version.
- `message_versions`: composite conversation/message/version key and source payload.
- `message_fts`: FTS5 with Unicode tokenization and accent-insensitive matching.
- `import_batches`: journal ID, export hash, timestamp, status and aggregate counters.

Foreign keys, composite keys and date index are created explicitly. Newer index versions are rejected; subsequent versions need explicit migrations. Batch journals are outside SQLite so rebuilding keeps operational records.

## Migration 2

Transactional migration from version 1 adds `cards` (UUID, title, type/status, dates, path, hash, metadata and body), `card_fts` (title/body), and card-filter index; `user_version=2`. Existing source messages are retained. Knowledge-card search supports type, status, tags, UTC creation-date filters and pagination.

## Migration 3 and durable tag catalog

Migration 2→3 adds derived `tags` and `tag_assignments` tables plus assignment filters, retaining previous messages/cards. Foreign keys enforce tag IDs and hierarchy references, deferred during full rebuild. `user_version=3` is current. `tags.json`, outside SQLite in the private instance, stores the canonical approved/proposed/rejected vocabulary, stable IDs, hierarchy, aliases, merge redirects, literal rules, reviewed assignments, rejection blocks, pending/outdated proposals, card-tag snapshots and audit. It is durable operational state and is included in backups. An index deletion never deletes approvals or human blocks. Invalid catalogs fail closed with static errors.

Tag names use NFKC and casefold, spaces become hyphens, slashes suggest hierarchy at creation, and accents are preserved. Canonical and alias collisions are rejected. An explicitly created child needs an approved parent. Approved hierarchy is stored by parent UUID. Merging redirects the source ID to the destination, reparents children, preserves old names/aliases and source/card references, and rejects cycles. Child slugs remain stable historical identifiers; the displayed tree follows parent UUIDs, not a rewritten lexical prefix. Merges never rewrite human Markdown. Sensitivity is inherited from parents and propagated on merge; sensitive rule targets require explicit opt-in.

Existing card `tags` remain canonical editable metadata. Known aliases/slugs are interpreted using the approved catalog. Unknown freeform tags are preserved verbatim and never silently approved. Rebuild compares canonical tag lists with previous snapshots: external additions/changes become protected manual assignments; removals become durable human blocks. CLI card tag changes require a current hash and preserve stale proposals. Message/conversation tags are operational state in the catalog; a conversation tag applies to its source messages when filtering. Searches understand aliases and descendants; literal freeform card-tag filtering remains available for compatibility.

Rules use user-configured literal terms with Unicode/case normalization and word boundaries, never executable patterns or AI. Classification only suggests approved tags, does not create vocabulary or edit notes, and prints aggregate counters. Suggestions are idempotent for a target/tag/evidence hash. Approval checks the observed evidence and, for a card, its current hash; it writes an assignment with rule provenance. Rejections and removals block future suggestions until an explicit manual reassignment. Changed/deleted targets or removed rules make proposals outdated. Approved/manual assignments are retained during reimport and reindexing. `import --suggest-tags` opts into the same local proposal generation.

Classification is transparent literal matching, not semantic reasoning or a claim about the author's beliefs. It currently scans targets/rules synchronously and is intended for prototype-sized libraries. The catalog is bounded to 64 MiB, each section to 100,000 records, hierarchy depth to 32 and each rule to 50 literal terms; larger libraries need the later performance/distribution work. Raw source message contents never enter classification logs or the rule audit.

## Card updates and proposal resolution

CLI updates require `--expect-hash` from `card show/list`. A stale expectation keeps the current file and a separate proposed version. Successful replacements save preceding bytes in `card_versions`. Changing a reviewed claim through the CLI returns it to draft unless explicitly reviewed again with reviewer identity. External Obsidian edits are canonical; users must maintain their review properties and timestamps when editing directly.

`conflicts list/show/resolve` supports keeping the current note or applying a proposal with its current hash. Applying saves the preceding bytes in `resolved_versions` and records a durable resolution audit; historical proposals remain in the backup. Outdated transcript proposals cannot replace a more recent source version. Applying to a deleted note is refused; keeping a proposal respects the deletion. Decision succession uses stable UUID references and rejects cycles. External deletion of a successor leaves its UUID reference in the older card rather than recreating it.

Hashes are optimistic checks against intervening editor saves, not a transaction across unrelated programs. Close the external editor while applying CLI replacements or restoring. A small race between the final check and an unrelated editor's write remains; multi-device live editing is outside this prototype's scope.

## Complete backup and restore

A stored ZIP backup contains all regular vault files (including Obsidian settings), configuration, originals, normalized sources/message versions, import journals, pending/resolved proposals, preceding note versions and unknown future operational files. SQLite, its journal/WAL/SHM, writer lock and incomplete internal writes are omitted; the index is rebuilt. A manifest records sizes and SHA-256 checksums. Original filename hashes are checked, and referenced originals must exist. The writer lock plus before/after inventories detects external saves during capture; close Obsidian before backup for a stable snapshot.

Backups must be outside Git, the instance and the vault, and never replace an existing filename. Publication uses a filesystem hard link to publish the completed archive without overwrite; choose a local filesystem supporting hard links (NTFS on Windows). Backup is unencrypted and may contain personal files/configuration; it belongs in the user's private storage. Checksums detect damage, not authenticity against a deliberately modified archive.

Restore requires two new/empty nonoverlapping directories outside Git. It validates a bounded manifest, paths, case-insensitive collisions, ZIP entries and hashes, stages all files, validates original provenance and canonical cards, and rebuilds the index before publication. It then rewrites the vault path, allocates an independent instance UUID recording the previous identity, and rebinds indexed paths in the final location. User-visible Markdown bytes and IDs remain unchanged. Existing data is never replaced. Publication across two directories is not a single filesystem transaction; an interruption can leave a populated new vault with an incomplete instance. Keep those target files and the original backup and retry into fresh destinations. Portable reindexing does not rewrite absolute paths embedded by a user in note bodies or third-party Obsidian configuration.

Backup bounds: 100,000 files, 1 GiB per file, 8 GiB total, 16 MiB manifest. Only stored/deflated entries and portable filenames are accepted on restore; path traversal, symlinks, encrypted entries, unsupported compression, collisions and unlisted files are rejected. Empty subdirectories are not preserved. Deletions remain absent after restore/reimport. Full round-trip is covered by synthetic tests in a different location.

## Interruption and conflicts

A single OS-owned writer lock prevents simultaneous writers and releases on process termination. Files use temporary writes, flush/fsync and replacement. Per-conversation source checkpoints precede index rebuilding; retry or rebuild repairs an interrupted index update. Original exports remain available to retry parsing. The transcript/source pair is not a multi-file atomic transaction: if interrupted after writing a transcript, retry recognizes its ID/hash and resumes without replacing human edits. Import statuses include running, interrupted, partial and completed.

Before replacing an unedited generated transcript, its preceding bytes are saved outside the vault. A note with a human edit is never replaced; a changed source produces a separate proposal. Duplicate canonical conversation IDs in vault notes block import/rebuild until resolved. Renaming a note is detected via its front matter. Preserve `matlas_kind` and `conversation_id` for tracking.

## Bounded input and current limitations

64 MiB input/JSON, 512 MiB total declared ZIP contents, 10,000 ZIP entries/conversations, 100,000 nodes per conversation, ZIP ratio <=200. ZIP entries are never extracted; absolute paths, traversal, encrypted entries and symlinks are rejected. Exactly one `conversations.json` is required. Limits can reject large legitimate exports; streaming import is future work. Unsupported/non-text parts warn and remain in original bytes. Malformed conversations are counted and skipped, while invalid outer JSON/ZIP aborts parsing.

The index rebuilds fully after each import and before card/tag queries; suited to validating the prototype, not yet optimized for large libraries. Source records accumulate versions; space quotas and archival policies are pending. Do not synchronize a live SQLite file. This prototype has no Obsidian plugin, MCP, semantic search, graph, automatic account sync, installer or chosen distribution license. All are tracked in the roadmap. The owner's ten real evaluation questions remain pending; synthetic verification does not establish usefulness for every real export format.
