# Heretic personal-use review — 2026-10-31

## Scope and reviewed state
User request: review the repository and suggest additions for the existing local model. Everyday personal use remains the relevant context. This is a recommendation record, not an approved implementation plan.

Reviewed GitHub main: `4927541949b5cbe187be50ea4386d48225862cb7`.
Repository: https://github.com/Yazeed-Alotaibi/heretic-local
Full clone: `/workspace/scratch/54fe5f80ee71/heretic-repo`.
Local working HEAD remains `374712a4e62c3a20234276d6f40f4f01c506992c`, clean at review. Fetch verified that the only newer files are AGENTS.md, the devcontainer, setup-codespace.sh and docs/codespaces.md; core source examined locally is identical to reviewed main. Key files and handovers were also read through GitHub.

Lead: root. A read-only reviewer checked memory, knowledge and phone continuity; that review is complete. No implementation writers or locks remain.

## Existing capabilities
The source configures the existing Windows model engine, private Tailscale UI, web search/page reading, public GitHub and YouTube reading, video downloads, approved memory, project-scoped knowledge and five filesystem read/list/search tools. Do not recommend those as wholly new features.

Read README.md, docs/document-retrieval-handover.md, docs/memory-optimization-plan.md, docs/filesystem-mcp-handover.md and docs/codespaces.md for authoritative delivery state. Recent document, memory-budget and filesystem changes are merged, but their latest handovers record PC installation as pending. Codespaces configuration is a development workspace, not hosted model inference.

The preceding launch attempt could not reach the desktop: both saved Tailscale hostnames returned HTTP 503, and Desktop Commander listed only offline Y-Lap. This is assistant-side access evidence, not proof that the user's phone link fails. No live installation, model start or runtime quality measurement occurred in this review.

## Fixes before more integrations
1. **Memory candidates can be crowded out by preferences.** Store.search applies LIMIT 8 across all record kinds (gateway/heretic_gateway/store.py:390–406); automatic recall then filters preferences in memory_selection.py:62–68. Preferences already have a separate profile path at app.py:510–512. Apply kind filtering before ranking/limiting automatic evidence. Explicit memory_search also uses Store.search, so repeating the query is not a dependable workaround. Existing handover already acknowledges the limitation.
2. **Deployment visibility is missing.** Extend the existing health/readiness system with installed source version, enabled tool inventory and last successful startup. A backed-up update/rollback action could then make the distinction between merged code and installed code visible. Auto-start and basic readiness checks already exist.

Tool availability was traced through the final LLM schema selection: although the upstream UI still defines browser/custom tools, getEnabledToolsForLLM() ultimately returns server tools only (ui/src/lib/stores/tools.svelte.ts:291–305), matching the execution restriction at agentic/index.svelte.ts:773–774. There is no demonstrated tool-advertisement mismatch. The upstream JavaScript calculator/sandbox is not an enabled Heretic capability; any calculator proposal needs a gateway integration.

## Proposed additions, in priority order
Effort labels are relative engineering estimates; none of these additions is authorized for implementation yet.

| Priority | Addition | Benefit and scope | Effort |
|---|---|---|---|
| 1 | Shared chat history and downloadable backup | Gateway-backed conversations/messages let phone and PC resume the same chat. Keep browser caching and migrate/export existing browser histories. Current messages are IndexedDB-only (database.service.ts:16–27); gateway conversation records hold flags, not message history (store.py:466–472). | Medium |
| 2 | Screenshot/scanned-document OCR plus DOCX/XLSX ingestion | Read text from screenshots, receipts and scans; retain page/sheet references. Knowledge import currently allows only TXT/MD/PDF (knowledge.py:239–248), and PDF extraction explicitly lacks OCR (pdf_worker.py:19–26). Evaluate a local Docling worker; test Arabic/English samples. OCR is text extraction, not general photograph understanding. | Medium |
| 3 | Voice messages, then spoken responses | A separate transcription endpoint converts recorded/uploaded speech into ordinary text for the existing model. Upstream UI audio code is not proof of a configured transcription backend. A CPU-first faster-whisper service is a candidate; measure Arabic/Najdi quality and response time before choosing a model or using GPU memory. Spoken output is a separate follow-on. | Medium |
| 4 | Calculator, unit conversion and current date/time tools | Reliable arithmetic, comparisons and date calculations through small deterministic gateway tools. Avoid relying on the currently blocked upstream browser sandbox. | Low |
| 5 | Narrow n8n personal tools | Expose a few purpose-built workflows such as save bookmark, create a reminder or fetch a digest through an authenticated MCP Server Trigger. Preserve existing privacy handling and add explicit write-action approval. This review did not inspect or change the user's n8n instance; current workflows/version remain unverified. | Medium |
| 6 | Hybrid multilingual retrieval | Combine existing FTS5/BM25 with multilingual semantic retrieval to improve paraphrase and Arabic/English matching. Preserve exact names/numbers, source references, project isolation and deletion behavior. Fix candidate starvation first, then measure benefit on actual questions; no quality gain is assumed. | Medium–high |
| 7 | Durable background tool jobs | Move multi-step orchestration into resumable gateway jobs so it can advance while the phone browser is suspended. The browser currently owns the loop (agentic/index.svelte.ts:510–580,778–785); existing engine-stream reconnect does not by itself continue future tool rounds. | High |

## Voice prerequisite
The preferred phone URL uses HTTP. Browser microphone capture normally requires a secure context; a remote HTTP Tailscale hostname is not localhost. Add a private HTTPS Serve route and explicitly allow its host/origin in the gateway and engine before expecting in-page recording to work. Preserve an export/migration path for browser histories because the HTTPS origin has separate browser storage. The saved short HTTP URL remains the user's current preference; no URL or routing changes were made.

## Suggested next batch and validation
First restore desktop execution access and install the previously authorized merged changes with backup/rollback. Then propose the memory-candidate fix, installed-version visibility and a calculator/date tool as a quick reliability batch. For the next larger feature, recommend shared history, then OCR, then voice.

Add a small, optional 20–30-question Arabic/English evaluation set covering saved facts, source citations, missing answers and correct tool use. Existing mocked integration tests establish application behavior, not real model answer quality. Do not run broad repeated suites for this review. A later implementation should use focused behavior checks and relevant live acceptance examples.

## External primary references checked
- Docling formats/OCR/local execution: https://github.com/docling-project/docling
- faster-whisper CPU/GPU transcription: https://github.com/SYSTRAN/faster-whisper
- Browser microphone secure-context requirement: https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia
- Private HTTPS Serve: https://tailscale.com/docs/reference/tailscale-cli/serve
- n8n workflow tools via MCP: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger/

Agent Reach's search command was unavailable in this environment, so ordinary web search was used as the alternative for these documentation checks. GitHub access and git fetch succeeded.

## Completion and authorization boundary
Source review and independent read-only review completed; no runtime, dependency, tool configuration or model code was changed. No tests were run and no new passing-test claim is made. Recommendations above are proposals only. Existing authorization to install earlier merged changes remains recorded in their handovers, subject to actual desktop access.

This record is published on documentation branch `docs/personal-use-review-20261031`; no main merge or implementation PR is part of the review. Next action: user selects a proposed feature/batch, or resumes the separately authorized deployment when access works. Recovery: this documentation-only branch can be discarded; application behavior is unchanged.
