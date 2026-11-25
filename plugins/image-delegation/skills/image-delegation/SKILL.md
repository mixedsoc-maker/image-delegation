---
name: image-delegation
description: MUST use BEFORE any Read of an image (.png/.jpg/.jpeg/.gif/.webp/.bmp) or PDF, and before any screenshot tool. Triggers - checking a screenshot, visual/UI verification, "what does this image show", figures/tables/scans inside a PDF, reading a chart or plot, comparing images. Keeps the main context at 0 images by saving files and delegating viewing to fresh image-inspector subagents with an explicit image budget.
---

# Image delegation

Limits: `HARD_LIMIT` (images per context; more = HTTP 400, session dead) and `DEFAULT_BUDGET` (per inspector) are given in the session-start "Image handling" context. They come from plugin config `hard_limit`/`default_budget`, defaults 8 and 6.

**Main agent never views pixels.** Forbidden in main: Read of images/PDFs, MCP screenshot tools or actions, tools that return screenshots after clicks. Allowed: saving files without opening them, and text substitutes.

`IMGTOOL` = `sh "${CLAUDE_PLUGIN_ROOT}/scripts/imgtool.sh"` (text output only; `IMGTOOL <cmd> -h` for options).

## Procedure
1. **Text first.** If a text source answers it, stop there: DOM/accessibility snapshot (e.g. `browser_snapshot`), `IMGTOOL pdf-text F`, OCR (`tesseract` if installed), `IMGTOOL info F`, `pdfimages -list`.
2. **Prepare files (never open them).**
   - Web page: `IMGTOOL shot URL --out /abs/out.png [--full-page] [--width 1280 --height 800]`
   - PDF: `IMGTOOL pdf-scan F` → `VISUAL_PAGES`; then `IMGTOOL pdf-render F --pages 2,5`
   - Long or huge image: `IMGTOOL tile F -n 3` or `IMGTOOL resize F`
   - Get an exact count of absolute paths: `IMGTOOL list <dirs/globs/files>`
3. **Batch.** `IMGTOOL list <paths> --batch --default-budget <DEFAULT_BUDGET> --hard-limit <HARD_LIMIT> [--batch-size K]` gives balanced batches with each batch ≤ budget. Put images that must be compared with each other in the same batch. Leave spare budget (batch < budget) when crops or zooms are likely.
4. **Delegate.** Spawn one NEW `image-delegation:image-inspector` per batch. Send independent batches as parallel Agent calls in ONE message. Never resume, SendMessage or fork an inspector.
5. **Prompt.** Make it self-contained. The inspector starts with no context. Use [template.md](template.md) and always include `IMAGE_BUDGET: <n>` (n ≤ HARD_LIMIT) and `HARD_LIMIT: <HARD_LIMIT>`.
6. **Use results as text only.** For `Not examined` items, gather them and send them to a NEW inspector. Never open an image to double-check. Instead, send a narrower question to a new inspector. Treat `Uncertainties` the same way.
7. **Cross-batch comparison.** Ask each batch to extract the comparable features in detail (exact text, positions, colors, sizes, values). Then compare the texts in main.

Details, edge cases and examples: [reference.md](reference.md).
