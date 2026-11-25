"""Effective image limits, shared by hooks, imgtool and tests.

Single source of truth: plugin userConfig (`hard_limit`, `default_budget`).
  - hooks get the configured values as env CLAUDE_PLUGIN_OPTION_HARD_LIMIT / _DEFAULT_BUDGET
  - the SessionStart hook announces them to the main agent, which passes HARD_LIMIT to inspectors
  - otherwise the `default` declared in .claude-plugin/plugin.json is used
Change them with `/plugin configure image-delegation@<marketplace>` (or the /config panel).
DEFAULT_BUDGET is clamped to HARD_LIMIT.
"""
from __future__ import annotations

import json
import os

PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = {"HARD_LIMIT": "hard_limit", "DEFAULT_BUDGET": "default_budget"}
FALLBACK = {"HARD_LIMIT": 8, "DEFAULT_BUDGET": 6}


def _int(v):
    try:
        i = int(float(str(v).strip()))
        return i if i >= 1 else None
    except Exception:
        return None


def manifest_defaults() -> dict:
    try:
        with open(os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            uc = json.load(f).get("userConfig") or {}
        return {k: (uc.get(key) or {}).get("default") for k, key in KEYS.items()}
    except Exception:
        return {}


def load(overrides: dict | None = None) -> dict:
    layers = [
        overrides or {},
        {k: os.environ.get(f"CLAUDE_PLUGIN_OPTION_{key.upper()}") for k, key in KEYS.items()},
        manifest_defaults(),
        FALLBACK,
    ]
    out = {}
    for k in KEYS:
        for layer in layers:
            v = _int(layer.get(k))
            if v is not None:
                out[k] = v
                break
    out["DEFAULT_BUDGET"] = min(out["DEFAULT_BUDGET"], out["HARD_LIMIT"])
    return out
