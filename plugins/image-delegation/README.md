# image-delegation (Claude Code plugin)

For model servers that accept a limited number of images per request (default 8). The history is re-sent with every request, so this limit is also the lifetime image cap of every context. This plugin keeps the main agent at **0 images**. Anything visual is viewed by a **fresh** `image-inspector` subagent with an explicit `IMAGE_BUDGET`, and main gets back a text-only report.

## Components
| Path | What it does |
|---|---|
| `agents/image-inspector.md` | `image-delegation:image-inspector`: tools `Read, Bash, Glob, Grep` only, `model: inherit`. Counts images against its budget and returns a fixed report (Answer / Images used / Per-image findings / Not examined / Uncertainties). |
| `skills/image-delegation/` | `/image-delegation:image-delegation`: loads automatically before image or PDF work. Covers text-first, save-don't-open, batching, the parallel-delegation procedure and the prompt template. |
| `hooks/hooks.json` | SessionStart injects the always-on rule. PreToolUse runs the guard (`scripts/image_guard.py`). |
| `scripts/imgtool.sh` | Text-only preprocessing: `list --batch`, `info`, `resize`, `crop`, `tile`, `pdf-scan`, `pdf-text`, `pdf-render`, `shot`. |
| `tests/` | Fixture generator, transcript auditor and a test plan. |

What the guard enforces, using the documented hook inputs `agent_id` and `agent_type`:
- **Main agent:**
  - denies Read of images, PDFs and notebooks with image outputs
  - denies screenshot MCP tools and `screenshot`/`zoom` actions
  - denies an inspector spawn without a valid `IMAGE_BUDGET`
  - denies image work sent to a fork or another agent type
  - denies SendMessage to an existing inspector
- **Subagents:** image Reads and screenshot-producing MCP calls share one counter per agent. Inspectors are capped at their `IMAGE_BUDGET`, other subagents at `hard_limit`. PDF Read is denied.

## Install
From a marketplace (this repo is one: `.claude-plugin/marketplace.json` at its root):
```sh
# inside Claude Code
/plugin marketplace add <git-url | owner/repo | local path to the repo root>
/plugin install image-delegation@image-tools
# or from a shell; --scope project writes .claude/settings.json so teammates get it enabled
claude plugin marketplace add <source> --scope project
claude plugin install image-delegation@image-tools --scope project
```
Try it without installing: `claude --plugin-dir <repo>/plugins/image-delegation`.
Restart Claude Code (or run `/reload-plugins`) after installing.

## Configure
| Option | Default | Meaning |
|---|---|---|
| `hard_limit` | 8 | Max images per request, i.e. the lifetime cap per context |
| `default_budget` | 6 | Budget used when a delegation states none (keep it below `hard_limit`) |

Set them with `/plugin configure image-delegation@image-tools`, the `/config` panel, or `claude plugin install ... --config hard_limit=8`. Restart Claude Code after changing them.

## Requirements
Run `sh <plugin>/scripts/imgtool.sh doctor` to check. At session start, the plugin also tells Claude what is missing, and Claude passes that on to you instead of installing anything.
- `sh` (Git Bash on Windows) and Python 3.8+ with Pillow.
- Optional: poppler (`pdftotext`, `pdfimages`, `pdftoppm`) or PyMuPDF for PDFs, and Playwright (Python, or `npx playwright`) for `shot`.
- A vision-capable model, because the inspector uses `model: inherit`.

## Limitations
- Images the user pastes into the chat count against main's limit, and nothing can block them.
- Screenshot-tool detection is heuristic (name/argument patterns). To cover other MCP servers, extend `SCREENSHOT_TOOL_RE` / `ACTION_IMAGE_TOOL_RE` in `scripts/image_guard.py`.
- Some lookups rely on internal transcript files (`<session>/subagents/agent-<id>.jsonl` / `.meta.json`), which may change between Claude Code versions:
  - the per-inspector budget (when that lookup fails, the cap falls back to `hard_limit`)
  - detecting SendMessage to an inspector
- The guard fails open: if Python is missing or the hook errors, the call is allowed.
