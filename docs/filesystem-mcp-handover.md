# Filesystem MCP — 2026-10-30

Objective: add the official filesystem MCP for basic personal use. User authorized adding it; earlier recommendations are not instructions to install other MCPs. Scope: dedicated local folder, five read/search/list tools, no model changes or broad disk access. Lead: root.

Current state: implemented in local worktree `heretic-filesystem`, branch `feature/filesystem-mcp`. Remote base is `c8c6889fa7efba65d7764d21371452821ab04510`; original gateway source matched main blob `92c8b9ffb8ddffb86d7c59bc0543b9538e2b0a9d`. The local repository remains a partial snapshot with different commit IDs. Remote delivery branch `feature/filesystem-mcp-20261030` created; source publication follows. No merge or installation yet.

Ownership: filesystem_gateway_review agent owns gateway app.py and tests; filesystem_installer owns Install-Filesystem.ps1 and Open-Heretic.ps1. Root owns manifests, configuration, smoke checks, documentation and publication. No shared file writers.

Decisions: pin official server 2.1.0 (Node >=24); default folder `C:\Users\PC\.heretic\files`, outside Git/OneDrive. Gateway enforces a five-tool allowlist and marks filesystem reads private so subsequent external requests use existing approval. Expose no write, move, delete, media or bulk-read tools. Memory-off must not bypass privacy after reading files.

Access: Desktop Commander lists only offline Y-Lap. Bounded request to `http://desktop-7ov7vat:8080/health` returned HTTP 503 upstream connection termination. No managed environment status tool or network-policy snapshot is available. Tailscale configuration is not proof of runtime access. Do not report deployed/installed.

Validation: `uv run --project gateway --frozen pytest gateway/tests/test_gateway.py -q -k filesystem` => 3 passed,39 deselected (0.98s), preexisting Starlette/httpx warning. One real Node24.22.1 / official2.1.0 stdio smoke negotiated MCP2024-11-05, found all five read tools, read a temporary text file, and blocked reading outside the configured directory. `git diff --check` passed. User requested faster delivery/no unnecessary tests; no broad suite was run. PowerShell and real Windows/llama-prism/phone behavior are unverified.

Completed: pinned manifest+lockfile, scoped runtime config, gateway read allowlist/private-context handling, Windows installer with backup/rollback, conditional startup checks, and docs/filesystem-mcp.md. Both agents finished their owned changes; root reviewed integration. No active writer locks remain after publication.

Next: push reviewable branch/PR, then install on desktop when execution access is available. Follow docs/filesystem-mcp.md for install/rollback; preserve newer local source before replacement. Installer backs up runtime files and leaves personal files intact. Do not claim this is running on the PC. Prior document/memory merges are included when installer copies current gateway source.
