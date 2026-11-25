#!/usr/bin/env python3
"""SessionStart hook: inject the always-on image rule (plugins cannot ship CLAUDE.md)
and a one-line-per-item notice for missing dependencies (never installs anything)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import limits  # noqa: E402

try:
    data = json.load(sys.stdin)
except Exception:
    data = {}

# Subagent-scoped sessions (`--agent image-inspector`) don't need the main-agent rule.
if str(data.get("agent_type") or "").split(":")[-1] == "image-inspector":
    sys.exit(0)

lim = limits.load()
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
imgtool = os.path.join(root, "scripts", "imgtool.sh").replace("\\", "/")
ctx = f"""## Image handling (image-delegation plugin)
- The main agent keeps 0 images in context. Each context can hold at most HARD_LIMIT={lim['HARD_LIMIT']} images over its whole life, and one more makes the session fail with HTTP 400.
- Never Read image files (.png/.jpg/.gif/.webp/...), PDFs or notebooks with image outputs, and never call screenshot tools or actions. Save files only, e.g. with `sh "{imgtool}" shot|pdf-render ...`.
- Whenever pixels must be checked, load the `image-delegation:image-delegation` skill first. Then delegate to a NEW `image-delegation:image-inspector` subagent per batch with an explicit `IMAGE_BUDGET` (DEFAULT_BUDGET={lim['DEFAULT_BUDGET']}) and `HARD_LIMIT: {lim['HARD_LIMIT']}` in the prompt. Never resume, SendMessage or fork it.
- Prefer text substitutes first: DOM/accessibility snapshot, pdftotext, OCR, image metadata. Never open an image to verify a subagent's report; ask a new inspector a narrower question instead."""

try:
    import deps  # noqa: E402

    probs = deps.problems()
except Exception as e:  # never let the check break session start
    probs = [f"dependency check failed ({e.__class__.__name__}); run `sh \"{imgtool}\" doctor`"]
if probs:
    ctx += ("\n\n### Missing dependencies (image-delegation)\n"
            + "\n".join(f"- {p}" for p in probs)
            + "\n- Do NOT install anything yourself. When a task needs one of these, tell the user what is missing and "
              f"the fix command, then continue with what still works. Full status: `sh \"{imgtool}\" doctor`.")

print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}}))
