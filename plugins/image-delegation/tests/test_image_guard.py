#!/usr/bin/env python3
"""Offline regression test for scripts/image_guard.py (no Claude session needed).

Feeds synthetic PreToolUse inputs to the hook and checks allow/deny decisions.
Usage: python tests/test_image_guard.py      -> exit 0 if all cases pass
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = ["sh", os.path.join(PLUGIN, "scripts", "py.sh"), "--fail-open", "image_guard.py"]
INSPECTOR = "image-delegation:image-inspector"

tmp = tempfile.mkdtemp(prefix="image-guard-test-")
SESSION = "test-" + uuid.uuid4().hex[:8]
TRANSCRIPT = os.path.join(tmp, SESSION + ".jsonl")
SUB = os.path.join(tmp, SESSION, "subagents")
os.makedirs(SUB)
open(TRANSCRIPT, "w").close()
STATE = os.path.join(tempfile.gettempdir(), "claude-image-delegation-guard", SESSION)


def subagent(agent_id, budget_line):
    with open(os.path.join(SUB, f"agent-{agent_id}.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": f"GOAL: t\n{budget_line}\n"}}) + "\n")
    with open(os.path.join(SUB, f"agent-{agent_id}.meta.json"), "w", encoding="utf-8") as f:
        json.dump({"agentType": INSPECTOR if budget_line else "general-purpose"}, f)


def hook(tool, ti, agent=None, env=None):
    d = {"session_id": SESSION, "transcript_path": TRANSCRIPT, "hook_event_name": "PreToolUse",
         "tool_name": tool, "tool_input": ti}
    if agent:
        d.update(agent_id=agent[0], agent_type=agent[1])
    r = subprocess.run(HOOK, input=json.dumps(d), capture_output=True, text=True,
                       env={**os.environ, **(env or {})})
    out = json.loads(r.stdout).get("hookSpecificOutput", {}) if r.stdout.strip() else {}
    return out.get("permissionDecision", "allow"), out.get("permissionDecisionReason") or out.get("additionalContext") or r.stderr


results = []


def case(name, expect, tool, ti, agent=None, env=None, contains=None):
    got, msg = hook(tool, ti, agent, env)
    ok = got == expect and (contains is None or contains in (msg or ""))
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name:58s} -> {got:5s} | {(msg or '')[:80]}")


PNG = os.path.join(tmp, "a.png")
SHOT = "mcp__playwright__browser_take_screenshot"
COMPUTER = "mcp__claude-in-chrome__computer"
BATCH = "mcp__claude-in-chrome__browser_batch"

# ---- main agent
case("main: Read png denied", "deny", "Read", {"file_path": PNG})
case("main: Read pdf denied", "deny", "Read", {"file_path": PNG[:-3] + "pdf"})
case("main: Read .py allowed", "allow", "Read", {"file_path": PNG[:-3] + "py"})
case("main: screenshot tool denied", "deny", SHOT, {})
case("main: computer click denied", "deny", COMPUTER, {"action": "left_click"})
case("main: batch with screenshot step denied", "deny", BATCH, {"steps": [{"action": "screenshot"}]})
case("main: read_page allowed", "allow", "mcp__claude-in-chrome__read_page", {"tabId": 1})
case("main: inspector without IMAGE_BUDGET denied", "deny", "Agent", {"subagent_type": INSPECTOR, "prompt": "look"})
case("main: inspector IMAGE_BUDGET 9 denied", "deny", "Agent", {"subagent_type": INSPECTOR, "prompt": "IMAGE_BUDGET: 9"})
case("main: inspector IMAGE_BUDGET 6 allowed", "allow", "Agent", {"subagent_type": INSPECTOR, "prompt": "IMAGE_BUDGET: 6"})
case("main: fork with IMAGE_BUDGET denied", "deny", "Agent", {"subagent_type": "fork", "prompt": "IMAGE_BUDGET: 6"})
case("main: general-purpose (no image work) allowed", "allow", "Agent", {"subagent_type": "general-purpose", "prompt": "write tests"})

# ---- inspector: Read budget from prompt
subagent("insp", "IMAGE_BUDGET: 2")
I = ("insp", INSPECTOR)
case("inspector: Read 1/2 allowed", "allow", "Read", {"file_path": PNG}, I, contains="1/2")
case("inspector: Read 2/2 allowed", "allow", "Read", {"file_path": PNG}, I, contains="2/2")
case("inspector: Read 3/2 denied", "deny", "Read", {"file_path": PNG}, I)
case("inspector: Read pdf denied", "deny", "Read", {"file_path": PNG[:-3] + "pdf"}, I)
case("main: SendMessage to inspector denied", "deny", "SendMessage", {"to": "insp", "message": "more"})
case("main: SendMessage to other allowed", "allow", "SendMessage", {"to": "someone", "message": "hi"})

# ---- NEW: subagent screenshots share the counter (cap = HARD_LIMIT 8 for non-inspectors)
G = ("gp1", "general-purpose")
for i in range(7):
    hook(SHOT, {}, G)
case("subagent: screenshot #8 allowed (8/8)", "allow", SHOT, {}, G, contains="8/8")
case("subagent: screenshot #9 denied", "deny", SHOT, {}, G, contains="budget exhausted")
case("subagent: Read after cap denied (shared counter)", "deny", "Read", {"file_path": PNG}, G)
case("subagent: non-image MCP still allowed at cap", "allow", "mcp__claude-in-chrome__read_page", {"tabId": 1}, G)

G2 = ("gp2", "general-purpose")
for i in range(5):
    hook("Read", {"file_path": PNG}, G2)
case("subagent: batch with 3 screenshots at 5/8 allowed (8/8)", "allow", BATCH,
     {"steps": [{"action": "screenshot"}, {"action": "left_click"}, {"action": "screenshot"}, {"action": "zoom"}]},
     G2, contains="8/8")
G3 = ("gp3", "general-purpose")
for i in range(6):
    hook("Read", {"file_path": PNG}, G3)
case("subagent: batch with 3 screenshots at 6/8 denied", "deny", BATCH,
     {"steps": [{"action": "screenshot"}, {"action": "screenshot"}, {"action": "zoom"}]}, G3)
case("subagent: single screenshot at 6/8 still allowed", "allow", SHOT, {}, G3, contains="7/8")

G4 = ("gp4", "general-purpose")
case("subagent: computer click counts 1", "allow", COMPUTER, {"action": "left_click"}, G4, contains="1/8")
case("subagent: navigate (no image) not counted", "allow", "mcp__claude-in-chrome__navigate", {"url": "x"}, G4)
case("subagent: next computer call is 2/8", "allow", COMPUTER, {"action": "screenshot"}, G4, contains="2/8")

# ---- userConfig override
case("hard_limit=4: IMAGE_BUDGET 6 denied", "deny", "Agent", {"subagent_type": INSPECTOR, "prompt": "IMAGE_BUDGET: 6"},
     env={"CLAUDE_PLUGIN_OPTION_HARD_LIMIT": "4"})
G5 = ("gp5", "general-purpose")
for i in range(4):
    hook(SHOT, {}, G5, env={"CLAUDE_PLUGIN_OPTION_HARD_LIMIT": "4"})
case("hard_limit=4: 5th subagent screenshot denied", "deny", SHOT, {}, G5, env={"CLAUDE_PLUGIN_OPTION_HARD_LIMIT": "4"})

shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(STATE, ignore_errors=True)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
