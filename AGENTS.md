# Heretic workspace

Work from this repository's root. GitHub is the durable source of truth; do not
resume from the old partial gateway snapshots. Read README.md and the latest
applicable handover before changes:
- docs/filesystem-mcp-handover.md
- docs/memory-optimization-plan.md
- docs/codespaces.md for the GitHub workspace.

Preferred PC/phone link: http://desktop-7ov7vat:8080/
When asked for access, provide that clickable link first. The user may be on a
phone without physical PC access. A failed assistant-side connection does not
prove the phone cannot open the link.

Keep source updates, merges, dependency installation and live model execution
distinct. The Windows launchers require the PC's model weights and runtime.
Codespaces installs development dependencies and the official Filesystem MCP;
it does not install or run the 27B model. Its filesystem MCP configuration is
generated in ignored .heretic/codespaces.mcp.json.

Keep personal files, model weights, secrets and generated dependencies out of Git.
Retain existing privacy/approval checks. Filesystem MCP read-only enforcement is
in the Heretic gateway, not an upstream filesystem-server flag.
The user prefers quick delivery and focused verification; avoid unnecessary
broad or repeated test runs. Record important decisions and actual limitations
in the relevant handover before ending substantial work.
