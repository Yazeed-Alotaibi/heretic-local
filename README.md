# Heretic local setup

Private recovery repository for the Windows PC's GPU model, 65,536-token context,
eight existing MCP tools, five local memory/knowledge tools, private Tailscale phone access,
and video downloads.

This is a source/configuration backup. It does not automatically synchronize the
running installation. It contains no model weights, installed binaries, videos,
browser conversations, runtime logs, API keys, or account credentials.
Image generation is not configured.

## Layout

- `runtime/`: model/file-server launchers, MCP configuration, video tool and tests.
- `gateway/`: single-process Python gateway, canonical local memory, document imports and tests.
- `ui/`: vendored Svelte interface from upstream llama.cpp commit
  `2459f68b5c0eb26261fd5a81682004b93cd645ba`, its license and local integration.
- `agent-reach/`: custom reading backend, tests, Python dependency lock and MCP configuration.
- `web-tools/` and `node-tools/`: pinned Node dependency manifests and lockfiles.
- `tailscale-serve.json`: the existing private chat and file proxy routes.

The configuration records paths and the private tailnet hostname for this PC.
Its MCP PATH contains only the required executable folders instead of the full
session environment. Existing installed files were not changed by making this
repository.

## Launch the model

These steps are for the installed setup on the Windows PC. Heretic also starts
hidden at every Windows sign-in, so usually only step 4 is needed.

1. Sign in to Windows on the PC. For phone access, make sure Tailscale is connected.
2. Double-click the desktop **Heretic** shortcut, or run the launcher from PowerShell:

   ```powershell
   cd 'C:\Users\PC\OneDrive\Documents\ChatGPT\chats with no projects\ternary-bonsai-runtime'
   .\Open-Heretic.ps1
   ```

   If script execution is disabled, run
   `powershell -NoProfile -ExecutionPolicy Bypass -File .\Open-Heretic.ps1` instead.
   Add `-NoBrowser` to skip opening the page.
3. Wait up to two minutes while the model loads onto the GPU. The launcher checks
   the gateway, model, 64k context, all thirteen tools and the file server. It
   reuses an instance that is already running.
4. Open `http://desktop-7ov7vat.tail4c4266.ts.net:8080/` on the PC or the phone.
   If the page reports the model as loading, wait and refresh.
5. If you use memory, select a project before the first message.

If something goes wrong:

- Read `startup-status.log` in the runtime folder. It shows `READY` or the error.
- `is not recognized as the name of a cmdlet`: PowerShell is in another folder,
  such as `C:\Users\PC`. Run the `cd` command from step 2 first.
- To restart owned components cleanly, run the following from the runtime folder:

  ```powershell
  cd 'C:\Users\PC\OneDrive\Documents\ChatGPT\chats with no projects\ternary-bonsai-runtime'
  .\Stop-Heretic.ps1
  .\Open-Heretic.ps1
  ```
- "Port 8080/8081 is already in use" or "A different model is running": another
  program, such as LM Studio's server, holds the port or has a model loaded. Stop
  it yourself and launch again. The launchers never stop processes they do not own.

To stop Heretic, run `.\Stop-Heretic.ps1` after the `cd` command from step 2.

## Restore on the same PC

Keep or recover the model and runtime binaries separately. The configured model is:

`C:/Users/PC/.lmstudio/models/OS-Software/Ternary-Bonsai-2-27B-Uncensored-Heretic-GGUF/Ternary-Bonsai-2-27B-Uncensored-Heretic-PQ2_0.gguf`

The runtime uses llama-prism build `b10754-2459f68b5`, CUDA 13.3, and FFmpeg 9.0.
`runtime/release-assets.json` records the downloaded runtime archive sizes and
SHA-256 digests. These large assets are not in Git.

1. Compare the backup with the installed files before replacing anything. Preserve
   newer local changes and stop the intended model only when replacement requires it.
2. Restore `runtime/` files into:
   `C:/Users/PC/OneDrive/Documents/ChatGPT/chats with no projects/ternary-bonsai-runtime`.
   Keep the existing `bin/` folder and `media-files/` downloads.
3. Restore `agent-reach/` files into `C:/Users/PC/.agent-reach/heretic-backend`.
   Restore `web-tools/` manifests into the runtime's `web-tools/` folder and
   `node-tools/` manifests into the backend's `node-tools/` folder.
4. If dependencies need rebuilding, use Python 3.12 and the committed lockfiles:

   ```powershell
   uv sync --project 'C:\Users\PC\.agent-reach\heretic-backend' --frozen --python 3.12 --link-mode copy
   npm ci --prefix 'C:\Users\PC\OneDrive\Documents\ChatGPT\chats with no projects\ternary-bonsai-runtime\web-tools'
   npm ci --prefix 'C:\Users\PC\.agent-reach\heretic-backend\node-tools'
   ```

