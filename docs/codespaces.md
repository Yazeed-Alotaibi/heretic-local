# GitHub workspace

The repository now includes a Codespaces devcontainer. Opening a new Codespace
runs scripts/setup-codespace.sh to install Python 3.12 gateway dependencies from
the frozen lockfile and the official Filesystem MCP 2.1.0 using its npm lockfile.
Node.js24 is supplied by the devcontainer feature.

Open the repository on GitHub, choose **Code → Codespaces → Create codespace**.
Existing Codespaces need **Codespaces: Rebuild Container** to apply this setup.
GitHub may apply account quotas or charges; creating a Codespace remains an action
in the user's GitHub account. This session's connector cannot create/start one.

Generated local configuration: .heretic/codespaces.mcp.json.
Allowed file folder: .heretic/files. Both stay outside Git through .gitignore.
The upstream server supports writes; Heretic's five-tool read-only policy is
enforced only when calls pass through the gateway. The generated configuration
does not itself limit tools for another MCP client.

## What is ready

This config installs a repository workspace and Filesystem MCP on its own host,
without requiring the Windows PC. It does not copy the PC's files or memory.
The workspace is for editing and integration work.

## Model execution remains separate

The repository contains Windows launchers, not model weights or Linux runtime
binaries. The Codespaces setup does not download or start the model. Running the
same model here still needs a compatible Linux llama-prism engine for the custom
GGUF quantization, model weights, enough memory/storage, and a cloud launch
configuration. Do not substitute a generic engine and assume it supports PQ2_0.

The current gateway also restricts hosts/origins to the saved Windows/Tailscale
addresses. Its chat endpoint must be adapted and verified before exposing it on a
Codespaces forwarded URL. No model/chat port is automatically forwarded here.
The existing PC chat link remains http://desktop-7ov7vat:8080/.

## Workspace checkpoint

User asked to make this workspace live in the GitHub repo and install there.
The ambiguous target question received no answer; implementation proceeds with
the cloud development workspace interpretation. No hosted compute was created.
Active full clone for this session: /workspace/scratch/54fe5f80ee71/heretic-repo,
origin https://github.com/Yazeed-Alotaibi/heretic-local.git.
The older heretic-local and heretic-filesystem snapshots were preserved.
Base main:374712a4e62c3a20234276d6f40f4f01c506992c.
Lead:root; no delegated writers or active locks. No desktop installation occurred.

Verification is limited to shell syntax, devcontainer JSON and embedded Python
syntax/configuration inspection. No Codespace/container was launched; automatic installation there
remains unverified. Earlier MCP/gateway checks are documented separately.
Source configuration is published in this repository. Next: open/rebuild a
Codespace and verify automatic installation.
Model hosting remains a separate unresolved task with the requirements above.
