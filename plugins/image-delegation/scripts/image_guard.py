#!/usr/bin/env python3
"""PreToolUse guard for the image-delegation workflow.

Main agent (no `agent_id` in hook input):
  - deny Read of image files, PDFs, and notebooks that contain image outputs
  - deny MCP screenshot-like tools / actions
  - deny Agent(image-inspector) without a valid IMAGE_BUDGET; deny image work
    sent to forks or other agent types; deny SendMessage that would reuse an
    image-inspector (resume) or carry image work
Subagents (`agent_id` present):
  - image Reads AND screenshot-producing MCP calls share one per-agent counter
    (computer-use style tools count 1 per call, batch tools 1 per screenshot step)
  - image-inspector: capped at its IMAGE_BUDGET (parsed from its delegation
    prompt), never above HARD_LIMIT; other subagents: capped at HARD_LIMIT
  - PDF Read is denied

Packaged as a Claude Code plugin: limits come from plugin userConfig
(env CLAUDE_PLUGIN_OPTION_HARD_LIMIT / _DEFAULT_BUDGET, defaults in plugin.json).

Hook input fields used (documented): tool_name, tool_input, session_id,
transcript_path, agent_id, agent_type. Locating the subagent transcript /
meta.json is best effort (internal format); on failure the guard falls back
to HARD_LIMIT. Any unexpected error fails open (exit 0, message on stderr).
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import limits as _limits  # noqa: E402

PLUGIN = "image-delegation"
INSPECTOR = f"{PLUGIN}:image-inspector"   # plugin agents are namespaced <plugin>:<name>
SKILL = f"{PLUGIN}:image-delegation"
IMGTOOL = 'sh "' + os.path.join(HERE, "imgtool.sh").replace("\\", "/") + '"'

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".ico", ".heic", ".avif"}
# Tool names that return pixels to the caller (main agent only). Extend for your MCP servers.
SCREENSHOT_TOOL_RE = re.compile(r"screenshot|screen_capture|capture_screen|snapshot_image", re.I)
# MCP tools that may attach screenshots after actions (computer-use style). Blocked in main entirely.
ACTION_IMAGE_TOOL_RE = re.compile(r"^mcp__.*__computer$", re.I)
# Any MCP tool whose input requests one of these as a value (e.g. action="screenshot", browser_batch steps).
IMAGE_ACTION_VALUES = {"screenshot", "zoom", "take_screenshot"}

BUDGET_RE = re.compile(r"IMAGE_BUDGET\s*[:=]\s*(\d+)")
IMG_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|/|\.{1,2}[\\/]|~[\\/])[^\s\"'<>|`*?]*?\.(?:png|jpe?g|gif|webp|bmp|tiff?|ico|heic|avif)\b",
    re.I,
)


def is_inspector(name) -> bool:
    """Matches the plugin-scoped id and the bare name (e.g. a project-level copy)."""
    return str(name or "").split(":")[-1] == "image-inspector"


_LIM = _limits.load()
HARD_LIMIT, DEFAULT_BUDGET = _LIM["HARD_LIMIT"], _LIM["DEFAULT_BUDGET"]


# ---------------------------------------------------------------- output
def emit(decision: str | None, reason: str = "", context: str = ""):
    out: dict = {"hookEventName": "PreToolUse"}
    if decision:
        out["permissionDecision"] = decision
        out["permissionDecisionReason"] = reason
    if context:
        out["additionalContext"] = context
    print(json.dumps({"hookSpecificOutput": out}))
    sys.exit(0)


def state_dir(session_id: str) -> str:
    d = os.path.join(tempfile.gettempdir(), "claude-image-delegation-guard", re.sub(r"[^\w.-]", "_", session_id or "nosession"))
    os.makedirs(d, exist_ok=True)
    return d


def log_event(sd: str, **kw):
    try:
        kw["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(os.path.join(sd, "events.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(kw, ensure_ascii=False) + "\n")
    except Exception:
        pass


def deny(sd: str, data: dict, reason: str, **extra):
    log_event(sd, decision="deny", tool=data.get("tool_name"), agent_id=data.get("agent_id"),
              agent_type=data.get("agent_type"), reason=reason, **extra)
    emit("deny", reason)


# ---------------------------------------------------------------- transcript helpers (best effort)
def subagents_dir(data: dict) -> str | None:
    tp = data.get("transcript_path") or ""
    if not tp:
        return None
    if os.path.basename(tp).startswith("agent-"):
        return os.path.dirname(tp)
    return os.path.join(os.path.splitext(tp)[0], "subagents")


def inspector_budget(data: dict) -> tuple[int, str]:
    """Budget for the current subagent, parsed from its first (delegation) prompt."""
    sub = subagents_dir(data)
    path = os.path.join(sub, f"agent-{data.get('agent_id')}.jsonl") if sub else None
    if not path or not os.path.exists(path):
        return HARD_LIMIT, "transcript not found; capped at HARD_LIMIT"
    try:
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i > 50:
                    break
                rec = json.loads(line)
                if rec.get("type") != "user":
                    continue
                content = (rec.get("message") or {}).get("content")
                text = content if isinstance(content, str) else " ".join(
                    c.get("text", "") for c in (content or []) if isinstance(c, dict))
                m = BUDGET_RE.search(text)
                if m:
                    return min(int(m.group(1)), HARD_LIMIT), "IMAGE_BUDGET from delegation prompt"
                return DEFAULT_BUDGET, "no IMAGE_BUDGET in prompt; DEFAULT_BUDGET"
    except Exception as e:
        return HARD_LIMIT, f"transcript unreadable ({e.__class__.__name__}); capped at HARD_LIMIT"
    return HARD_LIMIT, "no user record yet; capped at HARD_LIMIT"


def inspector_ids(data: dict) -> set[str]:
    """IDs/names of image-inspector subagents spawned in this session (from meta.json files)."""
    ids: set[str] = set()
    sub = subagents_dir(data)
    if not sub:
        return ids
    for mf in glob.glob(os.path.join(sub, "agent-*.meta.json")):
        try:
            with open(mf, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue
        if not is_inspector(meta.get("agentType")):
            continue
        ids.add(os.path.basename(mf)[len("agent-"):-len(".meta.json")])
        for k in ("name", "agentName"):
            if isinstance(meta.get(k), str):
                ids.add(meta[k])
    return ids


def notebook_has_images(path: str) -> bool:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return '"image/' in f.read()
    except Exception:
        return False


def values(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from values(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from values(v)
    elif isinstance(obj, str):
        yield obj


# ---------------------------------------------------------------- rules
MAIN_HINT = (f"Main agent must keep 0 images in context. Use the `{SKILL}` skill: save files only, "
             f"then delegate viewing to a NEW `{INSPECTOR}` subagent with an explicit IMAGE_BUDGET "
             f"(default {DEFAULT_BUDGET}, max {HARD_LIMIT}). Text alternatives: DOM/accessibility "
             f"snapshot, pdftotext, `{IMGTOOL} info`.")


def mcp_image_cost(tool: str, ti: dict) -> int:
    """Upper bound of images an MCP call may return (0 = not image-producing).

    Screenshot-named tools cost >= 1. Computer-use style tools cost >= 1 for ANY
    action (they may attach a screenshot after clicks). Batch tools cost one per
    screenshot/zoom step in their input.
    """
    n_actions = sum(1 for v in values(ti) if v.strip().lower() in IMAGE_ACTION_VALUES)
    if SCREENSHOT_TOOL_RE.search(tool) or ACTION_IMAGE_TOOL_RE.search(tool):
        return max(1, n_actions)
    return n_actions


def charge(sd: str, data: dict, cost: int, what: str):
    """Count `cost` images for the current subagent; deny if it would exceed its cap."""
    agent_id = data.get("agent_id")
    agent_type = data.get("agent_type") or ""
    tool = data.get("tool_name")
    if is_inspector(agent_type):
        budget, why = inspector_budget(data)
    else:
        budget, why = HARD_LIMIT, "non-inspector subagent; HARD_LIMIT"
    counter = os.path.join(sd, re.sub(r"[^\w.-]", "_", str(agent_id)) + ".reads")
    try:
        with open(counter, encoding="utf-8") as f:
            used = sum(1 for _ in f)
    except FileNotFoundError:
        used = 0
    if used + cost > budget:
        deny(sd, data, (f"Image budget exhausted: {used}/{budget} used ({why}); this `{tool}` call may add "
                        f"{cost} image(s). Do not load more images. List the remaining items under "
                        "'Not examined' with reason 'budget exhausted', or report back to the main agent."),
             path=what, used=used, cost=cost, budget=budget)
    with open(counter, "a", encoding="utf-8") as f:
        f.write((what.replace("\n", " ") + "\n") * cost)
    log_event(sd, decision="allow", tool=tool, agent_id=agent_id, agent_type=agent_type,
              path=what, used=used + cost, cost=cost, budget=budget)
    emit(None, context=f"image-guard: this call counts {cost} image(s); {used + cost}/{budget} used ({why}).")


def main():
    data = json.load(sys.stdin)
    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") or {}
    agent_id = data.get("agent_id")
    agent_type = data.get("agent_type") or ""
    is_main = not agent_id
    sd = state_dir(data.get("session_id") or "")

    if os.environ.get("IMAGE_GUARD_DEBUG"):
        log_event(sd, decision="debug-input", input=data)

    # ---- Read
    if tool == "Read":
        path = str(ti.get("file_path") or "")
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            deny(sd, data, ("PDF Read is blocked (pages enter context as images). "
                            + (MAIN_HINT if is_main else
                               f"Use `{IMGTOOL} pdf-text FILE` for text and `{IMGTOOL} pdf-render FILE --pages N` "
                               "to render single pages, then Read those PNGs one at a time.")), path=path)
        if ext == ".ipynb" and is_main and notebook_has_images(path):
            deny(sd, data, "This notebook has image outputs. " + MAIN_HINT, path=path)
        if ext not in IMAGE_EXTS:
            emit(None)
        if is_main:
            deny(sd, data, f"Blocked image Read in main agent: {path}. " + MAIN_HINT, path=path)
        charge(sd, data, 1, path)  # subagent image Read: count against its budget

    # ---- screenshot-returning MCP tools
    if tool.startswith("mcp__"):
        cost = mcp_image_cost(tool, ti)
        if cost == 0:
            emit(None)
        if is_main:
            if SCREENSHOT_TOOL_RE.search(tool) or ACTION_IMAGE_TOOL_RE.search(tool):
                deny(sd, data, f"Blocked `{tool}` in main agent (returns screenshots). Use a DOM/accessibility "
                               f"snapshot or save a file with `{IMGTOOL} shot`. " + MAIN_HINT)
            deny(sd, data, f"Blocked screenshot/zoom action via `{tool}` in main agent. " + MAIN_HINT)
        charge(sd, data, cost, tool)  # subagent: screenshots share the image counter with Reads

    if not is_main:
        emit(None)

    # ---- main: delegation hygiene
    if tool in ("Agent", "Task"):
        st = str(ti.get("subagent_type") or "")
        prompt = str(ti.get("prompt") or "")
        m = BUDGET_RE.search(prompt)
        n_imgs = len({p.lower() for p in IMG_PATH_RE.findall(prompt)})
        if is_inspector(st):
            if ti.get("resume"):
                deny(sd, data, f"Do not resume `{INSPECTOR}`; spawn a new one.")
            if not m:
                deny(sd, data, f"Delegation to `{INSPECTOR}` must state `IMAGE_BUDGET: <n>` "
                               f"(1..{HARD_LIMIT}, default {DEFAULT_BUDGET}). See the `{SKILL}` skill template.")
            b = int(m.group(1))
            if b < 1 or b > HARD_LIMIT:
                deny(sd, data, f"IMAGE_BUDGET={b} is outside 1..{HARD_LIMIT}. Split into more batches.")
            log_event(sd, decision="allow", tool=tool, subagent_type=st, budget=b, image_paths=n_imgs)
            if n_imgs > b:
                emit(None, context=(f"image-guard: prompt lists {n_imgs} image paths but IMAGE_BUDGET={b}; "
                                    "the inspector will return the excess as 'Not examined'. Prefer batches <= budget."))
            emit(None)
        if m:  # image-delegation prompt sent to the wrong agent type (fork, general-purpose, ...)
            kind = "a fork (inherits context, not a fresh agent)" if "fork" in st.lower() else f"`{st or 'default'}`"
            deny(sd, data, f"Image work must go to a NEW `{INSPECTOR}` subagent, not {kind}. "
                           f"Set subagent_type=\"{INSPECTOR}\".")
        emit(None)

    if tool == "SendMessage":
        to = str(ti.get("to") or "")
        msg = json.dumps(ti, ensure_ascii=False)
        if BUDGET_RE.search(msg) or (to and to in inspector_ids(data)):
            deny(sd, data, f"Do not continue/reuse an image subagent via SendMessage. Spawn a NEW "
                           f"`{INSPECTOR}` with the Agent tool and a self-contained prompt.", to=to)
        emit(None)

    emit(None)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # fail open, never wedge the session
        print(f"image-guard error (allowing): {e!r}", file=sys.stderr)
        sys.exit(0)
