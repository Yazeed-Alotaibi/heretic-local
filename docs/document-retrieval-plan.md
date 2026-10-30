# Document reading and retrieval — 2026-10-30

Authorized: implement the document-reading and retrieval improvements proposed in chat.
Base: Yazeed-Alotaibi/heretic-local main 69676f6209c88dddd14be0f60e7dc5f5fd617bdb.
Workspace: isolated gateway source snapshot; remote publication must preserve the full base tree.
Lead: Codex; no concurrent writers or resource locks.

Design: retain canonical schema-v1 JSON and original documents. Rebuild an in-memory
SQLite FTS5/BM25 index from canonical chunks; normalize Arabic and English with the
existing normalizer. Return zero-based chunk indexes in search and allow bounded
reads starting there. Prefer paragraph/word boundaries on new imports without
duplicating text. Existing imports remain readable without migration/reimport.
Builder choices: local lexical search, no new dependency or embedding service;
no overlapping chunks in this pass to preserve extraction limits and avoid duplicate context.
Scope excludes memory-budget changes, OCR, GPU tuning, and live installation.

Acceptance: later-document search/read roundtrip; references and project isolation;
correct continuation and parameter validation; Arabic normalization; relevance
ranking; reload/delete consistency and malformed-reload preservation; full gateway suite.

Plan:
- [x] Establish baseline with frozen Python 3.12 dependencies.
- [x] Add regressions for chunk reads, search ranking, indexing lifecycle, chunk boundaries,
      and real gateway tool dispatch. Watch them fail before implementation.
- [x] Implement index and chunk addressing; update tool schema and injected references.
- [x] Run full gateway tests and review diff; record platform limitations.
- [ ] Publish a feature branch and draft PR; verify published content. Do not merge/deploy.

Status: implementation and independent review complete; 77 tests passed, 1 Windows-only
test skipped. Publication is the next action; handover records final scope and limits.
No changes to the running PC. Desktop connection unavailable; user can open the UI via Tailscale.
