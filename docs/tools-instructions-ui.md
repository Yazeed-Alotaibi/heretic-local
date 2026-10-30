# Tools, instructions, settings and Tools panel — 2026-10-31

Branch: `feature/tools-instructions-ui`. State: implemented and tested in a cloud
workspace; NOT merged and NOT installed on the PC. GitHub changes do not reach the
running PC until the steps below are run there.

## What changed

- **Default instructions** (`gateway/heretic_gateway/app.py`, `INSTRUCTIONS`): the
  gateway prepends them to every chat completion, merged into the first system
  message so templates still see one leading system message. Heretic calls itself
  Heretic, replies in the user's language, is short by default, and must not claim
  tools that the request did not provide. Users can still add their own system
  message in the UI; it follows these instructions.
- **Gated file writes**: `filesystem_write_file`, `filesystem_edit_file` and
  `filesystem_create_directory` are advertised. Each call needs a per-invocation
  approval, even with no private context. Moves, bulk reads and unknown filesystem
  tools stay blocked. See `docs/filesystem-mcp.md`.
- **Online MCP servers**: Context7 (`context7_*`, library docs) and Hugging Face
  (`huggingface_*`, anonymous Hub search) through the existing pinned `mcp-remote`.
  Both worked anonymously on 2026-10-31 (Context7: `resolve-library-id`,
  `query-docs`; Hugging Face: `hf_fs`, `hf_whoami`, `hub_repo_search`,
  `hub_repo_details`). Hugging Face image generation/Spaces need a signed-in HF token
  and are NOT configured. Online tools use the existing private-context approval.
  `Open-Heretic.ps1` reports a missing online server as a WARNING in
  `startup-status.log` instead of failing startup.
- **Model settings** (`Start-Heretic.ps1`): `--temp 0.7 --top-p 0.9` as server
  defaults; the UI reads them from `/props`. Reply length was already unlimited
  (`max_tokens` unset → -1); only the 64k context bounds it, so nothing changed there.
- **Tools panel** (`ui/src/lib/components/HereticTools.svelte`): a "Tools" button
  under "Memory" lists `/tools` grouped by server with on-PC/online/asks-approval
  badges.

## Install on the PC (when someone can run commands there)

```powershell
$runtime = 'C:\Users\PC\OneDrive\Documents\ChatGPT\chats with no projects\ternary-bonsai-runtime'
git fetch; git checkout feature/tools-instructions-ui   # or main after merging
cd ui; npm ci; npm run build; cd ..
& "$runtime\Stop-Heretic.ps1"
.\runtime\Install-Gateway.ps1 -RuntimePath $runtime          # gateway, UI, launchers
.\runtime\Install-RemoteTools.ps1 -RuntimePath $runtime      # Context7 + Hugging Face
# Optional, only if the filesystem MCP is not installed yet (needs Node 24+):
# .\runtime\Install-Filesystem.ps1 -RuntimePath $runtime
& "$runtime\Open-Heretic.ps1"
```

Rollback: `Install-Gateway.ps1 -RollbackBackup <saved-setup\gateway-…>` and copy
`saved-setup\remote-tools-…\heretic.mcp.json` back while Heretic is stopped.

## Verification

- `uv run --frozen pytest -q` (gateway): 90 passed, 1 skipped. New tests cover
  per-call write approval, denial, single dispatch, and instruction merging.
  Ruff findings are unchanged from main (pre-existing).
- UI: `svelte-check` 0 errors; `vite build` succeeded; Playwright screenshots of
  the Tools panel at 1280px and 390px against the real gateway and a stub engine,
  with no page errors.
- Not verified: PowerShell scripts on Windows, the real llama-prism tool names for
  the new servers, and live model behavior with the new instructions.
