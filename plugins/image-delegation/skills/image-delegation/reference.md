# image-delegation reference

## Why
- The model server rejects a request that carries more than HARD_LIMIT images (HTTP 400), and the session cannot continue.
- The whole history is re-sent with every request. Any image that enters a context stays there for the rest of that context's life, so each context gets HARD_LIMIT images over its whole lifetime.
- Each subagent has its own context. The parent receives only the subagent's final text. A NEW subagent is a fresh budget. A resumed or SendMessage'd subagent keeps its old images. A fork inherits the parent history.

## What puts images into context
| Blocked in main | Allowed in main |
|---|---|
| Read of .png .jpg .jpeg .gif .webp .bmp .tif .ico .heic .avif | `IMGTOOL shot` / `npx playwright screenshot` / Python playwright that saves to a file |
| Read of .pdf (pages can be sent as images) | `pdftoppm` / `IMGTOOL pdf-render` that writes PNG files |
| Read of .ipynb that has image outputs | `pdftotext`, `pdfimages -list`, `IMGTOOL pdf-scan/pdf-text` |
| MCP `browser_take_screenshot`, `computer` (screenshot/zoom, or actions that attach screenshots) | DOM/accessibility snapshot (`browser_snapshot`, `read_page`, `get_page_text`) |
| Any tool whose result shows pixels | `IMGTOOL info`, `identify`, `exiftool`, `tesseract` OCR |

Images the user pastes into the chat also count against main's limit, and nothing can block that. If the user pastes images, tell them about the limit.

## IMGTOOL commands (all print paths and metadata only)
| cmd | purpose |
|---|---|
| `list P... [--batch] [--batch-size K] [--default-budget N --hard-limit N]` | expand files, dirs and globs into sorted absolute image paths, plus `COUNT`; plan balanced batches |
| `info P...` | `path  WxH  bytes  format/mode` |
| `resize P... [--max-side 1568]` | downscale copies into the temp dir |
| `crop F --box x0,y0,x1,y1 [--frac] [--scale 2]` | region copy (for inspectors) |
| `tile F -n K [--overlap 40]` | split a long screenshot into K tiles (each tile = 1 image) |
| `pdf-scan F` | per page: text chars, embedded images, vector ops (PyMuPDF only), flags, and `VISUAL_PAGES` |
| `pdf-text F [--pages 1,3-5]` | text per page |
| `pdf-render F --pages 2,5 [--dpi 110]` | one PNG per page, long side ≤ 1568 |
| `shot URL [--out F] [--full-page] [--selector CSS] [--wait-ms N]` | Playwright screenshot to a file (Python playwright, else `npx playwright`) |
| `doctor` | dependency status for the Python that the scripts use. Exits 1 if something required is missing |
| `limits` | print the effective limits seen by scripts (plugin.json defaults unless overridden by flags) |

Backends: poppler is used first, with PyMuPDF (`pip install pymupdf`) as the fallback. Raster work needs Pillow. Without PyMuPDF, vector-only charts are not flagged by `pdf-scan`, so check the captions in `pdf-text` ("Figure", "Chart", "Table").
Default output dir: `.claude/tmp/image-delegation/` under the cwd (normally the project root). Reads there need no extra permission. A `.claude/tmp/.gitignore` is created automatically. Override the dir with env `IMGTOOL_OUT`, and delete it any time.

## Batching rules
- Batch size ≤ IMAGE_BUDGET ≤ HARD_LIMIT. With the defaults (8 / 6), the default budget leaves 2 below the hard limit as a safety margin.
- If crops or zooms are likely (small text, dense UI), send a batch smaller than its budget, e.g. budget minus 2 files.
- Keep images that must be compared directly in one batch: before/after pairs, expected vs actual.
- Split a 30-page PDF scan into ceil(30 / budget) batches of rendered pages and send them in parallel in one message.
- For a full-page screenshot taller than ~3x its width, `tile` it first. Count the tiles, not the original.

## Changing the limits
Both values are plugin `userConfig` options: `hard_limit` (default 8) and `default_budget` (default 6). Change them with `/plugin configure image-delegation@<marketplace>`, the `/config` panel, or `claude plugin configure`. Restart Claude Code after changing them. The hooks read them from `CLAUDE_PLUGIN_OPTION_HARD_LIMIT` / `CLAUDE_PLUGIN_OPTION_DEFAULT_BUDGET`, falling back to the defaults in `.claude-plugin/plugin.json`. The SessionStart hook announces the effective values to the main agent, and main passes `HARD_LIMIT` to each inspector in the delegation prompt. The guard enforces both values either way. The md files use no `${user_config.*}` substitution, because it was not applied in testing.

## Guard hook (plugin `hooks/hooks.json` → `scripts/image_guard.py`)
- Main (hook input has no `agent_id`): denies the calls blocked above. It also denies an inspector spawn with no `IMAGE_BUDGET` or with a budget above HARD_LIMIT, an `IMAGE_BUDGET` prompt sent to a fork or another agent type, and a `SendMessage` to an existing inspector or one that carries `IMAGE_BUDGET`.
- Subagents (`agent_id` present): image Reads and screenshot-producing MCP calls share one counter per agent. A computer-use style tool counts 1 per call, because any action may attach a screenshot. A batch tool counts 1 per screenshot or zoom step. An inspector is capped at the `IMAGE_BUDGET` from its prompt, or DEFAULT_BUDGET if the prompt gives none. Any other subagent is capped at HARD_LIMIT. PDF Read is denied everywhere.
- Log: `<system temp>/claude-image-delegation-guard/<session_id>/events.jsonl`. Set the env var `IMAGE_GUARD_DEBUG=1` to also log raw hook inputs.
- If you are denied, don't work around it. Follow the procedure in SKILL.md.
- A SessionStart hook (`scripts/session_context.py`) injects the always-on main-agent rule, because plugins cannot ship CLAUDE.md. It also lists missing dependencies, one line each with the fix command. It never installs anything; the agent tells the user instead.
