#!/usr/bin/env python3
"""Audit a Claude Code session transcript for image usage.

Checks: main context has 0 image blocks (conversation records only); each subagent stayed within its
IMAGE_BUDGET (parsed from its first prompt, else DEFAULT_BUDGET) and HARD_LIMIT;
lists Agent / SendMessage calls made by main.

Usage: python check_transcript.py [SESSION_ID | --latest] [--project-dir DIR] [--hard-limit N --default-budget N]
Transcript layout (internal, may change between versions):
  ~/.claude/projects/<encoded-project>/<session>.jsonl                 main
  ~/.claude/projects/<encoded-project>/<session>/subagents/agent-*.jsonl  subagents
Exit 0 = PASS, 1 = FAIL.
"""
import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import limits as _limits  # noqa: E402

PROJECT = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
BUDGET_RE = re.compile(r"IMAGE_BUDGET\s*[:=]\s*(\d+)")


def proj_dir(project: str) -> str:
    base = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"), "projects")
    return os.path.join(base, re.sub(r"[^A-Za-z0-9]", "-", project))


def count_images(obj) -> int:
    if isinstance(obj, dict):
        n = 1 if obj.get("type") in ("image", "document") else 0
        return n + sum(count_images(v) for k, v in obj.items() if k != "toolUseResult")
    if isinstance(obj, list):
        return sum(count_images(v) for v in obj)
    return 0


def load(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    pass


def conversation(path, skip_sidechain=False):
    """Yield (record, message) for conversation records only.

    Skips non-conversation records (e.g. `api-request-blob`, which duplicate
    request payloads) and repeated tool_use/tool_result blocks.
    """
    seen = set()
    for rec in load(path):
        if rec.get("type") not in ("user", "assistant"):
            continue
        if skip_sidechain and rec.get("isSidechain"):
            continue
        msg = rec.get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):
            kept = []
            for c in content:
                key = (c.get("type"), c.get("id") or c.get("tool_use_id")) if isinstance(c, dict) else None
                if key and key[1]:
                    if key in seen:
                        continue
                    seen.add(key)
                kept.append(c)
            msg = dict(msg, content=kept)
        yield rec, msg


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return " ".join(c.get("text", "") for c in content or [] if isinstance(c, dict))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session", nargs="?")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--project-dir", default=PROJECT, help="project root (default: cwd)")
    ap.add_argument("--hard-limit", type=int, help="configured hard_limit (default: plugin.json default)")
    ap.add_argument("--default-budget", type=int, help="configured default_budget")
    a = ap.parse_args()
    global HARD, DEFAULT
    lim = _limits.load({"HARD_LIMIT": a.hard_limit, "DEFAULT_BUDGET": a.default_budget})
    HARD, DEFAULT = lim["HARD_LIMIT"], lim["DEFAULT_BUDGET"]
    pd = proj_dir(os.path.abspath(a.project_dir))
    if a.latest or not a.session:
        mains = sorted(glob.glob(os.path.join(pd, "*.jsonl")), key=os.path.getmtime)
        if not mains:
            sys.exit(f"no transcripts in {pd}")
        main_path = mains[-1]
    else:
        main_path = os.path.join(pd, a.session + ".jsonl")
    sid = os.path.splitext(os.path.basename(main_path))[0]
    ok = True

    main_imgs, calls = 0, []
    for rec, msg in conversation(main_path, skip_sidechain=True):
        main_imgs += count_images(msg)
        if rec.get("type") == "assistant":
            for c in msg.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") in ("Agent", "Task", "SendMessage", "Read"):
                    inp = c.get("input") or {}
                    calls.append((msg.get("id") or rec.get("uuid"), c["name"],
                                  inp.get("subagent_type") or inp.get("to") or inp.get("file_path"),
                                  (BUDGET_RE.search(json.dumps(inp)) or [None, "-"])[1]))
    print(f"SESSION {sid}")
    print(f"MAIN image blocks: {main_imgs}  {'PASS' if main_imgs == 0 else 'FAIL'}")
    ok &= main_imgs == 0
    groups = {}
    for mid, name, target, budget in calls:
        groups.setdefault(mid, []).append(name)
        print(f"  main call: {name}  target={target}  IMAGE_BUDGET={budget}  msg={str(mid)[-8:]}")
    par = [g for g in groups.values() if g.count("Agent") + g.count("Task") > 1]
    if par:
        print(f"  parallel Agent spawns in one message: {[len(g) for g in par]}")

    subs = sorted(glob.glob(os.path.join(pd, sid, "subagents", "agent-*.jsonl")), key=os.path.getmtime)
    print(f"SUBAGENTS: {len(subs)}")
    for sp in subs:
        aid = os.path.basename(sp)[len("agent-"):-len(".jsonl")]
        meta = {}
        mp = sp[:-len(".jsonl")] + ".meta.json"
        if os.path.exists(mp):
            with open(mp, encoding="utf-8") as f:
                meta = json.load(f)
        imgs, budget, reads, denied = 0, None, 0, 0
        for rec, msg in conversation(sp):
            if budget is None and rec.get("type") == "user":
                m = BUDGET_RE.search(text_of(msg.get("content")))
                budget = int(m.group(1)) if m else DEFAULT
            imgs += count_images(msg)
            for c in msg.get("content") or [] if isinstance(msg.get("content"), list) else []:
                if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Read":
                    reads += 1
                if isinstance(c, dict) and c.get("type") == "tool_result" and "IMAGE_BUDGET exhausted" in json.dumps(c):
                    denied += 1
        budget = budget if budget is not None else DEFAULT
        cap = min(budget, HARD)
        good = imgs <= cap
        ok &= good
        print(f"  {meta.get('agentType', '?'):16s} {aid}  images={imgs}/{budget} (cap {cap})  "
              f"Read calls={reads}  hook-denied={denied}  {'PASS' if good else 'FAIL'}")
    print("RESULT", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
