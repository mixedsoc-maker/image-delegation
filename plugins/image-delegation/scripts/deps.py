"""Dependency check for image-delegation (fast: no imports, no subprocesses).

Checks the SAME Python interpreter that py.sh selected for hooks and imgtool.
Used by session_context.py (announces missing items) and `imgtool doctor`.
Testing: env IMAGE_DELEGATION_ASSUME_MISSING=pillow,poppler,pymupdf,playwright,npx
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys

POPPLER = ("pdftotext", "pdfimages", "pdftoppm")


def _assumed_missing() -> set:
    return {s.strip().lower() for s in os.environ.get("IMAGE_DELEGATION_ASSUME_MISSING", "").split(",") if s.strip()}


def status() -> dict:
    fake = _assumed_missing()

    def mod(name, key):
        return key not in fake and importlib.util.find_spec(name) is not None

    def exe(name, key):
        return key not in fake and shutil.which(name) is not None

    return {
        "python": sys.executable,
        "pillow": mod("PIL", "pillow"),
        "pymupdf": mod("fitz", "pymupdf"),
        "poppler": all(exe(t, "poppler") for t in POPPLER),
        "playwright_py": mod("playwright", "playwright"),
        "npx": exe("npx", "npx") or exe("npx.cmd", "npx"),
        "tesseract": exe("tesseract", "tesseract"),
    }


def problems(st: dict | None = None) -> list[str]:
    """One line per missing capability: what breaks + how to fix. Empty list = all good."""
    st = st or status()
    out = []
    if not st["pillow"]:
        out.append("Pillow missing -> imgtool info/resize/crop/tile/pdf-render/shot will fail. "
                   "Fix: pip install pillow")
    if not st["poppler"] and not st["pymupdf"]:
        out.append("No PDF backend (poppler or PyMuPDF) -> imgtool pdf-scan/pdf-text/pdf-render will fail. "
                   "Fix: install poppler (pdftotext/pdfimages/pdftoppm on PATH) or pip install pymupdf")
    if not st["playwright_py"] and not st["npx"]:
        out.append("No Playwright -> imgtool shot (web screenshots) will fail. "
                   "Fix: pip install playwright && playwright install chromium (or install Node.js for npx playwright)")
    return out


def report() -> str:
    st = status()
    rows = [
        f"python      {st['python']}",
        f"pillow      {'ok' if st['pillow'] else 'MISSING (required for raster ops)'}",
        f"poppler     {'ok' if st['poppler'] else 'missing'}",
        f"pymupdf     {'ok' if st['pymupdf'] else 'missing'}  (PDF fallback; needed to flag vector charts)",
        f"playwright  {'ok (python)' if st['playwright_py'] else ('via npx' if st['npx'] else 'missing')}",
        f"tesseract   {'ok' if st['tesseract'] else 'missing'}  (optional OCR)",
    ]
    probs = problems(st)
    rows.append("STATUS " + ("ok" if not probs else f"{len(probs)} problem(s)"))
    rows += [f"- {p}" for p in probs]
    return "\n".join(rows)
