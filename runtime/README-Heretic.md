# Heretic local runtime

Phone chat: http://desktop-7ov7vat.tail4c4266.ts.net:8080/

Keep Tailscale connected on the phone and PC, and keep the PC awake. The model
listens on loopback; Tailscale Serve privately proxies this page. Refresh the
page after a server/tool change. Conversations remain in the browser's storage.

## Runtime

The installed layout is `gateway/heretic_gateway`, `gateway/.venv`, and `ui/`.
The gateway starts before the model and reports `model: loading` until the model
is ready. The phone can open the page while loading. `/health`, `/props`, and
`/slots` pass through to the model; `/api/heretic/health` reports gateway, model,
memory, and file-service readiness. The memory and knowledge tools are
`memory_search`, `memory_read`, `memory_propose`, `knowledge_search`, and
`knowledge_read`, in addition to the existing eight tools. `/api/heretic/gpu`
(session token required) reports `nvidia-smi` load, memory, power and temperature
for the interface's GPU badge; it is not a model tool.

Build the UI in the repository before installation; Vite emits `ui/dist/`.
From the repository root:

```powershell
& .\runtime\Install-Gateway.ps1
```

Override `-RepositoryRoot` and `-RuntimePath` for another explicitly selected
installation. The installer copies launchers, Python package sources, and built
UI files, then runs `uv sync --frozen --python 3.12 --link-mode copy` in the
installed gateway directory. It backs up existing launchers and gateway/UI
directories under a unique `saved-setup/gateway-*` directory. It leaves MCP
configuration, model binaries, model weights, shortcuts, and personal data in
place. It does not stop or start services. An existing legacy model on 8080 must
be deliberately stopped before starting the new gateway; no launcher kills a
process by its listening port. Listener checks target loopback and wildcard
addresses, allowing the existing Tailscale Serve listener on its private IP.

Open or reuse the installed runtime with `./Open-Heretic.ps1`. To stop only the
processes created by this installation, run `./Stop-Heretic.ps1`; use
`-ValidateOnly` to inspect ownership without stopping anything. Process records
contain launcher and descendant PIDs, executable paths, UTC creation times,
parent PIDs, and the gateway's actual listening PID. Windows virtual environments
can launch a second Python process; reopening validates that child's listener.
Every live record is
validated before any process is stopped, and each identity is checked again at
stop time. Descendants stop before their launcher; cleanup failures preserve the
ownership records. A reused existing file server is excluded from owned records.
Failed startup leaves logs and ownership records available for inspection.

After stopping owned gateway/model processes, restore the original launchers:

```powershell
& .\Install-Gateway.ps1 -RuntimePath 'C:\path\to\runtime' -RollbackBackup 'C:\path\to\runtime\saved-setup\gateway-TIMESTAMP-ID'
& .\Open-Heretic.ps1 -NoBrowser
```

The backup must belong to the selected runtime. Restored original launchers
return the original model to 8080. Rollback preserves new memory, knowledge,
browser conversations, and downloads; gateway/UI files remain available for
inspection. The rollback command does not stop or start services itself.

Verification uses isolated temporary processes and leaves existing services intact.
It requires the gateway's synchronized Windows virtual environment:

```powershell
& C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\runtime\Test-SavedStartup.ps1
```

This passed on Windows PowerShell 5.1 and PowerShell 7.6.5: script syntax, loopback listener filtering
that excludes Tailscale Serve, valid process ownership,
PID reuse rejection, backup creation, package/UI copying, original-launcher
rollback, and preservation of personal data and MCP configuration. The install
fixture mocks `uv`. A real Windows venv HTTP fixture verifies its redirector
child, actual listening PID, reopening ownership, a two-second health response,
and cleanup of both initial and late-spawned descendants on an ephemeral loopback
port. The real environment synchronization and complete live readiness also passed
on this PC. `-Live` explicitly enables the startup mutex
test and may start the saved runtime.

- Model: Ternary-Bonsai-2-27B-Uncensored-Heretic-PQ2_0.gguf
- GPU: RTX 5070 Ti; all requested model layers are offloaded.
- Context: 65,536 tokens; one chat slot; Q8_0 key/value cache; flash attention.
- Q8 cache reduces memory use compared with the original F16 cache. Its effect
  on answer quality has not been benchmarked.
- Start after the previous instance is stopped: `./Start-Heretic.ps1`
- The model runs privately on 8081; the gateway serves the phone UI on 8080.
  The private video file service remains on 8082.
- Startup logs have unique UTC filenames. The launcher refuses to replace an
  existing local listener. `before-64k-process.json` records the previous command.
- Heretic starts hidden when this Windows user signs in, using the current-user
  Startup folder's `Heretic.lnk`. It loads the same model, 64k context, and tools.
- Double-click the desktop **Heretic** shortcut to start or reopen the chat.
  `Open-Heretic.ps1` reuses an existing instance and checks the model, context,
  all thirteen tools, gateway, memory, and file server. It never stops an existing chat.
