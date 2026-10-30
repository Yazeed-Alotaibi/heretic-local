# Filesystem MCP

Adds the official `@modelcontextprotocol/server-filesystem` pinned to **2.1.0**.
Requires **Node.js 24+**. The default folder is `%USERPROFILE%\.heretic\files`;
it is outside the repository and OneDrive. Put files you want Heretic to read there.

Heretic exposes five tools: `filesystem_list_allowed_directories`,
`filesystem_list_directory`, `filesystem_search_files`, `filesystem_get_file_info`,
and `filesystem_read_text_file`. Writes, moves, deletes, bulk reads, and all other
filesystem tools are blocked by the gateway. The official upstream server itself
has write capabilities; this read-only policy is enforced by Heretic's gateway,
not by a nonexistent server `--read-only` flag. Keep the engine on loopback 8081.

File paths and results mark the conversation private, even with memory off.
Subsequent web/other external tools use Heretic's existing approval dialog. Local
file reads do not require external-request approval. These tools do not import
files into the knowledge store or automatically share them with cloud services.
`read_text_file` reads text; it is not a PDF/Office extractor. Ask for the first
few lines of large files to avoid filling the model context.

## Install on the existing Windows PC

GitHub changes do not install automatically. From the checked-out repository:

```powershell
$runtime = 'C:\Users\PC\OneDrive\Documents\ChatGPT\chats with no projects\ternary-bonsai-runtime'
& "$runtime\Stop-Heretic.ps1"
.\runtime\Install-Filesystem.ps1 -RuntimePath $runtime
& "$runtime\Open-Heretic.ps1"
```

The installer checks prerequisites, stages `npm ci --ignore-scripts`, backs up
replaced files, installs current gateway Python source (including the already-merged
retrieval improvements), and merges only the filesystem server into the existing
MCP configuration. It preserves all other servers and user data. Compare newer
local gateway changes before running. It requires services on 8080/8081 to be
stopped and never kills processes itself. It restores replaced files if installation
fails. Node is not upgraded automatically.

To use a different folder, pass `-AllowedDirectory 'C:\path\to\personal-files'`.
Use a dedicated folder. Do not point it at your whole drive, user profile, secrets,
or Heretic's internal data directory. `-NodePath` supports a non-default Node install.
No Tailscale route changes are needed; the phone uses the existing chat URL.

After startup, refresh the chat page. Try **"List the folders you can access"**,
then **"List the files there"**, then **"Read the first 20 lines of hello.txt"**
after placing a text file in that folder. Startup checks require all five tools
when the filesystem server is configured. Expected total with the current setup:18.

## Roll back

Stop Heretic. The installer prints a backup under
`<runtime>\saved-setup\filesystem-<timestamp>-<id>`. Read its `manifest.json`:
restore entries marked `Existed` from its `files` folder to the matching relative
runtime paths; remove only installed source entries marked `Existed: false`.
Move the new runtime `filesystem-tools` aside and restore
`previous-filesystem-tools` from the backup if it exists. Restart Heretic.
Leave the allowed personal-files folder intact. Backups can contain private runtime
paths/configuration and remain on the PC; never commit them.

## Verification and limits

Three focused gateway checks passed: filtering/denied writes, exact model dispatch,
and sticky privacy with memory off. A real Node24/official2.1.0 stdio smoke negotiated
MCP2024-11-05, found the five tools, read a temporary file and blocked a file outside
the allowed directory. Windows installer and the actual llama-prism/phone workflow
remain unverified because the desktop execution connection was unavailable.