5. Keep Tailscale signed in on the PC and phone. The current Serve configuration
   already persists. If its two routes are missing, restore just those routes:

   ```powershell
   tailscale serve --bg --http=8080 http://127.0.0.1:8080
   tailscale serve --bg --http=8080 --set-path=/files http://127.0.0.1:8082
   ```

6. Build the interface with `npm ci` and `npm run build` inside `ui`, then run
   `runtime/Install-Gateway.ps1` from the repository. It installs the frozen gateway
   environment and static interface, preserving a rollback copy of the launchers.
   Stop the identified old model before starting the new gateway; do not kill by port.
7. Run the installed `Open-Heretic.ps1`, or use the existing desktop **Heretic**
   shortcut. It checks the gateway, model, context, all thirteen tools, and file server.
   Existing user-login startup points to this same script with `-NoBrowser`.

On a different PC, adjust the model, executable, MCP, and shortcut paths and
tailnet hostname first. The installer targets the existing saved installation on this PC.

## Memory and knowledge

All three HTTP services run on this PC. The phone continues using the same Tailscale
URL on port 8080. The gateway serves the interface and memory controls on 8080, the
GPU engine listens only on loopback 8081, and validated video files remain on 8082.
Do not add a Tailscale Serve route for 8081.

Use the Memory button or `#/memory` to manage records, projects and documents.
`Remember: <exact fact>` saves that text explicitly; ordinary suggestions require
review and Save. Corrections require the displayed revision. Forget removes a record,
its derived checkpoints, retrieval data and active execution capabilities. Existing
browser messages, source documents and manual exports are separate copies.

Memory is on by default. Select a project before the first message; changing projects
requires a new chat. A fresh chat with memory off uses no local recall. Turning recall
off in an existing private conversation preserves external-request approval checks.
The review dialog shows the exact tool arguments; each invocation gets its own approval.
Proposals and pending approvals expire after 15 minutes. Execution capabilities expire
after 30 minutes of inactivity. Restart invalidates all three. Successful save retry
receipts last 24 hours; project bindings and privacy state persist.

Personal data is stored under `C:\Users\PC\.heretic\data`, outside this repository and
OneDrive. Facts/preferences are JSON; notes/checkpoints are Markdown. The search index
is rebuildable SQLite FTS5. Manual file changes become active at startup or Reload files.
Invalid changes produce a visible error and preserve the working retrieval snapshot.
Manual export writes a local ZIP in that data directory's `exports` folder; it excludes
session tokens, approvals, operational state and logs. Nothing automatically pushes
personal memory to GitHub.

Knowledge accepts UTF-8 text, Markdown and searchable PDFs. Limits: 25 MiB, 500 PDF
pages, 60 seconds, 512 MiB PDF-worker memory and 5 million extracted characters.
Arabic and English retrieval is lexical; OCR and cross-language semantic search are
not included. Original documents and source/page references are retained. Current
instructions override remembered preferences; injected context is bounded to 4,096
tokens counted with the model tokenizer.

The browser owns tool rounds. The gateway modifies requests and preserves model SSE
bytes for reconnects. Browser-direct MCP, custom tools and remote media loads are
disabled so external requests use the gateway's approval checks. Local Windows
processes are trusted in this single-user setup.

Gateway checks: `uv run --project gateway --frozen pytest gateway/tests -q`.
UI checks: `npm run check` and `npm run test:unit -- --run tests/unit/heretic.spec.ts`
inside `ui`. Startup checks: `powershell -File runtime/Test-SavedStartup.ps1`.

## Verification

The three-server upgrade was installed and verified on 2026-10-04. Gateway, GPU
model and file service report ready through both loopback and the unchanged
Tailscale URL. The live model reports 65,536 context tokens; all thirteen tools
are present. Port 8081 is loopback-only and is not forwarded by Tailscale Serve.
Existing videos passed HEAD and partial-content delivery through `/files`.

The memory/knowledge gateway, targeted UI tests, typecheck and production build
passed. A real Chrome workflow covered save, correction, document import/read,
export, GPU recall, conversation persistence across reload, exact external-tool
approval/denial, and forgetting without page errors. Startup fixtures passed on
Windows PowerShell 5.1 and PowerShell 7.6.5, and reopening reused the live process
identities. Details and limitations are recorded in `IMPLEMENTATION.md`.

The saved installation passed 23 media tests and backend tests, independent
review, direct MP4 and YouTube downloads, a model/tool round trip, private file
delivery, and Windows PowerShell 5.1 startup/concurrent-launch checks.
An actual Windows reboot was not performed.

Run backend tests using its restored environment. For the media tests:

```powershell
uv run --project 'C:\Users\PC\.agent-reach\heretic-backend' --no-sync pytest -q .\runtime\test_media_tools.py
```

Future backups should copy only changed source/configuration files, review the
diff for private data and credentials, then commit and push explicitly. Downloaded
files and chat history remain local. Do not add third-party model or runtime
binaries to this repository.
