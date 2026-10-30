#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python -m pip install --user 'uv==0.13.4'
python -m uv sync --project gateway --frozen
npm ci --prefix filesystem-tools --ignore-scripts --no-audit --no-fund

python - <<'PY'
import json
import shutil
from pathlib import Path

root = Path.cwd()
private = root / ".heretic"
allowed = private / "files"
allowed.mkdir(parents=True, exist_ok=True)
node = shutil.which("node")
if not node:
    raise SystemExit("Node.js is missing")
server = root / "filesystem-tools/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"
if not server.is_file():
    raise SystemExit("Filesystem MCP installation is incomplete")
config = {"mcpServers": {"filesystem": {
    "command": node,
    "cwd": str(root),
    "timeout_ms": 30000,
    "args": [str(server), str(allowed)]
}}}
target = private / "codespaces.mcp.json"
target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
print(f"Installed workspace dependencies and Filesystem MCP. Config: {target}")
print("The model server has not been installed or started.")
PY
