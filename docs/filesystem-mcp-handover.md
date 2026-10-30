# Filesystem MCP — 2026-10-30

Objective: add the official filesystem MCP for basic personal use. User authorized adding it; earlier recommendations are not instructions to install other MCPs. Scope: dedicated local folder, five read/search/list tools, no model changes or broad disk access. Lead: root.

Current state: implemented in local worktree `heretic-filesystem`, branch `feature/filesystem-mcp`. Remote base is `c8c6889fa7efba65d7764d21371452821ab04510`; original gateway source matched main blob `92c8b9ffb8ddffb86d7c59bc0543b9538e2b0a9d`. The local repository remains a partial snapshot with different commit IDs. Remote delivery branch `feature/filesystem-mcp-20261030` created; source publication follows. No merge or installation yet.

Ownership: filesystem_gateway_review agent owns gateway app.py and tests; filesystem_installer owns Install-Filesystem.ps1 and Open-Heretic.ps1. Root owns manifests, configuration, smoke checks, documentation and publication. No shared file writers.

Decisions: pin official server 2.1.0 (Node >=24); default folder `C:\Users\PC\.heretic\files`, outside Git/OneDrive. Gateway enforces a five-tool allowlist and marks filesystem reads private so subsequent external requests use existing approval. Expose no write, move, delete, media or bulk-read tools. Memory-off must not bypass privacy after reading files.

Access: Desktop Commander lists only offline Y-Lap. Bounded request to `http://desktop-7ov7vat:8080/health` returned HTTP 503 upstream connection termination. No managed environment status tool or network-policy snapshot is available. Tailscale configuration is not proof of runtime access. Do not report deployed/installed.

Validation: `uv run --project gateway --frozen pytest gateway/tests/test_gateway.py -q -k filesystem` => 3 passed,39 deselected (0.98s), preexisting Starlette/httpx warning. One real Node24.22.1 / official2.1.0 stdio smoke negotiated MCP2024-11-05, found all five read tools, read a temporary text file, and blocked reading outside the configured directory. `git diff --check` passed. User requested faster delivery/no unnecessary tests; no broad suite was run. PowerShell and real Windows/llama-prism/phone behavior are unverified.

Completed: pinned manifest+lockfile, scoped runtime config, gateway read allowlist/private-context handling, Windows installer with backup/rollback, conditional startup checks, and docs/filesystem-mcp.md. Both agents finished their owned changes; root reviewed integration. No active writer locks remain after publication.

Next: push reviewable branch/PR, then install on desktop when execution access is available. Follow docs/filesystem-mcp.md for install/rollback; preserve newer local source before replacement. Installer backs up runtime files and leaves personal files intact. Do not claim this is running on the PC. Prior document/memory merges are included when installer copies current gateway source.

Publication checkpoint — supersedes pending publication above:
- Source pushed and verified byte-for-byte in draft PR #6: https://github.com/Yazeed-Alotaibi/heretic-local/pull/6
- Tested source commit: `f366f7467c07303bedeeab734198b9945229a9c2`; all nine published files match the reviewed local files. Only this documentation checkpoint follows validation.
- State: implemented, focused tests passed, pushed; NOT merged and NOT installed. Main remains `c8c6889fa7efba65d7764d21371452821ab04510` at publication.
- Next: merge the reviewable PR, then run the installer on the desktop once remote execution access is restored (or locally on the PC). No live access or Node version on the PC has been verified.
- Agent tasks are complete; no active resource locks. Root owns handoff. Local fetched README/web-tools/other launcher snapshots were reference material and are not included in this PR.

Latest checkpoint — user-authorized merge:
PR #6 was merged into main and read back as merged/closed. Merge commit:
`a426b7ca0d69c2171271c44e2eff84ebb2f1563f`.
No source changes or new tests were needed for merge. Validation above remains applicable.
State: implemented, tested, pushed and merged; NOT installed on the PC.
Next: restore desktop execution access, compare installed source and run
`runtime/Install-Filesystem.ps1` as described in `docs/filesystem-mcp.md`.
