# Heretic local setup

Private recovery repository for the Windows PC's GPU model, 65,536-token context,
eight MCP tools, private Tailscale phone access, and video downloads.

This is a source/configuration backup. It does not automatically synchronize the
running installation. It contains no model weights, installed binaries, videos,
browser conversations, runtime logs, API keys, or account credentials.
Image generation is not configured.

## Layout

- `runtime/`: model/file-server launchers, MCP configuration, video tool and tests.
- `agent-reach/`: custom reading backend, tests, Python dependency lock and MCP configuration.
- `web-tools/` and `node-tools/`: pinned Node dependency manifests and lockfiles.
- `tailscale-serve.json`: the existing private chat and file proxy routes.

The configuration records paths and the private tailnet hostname for this PC.
Its MCP PATH contains only the required executable folders instead of the full
session environment. Existing installed files were not changed by making this
repository.

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

6. Run the installed `Open-Heretic.ps1`, or use the existing desktop **Heretic**
   shortcut. It checks the model, context, all eight tools, and the file server.
   Existing user-login startup points to this same script with `-NoBrowser`.

On a different PC, adjust the model, executable, MCP, and shortcut paths and
tailnet hostname first. This snapshot is not an automatic installer.

## Verification

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
