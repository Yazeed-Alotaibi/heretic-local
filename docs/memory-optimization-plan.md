# Memory allocation and preparation — 2026-10-30

User authorized priorities 1 and 2 together with parallel subagents, then requested
less testing to reduce time. Use narrow behavioral checks and one final gateway suite;
avoid repeated broad runs and multi-stage reviews. Lead/root owns app.py integration.
Remote base: aa7473ad1b807e9072d3f3345fac8eceb463f79d. Local isolated gateway snapshot
branch: feature/memory-budget-latency. No live PC access; previous update merged but
installation pending. This task prepares a new reviewable branch/PR.

Policy choices (builder decisions): retain 4096 total tokens, reserve 1536 initially
for tools (snapshot at most2560), preference allocation at most512 measured as the
rendered preference block's token increase over empty policy framing. Up to4
preferences selected by query relevance, project scope, then recency. Round-robin
document/memory evidence so neither class occupies all shortlist positions.

Interfaces and ownership:
- Agent selection owns memory_selection.py and test_memory_selection.py.
  select_candidates(preferences, memories, documents, query, scope) returns
  (ranked_preferences, ranked_evidence); original record dictionaries returned.
- Agent builder owns context_builder.py and test_context_builder.py.
  async build_context(preferences, evidence, policy, count, *, snapshot_budget=2560,
  preference_budget=512) returns (blocks, records, exact_cost). count(blocks) is an
  async callback supplied by app; it renders/counts with model and checks revocation.
  Use local length estimates only for preselection, then exact verification of
  preference allocation and final blocks; batch trim lower-priority records if over.
  Avoid per-candidate engine calls, no shared cross-turn cache or saved authority.
- Root owns app.py, integration checks and handover. Preserve execution lock,
  current() checks, project isolation, snapshot reuse, privacy marking and4096 cap.
  Apply existing ranked-hit shrinking to memory_search as well as knowledge_search.

Acceptance: relevant docs survive many preferences; follow-up tool budget remains;
first snapshot uses fewer engine calls as preferences grow; exact tokenizer can
override estimates; memory-off and revoked execution cannot publish private context.
Run targeted module checks, inspect integration, then gateway suite once at completion.
One independent combined review; no changes to GPU/runtime settings or user data.

Completion checkpoint:
- Both isolated module tasks completed by parallel subagents; root integrated app.py.
- Two focused checks per helper, two gateway behavioral scenarios. The gateway regressions
  reproduced the old failure before integration. One final complete gateway run:
  `uv run --project gateway --frozen pytest gateway/tests -q` =>83 passed,1 skipped
  (Windows JobObject),1 preexisting Starlette/httpx warning;3.69seconds. Diff check passed.
- Independent combined review found no new correctness/privacy blockers.
- Delivery branch: feature/memory-budget-latency-20261030, based on main aa7473a.
  Changes prepared for a draft PR; no merge or installation performed for this task.
  Remote Git/PR state is authoritative for publication; local repository is a gateway
  snapshot and has different commit IDs from the full remote repository.
- Existing limitation: store.search can fill its eight hits with preferences before
  the selector filters them, so some matching facts may need explicit memory_search.
  This was not expanded into a separate Store search redesign in this pass.
- The 1536-token reserve is initial headroom, not a guarantee every large result fits.
  Local size estimates can omit records that the real tokenizer might fit; exact final
  counts prevent overflow. No cross-turn cache or stale private-memory cache is added.
- Speed validation is structural (at most3 render/count pairs in the typical integration
  fixture, rather than one pair per candidate). No actual GPU latency or answer-quality
  gains are claimed; those require a running desktop and representative user documents.

Next action: review the draft PR and authorize merge for these new changes. Desktop
installation of the earlier document patch remains authorized but blocked on a working
remote execution connection. Only offline source tests were possible in this session.
When deploying the combined upgrades, compare installed files against their base and
back up existing files first. Stop owned services, copy app.py, context_builder.py and
memory_selection.py into installed gateway/heretic_gateway; include the already-merged
knowledge.py from PR4 if not yet installed. No dependency/UI/model change is required.
Restart with Open-Heretic.ps1, refresh browser, test recall and a follow-up tool read.
Rollback by restoring the previous app.py and any other replaced files while stopped.
