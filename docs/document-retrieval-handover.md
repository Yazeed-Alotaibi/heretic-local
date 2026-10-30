# Document retrieval handover — 2026-10-30

Objective: fix reading/searching long documents in Heretic. User selected these
changes from the reviewed optimization proposal. Lead: Codex; no other writers.
Base main commit: 69676f6209c88dddd14be0f60e7dc5f5fd617bdb.
Delivery branch: feature/document-retrieval-20261030; draft PR against main.

Implemented:
- Search returns document ID, zero-based chunk_index, source, section and PDF page.
- knowledge_read accepts start_chunk and max_chunks (1–20, default 1 in the tool).
  Reads can reach any chunk, including beyond the previous 20-chunk store limit.
  next_chunk and total_chunks support continuation. truncated means a partial document.
- SQLite FTS5/BM25 ranks normalized Arabic/English passages. The index is in memory
  and rebuilt at startup/reload/import/delete; canonical files remain unchanged.
- New imports prefer paragraph/line/word boundaries near 2,000 characters.
  Fixed-cut fallback retains the existing 3,000-chunk cap on large documents.
  No overlapping text, schema migration, embeddings, OCR or dependency changes.
- Injected document references retain chunk indexes so the model can expand hits.
- Search drops lowest-ranked hits if necessary to fit the remaining 4,096-token
  shared budget. If even one hit cannot fit, the existing budget error remains.

Verification: frozen Python 3.12 environment; command
`uv run --project gateway --frozen pytest gateway/tests -q` => 77 passed, 1 skipped
(Windows JobObject test), 1 preexisting Starlette/httpx deprecation warning.
Baseline: 63 passed, 1 skipped. New regressions were observed failing before fixes.
Python compilation and git diff --check passed. Isolated Ruff check retains the
same two preexisting TRY004 warnings as the baseline; no clean-lint claim.
Independent source review found a dropped-query-term regression and the preexisting
all-or-nothing search-budget issue. Both have RED→GREEN coverage in the final suite.

Limits: only the complete gateway suite was run, using the real local knowledge
store and a simulated model transport. Live Windows/model/phone behavior and the
unchanged frontend/media/backend suites were not run. No speedup or answer-quality
gain on the user's documents has been measured. Full-index rebuild on writes
trades import/delete cost for simple atomic reload behavior; future tuning can
use a larger real corpus. Existing preference-budget behavior is outside this scope.

State: implemented, locally tested, pushed and verified in draft PR #4:
https://github.com/Yazeed-Alotaibi/heretic-local/pull/4
Published source commit: 6e2815a685941bae86b0ab0d3fdf1bf1f0debb0a.
The four published Python/test files were read back and exactly matched the tested files.
No merge or live installation performed.
Local workspace is an isolated gateway-only Git snapshot, not a full clone. Remote
publication uses the full original tree and changes only the listed Python/test/docs
files. Main, UI, launchers, model weights and personal documents are preserved.

Next action: review the draft PR, then install on the desktop when access is available.
Before installation compare installed files with the base and preserve newer edits.
For this gateway-only change, stop owned services with the installed Stop-Heretic.ps1,
back up installed gateway/heretic_gateway/app.py and knowledge.py, then copy the two
reviewed files into that same package under ternary-bonsai-runtime/gateway. No pip/npm
update is needed. Start with Open-Heretic.ps1 and refresh the browser to discover the
new tool schema. Verify health, import a disposable long text, search a phrase near
its end, read the returned chunk, and confirm a project-private document is isolated.
Rollback: stop owned services, restore the two backed-up Python files, and reopen.
Schema-v1 documents and original files need no rollback or migration.
