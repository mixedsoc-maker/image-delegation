#!/usr/bin/env python3
"""Offline test for the dependency check (scripts/deps.py, SessionStart notice, `imgtool doctor`).

Simulates missing dependencies with IMAGE_DELEGATION_ASSUME_MISSING; installs nothing.
Usage: python tests/test_deps.py      -> exit 0 if all cases pass
"""
import importlib.util
import json
import os
import subprocess
import sys

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(PLUGIN, "scripts", "py.sh")
results = []


def run(args, missing="", stdin=""):
    env = {**os.environ, "IMAGE_DELEGATION_ASSUME_MISSING": missing}
    return subprocess.run(["sh", PY] + args, input=stdin, capture_output=True, text=True, env=env)


def session_ctx(missing):
    r = run(["--fail-open", "session_context.py"], missing, '{"source":"startup"}')
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def check(name, cond):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}")


# SessionStart notice
c = session_ctx("pillow")
check("pillow missing -> notice lists Pillow + fix", "Pillow missing" in c and "pip install pillow" in c)
check("notice tells the agent not to install", "Do NOT install anything yourself" in c)
c = session_ctx("poppler")
if importlib.util.find_spec("fitz"):
    check("poppler missing but PyMuPDF present -> no PDF notice", "No PDF backend" not in c)
else:
    check("poppler missing, no PyMuPDF -> PDF notice", "No PDF backend" in c)
c = session_ctx("poppler,pymupdf")
check("poppler + PyMuPDF missing -> PDF notice", "No PDF backend" in c)
c = session_ctx("playwright,npx")
check("no Playwright and no npx -> screenshot notice", "No Playwright" in c)
c = session_ctx("playwright")
check("npx alone is enough for screenshots", "No Playwright" not in c)
c = session_ctx("tesseract")
check("tesseract (optional) missing -> no notice", "Missing dependencies" not in c)
c = session_ctx("pillow,poppler,pymupdf,playwright,npx")
check("all missing -> 3 problem lines", c.count("-> imgtool") == 3)
check("rule section always present", "## Image handling (image-delegation plugin)" in c)

# imgtool doctor
r = run(["imgtool.py", "doctor"], "pillow")
check("doctor exits 1 when Pillow missing", r.returncode == 1 and "MISSING" in r.stdout)
r = run(["imgtool.py", "doctor"], "tesseract")
check("doctor exits 0 when only optional deps missing", r.returncode == 0 and "STATUS ok" in r.stdout)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
