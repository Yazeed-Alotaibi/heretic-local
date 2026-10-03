# Heretic three-server upgrade

Approved scope: gateway/UI 8080, unchanged GPU engine at 8081 (65,536 context), existing files 8082. Preserve HTTP Tailscale origin and browser IndexedDB. Browser owns tool loop; gateway transforms requests and passes streaming bytes unchanged. All external tools require invocation-specific approval once a conversation has used private context. Fresh memory-off chats skip recall; historical privacy is sticky.

Canonical local memory and knowledge live under C:\Users\PC\.heretic\data, outside OneDrive/Git. Explicit saves, revisioned corrections, forget, project scope, manual export, conservative Arabic/English lexical retrieval, 4,096-token injected context using model tokenizer. Imports: UTF8 text/Markdown/searchable PDF; 25MiB,500pages,60s,512MiB Windows JobObject,5Mcharacters. No OCR, image generation, cloud memory, or automatic personal-data backups.

## Work ledger

- Baseline: clean repository dd2b1d1; 53 existing tests passed on 2026-10-04.
- Isolated worktree: heretic-memory-worktree, feature/memory-gateway. Native worktree tool targeted the outer chat repository and could not resolve dd2b1d1; created a Git worktree of the actual saved Heretic repository.
- Memory storage: memory_storage agent, store.py and test_store.py.
- Knowledge: knowledge_worker agent, knowledge.py/pdf_worker.py/test_knowledge.py.
- UI: ui_integration agent, ui/ and scripts/vendor-ui.ps1.
- Gateway/auth/proxy, launcher integration, documentation and overall verification: root.
- Independent code, Python, TypeScript and security reviews completed, including separate review of the final launcher, UI loading-status, and execution-timeout changes.
- The implementation was initially left uncommitted. The user subsequently authorized committing and pushing the completed changes to the private Heretic repository.

## Completed implementation and verification

- Gateway suite: 61 passed (31 storage/knowledge, 30 gateway/security), including exact invocation/generation approvals, denial attestations, stale stream rejection, Arabic retrieval, project isolation, staged reload, cascade forgetting, idempotency and active-stream inactivity expiry. One upstream Starlette TestClient deprecation warning remains.
- Existing media/backend suite: 53 passed. Existing eight tools, binaries, model weights and MCP configuration are retained.
- UI: 17 targeted tests passed; typecheck reported zero errors/warnings; production build passed. Vendored upstream UI matches GPU binary commit 2459f68b5. The original LlamaUi database and HTTP Tailscale origin are unchanged. Loading health polling is sequential and stops on readiness or unmount.
- Browser: headless Chrome with isolated temporary memory passed save, correction, document import/read, export, real GPU recall, chat history after reload, exact external approval/denial, and forget, without page errors. No screenshots or recordings were captured. Jev was unavailable (no daemon/connections), so Playwright Chrome was used.
- Startup: all six fixture groups passed on Windows PowerShell 5.1 and PowerShell 7.6.5. Coverage includes real virtualenv child processes, two-second health responses, PID reuse rejection, late child discovery, complete owned-tree cleanup, install rollback and personal-data preservation. Final timestamp comparisons preserve subsecond UTC identity under either JSON parser.
- Live installation: gateway 127.0.0.1:8080, original GPU engine 127.0.0.1:8081, existing file service 127.0.0.1:8082. Frozen gateway environment installed successfully. The launchers validate all thirteen tools and 65,536 context tokens. Cold startup and ordinary PowerShell 7 reopening passed; reopening retained exact process identities.
- Follow-up live concurrent launch passed after the permission change: it waited for the named startup mutex, completed successfully, and retained identical gateway/model ownership records. The initial sandboxed attempt could not see Windows listeners; an approved unsandboxed retry passed without replacing services.
- The previously blocked disposable test folder `C:\Users\PC\AppData\Local\Temp\heretic-startup-test-39a39a4ecb5549b2b4aa573443ed4756` was removed after verifying its exact temporary-directory boundary, absence of filesystem links, known fixture markers, and stopped test PIDs. Its absence was verified.
- Network: the existing Tailscale URL returns all services ready and serves the installed UI build. Serve routes are unchanged (8080 / to gateway, /files to 8082). Model port 8081 is not forwarded and cannot be reached through the PC's Tailscale IP. A completed video passed HEAD 200 and range 206 (16 bytes) through the existing private file URL.
- Prompt prefix check: consecutive live model turns reused 186 and 207 cached prompt tokens; injected context remained bounded. This is a prefix reuse check, not a full 64k performance or quality benchmark.
- Restart persistence: temporary memory records and conversation privacy/binding state survived gateway recreation. Proposals, approvals and execution capabilities intentionally expire on restart. No test personal records were written into the installed data directory.
- Security updates: Mermaid 11.17.2, DOMPurify 3.4.16 and devalue 5.9.4 were updated with the lockfile. npm audit still reports 18 advisories (1 low, 9 moderate, 8 high), mainly inherited build/test tooling. A broader upstream dependency migration is outside this change.

Source is maintained on feature/memory-gateway. The original saved repository is preserved. The follow-up commit and push cover source, configuration, tests and recovery instructions; personal memory, documents, downloads and runtime binaries remain outside Git.

## Installed paths and recovery

- Source: `C:\Users\PC\OneDrive\Documents\ChatGPT\chats with no projects\heretic-memory-worktree`
- Runtime: sibling `ternary-bonsai-runtime`; existing desktop and login shortcuts still open its `Open-Heretic.ps1`.
- Personal memory/documents: `C:\Users\PC\.heretic\data` (outside OneDrive and Git).
- Initial rollback backup: `ternary-bonsai-runtime\saved-setup\gateway-20261003-232918-640-86a88d91d7ea43808230b6cf51d18870`.
- To roll back: stop only owned services using installed `Stop-Heretic.ps1`, then invoke `Install-Gateway.ps1 -RollbackBackup <absolute backup path>`, then `Open-Heretic.ps1`. This restores original launchers and returns the engine to 8080 while preserving memory, documents, downloads and browser history.

The first rollout probe timed out while the model was stopped; six-second probes within bounded startup deadlines resolved it. PowerShell 7 timestamp parsing was also fixed before the successful rollout. A new test initially compared floating-point elapsed time exactly; the final passing regression uses `pytest.approx`.

## Remaining limits

- The phone itself and a full Windows reboot were not directly tested. Tailscale requests, existing shortcut targets and live startup were verified from this PC.

## Interface checks

| Producer/consumer | Contract / resolution |
| --- | --- |
| Store / gateway | Canonical record methods; separate durable conversation privacy/bindings; transient execution/approval state invalidated on restart. |
| Knowledge / gateway | Bounded import/read/search/delete methods, local originals retained. |
| UI / gateway | Session token header, execution capability, conversation/human/assistant/tool IDs; approval response 409; unchanged model SSE. |
| Gateway / engine | Loopback 8081; exact original eight tool names and JSON tool response preserved. |
| Launchers / runtime | Gateway first; reuse owned healthy processes; no kill-by-port. Preserve startup shortcuts. |

Decision: implement parallel work with explicit file ownership as the user requested; this overrides the skill's default serial implementer preference. Preserve this work ledger as the implementation and verification record.

## Verification targets

Record correctness/idempotency/reload/project scope, private-history approval isolation, TTL/restart/cancellation/forget, malicious model proposals, PDF limits and Arabic/English search, browser history/stream resume/eight existing tools/64k context, live startup and rollback preservation. Phone reachability needs actual mobile observation if unavailable through connected tools.