- Startup diagnostics: `startup-status.log` and the timestamped server logs.
- A PC reboot was not performed for verification. The shortcut's actual Windows
  PowerShell command was tested against the running instance.
- Disable automatic model startup by removing only `Heretic.lnk` from the
  Windows Startup folder (`shell:startup`). Tailscale runs as its existing
  automatic Windows service; both private Serve routes persist on disk.
- To stop private sharing alone:
  `tailscale serve --http=8080 off`

## Saved setup

The runtime scripts and MCP configuration stay in this folder. The model stays
in LM Studio's model folder; Agent Reach stays in its isolated backend folder.
`saved-setup` contains a dated copy and ZIP of launchers, configuration, custom
tools, dependency lockfiles, and private Serve configuration. These are recovery
copies for this PC; model weights, installed binaries, downloads and browser
chat history are not included. Keep the installed folders in their current
locations. Browser conversations remain in that browser's local storage.

## Agent Reach and MCP

Agent Reach 1.5.0 is installed from commit
`a19a171fa980a0785849596492e0af4db800c82f`, in an isolated environment at
`C:/Users/PC/.agent-reach/heretic-backend/.venv`.
Its source checkout and existing user configuration were preserved.

The stock Agent Reach MCP only exposes status. The local `backend.py` adapter
exposes its public reading backends as bounded, read-only MCP tools. Diagnostics
run the real `agent-reach doctor --json` CLI with detached stdin, which avoids
a Windows child-process hang when launched from an MCP pipe.

`heretic.mcp.json` connects:

- Exa web search and webpage fetch through pinned `mcp-remote` 0.14.3.
- Jina Reader for public webpages.
- Public GitHub repository search (no account token).
- yt-dlp for YouTube search, metadata and available captions.
- Agent Reach backend diagnostics.
- Video downloads through `media_download_video`, with private Tailscale links
  that open or save the MP4 on the phone.

Exa receives search queries and requested URLs; Jina receives requested page
URLs. These tools do not have general shell, local-file or account-write access.
YouTube may refuse some videos or captions; errors are returned explicitly.
No paid transcription service or browser-cookie extraction is configured.
Optional social channels need their own explicit setup/login.

## Downloading videos

Refresh Chrome after this tool change, then ask:
`Download this video and send me the file: <video URL>`.
Heretic returns a clickable download link in the chat. This is file delivery
through the PC, rather than sending a message through another app.

Public HTTPS MP4 links and yt-dlp-supported websites are supported, subject to
the site's download restrictions. Limits: one download at a time, 500 MB,
30 minutes, five-minute download timeout, and 5 GB of saved downloads. Website
downloads prefer compatible MP4 up to 720p. No login, browser cookies, playlists
or live streams are configured. Failed attempts remove only their own files.

`media_tools.py` validates the MP4 before making it available, serves range
requests for playback, and exposes only completed video files. Its file server
listens at `127.0.0.1:8082`; Tailscale Serve maps `/files` to it while retaining
the chat at `/`. The launcher starts this helper when media tools are enabled.
Files remain in `media-files` until removed locally. Keep the PC awake and
Tailscale connected. Website requests use a proxy that validates and pins public
destinations for each HTTPS connection. Image generation remains disconnected.
Website formats must use HTTPS; unsupported streaming-only formats return an
error rather than invoking a separate network downloader.

Download failures return distinct codes for unsupported sites/formats, PC DNS,
PC connections, HTTPS verification, and site denial. These are evidence from the
PC download, not proof of a country block or unstable DNS. The phone receives the
saved file over Tailscale and does not need to reach the original website.

Verified a direct MP4 download and a public YouTube download through the live
MCP tool. Heretic selected the tool and returned the resulting clickable link.
The private phone URL passed HTTP download and partial-playback checks. All 23
media tests and Ruff passed; independent review approved the final changes.
Records: `verified-video.json`, `verified-video-model.json`,
`verified-video-answer.json`, and `verified-video-website.json`.

Agent Reach's doctor conservatively distinguishes installed/configured backends
from live verification. Its report can show Exa as unverified even after a
successful search through the separate MCP connection.

Python dependencies are pinned in the backend's `uv.lock`; Node dependencies
are pinned in their package-lock files. No global npm package was installed.

## Verification

The live server reports 65,536 context tokens and one slot. A retrieval test
with 10,829 input tokens succeeded; this is not a benchmark of answer quality
at the full context limit. The model completed an Exa tool-call round trip.
See `verified-context.json`, `verified-search.json`, and `verified-backends.json`
for task-owned verification records.

The backend has input validation and timeout tests in `test_backend.py`, and
received independent Python and integration review. Run checks from its folder:

```powershell
uv run --no-sync pytest -q
uv run --no-sync ruff check --config pyproject.toml backend.py test_backend.py
```
